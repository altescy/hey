from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable


def create_bash_tool_spec() -> ToolSpec:
    import subprocess

    async def bash_command(command: str) -> str:
        """Execute a bash command and return its output."""
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {result.returncode}: {result.stderr.strip()}")
        return result.stdout.strip()

    return generate_tool_spec_from_callable(
        bash_command,
        name="bash_command",
        description="Execute a bash command and return its output.",
    )
