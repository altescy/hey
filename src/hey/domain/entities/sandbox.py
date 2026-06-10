from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

type SandboxEnforcement = Literal["managed", "external", "disabled"]
type FileSystemMode = Literal["read_only", "workspace_write", "unrestricted", "custom"]
type FileAccess = Literal["read", "write", "deny"]
type NetworkMode = Literal["restricted", "enabled", "proxy_only"]
type ApprovalPolicy = Literal["never", "on_request", "on_failure", "untrusted"]
type SandboxStdio = Literal["capture", "inherit"]


@dataclasses.dataclass(frozen=True, slots=True)
class FileSystemRule:
    path: Path
    access: FileAccess


@dataclasses.dataclass(frozen=True, slots=True)
class FileSystemPolicy:
    mode: FileSystemMode = "workspace_write"
    entries: tuple[FileSystemRule, ...] = ()
    protected_names: tuple[str, ...] = (".git", ".hey", ".agents", ".codex")


@dataclasses.dataclass(frozen=True, slots=True)
class NetworkPolicy:
    mode: NetworkMode = "restricted"


@dataclasses.dataclass(frozen=True, slots=True)
class CommandRule:
    pattern: str
    action: Literal["allow", "ask", "deny"]


@dataclasses.dataclass(frozen=True, slots=True)
class CommandPolicy:
    rules: tuple[CommandRule, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class PermissionProfile:
    filesystem: FileSystemPolicy = dataclasses.field(default_factory=FileSystemPolicy)
    network: NetworkPolicy = dataclasses.field(default_factory=NetworkPolicy)
    approval: ApprovalPolicy = "on_request"
    command: CommandPolicy = dataclasses.field(default_factory=CommandPolicy)
    enforcement: SandboxEnforcement = "managed"


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxExecRequest:
    command: Sequence[str]
    cwd: Path
    env: Mapping[str, str]
    profile: PermissionProfile
    timeout_seconds: float | None = None
    stdio: SandboxStdio = "capture"
    temp_dir: Path | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def output(self) -> str:
        if not self.stderr:
            return self.stdout
        if not self.stdout:
            return self.stderr
        return f"{self.stdout}{self.stderr}"
