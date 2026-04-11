from collections import defaultdict
from typing import Self

from hey.domain.entities.chat import ChatMessage, ChatMessageID, ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMMessage
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.chat import get_chat_timestamp


class InMemoryChatRepository(IChatRepository):
    def __init__(self) -> None:
        self._sessions: dict[ChatSessionID, ChatSession] = {}
        self._messages: dict[ChatSessionID, list[ChatMessage]] = defaultdict(list)

    def create_session(self, project_id: ProjectID) -> ChatSession:
        session_id = ChatSessionID(len(self._sessions) + 1)
        timestamp = get_chat_timestamp()
        session = ChatSession(
            id=session_id,
            project_id=project_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._sessions[session_id] = session
        return session

    def create_message(self, session_id: ChatSessionID, message: LLMMessage) -> ChatMessage:
        message_id = ChatMessageID(len(self._messages[session_id]) + 1)
        timestamp = get_chat_timestamp()
        chat_message = ChatMessage(
            id=message_id,
            session_id=session_id,
            message=message,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.save_message(chat_message)
        return chat_message

    def get_session_by_id(self, session_id: ChatSessionID) -> ChatSession | None:
        return self._sessions.get(session_id)

    def save_message(self, message: ChatMessage) -> None:
        self._messages[message.session_id].append(message)

    def get_messages_by_session_id(self, session_id: ChatSessionID) -> list[ChatMessage]:
        return self._messages.get(session_id, [])

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass
