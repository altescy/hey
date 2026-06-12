from __future__ import annotations

from pathlib import Path
from typing import Protocol

from hey.domain.entities.sandbox import (
    FileAccess,
    FileSystemMode,
    FileSystemPolicy,
    FileSystemRule,
    NetworkMode,
    NetworkPolicy,
    PermissionProfile,
    SandboxEnforcement,
    SandboxExecRequest,
    SandboxExecResult,
)
from hey.domain.exceptions.tool import ToolCallDenied


class ISandboxRunner(Protocol):
    async def run(self, request: SandboxExecRequest) -> SandboxExecResult: ...


def build_workspace_permission_profile(
    workspace: Path,
    *,
    mode: FileSystemMode = "workspace_write",
    network: NetworkMode = "restricted",
    enforcement: SandboxEnforcement = "managed",
) -> PermissionProfile:
    workspace = workspace.resolve()
    entries: list[FileSystemRule] = []

    if mode == "read_only":
        entries.append(FileSystemRule(path=workspace, access="read"))
    elif mode == "workspace_write":
        entries.append(FileSystemRule(path=workspace, access="write"))
    elif mode != "unrestricted":
        raise ValueError(f"unsupported sandbox filesystem mode: {mode}")

    return PermissionProfile(
        filesystem=FileSystemPolicy(mode=mode, entries=tuple(entries)),
        network=NetworkPolicy(mode=network),
        enforcement=enforcement,
    )


def resolve_tool_path(path: str | None, *, project_directory: Path) -> Path:
    if path is None:
        return project_directory.resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = project_directory / candidate
    return candidate.resolve()


def assert_path_access(path: Path, *, profile: PermissionProfile, access: FileAccess) -> None:
    path = path.resolve()
    if profile.enforcement == "disabled" or profile.filesystem.mode == "unrestricted":
        return

    if _is_protected(path, profile):
        raise ToolCallDenied(f"{access} access to protected path is denied: {path}")

    if _matches_rule(path, profile, "deny"):
        raise ToolCallDenied(f"{access} access denied by sandbox policy: {path}")

    if access == "read":
        if _matches_rule(path, profile, "read") or _matches_rule(path, profile, "write"):
            return
    elif access == "write":
        if _matches_rule(path, profile, "write"):
            return

    raise ToolCallDenied(f"{access} access outside the sandbox is denied: {path}")


def _matches_rule(path: Path, profile: PermissionProfile, access: FileAccess) -> bool:
    return any(
        rule.access == access and _is_relative_or_same(path, rule.path.resolve()) for rule in profile.filesystem.entries
    )


def _is_protected(path: Path, profile: PermissionProfile) -> bool:
    for rule in profile.filesystem.entries:
        root = rule.path.resolve()
        if not _is_relative_or_same(path, root):
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        return any(part in profile.filesystem.protected_names for part in relative.parts)
    return False


def _is_relative_or_same(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)
