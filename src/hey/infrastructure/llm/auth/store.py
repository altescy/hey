"""Token persistence helpers shared by Copilot and Codex auth providers.

Tokens are stored as JSON files under ``~/.config/hey/auth/<provider>.json``
(XDG_CONFIG_HOME is respected when set).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "hey" / "auth"


def load_token(provider: str) -> dict[str, Any] | None:
    """Return the stored token dict for *provider*, or ``None`` if absent."""
    path = _config_dir() / f"{provider}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_token(provider: str, data: dict[str, Any]) -> None:
    """Persist *data* for *provider* atomically."""
    dir_ = _config_dir()
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{provider}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def delete_token(provider: str) -> None:
    """Remove stored credentials for *provider* (no-op if absent)."""
    path = _config_dir() / f"{provider}.json"
    path.unlink(missing_ok=True)
