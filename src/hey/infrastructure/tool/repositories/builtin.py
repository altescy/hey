from hey.domain.entities.tool import ToolName, ToolSpec
from hey.domain.repositories.tool import IToolRepository

from .. import builtins


class BuiltinToolRepository(IToolRepository):
    def __init__(self) -> None:
        tools = [
            builtins.create_read_tool_spec(),
            builtins.create_edit_tool_spec(),
            builtins.create_bash_tool_spec(),
            builtins.create_ls_tool_spec(),
            builtins.create_glob_tool_spec(),
            builtins.create_grep_tool_spec(),
            builtins.create_web_fetch_tool_spec(),
            builtins.create_web_search_tool_spec(),
        ]

        self._tools = {tool.name: tool for tool in tools}

    def get_all_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_spec_by_name(self, name: ToolName) -> ToolSpec:
        return self._tools[name]
