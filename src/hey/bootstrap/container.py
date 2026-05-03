import dataclasses
from os import PathLike
from typing import Self

from hey.application.usecases.chat import AgentChatUseCase
from hey.application.usecases.project import ProjectUseCase
from hey.domain.entities.tool import AskPermissionFunc

from .factories import (
    build_agent_spec,
    build_chat_repository,
    build_project_repository,
    build_tool_dependencies,
    build_tool_repository,
)


@dataclasses.dataclass
class Container:
    project_usecase: ProjectUseCase
    chat_usecase: AgentChatUseCase

    @classmethod
    def build(
        cls,
        *,
        project_directory: str | PathLike = ".",
        temporary: bool = False,
        ask_permission: AskPermissionFunc | None = None,
    ) -> Self:
        from hey.application.dto import GetProjectInput

        project_repository = build_project_repository()
        project_usecase = ProjectUseCase(project_repository=project_repository)

        project = project_usecase.get_project(GetProjectInput(path=project_directory))["project"]

        chat_repository = build_chat_repository(project.directory, temporary=temporary)
        tool_dependencies = build_tool_dependencies(project.id, chat_repository)
        tool_repository = build_tool_repository(project.config.chat, tool_dependencies)
        agent_spec = build_agent_spec(project.config.chat, tool_repository, ask_permission=ask_permission)
        chat_usecase = AgentChatUseCase(agent=agent_spec, chat_repository=chat_repository)

        return cls(
            project_usecase=project_usecase,
            chat_usecase=chat_usecase,
        )
