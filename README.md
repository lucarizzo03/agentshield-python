# AgentShield Python SDK

Python SDK for [AgentShield](https://github.com/your-org/agentshieldv2) — a spend-control firewall for autonomous AI agents. Wrap every payment your agent makes with policy enforcement, fraud detection, and human-in-the-loop review.

---

## Installation

```bash
pip install agentshield
```

Requires Python 3.11+.

---

## Concepts

Every spend request your agent makes is evaluated across three layers:

| Layer | What it checks |
|---|---|
| **Quantitative** | Daily budget, duplicate transaction loops, destination address bursting |
| **Policy** | Vendor blocklist, amount thresholds, stablecoin/network allowlists |
| **Semantic** | LLM-based alignment between declared goal and what's actually being purchased |

The result is one of three verdicts:

- **`SAFE`** — auto-approved, budget committed
- **`SUSPICIOUS`** — routed to a human reviewer (HITL), agent must wait
- **`MALICIOUS`** — hard blocked, do not retry

---

## Authentication

AgentShield uses **HMAC-signed requests**. Every call is signed with your `agent_id` and `hmac_secret` — the SDK handles this automatically.

You get these credentials when you create an agent:

```python
from agentshield import AgentShieldAdmin, AgentCreateRequest

admin = AgentShieldAdmin(bearer_token="your-auth0-token")
agent = admin.create_agent(AgentCreateRequest(
    agent_name="my-buying-agent",
    daily_spend_limit_usd=500,
    per_transaction_limit_usd=100,
    auto_approve_under_usd=20,
    asset_type="FIAT",
))

print(agent.agent_id)    # agt_...
print(agent.hmac_secret) # sk_live_...
```

Store both securely — you pass them to every client instantiation.

---

## Quick Start

```python
from agentshield import AgentShield, SpendRequest

client = AgentShield(
    agent_id="agt_...",
    hmac_secret="sk_live_...",
    base_url="https://your-agentshield-instance.com",
)

result = client.spend_request(SpendRequest(
    agent_id="agt_...",
    declared_goal="Book a flight from JFK to LAX for the team offsite",
    amount_cents=25000,
    currency="USD",
    vendor_url_or_name="delta.com",
    item_description="Economy seat JFK-LAX, Oct 12",
    asset_type="FIAT",
))

if result.approved:
    print(f"Approved: ${result.approved_amount_cents / 100:.2f}")
elif result.pending_hitl:
    print(f"Waiting for human review — poll {result.request_id}")
elif result.blocked:
    print(f"Blocked: {result.reasons}")
```

---

## Sync Client

### `AgentShield(agent_id, hmac_secret, *, base_url, timeout)`

The primary client for agent-level operations. Use as a context manager or call `.close()` when done.

```python
with AgentShield("agt_...", "sk_live_...") as client:
    ...
```

---

### `spend_request(request: SpendRequest) → SpendResponse`

Submit a payment for evaluation.

```python
from agentshield import SpendRequest

result = client.spend_request(SpendRequest(
    agent_id="agt_...",
    declared_goal="Pay monthly invoice for cloud hosting",
    amount_cents=9900,
    currency="USD",
    vendor_url_or_name="aws.amazon.com",
    item_description="EC2 compute — November invoice",
    asset_type="FIAT",
    idempotency_key="invoice-nov-2024",  # optional, auto-generated if omitted
))
```

**SpendRequest fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `agent_id` | `str` | Yes | Your agent's ID |
| `declared_goal` | `str` | Yes | Why the agent is making this payment |
| `amount_cents` | `int` | Yes | Amount in cents (e.g. `2500` = $25.00) |
| `currency` | `str` | Yes | 3-letter ISO code, e.g. `"USD"` |
| `vendor_url_or_name` | `str` | Yes | Vendor domain or display name |
| `item_description` | `str` | Yes | What is being purchased |
| `asset_type` | `"FIAT"` \| `"STABLECOIN"` | Yes | Payment type |
| `stablecoin_symbol` | `"USDC"` \| `"USDT"` \| ... | If STABLECOIN | Token symbol |
| `network` | `"base"` \| `"ethereum"` \| ... | If STABLECOIN | Chain |
| `destination_address` | `str` | If STABLECOIN | Wallet address |
| `idempotency_key` | `str` | No | Deduplication key, auto-generated if omitted |
| `agent_callback_url` | `str` | No | URL to notify when HITL is resolved |

**SpendResponse fields:**

| Field | Type | Description |
|---|---|---|
| `request_id` | `str` | Unique ID for this transaction |
| `status` | `str` | `APPROVED_EXECUTED`, `BLOCKED`, or `PENDING_HITL` |
| `verdict` | `str` | `SAFE`, `MALICIOUS`, or `SUSPICIOUS` |
| `approved_amount_cents` | `int \| None` | Set when approved |
| `reasons` | `list[str]` | Policy reason codes |
| `hitl` | `HitlState \| None` | Set when pending human review |
| `approved` | `bool` | Convenience property |
| `blocked` | `bool` | Convenience property |
| `pending_hitl` | `bool` | Convenience property |

---

### `get_spend_status(request_id: str) → SpendStatusResponse`

Poll for the outcome of a `PENDING_HITL` request.

```python
status = client.get_spend_status("req_abc123")

if status.resolved:
    print(f"Decision: {status.decision}")  # "APPROVE" or "DENY"
else:
    print(f"Still waiting, expires at {status.expires_at}")
```

**Polling pattern:**

```python
import time

result = client.spend_request(...)
if result.pending_hitl:
    while True:
        status = client.get_spend_status(result.request_id)
        if status.resolved:
            break
        time.sleep(10)
```

Or use `agent_callback_url` on the spend request to receive a webhook instead of polling.

---

### `resolve_hitl(request_id: str, request: HitlResolveRequest) → HitlResolveResponse`

Programmatically approve or deny a pending HITL request (e.g. from a custom dashboard).

```python
from agentshield import HitlResolveRequest

result = client.resolve_hitl(
    "req_abc123",
    HitlResolveRequest(
        decision="APPROVE",          # or "DENY"
        resolver_id="ops-team",
        channel="dashboard",
        resolution_note="Verified with finance team",
    ),
)
print(result.resolved_at)
```

---

### `rotate_hmac() → AgentRotateHmacResponse`

Rotate your HMAC secret. The client automatically updates its internal secret after rotation.

```python
rotated = client.rotate_hmac()
print(rotated.hmac_secret)  # store this — the old secret is now invalid
```

---

### `get_stats() → DashboardStats`

Today's transaction summary for this agent.

```python
stats = client.get_stats()
print(f"Auto-approved: {stats.auto_approved}")
print(f"Blocked: {stats.blocked}")
print(f"Pending review: {stats.pending_approval}")
```

---

### `get_activity(limit=100) → list[ActivityEntry]`

Full audit log of recent transactions, newest first.

```python
activity = client.get_activity(limit=50)
for entry in activity:
    print(f"{entry.created_at} | {entry.verdict} | ${entry.amount_cents / 100:.2f} | {entry.vendor_url_or_name}")
```

---

### `get_notifications(status="OPEN", limit=50) → list[Notification]`

Dashboard notifications for pending HITL items.

```python
notifications = client.get_notifications(status="OPEN")
for n in notifications:
    print(f"[{n.priority}] {n.summary}")
```

---

## Async Client

`AsyncAgentShield` and `AsyncAgentShieldAdmin` mirror the sync API exactly — every method is a coroutine. Use with `async with` and `await`.

```python
from agentshield import AsyncAgentShield, SpendRequest

async def run():
    async with AsyncAgentShield("agt_...", "sk_live_...") as client:
        result = await client.spend_request(SpendRequest(
            agent_id="agt_...",
            declared_goal="Pay for API usage",
            amount_cents=200,
            currency="USD",
            vendor_url_or_name="openweather.com",
            item_description="Weather API call",
            asset_type="FIAT",
        ))
        print(result.verdict)
```

All methods available on `AsyncAgentShield`:
- `await client.spend_request(...)`
- `await client.get_spend_status(...)`
- `await client.resolve_hitl(...)`
- `await client.rotate_hmac()`
- `await client.get_stats()`
- `await client.get_activity(...)`
- `await client.get_notifications(...)`

---

## Stablecoin Payments

When `asset_type="STABLECOIN"`, three additional fields are required:

```python
result = client.spend_request(SpendRequest(
    agent_id="agt_...",
    declared_goal="Pay contractor invoice in USDC",
    amount_cents=50000,
    currency="USD",
    vendor_url_or_name="contractor.eth",
    item_description="Design work — November",
    asset_type="STABLECOIN",
    stablecoin_symbol="USDC",
    network="base",
    destination_address="0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
))
```

Supported tokens: `USDC`, `USDT`, `USDC.e`, `USDC.b`

Supported networks: `ethereum`, `base`, `solana`, `polygon`, `arbitrum`, `tempo`

---

## Error Handling

```python
from agentshield import (
    AgentShieldError,
    AgentShieldAPIError,
    AgentShieldAuthError,
    AgentShieldBlockedError,
)

try:
    result = client.spend_request(...)
except AgentShieldBlockedError as e:
    print(f"Hard blocked: {e.block_code}")
    print(f"Reasons: {e.reasons}")
    # do not retry
except AgentShieldAuthError as e:
    print(f"Auth failed ({e.status_code}): {e.detail}")
except AgentShieldAPIError as e:
    print(f"API error ({e.status_code}): {e.detail}")
except AgentShieldError as e:
    print(f"SDK error: {e}")
```

| Exception | When raised |
|---|---|
| `AgentShieldBlockedError` | `MALICIOUS` verdict — hard deny |
| `AgentShieldAuthError` | 401 or 403 — bad credentials or inactive agent |
| `AgentShieldAPIError` | Any other 4xx/5xx |
| `AgentShieldError` | Base class for all SDK exceptions |

> `PENDING_HITL` (202) is **not** an exception — it is a normal `SpendResponse` with `result.pending_hitl == True`.

---

## Admin Client

`AgentShieldAdmin` (and `AsyncAgentShieldAdmin`) use Bearer token auth for user-level operations.

```python
from agentshield import AgentShieldAdmin, AgentCreateRequest

with AgentShieldAdmin(bearer_token="your-token") as admin:
    # Create an agent
    agent = admin.create_agent(AgentCreateRequest(
        agent_name="research-agent",
        daily_spend_limit_usd=200,
        per_transaction_limit_usd=50,
        auto_approve_under_usd=10,
        asset_type="FIAT",
        blocked_vendors=["gambling.com"],
        allowed_networks=["base"],
        allowed_tokens=["USDC"],
    ))

    # List all agents
    agents = admin.list_agents()
    for a in agents:
        print(f"{a.agent_id} — {a.display_name} ({a.status})")
```

---

## Development

```bash
git clone https://github.com/your-org/agentshield-python
cd agentshield-python
uv venv && uv pip install -e ".[dev]"
pytest
```

To run against a local AgentShield server:

```python
client = AgentShield("agt_...", "sk_live_...", base_url="http://localhost:8000")
```

In dev mode the server accepts `local-dev-key` as a bypass — useful for manual smoke tests but **never use in production**.
