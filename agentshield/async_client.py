import os
import json
from secrets import token_urlsafe
from typing import Any

import httpx

from agentshield._auth import _body_bytes, sign_request
from agentshield._exceptions import AgentShieldAPIError, AgentShieldAuthError, AgentShieldBlockedError
from agentshield._models import (
    ActivityEntry,
    AgentCreateRequest,
    AgentCreateResponse,
    AgentRotateHmacResponse,
    AgentSummary,
    DashboardStats,
    HitlResolveRequest,
    HitlResolveResponse,
    Notification,
    SpendRequest,
    SpendResponse,
    SpendStatusResponse,
)

DEFAULT_BASE_URL = os.getenv(
    "AGENTSHIELD_BASE_URL", "https://agentshieldv2-backend-production.up.railway.app"
)


class AsyncAgentShield:
    def __init__(
        self,
        agent_id: str,
        hmac_secret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.agent_id = agent_id
        self._hmac_secret = hmac_secret
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncAgentShield":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _post(self, path: str, payload: dict) -> dict:
        body = _body_bytes(payload)
        headers = sign_request(
            method="POST",
            path=path,
            body=body,
            agent_id=self.agent_id,
            hmac_secret=self._hmac_secret,
        )
        headers["content-type"] = "application/json"
        resp = await self._http.post(path, content=body, headers=headers)
        return self._handle(resp)

    async def _get(self, path: str) -> dict:
        body = _body_bytes(None)
        headers = sign_request(
            method="GET",
            path=path,
            body=body,
            agent_id=self.agent_id,
            hmac_secret=self._hmac_secret,
        )
        resp = await self._http.get(path, headers=headers)
        return self._handle(resp)

    @staticmethod
    def _handle(resp: httpx.Response) -> dict:
        if resp.status_code == 403:
            data = resp.json() if resp.content else {}
            raise AgentShieldBlockedError(
                resp.status_code,
                data.get("detail", "blocked"),
                data.get("block_code", "POLICY_HARD_DENY"),
                data.get("reasons", []),
            )
        if resp.status_code == 401:
            data = resp.json() if resp.content else {}
            detail = data.get("detail", resp.text)
            raise AgentShieldAuthError(resp.status_code, detail)
        if resp.status_code >= 400:
            detail = (resp.json() if resp.content else {}).get("detail", resp.text)
            raise AgentShieldAPIError(resp.status_code, detail)
        return resp.json()

    # ── Spend ──────────────────────────────────────────────────────────────────

    async def spend_request(self, request: SpendRequest) -> SpendResponse:
        if request.idempotency_key is None:
            request = request.model_copy(update={"idempotency_key": f"sdk_{token_urlsafe(12)}"})
        payload = json.loads(request.model_dump_json(exclude_none=False))
        data = await self._post("/v1/spend-request", payload)
        return SpendResponse.model_validate(data)

    async def get_spend_status(self, request_id: str) -> SpendStatusResponse:
        data = await self._get(f"/v1/spend-request/{request_id}/status")
        return SpendStatusResponse.model_validate(data)

    # ── HITL ───────────────────────────────────────────────────────────────────

    async def resolve_hitl(self, request_id: str, request: HitlResolveRequest) -> HitlResolveResponse:
        payload = json.loads(request.model_dump_json())
        data = await self._post(f"/v1/hitl/resolve/{request_id}", payload)
        return HitlResolveResponse.model_validate(data)

    # ── Agents ─────────────────────────────────────────────────────────────────

    async def rotate_hmac(self) -> AgentRotateHmacResponse:
        data = await self._post(f"/v1/agents/{self.agent_id}/credentials/hmac/rotate", {})
        resp = AgentRotateHmacResponse.model_validate(data)
        self._hmac_secret = resp.hmac_secret
        return resp

    # ── Dashboard ──────────────────────────────────────────────────────────────

    async def get_stats(self) -> DashboardStats:
        data = await self._get(f"/v1/dashboard/agents/{self.agent_id}/stats")
        return DashboardStats.model_validate(data)

    async def get_activity(self, limit: int = 100) -> list[ActivityEntry]:
        data = await self._get(f"/v1/dashboard/agents/{self.agent_id}/activity?limit={limit}")
        return [ActivityEntry.model_validate(r) for r in data.get("activity", [])]

    async def get_notifications(self, status: str = "OPEN", limit: int = 50) -> list[Notification]:
        data = await self._get(
            f"/v1/dashboard/agents/{self.agent_id}/notifications?status={status}&limit={limit}"
        )
        return [Notification.model_validate(n) for n in data.get("notifications", [])]


# ── Management client ──────────────────────────────────────────────────────────

class AsyncAgentShieldAdmin:
    """Async client for user-level operations. Uses Bearer token auth."""

    def __init__(
        self,
        bearer_token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncAgentShieldAdmin":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    @staticmethod
    def _handle(resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.text
            raise AgentShieldAPIError(resp.status_code, detail)
        return resp.json()

    async def create_agent(self, request: AgentCreateRequest) -> AgentCreateResponse:
        resp = await self._http.post("/v1/agents", json=json.loads(request.model_dump_json()))
        return AgentCreateResponse.model_validate(self._handle(resp))

    async def list_agents(self) -> list[AgentSummary]:
        resp = await self._http.get("/v1/agents")
        data = self._handle(resp)
        return [AgentSummary.model_validate(a) for a in data.get("agents", [])]
