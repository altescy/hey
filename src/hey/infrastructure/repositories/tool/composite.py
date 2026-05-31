from hey.domain.entities.tool import ToolName, ToolSpec
from hey.domain.repositories.tool import IToolRepository


class CompositeToolRepository(IToolRepository):
    def __init__(self, repositories: list[IToolRepository]) -> None:
        self._tools: dict[ToolName, ToolSpec] = {}
        for repository in repositories:
            for spec in repository.get_all_specs():
                self._tools[spec.name] = spec

    def get_all_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_spec_by_name(self, name: ToolName) -> ToolSpec:
        return self._tools[name]
