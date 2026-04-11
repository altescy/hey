from typing import Protocol

from hey.domain.entities.tool import ToolName, ToolSpec


class IToolRepository(Protocol):
    def get_all_specs(self) -> list[ToolSpec]: ...
    def get_spec_by_name(self, name: ToolName) -> ToolSpec: ...
