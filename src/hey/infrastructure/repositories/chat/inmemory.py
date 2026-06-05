from collections import defaultdict
from typing import Any, Self

from hey.domain.entities.chat import ChatMessage, ChatMessageID, ChatMessageKind, ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMMessage
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import (
    ChatMessageRetrievalRequest,
    ChatMessageRetrievalResponse,
    IChatRepository,
)
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

    def create_message(
        self,
        session_id: ChatSessionID,
        message: LLMMessage,
        *,
        kind: ChatMessageKind = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        message_id = ChatMessageID(len(self._messages[session_id]) + 1)
        timestamp = get_chat_timestamp()
        metadata = metadata or {}
        chat_message = ChatMessage(
            id=message_id,
            session_id=session_id,
            message=message,
            kind=kind,
            metadata=metadata,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._messages[session_id].append(chat_message)
        return chat_message

    def get_session_by_id(self, session_id: ChatSessionID) -> ChatSession | None:
        return self._sessions.get(session_id)

    def get_latest_session_by_project_id(self, project_id: ProjectID) -> ChatSession | None:
        sessions = [s for s in self._sessions.values() if s.project_id == project_id]
        if not sessions:
            return None
        return max(sessions, key=lambda s: s.updated_at)

    def get_messages_by_session_id(
        self,
        session_id: ChatSessionID,
        request: ChatMessageRetrievalRequest | None = None,
    ) -> ChatMessageRetrievalResponse:
        req = request or ChatMessageRetrievalRequest()
        all_messages = self._messages.get(session_id, [])
        return self._build_message_response(all_messages, req)

    def get_messages_by_project_id(
        self,
        project_id: ProjectID,
        request: ChatMessageRetrievalRequest | None = None,
    ) -> ChatMessageRetrievalResponse:
        req = request or ChatMessageRetrievalRequest()
        session_ids = {s.id for s in self._sessions.values() if s.project_id == project_id}
        all_messages = [m for sid in session_ids for m in self._messages.get(sid, [])]
        all_messages.sort(key=lambda m: (m.created_at, int(m.session_id), int(m.id)))
        return self._build_message_response(all_messages, req)

    def _build_message_response(
        self,
        all_messages: list[ChatMessage],
        request: ChatMessageRetrievalRequest,
    ) -> ChatMessageRetrievalResponse:
        query = (request.query or "").strip().lower()
        if query:
            filtered_messages = [
                msg
                for msg in all_messages
                if any(part["text"].lower().find(query) >= 0 for part in msg.message.get("parts", ()))
            ]
        else:
            filtered_messages = all_messages

        total = len(filtered_messages)
        start = max(request.offset, 0)

        if request.limit is None:
            results = filtered_messages[start:]
            next_offset = None
        else:
            end = start + max(request.limit, 0)
            results = filtered_messages[start:end]
            next_offset = end if end < total else None

        return ChatMessageRetrievalResponse(results=list(results), total=total, next_offset=next_offset)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass
