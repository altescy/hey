"""Factories that wire config and infrastructure into domain objects."""

from __future__ import annotations

from pathlib import Path

from hey.domain.entities.agent import LLMAgentSpec
from hey.domain.entities.config import ChatConfig
from hey.domain.entities.llm import LLMSpec
from hey.domain.entities.project import ProjectID
from hey.domain.entities.tool import AskPermissionFunc
from hey.domain.repositories.chat import IChatRepository
from hey.domain.repositories.tool import IToolRepository
from hey.domain.services.agentsmd import build_agents_instructions
from hey.domain.services.project import get_hey_dot_directory
from hey.infrastructure.repositories.chat import InMemoryChatRepository, SQLiteChatRepository
from hey.infrastructure.repositories.project import LocalProjectRepository
from hey.infrastructure.repositories.tool import BuiltinToolRepository, CompositeToolRepository, MCPToolRepository
from hey.infrastructure.tool.builtins.dependencies import ToolDependencies

from .constants import (
    CODEX_MODEL_PREFIX,
    COPILOT_MODEL_PREFIX,
    HEY_DB_FILENAME,
    OPENCODE_GO_MODEL_PREFIX,
    OPENCODE_MODEL_PREFIX,
)


def _merge_instructions(config_instructions: str, agentsmd_instructions: str | None) -> str:
    if not agentsmd_instructions:
        return config_instructions
    if not config_instructions.strip():
        return agentsmd_instructions
    return f"{agentsmd_instructions}\n\n{config_instructions}"


def build_llm_spec(config: ChatConfig, *, project_directory: Path | None = None) -> LLMSpec:
    model = config.model
    agentsmd = build_agents_instructions(project_directory) if project_directory else None
    instructions = _merge_instructions(config.instructions, agentsmd)

    if model.startswith(COPILOT_MODEL_PREFIX):
        from hey.infrastructure.llm.copilot import get_copilot_spec

        return get_copilot_spec(model=model[len(COPILOT_MODEL_PREFIX) :], instructions=instructions)

    if model.startswith(CODEX_MODEL_PREFIX):
        from hey.infrastructure.llm.codex import get_codex_spec

        return get_codex_spec(model=model[len(CODEX_MODEL_PREFIX) :], instructions=instructions)

    if model.startswith(OPENCODE_GO_MODEL_PREFIX):
        from hey.infrastructure.llm.opencode import get_opencode_spec

        return get_opencode_spec(
            model=model[len(OPENCODE_GO_MODEL_PREFIX) :],
            base_url="https://opencode.ai/zen/go/v1/chat/completions",
            instructions=instructions,
        )

    if model.startswith(OPENCODE_MODEL_PREFIX):
        from hey.infrastructure.llm.opencode import get_opencode_spec

        return get_opencode_spec(
            model=model[len(OPENCODE_MODEL_PREFIX) :],
            base_url="https://opencode.ai/zen/v1/chat/completions",
            instructions=instructions,
        )

    from hey.infrastructure.llm.litellm import get_litellm_spec

    return get_litellm_spec(model=model, instructions=instructions)


def build_agent_spec(
    config: ChatConfig,
    tool_repository: IToolRepository,
    *,
    project_directory: Path | None = None,
    ask_permission: AskPermissionFunc | None = None,
) -> LLMAgentSpec:  # type: ignore[type-arg]
    return LLMAgentSpec(
        llm=build_llm_spec(config, project_directory=project_directory),
        instructions=config.instructions,
        response_format=str,
        tools=tool_repository.get_all_specs(),
        permission=config.permission,
        ask_permission=ask_permission,
    )


def build_project_repository() -> LocalProjectRepository:
    return LocalProjectRepository()


def build_chat_repository(
    project_directory: Path,
    *,
    temporary: bool = False,
) -> IChatRepository:
    if temporary:
        return InMemoryChatRepository()
    return SQLiteChatRepository(get_hey_dot_directory(project_directory) / HEY_DB_FILENAME)


def build_tool_dependencies(project_id: ProjectID, chat_repository: IChatRepository) -> ToolDependencies:
    return ToolDependencies(chat_repository=chat_repository, project_id=project_id)


def build_tool_repository(config: ChatConfig, dependencies: ToolDependencies) -> IToolRepository:
    repositories: list[IToolRepository] = [BuiltinToolRepository(dependencies)]
    if config.mcp:
        repositories.append(MCPToolRepository(config.mcp))
    return CompositeToolRepository(repositories)
