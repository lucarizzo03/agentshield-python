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


class AgentShield:
    def __init__(
        self,
        agent_id: str,
        hmac_secret: str,
        *,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ) -> None:
        self.agent_id = agent_id
        self._hmac_secret = hmac_secret
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self._base_url, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AgentShield":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> dict:
        body = _body_bytes(payload)
        headers = sign_request(
            method="POST",
            path=path,
            body=body,
            agent_id=self.agent_id,
            hmac_secret=self._hmac_secret,
        )
        headers["content-type"] = "application/json"
        resp = self._http.post(path, content=body, headers=headers)
        return self._handle(resp)

    def _get(self, path: str) -> dict:
        body = _body_bytes(None)
        headers = sign_request(
            method="GET",
            path=path,
            body=body,
            agent_id=self.agent_id,
            hmac_secret=self._hmac_secret,
        )
        resp = self._http.get(path, headers=headers)
        return self._handle(resp)

    @staticmethod
    def _handle(resp: httpx.Response) -> dict:
        if resp.status_code in (401, 403):
            detail = resp.json().get("detail", resp.text)
            raise AgentShieldAuthError(resp.status_code, detail)
        if resp.status_code == 403:
            data = resp.json()
            raise AgentShieldBlockedError(
                resp.status_code,
                data.get("detail", "blocked"),
                data.get("block_code", "POLICY_HARD_DENY"),
                data.get("reasons", []),
            )
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.text
            raise AgentShieldAPIError(resp.status_code, detail)
        return resp.json()

    # ── Spend ──────────────────────────────────────────────────────────────────

    def spend_request(self, request: SpendRequest) -> SpendResponse:
        if request.idempotency_key is None:
            request = request.model_copy(update={"idempotency_key": f"sdk_{token_urlsafe(12)}"})
        payload = json.loads(request.model_dump_json(exclude_none=False))
        data = self._post("/v1/spend-request", payload)
        return SpendResponse.model_validate(data)

    def get_spend_status(self, request_id: str) -> SpendStatusResponse:
        data = self._get(f"/v1/spend-request/{request_id}/status")
        return SpendStatusResponse.model_validate(data)

    # ── HITL ───────────────────────────────────────────────────────────────────

    def resolve_hitl(self, request_id: str, request: HitlResolveRequest) -> HitlResolveResponse:
        payload = json.loads(request.model_dump_json())
        data = self._post(f"/v1/hitl/resolve/{request_id}", payload)
        return HitlResolveResponse.model_validate(data)

    # ── Agents ─────────────────────────────────────────────────────────────────

    def rotate_hmac(self) -> AgentRotateHmacResponse:
        data = self._post(f"/v1/agents/{self.agent_id}/credentials/hmac/rotate", {})
        resp = AgentRotateHmacResponse.model_validate(data)
        self._hmac_secret = resp.hmac_secret
        return resp

    # ── Dashboard ──────────────────────────────────────────────────────────────

    def get_stats(self) -> DashboardStats:
        data = self._get(f"/v1/dashboard/agents/{self.agent_id}/stats")
        return DashboardStats.model_validate(data)

    def get_activity(self, limit: int = 100) -> list[ActivityEntry]:
        data = self._get(f"/v1/dashboard/agents/{self.agent_id}/activity?limit={limit}")
        return [ActivityEntry.model_validate(r) for r in data.get("activity", [])]

    def get_notifications(self, status: str = "OPEN", limit: int = 50) -> list[Notification]:
        data = self._get(
            f"/v1/dashboard/agents/{self.agent_id}/notifications?status={status}&limit={limit}"
        )
        return [Notification.model_validate(n) for n in data.get("notifications", [])]


# ── Management client (user-auth, no HMAC) ─────────────────────────────────────

class AgentShieldAdmin:
    """Client for user-level operations (create agents, list agents). Uses Bearer token auth."""

    def __init__(
        self,
        bearer_token: str,
        *,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AgentShieldAdmin":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @staticmethod
    def _handle(resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.text
            raise AgentShieldAPIError(resp.status_code, detail)
        return resp.json()

    def create_agent(self, request: AgentCreateRequest) -> AgentCreateResponse:
        resp = self._http.post("/v1/agents", json=json.loads(request.model_dump_json()))
        return AgentCreateResponse.model_validate(self._handle(resp))

    def list_agents(self) -> list[AgentSummary]:
        resp = self._http.get("/v1/agents")
        data = self._handle(resp)
        return [AgentSummary.model_validate(a) for a in data.get("agents", [])]
