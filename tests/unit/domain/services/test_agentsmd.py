"""Tests for hey.domain.services.agentsmd."""

from hey.bootstrap.factories import _merge_instructions
from hey.domain.services.agentsmd import (
    AGENTS_MD_FILENAME,
    _find_up,
    build_agents_instructions,
    find_project_agents_md,
    load_agents_md,
)


class TestFindUp:
    def test_finds_file_in_start_directory(self, tmp_path) -> None:
        file = tmp_path / "marker.txt"
        file.write_text("x")
        result = _find_up(tmp_path, tmp_path, "marker.txt")
        assert result == file

    def test_finds_file_in_parent(self, tmp_path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        child = root / "child"
        child.mkdir()
        file = root / "marker.txt"
        file.write_text("x")
        result = _find_up(child, root, "marker.txt")
        assert result == file

    def test_stops_at_root(self, tmp_path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("x")
        child = root / "child"
        child.mkdir()
        result = _find_up(child, root, "outside.txt")
        assert result is None

    def test_prefers_nearest_match(self, tmp_path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        child = root / "child"
        child.mkdir()
        root_file = root / "marker.txt"
        root_file.write_text("root")
        child_file = child / "marker.txt"
        child_file.write_text("child")
        result = _find_up(child, root, "marker.txt")
        assert result == child_file


class TestFindProjectAgentsMd:
    def test_returns_none_when_no_agents_md(self, tmp_path) -> None:
        result = find_project_agents_md(tmp_path)
        assert result is None

    def test_finds_agents_md_in_project_root(self, tmp_path) -> None:
        file = tmp_path / AGENTS_MD_FILENAME
        file.write_text("project rules")
        result = find_project_agents_md(tmp_path)
        assert result == file

    def test_finds_agents_md_in_subdirectory(self, tmp_path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        file = sub / AGENTS_MD_FILENAME
        file.write_text("sub rules")
        result = find_project_agents_md(sub)
        assert result == file


class TestLoadAgentsMd:
    def test_loads_and_formats_content(self, tmp_path) -> None:
        file = tmp_path / "AGENTS.md"
        file.write_text("Use 4 spaces.\n")
        result = load_agents_md(file)
        assert result is not None
        assert result.startswith(f"Instructions from: {file}")
        assert "Use 4 spaces." in result

    def test_returns_none_for_empty_file(self, tmp_path) -> None:
        file = tmp_path / "AGENTS.md"
        file.write_text("   \n")
        result = load_agents_md(file)
        assert result is None

    def test_returns_none_for_missing_file(self, tmp_path) -> None:
        file = tmp_path / "AGENTS.md"
        result = load_agents_md(file)
        assert result is None


class TestBuildAgentsInstructions:
    def test_returns_none_when_no_agents_md_anywhere(self, tmp_path) -> None:
        result = build_agents_instructions(tmp_path)
        assert result is None

    def test_includes_project_agents_md(self, tmp_path) -> None:
        file = tmp_path / AGENTS_MD_FILENAME
        file.write_text("project rules")
        result = build_agents_instructions(tmp_path)
        assert result is not None
        assert "Instructions from:" in result
        assert "project rules" in result


class TestMergeInstructions:
    def test_returns_config_when_no_agentsmd(self) -> None:
        assert _merge_instructions("config", None) == "config"

    def test_returns_agentsmd_when_config_empty(self) -> None:
        assert _merge_instructions("", "agents") == "agents"

    def test_concatenates_both(self) -> None:
        merged = _merge_instructions("config", "agents")
        assert merged == "agents\n\nconfig"
