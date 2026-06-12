from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile
from pathlib import Path

from hey.domain.entities.sandbox import FileSystemRule, PermissionProfile, SandboxExecRequest, SandboxExecResult
from hey.domain.services.sandbox import ISandboxRunner
from hey.infrastructure.sandbox.exceptions import SandboxUnavailableError


def _quote_sbpl(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve()


def _rules_for_profile(profile: PermissionProfile, cwd: Path) -> tuple[FileSystemRule, ...]:
    if profile.filesystem.mode == "unrestricted":
        return ()
    if profile.filesystem.entries:
        return profile.filesystem.entries
    if profile.filesystem.mode == "read_only":
        return (FileSystemRule(path=cwd, access="read"),)
    if profile.filesystem.mode == "workspace_write":
        return (FileSystemRule(path=cwd, access="write"),)
    return ()


def build_seatbelt_profile(profile: PermissionProfile, cwd: Path, *, temp_dir: Path | None = None) -> str:
    temp_dir = _canonical(temp_dir) if temp_dir is not None else _canonical(Path(tempfile.gettempdir()))
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow signal (target same-sandbox))",
        "(allow process-info* (target same-sandbox))",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
        '(allow file-read* file-test-existence (literal "/"))',
        '(allow file-read* (subpath "/System"))',
        '(allow file-read* (subpath "/Library"))',
        '(allow file-read* (subpath "/usr"))',
        '(allow file-read* (subpath "/bin"))',
        '(allow file-read* (subpath "/sbin"))',
        '(allow file-read* (subpath "/etc"))',
        '(allow file-read* (subpath "/private/etc"))',
        '(allow file-read* (subpath "/opt/homebrew"))',
        '(allow file-read* (subpath "/private/var/db"))',
        '(allow file-map-executable (subpath "/usr/lib"))',
        '(allow file-map-executable (subpath "/System/Library/Frameworks"))',
        '(allow file-map-executable (subpath "/System/Library/PrivateFrameworks"))',
        '(allow file-read* (literal "/dev/null"))',
        '(allow file-read* (literal "/dev/urandom"))',
        '(allow file-read* (literal "/dev/random"))',
        '(allow file-write* (literal "/dev/null"))',
        '(allow file-read* (subpath "/dev/fd"))',
        '(allow file-write* (subpath "/dev/fd"))',
        f"(allow file* (subpath {_quote_sbpl(str(temp_dir))}))",
        '(allow mach-lookup (global-name "com.apple.cfprefsd.agent"))',
        '(allow mach-lookup (global-name "com.apple.cfprefsd.daemon"))',
        '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo"))',
        '(allow mach-lookup (global-name "com.apple.system.DirectoryService.libinfo_v1"))',
        '(allow mach-lookup (global-name "com.apple.trustd"))',
        '(allow mach-lookup (global-name "com.apple.trustd.agent"))',
    ]

    if profile.filesystem.mode == "unrestricted":
        lines.append("(allow file*)")
    else:
        for rule in _rules_for_profile(profile, cwd):
            path = _canonical(rule.path)
            if rule.access in {"read", "write"}:
                lines.append(f"(allow file-read* (subpath {_quote_sbpl(str(path))}))")
            if rule.access == "write":
                lines.append(f"(allow file-write* (subpath {_quote_sbpl(str(path))}))")

        for rule in _rules_for_profile(profile, cwd):
            root = _canonical(rule.path)
            for name in profile.filesystem.protected_names:
                protected = root / name
                lines.append(f"(deny file-write* (subpath {_quote_sbpl(str(protected))}))")

    if profile.network.mode == "enabled":
        lines.append("(allow network*)")
    else:
        lines.append("(deny network*)")

    return "\n".join(lines) + "\n"


class MacOSSandboxRunner(ISandboxRunner):
    def __init__(self, sandbox_exec_path: str = "/usr/bin/sandbox-exec") -> None:
        self._sandbox_exec_path = sandbox_exec_path

    async def run(self, request: SandboxExecRequest) -> SandboxExecResult:
        if shutil.which(self._sandbox_exec_path) is None and not Path(self._sandbox_exec_path).exists():
            raise SandboxUnavailableError("sandbox-exec is not available on this system")

        with tempfile.TemporaryDirectory(prefix="hey-sandbox-") as temp_dir:
            profile = build_seatbelt_profile(request.profile, request.cwd, temp_dir=Path(temp_dir))
            env = dict(request.env)
            env.update({"TMPDIR": temp_dir, "TMP": temp_dir, "TEMP": temp_dir})
            return await self._run_with_profile(request, profile, env)

    async def _run_with_profile(
        self,
        request: SandboxExecRequest,
        profile: str,
        env: dict[str, str],
    ) -> SandboxExecResult:
        with tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False) as profile_file:
            profile_file.write(profile)
            profile_path = profile_file.name

        try:
            process = await asyncio.create_subprocess_exec(
                self._sandbox_exec_path,
                "-f",
                profile_path,
                *request.command,
                cwd=request.cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=request.timeout_seconds)
            except TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                return SandboxExecResult(
                    exit_code=-1,
                    stdout=stdout.decode(errors="replace"),
                    stderr=stderr.decode(errors="replace"),
                    timed_out=True,
                )

            return SandboxExecResult(
                exit_code=process.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(profile_path)
