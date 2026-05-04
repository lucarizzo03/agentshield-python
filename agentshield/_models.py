from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


# ── Spend ──────────────────────────────────────────────────────────────────────

class SpendRequest(BaseModel):
    agent_id: str = Field(min_length=3, max_length=128)
    declared_goal: str = Field(min_length=3, max_length=2000)
    amount_cents: int = Field(ge=1, le=100_000_000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    vendor_url_or_name: str = Field(min_length=2, max_length=512)
    item_description: str = Field(min_length=2, max_length=4000)
    asset_type: Literal["STABLECOIN", "FIAT"] = "FIAT"
    stablecoin_symbol: Literal["USDC", "USDT", "USDC.e", "USDC.b"] | None = None
    network: Literal["ethereum", "base", "solana", "polygon", "arbitrum", "tempo"] | None = None
    destination_address: str | None = Field(default=None, min_length=16, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    agent_callback_url: HttpUrl | None = None
    dev_slm_preset: Literal["ALIGNED", "WEAK", "MISMATCH"] | None = None

    @model_validator(mode="after")
    def _require_stablecoin_fields(self) -> "SpendRequest":
        if self.asset_type == "STABLECOIN":
            if any(v is None for v in [self.stablecoin_symbol, self.network, self.destination_address]):
                raise ValueError(
                    "stablecoin_symbol, network, and destination_address are required when asset_type='STABLECOIN'"
                )
        return self


class HitlState(BaseModel):
    state: str
    channel: str
    requested_at: datetime
    expires_at: datetime


class SpendResponse(BaseModel):
    request_id: str
    status: str
    verdict: str
    approved_amount_cents: int | None = None
    currency: str | None = None
    reasons: list[str] = []
    hitl: HitlState | None = None
    next_action: str | None = None
    block_code: str | None = None

    @property
    def approved(self) -> bool:
        return self.status == "APPROVED_EXECUTED"

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCKED"

    @property
    def pending_hitl(self) -> bool:
        return self.status == "PENDING_HITL"


class SpendStatusResponse(BaseModel):
    request_id: str
    status: str
    verdict: str
    decision: str | None = None
    resolved: bool = False
    expires_at: datetime | None = None


# ── HITL ───────────────────────────────────────────────────────────────────────

class HitlResolveRequest(BaseModel):
    decision: Literal["APPROVE", "DENY"]
    resolver_id: str = Field(min_length=2, max_length=128)
    channel: Literal["dashboard", "email"] = "dashboard"
    resolution_note: str | None = Field(default=None, max_length=1000)


class HitlResolveResponse(BaseModel):
    request_id: str
    status: str
    decision: str
    resolved_at: datetime


# ── Agents ─────────────────────────────────────────────────────────────────────

class AgentCreateRequest(BaseModel):
    agent_name: str = Field(min_length=3, max_length=128)
    daily_spend_limit_usd: int = Field(ge=0, le=1_000_000)
    per_transaction_limit_usd: int = Field(ge=0, le=1_000_000)
    auto_approve_under_usd: int = Field(ge=0, le=1_000_000)
    asset_type: Literal["STABLECOIN", "FIAT"] = "FIAT"
    blocked_vendors: list[str] = Field(default_factory=list)
    allowed_networks: list[str] = Field(default_factory=list)
    allowed_tokens: list[str] = Field(default_factory=list)


class AgentCreateResponse(BaseModel):
    agent_id: str
    hmac_secret: str
    display_name: str
    created_at: datetime


class AgentSummary(BaseModel):
    agent_id: str
    display_name: str
    status: str


class AgentRotateHmacResponse(BaseModel):
    agent_id: str
    hmac_secret: str
    rotated_at: datetime


# ── Dashboard ──────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    agent_id: str
    total_transactions_today: int
    blocked: int
    pending_approval: int
    auto_approved: int


class ActivityEntry(BaseModel):
    request_id: str
    created_at: datetime
    status: str
    verdict: str
    vendor_url_or_name: str
    amount_cents: int
    currency: str
    asset_type: str
    network: str | None = None
    declared_goal: str
    reason: str | None = None
    quantitative_result: dict | None = None
    policy_result: dict | None = None
    semantic_result: dict | None = None


class Notification(BaseModel):
    id: str
    agent_id: str
    request_id: str
    category: str
    priority: str
    status: str
    summary: str
    payload_json: dict | None = None
    created_at: datetime
