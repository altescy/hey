"""Tests for hey.domain.services.project."""

import pytest

from hey.domain.services.project import (
    HEY_CONFIG_FILENAME,
    HEY_DOT_DIRECTORY_NAME,
    get_hey_config_path,
    get_hey_dot_directory,
    get_project_directory,
    get_project_id_from_path,
)


class TestGetProjectIdFromPath:
    def test_returns_absolute_path_string(self, tmp_path) -> None:
        project_id = get_project_id_from_path(tmp_path)
        assert project_id == str(tmp_path.resolve())

    def test_resolves_relative_path(self) -> None:
        project_id = get_project_id_from_path(".")
        import os

        assert project_id == os.getcwd()

    @pytest.mark.parametrize("path_input", [".", "/tmp", "/usr/local"])
    def test_result_is_always_absolute(self, path_input: str) -> None:
        project_id = get_project_id_from_path(path_input)
        assert project_id.startswith("/")

    def test_same_path_gives_same_id(self, tmp_path) -> None:
        id1 = get_project_id_from_path(tmp_path)
        id2 = get_project_id_from_path(str(tmp_path))
        assert id1 == id2


class TestGetProjectDirectory:
    def test_returns_given_directory_when_no_markers(self, tmp_path) -> None:
        # tmp_path には何もマーカーがないので、tmp_path 自身を返す
        result = get_project_directory(tmp_path)
        assert result == tmp_path.resolve()

    def test_resolves_string_input(self, tmp_path) -> None:
        result = get_project_directory(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_finds_root_with_git_marker(self, tmp_path) -> None:
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "src" / "pkg"
        subdir.mkdir(parents=True)
        result = get_project_directory(subdir)
        assert result == tmp_path

    def test_finds_root_with_hey_yaml_marker(self, tmp_path) -> None:
        (tmp_path / HEY_CONFIG_FILENAME).touch()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = get_project_directory(subdir)
        assert result == tmp_path

    def test_prefers_nearest_marker(self, tmp_path) -> None:
        # ルートと中間の両方にマーカーがある場合、最も近い（深い）ものを返す
        (tmp_path / ".git").mkdir()
        inner = tmp_path / "inner"
        inner.mkdir()
        (inner / ".git").mkdir()
        subdir = inner / "src"
        subdir.mkdir()
        result = get_project_directory(subdir)
        assert result == inner

    def test_file_path_uses_parent_directory(self, tmp_path) -> None:
        (tmp_path / ".git").mkdir()
        file = tmp_path / "file.txt"
        file.touch()
        result = get_project_directory(file)
        assert result == tmp_path


class TestGetHeyConfigPath:
    def test_returns_config_filename_under_directory(self, tmp_path) -> None:
        config_path = get_hey_config_path(tmp_path)
        assert config_path == tmp_path / HEY_CONFIG_FILENAME

    def test_filename_is_hey_yaml(self, tmp_path) -> None:
        config_path = get_hey_config_path(tmp_path)
        assert config_path.name == "hey.yaml"


class TestGetHeyDotDirectory:
    def test_returns_dot_directory_under_project(self, tmp_path) -> None:
        dot_dir = get_hey_dot_directory(tmp_path)
        assert dot_dir == tmp_path / HEY_DOT_DIRECTORY_NAME

    def test_directory_name_starts_with_dot(self, tmp_path) -> None:
        dot_dir = get_hey_dot_directory(tmp_path)
        assert dot_dir.name.startswith(".")
