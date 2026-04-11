import asyncio

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable


def create_bash_tool_spec() -> ToolSpec:
    async def bash(command: str) -> str:
        """Execute a bash command and return its output."""
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        output = stdout.decode().strip()
        if process.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {process.returncode}:\n{output}")
        return output

    return generate_tool_spec_from_callable(
        bash,
        name="bash",
        description="Execute a bash command and return its output.",
        permission={"command.*": "ask", "command.ls *": "allow"},
    )
