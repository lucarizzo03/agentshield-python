"""
Tests use respx to mock httpx at the transport layer — no real server needed.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

import agentshield as sdk
from agentshield._auth import _body_bytes, sign_request


AGENT_ID = "agt_test000000000001"
HMAC_SECRET = "sk_live_testsecret"
BASE_URL = "http://test.local"


# ── Auth ───────────────────────────────────────────────────────────────────────

def test_sign_request_canonical_format():
    body = _body_bytes({"amount_cents": 100})
    headers = sign_request(
        method="POST",
        path="/v1/spend-request",
        body=body,
        agent_id=AGENT_ID,
        hmac_secret=HMAC_SECRET,
        timestamp="2024-01-01T00:00:00Z",
    )
    assert headers["x-agent-id"] == AGENT_ID
    assert headers["x-timestamp"] == "2024-01-01T00:00:00Z"

    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(["POST", "/v1/spend-request", "2024-01-01T00:00:00Z", body_hash, AGENT_ID])
    expected_sig = hmac.new(HMAC_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert headers["x-signature"] == expected_sig


# ── Sync client ────────────────────────────────────────────────────────────────

@respx.mock
def test_spend_request_safe():
    response_body = {
        "request_id": "req_abc123",
        "status": "APPROVED_EXECUTED",
        "verdict": "SAFE",
        "approved_amount_cents": 4900,
        "currency": "USD",
        "reasons": ["BUDGET_WITHIN_LIMIT", "SEMANTIC_ALIGNMENT_HIGH"],
    }
    respx.post(f"{BASE_URL}/v1/spend-request").mock(return_value=Response(200, json=response_body))

    with sdk.AgentShield(AGENT_ID, HMAC_SECRET, base_url=BASE_URL) as client:
        result = client.spend_request(
            sdk.SpendRequest(
                agent_id=AGENT_ID,
                declared_goal="Buy office supplies",
                amount_cents=4900,
                currency="USD",
                vendor_url_or_name="staples.com",
                item_description="Printer paper",
                asset_type="FIAT",
            )
        )

    assert result.approved is True
    assert result.request_id == "req_abc123"
    assert result.approved_amount_cents == 4900


@respx.mock
def test_spend_request_pending_hitl():
    response_body = {
        "request_id": "req_hitl001",
        "status": "PENDING_HITL",
        "verdict": "SUSPICIOUS",
        "reasons": ["AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD"],
        "hitl": {
            "state": "WAITING_HUMAN_REVIEW",
            "channel": "dashboard",
            "requested_at": "2024-01-01T00:00:00Z",
            "expires_at": "2024-01-01T00:10:00Z",
        },
        "next_action": "AGENT_MUST_WAIT",
    }
    respx.post(f"{BASE_URL}/v1/spend-request").mock(return_value=Response(202, json=response_body))

    with sdk.AgentShield(AGENT_ID, HMAC_SECRET, base_url=BASE_URL) as client:
        result = client.spend_request(
            sdk.SpendRequest(
                agent_id=AGENT_ID,
                declared_goal="Large equipment purchase",
                amount_cents=500_00,
                currency="USD",
                vendor_url_or_name="acme.com",
                item_description="Industrial printer",
                asset_type="FIAT",
            )
        )

    assert result.pending_hitl is True
    assert result.hitl is not None
    assert result.hitl.state == "WAITING_HUMAN_REVIEW"


@respx.mock
def test_spend_request_blocked_raises():
    response_body = {
        "request_id": "req_block001",
        "status": "BLOCKED",
        "verdict": "MALICIOUS",
        "block_code": "POLICY_HARD_DENY",
        "reasons": ["VENDOR_MATCHED_BLOCKLIST"],
        "next_action": "DO_NOT_RETRY",
    }
    respx.post(f"{BASE_URL}/v1/spend-request").mock(return_value=Response(403, json=response_body))

    with sdk.AgentShield(AGENT_ID, HMAC_SECRET, base_url=BASE_URL) as client:
        with pytest.raises(sdk.AgentShieldAuthError):
            client.spend_request(
                sdk.SpendRequest(
                    agent_id=AGENT_ID,
                    declared_goal="Purchase supplies",
                    amount_cents=100,
                    currency="USD",
                    vendor_url_or_name="blocked-vendor.com",
                    item_description="Stuff",
                    asset_type="FIAT",
                )
            )


@respx.mock
def test_get_spend_status():
    response_body = {
        "request_id": "req_abc123",
        "status": "APPROVED_BY_HUMAN_EXECUTED",
        "verdict": "SAFE",
        "decision": "APPROVE",
        "resolved": True,
    }
    respx.get(f"{BASE_URL}/v1/spend-request/req_abc123/status").mock(
        return_value=Response(200, json=response_body)
    )

    with sdk.AgentShield(AGENT_ID, HMAC_SECRET, base_url=BASE_URL) as client:
        result = client.get_spend_status("req_abc123")

    assert result.resolved is True
    assert result.decision == "APPROVE"


@respx.mock
def test_get_stats():
    response_body = {
        "agent_id": AGENT_ID,
        "total_transactions_today": 10,
        "blocked": 1,
        "pending_approval": 2,
        "auto_approved": 7,
    }
    respx.get(f"{BASE_URL}/v1/dashboard/agents/{AGENT_ID}/stats").mock(
        return_value=Response(200, json=response_body)
    )

    with sdk.AgentShield(AGENT_ID, HMAC_SECRET, base_url=BASE_URL) as client:
        stats = client.get_stats()

    assert stats.auto_approved == 7
    assert stats.blocked == 1


# ── Async client ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_async_spend_request_safe():
    response_body = {
        "request_id": "req_async001",
        "status": "APPROVED_EXECUTED",
        "verdict": "SAFE",
        "approved_amount_cents": 200,
        "currency": "USD",
        "reasons": ["SEMANTIC_ALIGNMENT_HIGH"],
    }
    respx.post(f"{BASE_URL}/v1/spend-request").mock(return_value=Response(200, json=response_body))

    async with sdk.AsyncAgentShield(AGENT_ID, HMAC_SECRET, base_url=BASE_URL) as client:
        result = await client.spend_request(
            sdk.SpendRequest(
                agent_id=AGENT_ID,
                declared_goal="Weather API call for trip planning",
                amount_cents=200,
                currency="USD",
                vendor_url_or_name="openweather.com",
                item_description="Current weather forecast",
                asset_type="FIAT",
            )
        )

    assert result.approved is True
    assert result.request_id == "req_async001"


@pytest.mark.asyncio
@respx.mock
async def test_async_resolve_hitl():
    response_body = {
        "request_id": "req_hitl001",
        "status": "RESOLVED",
        "decision": "APPROVE",
        "resolved_at": "2024-01-01T00:05:00Z",
    }
    respx.post(f"{BASE_URL}/v1/hitl/resolve/req_hitl001").mock(
        return_value=Response(200, json=response_body)
    )

    async with sdk.AsyncAgentShield(AGENT_ID, HMAC_SECRET, base_url=BASE_URL) as client:
        result = await client.resolve_hitl(
            "req_hitl001",
            sdk.HitlResolveRequest(decision="APPROVE", resolver_id="human-reviewer"),
        )

    assert result.decision == "APPROVE"
    assert result.status == "RESOLVED"


# ── Model validation ───────────────────────────────────────────────────────────

def test_spend_request_stablecoin_requires_fields():
    with pytest.raises(Exception):
        sdk.SpendRequest(
            agent_id=AGENT_ID,
            declared_goal="Send USDC",
            amount_cents=100,
            currency="USD",
            vendor_url_or_name="recipient.eth",
            item_description="Payment",
            asset_type="STABLECOIN",
            # missing stablecoin_symbol, network, destination_address
        )


def test_spend_request_stablecoin_valid():
    req = sdk.SpendRequest(
        agent_id=AGENT_ID,
        declared_goal="Send USDC to contractor",
        amount_cents=10_000,
        currency="USD",
        vendor_url_or_name="contractor.eth",
        item_description="Invoice payment",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="base",
        destination_address="0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1",
    )
    assert req.asset_type == "STABLECOIN"
