from __future__ import annotations

from pathlib import Path

from hey.domain.entities.sandbox import (
    FileSystemMode,
    FileSystemPolicy,
    FileSystemRule,
    NetworkMode,
    NetworkPolicy,
    PermissionProfile,
    SandboxEnforcement,
)


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
    elif mode == "unrestricted":
        pass
    elif mode != "custom":
        raise ValueError(f"unsupported sandbox filesystem mode: {mode}")

    return PermissionProfile(
        filesystem=FileSystemPolicy(mode=mode, entries=tuple(entries)),
        network=NetworkPolicy(mode=network),
        enforcement=enforcement,
    )
