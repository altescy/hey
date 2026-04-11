from hey.domain.entities.tool import ToolSpec
from hey.domain.repositories.tool import IToolRepository

from ..builtins import create_bash_tool_spec


class BuiltinToolRepository(IToolRepository):
    def __init__(self) -> None:
        tools = [create_bash_tool_spec()]

        self._tools = {tool.name: tool for tool in tools}

    def get_all_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_spec_by_name(self, name: str) -> ToolSpec:
        return self._tools[name]
