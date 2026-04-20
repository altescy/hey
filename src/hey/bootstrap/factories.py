"""Factories that wire config and infrastructure into domain objects."""

from __future__ import annotations

from pathlib import Path

from hey.domain.entities.agent import LLMAgentSpec
from hey.domain.entities.config import ChatConfig
from hey.domain.entities.tool import AskPermissionFunc
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.project import get_hey_dot_directory
from hey.infrastructure.chat import InMemoryChatRepository, SQLiteChatRepository
from hey.infrastructure.tool import BuiltinToolRepository

from .llm import build_llm_spec


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


def build_chat_repository(
    project_directory: Path,
    *,
    temporary: bool = False,
) -> IChatRepository:
    if temporary:
        return InMemoryChatRepository()
    return SQLiteChatRepository(get_hey_dot_directory(project_directory) / "hey.db")
