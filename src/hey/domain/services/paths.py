"""Pure path construction for global configuration and data directories.

These functions only build ``Path`` objects; they do **not** perform I/O
(create directories, read files, etc.).
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "hey"
_DIRS = PlatformDirs(_APP_NAME)


def global_config_dir_path() -> Path:
    """Return the user-level configuration directory path for *hey*."""
    return Path(_DIRS.user_config_dir)


def global_data_dir_path() -> Path:
    """Return the user-level data directory path for *hey*."""
    return Path(_DIRS.user_data_dir)


def global_auth_dir_path() -> Path:
    """Return the path to the auth token subdirectory."""
    return global_config_dir_path() / "auth"


def global_config_file_path() -> Path:
    """Return the path to the global ``config.yaml``."""
    return global_config_dir_path() / "config.yaml"


def global_agents_md_path() -> Path:
    """Return the path to the global ``AGENTS.md``."""
    return global_config_dir_path() / "AGENTS.md"
