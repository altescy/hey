import os
import re
from pathlib import Path
from typing import Optional

from hey.domain.entities.sandbox import PermissionProfile, SandboxExecRequest
from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable
from hey.infrastructure.sandbox.noop import NoopSandboxRunner
from hey.infrastructure.sandbox.protocol import SandboxRunner

_DESCRIPTION = """
Execute a shell command and return its combined stdout/stderr output.

Be aware of the current OS and shell environment when composing commands.
All commands run in the current working directory unless `workdir` is specified.

Parameters:
- command: Shell command to run.
- workdir: Optional directory to run in.
- timeout: Timeout in milliseconds. The process is killed when exceeding the timeout
  (default: 120000ms / 2 minutes).
"""

_DEFAULT_TIMEOUT_MS = 120_000


def is_available() -> bool:
    return True


def _code_fence_for(prefix: str, output: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", f"{prefix}\n{output}")), default=0)
    return "`" * max(3, longest + 1)


def _resolve_workdir(workdir: str | None) -> Path:
    if workdir is None:
        return Path.cwd()
    return Path(workdir).expanduser().resolve()


def _shell_command(command: str) -> list[str]:
    return ["/bin/sh", "-c", command]


def _format_result(output: str, exit_code: int, timed_out: bool) -> str:
    if timed_out:
        return f"{output}\nCommand timed out."
    if exit_code == 0:
        return output
    return f"{output}\nCommand exited with status {exit_code}."


def create_tool_spec(
    sandbox_runner: SandboxRunner | None = None,
    permission_profile: PermissionProfile | None = None,
) -> ToolSpec:
    runner = sandbox_runner or NoopSandboxRunner()
    profile = permission_profile or PermissionProfile(enforcement="disabled")

    async def bash(command: str, workdir: Optional[str] = None, timeout: Optional[int] = None) -> str:
        """Execute a shell command and return its output."""

        cwd = _resolve_workdir(workdir)
        timeout_seconds = (timeout or _DEFAULT_TIMEOUT_MS) / 1000
        result = await runner.run(
            SandboxExecRequest(
                command=_shell_command(command),
                cwd=cwd,
                env=os.environ,
                profile=profile,
                timeout_seconds=timeout_seconds,
            )
        )
        return _format_result(result.output, result.exit_code, result.timed_out)

    async def render_markdown(
        output: str, command: str, workdir: Optional[str] = None, timeout: Optional[int] = None
    ) -> str:
        prefix = f"$ {command}"
        if workdir:
            prefix = f"[{workdir}] {prefix}"
        fence = _code_fence_for(prefix, output)
        return f"{fence}\n{prefix}\n\n{output}\n{fence}"

    return generate_tool_spec_from_callable(
        bash,
        name="bash",
        description=_DESCRIPTION,
        permission={
            "command.*": "ask",
            "command.ls": "allow",
            "command.ls *": "allow",
            "command.pwd": "allow",
            "command.rtk ls": "allow",
            "command.rtk ls *": "allow",
            "command.rtk pwd": "allow",
        },
        render=render_markdown,
    )
