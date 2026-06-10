from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from hey.domain.entities.project import ProjectID
from hey.domain.exceptions.tool import ToolCallDenied
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.sandbox import build_workspace_permission_profile
from hey.infrastructure.sandbox.noop import NoopSandboxRunner
from hey.infrastructure.tool.builtins import edit, glob, grep, ls, read
from hey.infrastructure.tool.builtins.dependencies import ToolDependencies


def _dependencies(project_directory: Path) -> ToolDependencies:
    return ToolDependencies(
        chat_repository=cast(IChatRepository, object()),
        project_id=ProjectID("test-project"),
        project_directory=project_directory,
        sandbox_runner=NoopSandboxRunner(),
        permission_profile=build_workspace_permission_profile(project_directory, enforcement="managed"),
    )


async def test_read_denies_file_outside_project(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    spec = read.create_tool_spec(_dependencies(project))

    with pytest.raises(ToolCallDenied, match="outside the sandbox"):
        await spec.func(str(outside))


async def test_read_denies_symlink_that_resolves_outside_project(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (project / "link.txt").symlink_to(outside)
    spec = read.create_tool_spec(_dependencies(project))

    with pytest.raises(ToolCallDenied, match="outside the sandbox"):
        await spec.func("link.txt")


@pytest.mark.parametrize(
    "tool_name",
    [
        "grep",
        "glob",
        "ls",
    ],
)
async def test_directory_tools_deny_path_outside_project(tmp_path, tool_name: str) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    dependencies = _dependencies(project)

    if tool_name == "grep":
        call = grep.create_tool_spec(dependencies).func("secret", path=str(outside))
    elif tool_name == "glob":
        call = glob.create_tool_spec(dependencies).func("*", path=str(outside))
    else:
        call = ls.create_tool_spec(dependencies).func(str(outside))

    with pytest.raises(ToolCallDenied, match="outside the sandbox"):
        await call


async def test_edit_denies_protected_project_directory(tmp_path) -> None:
    project = tmp_path / "project"
    protected = project / ".hey"
    protected.mkdir(parents=True)
    file_path = protected / "hey.db"
    file_path.write_text("old")
    spec = edit.create_tool_spec(_dependencies(project))

    with pytest.raises(ToolCallDenied, match="protected path"):
        await spec.func(".hey/hey.db", "old", "new")


async def test_file_tools_allow_project_paths(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    file_path = project / "notes.txt"
    file_path.write_text("hello")

    read_spec = read.create_tool_spec(_dependencies(project))
    grep_spec = grep.create_tool_spec(_dependencies(project))

    assert "hello" in await read_spec.func("notes.txt")
    assert "hello" in await grep_spec.func("hello", path=".")
