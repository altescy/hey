from hey.domain.entities.tool import ToolSpec
from hey.domain.repositories.tool import IToolRepository
from hey.domain.services.tool import generate_tool_spec_from_callable


def _create_bash_tool_spec() -> ToolSpec:
    import subprocess

    async def bash_command(command: str) -> str:
        """Execute a bash command and return its output."""
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip()

    return generate_tool_spec_from_callable(
        bash_command,
        name="bash_command",
        description="Execute a bash command and return its output.",
    )


class BuiltinToolRepository(IToolRepository):
    def __init__(self) -> None:
        tools = [_create_bash_tool_spec()]

        self._tools = {tool.name: tool for tool in tools}

    def get_all_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_spec_by_name(self, name: str) -> ToolSpec:
        return self._tools[name]


if __name__ == "__main__":
    from hey.domain.services.tool import generate_tool_definition_from_spec

    spec = _create_bash_tool_spec()
    definition = generate_tool_definition_from_spec(spec)
    print(spec)
    print(definition)
