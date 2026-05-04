class AgentShieldError(Exception):
    """Base exception for all SDK errors."""


class AgentShieldAPIError(AgentShieldError):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class AgentShieldBlockedError(AgentShieldAPIError):
    """Raised when the spend request is hard-blocked (MALICIOUS verdict)."""

    def __init__(self, status_code: int, detail: str, block_code: str, reasons: list[str]) -> None:
        self.block_code = block_code
        self.reasons = reasons
        super().__init__(status_code, detail)


class AgentShieldAuthError(AgentShieldAPIError):
    """Raised on authentication failures (401/403)."""
