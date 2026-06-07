"""Token persistence helpers shared by Copilot and Codex auth providers.

Tokens are stored as JSON files under the platform-appropriate global auth
 directory (e.g. ``~/.config/hey/auth/<provider>.json`` on Linux).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hey.infrastructure.paths import global_auth_dir


def _token_path(provider: str) -> Path:
    return global_auth_dir() / f"{provider}.json"


def load_token(provider: str) -> dict[str, Any] | None:
    """Return the stored token dict for *provider*, or ``None`` if absent."""
    path = _token_path(provider)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_token(provider: str, data: dict[str, Any]) -> None:
    """Persist *data* for *provider* atomically."""
    path = _token_path(provider)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def delete_token(provider: str) -> None:
    """Remove stored credentials for *provider* (no-op if absent)."""
    _token_path(provider).unlink(missing_ok=True)
