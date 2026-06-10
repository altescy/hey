class SandboxError(Exception):
    """Base sandbox execution error."""


class SandboxUnavailableError(SandboxError):
    """Raised when the configured sandbox backend is unavailable."""
