import asyncio
from typing import Optional

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable

_DESCRIPTION = """\
Execute a shell command and return its combined stdout/stderr output.

Be aware of the current OS and shell environment when composing commands.

All commands run in the current working directory unless `workdir` is specified.
Use `workdir` to run in a different directory instead of prefixing with `cd <dir> &&`.

Parameters:
- command: The shell command to run.
- workdir: Optional directory to run the command in (default: current directory).
- timeout: Optional timeout in milliseconds. Commands exceeding this limit are \
killed and an error is raised (default: 120000ms / 2 minutes).

Notes:
- stdout and stderr are merged into a single output stream. \
A non-zero exit code raises an error containing the output.
- Commands requiring interactive input will hang; avoid them.
- Prefer dedicated file tools (read, edit) over shell equivalents \
like cat, echo, or sed.
- Use this tool for running tests, builds, git operations, or any \
process that has no dedicated tool.
""".strip()


def is_available() -> bool:
    return True


def create_bash_tool_spec() -> ToolSpec:
    async def bash(
        command: str,
        workdir: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """Execute a bash command and return its output."""
        cwd = workdir if workdir is not None else None
        timeout_sec = (timeout / 1000.0) if timeout is not None else 120.0

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError(f"Command timed out after {timeout_sec:.0f}s: {command}")

        output = stdout.decode().strip()
        if process.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {process.returncode}:\n{output}")
        return output

    async def render_markdown(
        output: str, command: str, workdir: Optional[str] = None, timeout: Optional[int] = None
    ) -> str:
        prefix = f"$ {command}"
        if workdir:
            prefix = f"[{workdir}] {prefix}"
        return f"```\n{prefix}\n\n{output}\n```"

    return generate_tool_spec_from_callable(
        bash,
        name="bash",
        description=_DESCRIPTION,
        permission={"command.*": "ask", "command.ls *": "allow"},
        render_markdown=render_markdown,
    )
