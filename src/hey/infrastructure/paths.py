"""I/O wrappers around the pure path helpers in ``domain/services/paths``.

These functions return ``Path`` objects **and** ensure the directories exist on
disk so callers do not need to call ``mkdir`` themselves.
"""

from __future__ import annotations

from pathlib import Path

from hey.domain.services.paths import (
    global_agents_md_path as _global_agents_md,
)
from hey.domain.services.paths import (
    global_auth_dir_path as _global_auth_dir,
)
from hey.domain.services.paths import (
    global_config_dir_path as _global_config_dir,
)
from hey.domain.services.paths import (
    global_config_file_path as _global_config_file,
)
from hey.domain.services.paths import (
    global_data_dir_path as _global_data_dir,
)


def global_config_dir() -> Path:
    """Return the user-level configuration directory for *hey* (creates if missing)."""
    path = _global_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def global_data_dir() -> Path:
    """Return the user-level data directory for *hey* (creates if missing)."""
    path = _global_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def global_auth_dir() -> Path:
    """Return the directory used to store authentication tokens (creates if missing)."""
    path = _global_auth_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def global_config_path() -> Path:
    """Return the full path to the global config file (``config.yaml``)."""
    return _global_config_file()


def global_agents_md_path() -> Path:
    """Return the full path to the global ``AGENTS.md``."""
    return _global_agents_md()
