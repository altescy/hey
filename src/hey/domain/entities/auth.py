from __future__ import annotations

from typing import Protocol, runtime_checkable


class AuthToken(Protocol):
    """Minimal interface a token must satisfy to be usable as a Bearer token."""

    @property
    def access_token(self) -> str: ...


@runtime_checkable
class AuthProvider(Protocol):
    """Supplies a valid (possibly refreshed) access token on demand.

    Implementations are expected to be async-safe and to handle token
    refresh transparently so callers only ever see a ready-to-use token.
    """

    async def get_token(self) -> str:
        """Return a valid Bearer token string."""
        ...
