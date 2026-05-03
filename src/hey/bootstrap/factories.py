"""Factories that wire config and infrastructure into domain objects."""

from __future__ import annotations

from pathlib import Path

from hey.domain.entities.agent import LLMAgentSpec
from hey.domain.entities.config import ChatConfig
from hey.domain.entities.llm import LLMSpec
from hey.domain.entities.tool import AskPermissionFunc
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.project import get_hey_dot_directory
from hey.infrastructure.repositories.chat import InMemoryChatRepository, SQLiteChatRepository
from hey.infrastructure.repositories.project import LocalProjectRepository
from hey.infrastructure.repositories.tool import BuiltinToolRepository

from .constants import CODEX_MODEL_PREFIX, COPILOT_MODEL_PREFIX, HEY_DB_FILENAME


def build_llm_spec(config: ChatConfig) -> LLMSpec:
    model = config.model
    instructions = config.instructions

    if model.startswith(COPILOT_MODEL_PREFIX):
        from hey.infrastructure.llm.copilot import get_copilot_spec

        return get_copilot_spec(model=model[len(COPILOT_MODEL_PREFIX) :], instructions=instructions)

    if model.startswith(CODEX_MODEL_PREFIX):
        from hey.infrastructure.llm.codex import get_codex_spec

        return get_codex_spec(model=model[len(COPILOT_MODEL_PREFIX) :], instructions=instructions)

    from hey.infrastructure.llm.litellm import get_litellm_spec

    return get_litellm_spec(model=model, instructions=instructions)


def build_agent_spec(
    config: ChatConfig,
    *,
    ask_permission: AskPermissionFunc | None = None,
) -> LLMAgentSpec:  # type: ignore[type-arg]
    return LLMAgentSpec(
        llm=build_llm_spec(config),
        instructions=config.instructions,
        response_format=str,
        tools=BuiltinToolRepository().get_all_specs(),
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
