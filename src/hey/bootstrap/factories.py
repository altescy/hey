"""Factories that wire config and infrastructure into domain objects."""

from __future__ import annotations

from pathlib import Path

from hey.application.defaults import DEFAULT_CHAT_INSTRUCTIONS
from hey.domain.entities.agent import LLMAgentSpec
from hey.domain.entities.config import ChatConfig
from hey.domain.entities.llm import LLMSpec
from hey.domain.entities.project import ProjectID
from hey.domain.entities.tool import AskPermissionFunc
from hey.domain.repositories.chat import IChatRepository
from hey.domain.repositories.tool import IToolRepository
from hey.domain.services.agentsmd import build_agents_instructions
from hey.domain.services.project import get_hey_dot_directory
from hey.domain.services.sandbox import build_workspace_permission_profile
from hey.infrastructure.repositories.chat import InMemoryChatRepository, SQLiteChatRepository
from hey.infrastructure.repositories.project import LocalProjectRepository
from hey.infrastructure.repositories.tool import BuiltinToolRepository, CompositeToolRepository, MCPToolRepository
from hey.infrastructure.sandbox import build_sandbox_runner
from hey.infrastructure.tool.dependencies import ToolDependencies

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


def _resolve_chat_instructions(config: ChatConfig, *, project_directory: Path | None = None) -> str:
    config_instructions = (
        config.instructions if config.instructions and config.instructions.strip() else DEFAULT_CHAT_INSTRUCTIONS
    )
    agentsmd = build_agents_instructions(project_directory) if project_directory else None
    return _merge_instructions(config_instructions, agentsmd)


def build_llm_spec(config: ChatConfig, *, project_directory: Path | None = None) -> LLMSpec:
    model = config.model
    instructions = _resolve_chat_instructions(config, project_directory=project_directory)

    if model.startswith(COPILOT_MODEL_PREFIX):
        from hey.infrastructure.llm.specs.copilot import get_copilot_spec

        return get_copilot_spec(model=model[len(COPILOT_MODEL_PREFIX) :], instructions=instructions)

    if model.startswith(CODEX_MODEL_PREFIX):
        from hey.infrastructure.llm.specs.codex import get_codex_spec

        return get_codex_spec(model=model[len(CODEX_MODEL_PREFIX) :], instructions=instructions)

    if model.startswith(OPENCODE_GO_MODEL_PREFIX):
        from hey.infrastructure.llm.specs.opencode import get_opencode_spec

        return get_opencode_spec(
            model=model[len(OPENCODE_GO_MODEL_PREFIX) :],
            base_url="https://opencode.ai/zen/go/v1/chat/completions",
            instructions=instructions,
        )

    if model.startswith(OPENCODE_MODEL_PREFIX):
        from hey.infrastructure.llm.specs.opencode import get_opencode_spec

        return get_opencode_spec(
            model=model[len(OPENCODE_MODEL_PREFIX) :],
            base_url="https://opencode.ai/zen/v1/chat/completions",
            instructions=instructions,
        )

    from hey.infrastructure.llm.specs.litellm import get_litellm_spec

    return get_litellm_spec(model=model, instructions=instructions)


def build_agent_spec(
    config: ChatConfig,
    tool_repository: IToolRepository,
    *,
    project_directory: Path | None = None,
    ask_permission: AskPermissionFunc | None = None,
) -> LLMAgentSpec:  # type: ignore[type-arg]
    instructions = _resolve_chat_instructions(config, project_directory=project_directory)
    return LLMAgentSpec(
        llm=build_llm_spec(config, project_directory=project_directory),
        instructions=instructions,
        response_format=str,
        tools=tool_repository.get_all_specs(),
        permission=config.permission,
        ask_permission=ask_permission,
    )


def build_compaction_agent_spec(
    config: ChatConfig,
    *,
    project_directory: Path | None = None,
) -> LLMAgentSpec[str, str]:
    return LLMAgentSpec(
        llm=build_llm_spec(config, project_directory=project_directory),
        instructions=(
            "You are a precise conversation compaction agent. "
            "Summarize only the provided conversation context for future continuation. "
            "Do not call tools. Do not add facts that are not supported by the conversation."
        ),
        response_format=str,
        tools=(),
        permission={},
        ask_permission=None,
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


def build_tool_dependencies(
    project_id: ProjectID,
    chat_repository: IChatRepository,
    *,
    config: ChatConfig,
    project_directory: Path,
) -> ToolDependencies:
    enforcement = config.sandbox.enforcement if config.sandbox.enabled else "disabled"
    permission_profile = build_workspace_permission_profile(
        project_directory,
        mode=config.sandbox.filesystem,
        network=config.sandbox.network,
        enforcement=enforcement,
    )
    return ToolDependencies(
        chat_repository=chat_repository,
        project_id=project_id,
        project_directory=project_directory,
        sandbox_runner=build_sandbox_runner(permission_profile),
        permission_profile=permission_profile,
    )


def build_tool_repository(config: ChatConfig, dependencies: ToolDependencies) -> IToolRepository:
    repositories: list[IToolRepository] = [BuiltinToolRepository(dependencies)]
    if config.mcp:
        repositories.append(MCPToolRepository(config.mcp))
    return CompositeToolRepository(repositories)
