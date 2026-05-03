from hey.domain.entities.tool import ToolName, ToolSpec
from hey.domain.repositories.tool import IToolRepository
from hey.infrastructure.tool.builtins import bash, edit, glob, grep, ls, read, web_fetch, web_search

# Each entry pairs an availability check with the corresponding factory.
# Tools whose is_available() returns False are silently skipped at startup.
_BUILTIN_TOOL_ENTRIES = [
    (bash.is_available, bash.create_tool_spec),
    (edit.is_available, edit.create_tool_spec),
    (glob.is_available, glob.create_tool_spec),
    (grep.is_available, grep.create_tool_spec),
    (ls.is_available, ls.create_tool_spec),
    (read.is_available, read.create_tool_spec),
    (web_fetch.is_available, web_fetch.create_tool_spec),
    (web_search.is_available, web_search.create_tool_spec),
]


class BuiltinToolRepository(IToolRepository):
    def __init__(self) -> None:
        tools = [create_spec() for is_available, create_spec in _BUILTIN_TOOL_ENTRIES if is_available()]
        self._tools = {tool.name: tool for tool in tools}

    def get_all_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_spec_by_name(self, name: ToolName) -> ToolSpec:
        return self._tools[name]
