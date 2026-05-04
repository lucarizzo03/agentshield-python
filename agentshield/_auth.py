import hashlib
import hmac
import json
from datetime import datetime, timezone


def _body_bytes(payload: dict | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sign_request(
    *,
    method: str,
    path: str,
    body: bytes,
    agent_id: str,
    hmac_secret: str,
    timestamp: str | None = None,
) -> dict[str, str]:
    """Return the three HMAC auth headers expected by the AgentShield API."""
    ts = timestamp or _now_iso()
    body_hash = _body_sha256(body)
    canonical = "\n".join([method.upper(), path, ts, body_hash, agent_id])
    signature = hmac.new(
        hmac_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-agent-id": agent_id,
        "x-timestamp": ts,
        "x-signature": signature,
    }
