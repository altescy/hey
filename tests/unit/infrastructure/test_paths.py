"""Tests for the centralised path module."""

from pathlib import Path

from hey.infrastructure.paths import (
    global_agents_md_path,
    global_auth_dir,
    global_config_dir,
    global_config_path,
    global_data_dir,
)


def test_global_config_dir_returns_existing_directory() -> None:
    path = global_config_dir()
    assert isinstance(path, Path)
    assert path.is_dir()
    assert path.name == "hey"


def test_global_data_dir_returns_existing_directory() -> None:
    path = global_data_dir()
    assert isinstance(path, Path)
    assert path.is_dir()


def test_global_auth_dir_returns_existing_subdirectory() -> None:
    path = global_auth_dir()
    assert isinstance(path, Path)
    assert path.is_dir()
    assert path.name == "auth"
    assert path.parent == global_config_dir()


def test_global_config_path_is_under_config_dir() -> None:
    path = global_config_path()
    assert path.parent == global_config_dir()
    assert path.name == "config.yaml"


def test_global_agents_md_path_is_under_config_dir() -> None:
    path = global_agents_md_path()
    assert path.parent == global_config_dir()
    assert path.name == "AGENTS.md"
