import dataclasses
from typing import Protocol, Self

from hey.domain.entities.chat import ChatMessage, ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMMessage
from hey.domain.entities.project import ProjectID


@dataclasses.dataclass
class ChatMessageRetrievalRequest:
    offset: int = 0
    limit: int | None = None
    query: str | None = None


@dataclasses.dataclass
class ChatSessionRetrievalResponse:
    results: list[ChatSession]
    total: int
    next_offset: int | None


@dataclasses.dataclass
class ChatMessageRetrievalResponse:
    results: list[ChatMessage]
    total: int
    next_offset: int | None


class IChatRepository(Protocol):
    def create_session(
        self,
        project_id: ProjectID,
    ) -> ChatSession: ...
    def create_message(
        self,
        session_id: ChatSessionID,
        message: LLMMessage,
    ) -> ChatMessage: ...
    def get_session_by_id(
        self,
        session_id: ChatSessionID,
    ) -> ChatSession | None: ...
    def get_latest_session_by_project_id(
        self,
        project_id: ProjectID,
    ) -> ChatSession | None: ...
    def get_messages_by_session_id(
        self, session_id: ChatSessionID, request: ChatMessageRetrievalRequest | None = None
    ) -> ChatMessageRetrievalResponse: ...
    def get_messages_by_project_id(
        self, project_id: ProjectID, request: ChatMessageRetrievalRequest | None = None
    ) -> ChatMessageRetrievalResponse: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
