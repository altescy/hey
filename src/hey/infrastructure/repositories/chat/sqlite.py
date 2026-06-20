import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Final, Self

from pydantic import TypeAdapter

from hey.domain.entities.chat import ChatMessage, ChatMessageID, ChatMessageKind, ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMMessage
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import (
    ChatMessageRetrievalRequest,
    ChatMessageRetrievalResponse,
    ChatSessionListItem,
    ChatSessionRetrievalRequest,
    ChatSessionRetrievalResponse,
    IChatRepository,
)
from hey.domain.services.chat import get_chat_timestamp

_LLM_MESSAGE_TA: Final[TypeAdapter[LLMMessage]] = TypeAdapter(LLMMessage)

_SESSIONS_QUERY = """
SELECT
    s.*,
    COUNT(m.id) AS message_count,
    (
        SELECT m2.message
        FROM chat_messages AS m2
        WHERE m2.session_id = s.id AND m2.kind = 'normal'
        ORDER BY m2.id ASC
        LIMIT 1
    ) AS first_message_json
FROM chat_sessions AS s
LEFT JOIN chat_messages AS m ON m.session_id = s.id
WHERE s.project_id = ?
GROUP BY s.id
ORDER BY {order_column} {order_direction}
LIMIT ? OFFSET ?
"""

_COUNT_MESSAGES_BY_SESSION = """
SELECT COUNT(*) FROM chat_messages WHERE session_id = ?
"""

_COUNT_MESSAGES_BY_PROJECT = """
SELECT COUNT(m.id)
FROM chat_messages AS m
INNER JOIN chat_sessions AS s ON s.id = m.session_id
WHERE s.project_id = ?
"""

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)
"""

_CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES chat_sessions(id),
    message     TEXT    NOT NULL,
    kind        TEXT    NOT NULL DEFAULT 'normal',
    metadata    TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)
"""


class SQLiteChatRepository(IChatRepository):
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._initialize()

    # ------------------------------------------------------------------
    # Context manager (transaction boundary)
    # ------------------------------------------------------------------

    def __enter__(self) -> Self:
        self._conn.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            self._conn.execute("ROLLBACK")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initialize(self) -> None:
        with self:
            self._conn.execute(_CREATE_SESSIONS_TABLE)
            self._conn.execute(_CREATE_MESSAGES_TABLE)
            self._ensure_message_column("kind", "TEXT NOT NULL DEFAULT 'normal'")
            self._ensure_message_column("metadata", "TEXT NOT NULL DEFAULT '{}'")

    def _ensure_message_column(self, name: str, definition: str) -> None:
        cursor = self._conn.execute("PRAGMA table_info(chat_messages)")
        columns = {row["name"] for row in cursor.fetchall()}
        if name not in columns:
            self._conn.execute(f"ALTER TABLE chat_messages ADD COLUMN {name} {definition}")

    # ------------------------------------------------------------------
    # IChatRepository
    # ------------------------------------------------------------------

    def create_session(self, project_id: ProjectID) -> ChatSession:
        timestamp = get_chat_timestamp()
        cursor = self._conn.execute(
            "INSERT INTO chat_sessions (project_id, created_at, updated_at) VALUES (?, ?, ?)",
            (str(project_id), timestamp.isoformat(), timestamp.isoformat()),
        )
        session_id = ChatSessionID(cursor.lastrowid)  # type: ignore[arg-type]
        return ChatSession(
            id=session_id,
            project_id=project_id,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def create_message(
        self,
        session_id: ChatSessionID,
        message: LLMMessage,
        *,
        kind: ChatMessageKind = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        timestamp = get_chat_timestamp()
        message_json = json.dumps(_LLM_MESSAGE_TA.dump_python(message))
        metadata = metadata or {}
        metadata_json = json.dumps(metadata)
        cursor = self._conn.execute(
            """
            INSERT INTO chat_messages (session_id, message, kind, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(session_id), message_json, kind, metadata_json, timestamp.isoformat(), timestamp.isoformat()),
        )
        message_id = ChatMessageID(cursor.lastrowid)  # type: ignore[arg-type]
        return ChatMessage(
            id=message_id,
            session_id=session_id,
            message=message,
            kind=kind,
            metadata=metadata,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def get_session_by_id(self, session_id: ChatSessionID) -> ChatSession | None:
        cursor = self._conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (int(session_id),))
        row = cursor.fetchone()
        if row is None:
            return None
        return ChatSession(
            id=ChatSessionID(row["id"]),
            project_id=ProjectID(row["project_id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_latest_session_by_project_id(self, project_id: ProjectID) -> ChatSession | None:
        cursor = self._conn.execute(
            "SELECT * FROM chat_sessions WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
            (str(project_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return ChatSession(
            id=ChatSessionID(row["id"]),
            project_id=ProjectID(row["project_id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_sessions_by_project_id(
        self,
        project_id: ProjectID,
        request: ChatSessionRetrievalRequest | None = None,
    ) -> ChatSessionRetrievalResponse:
        req = request or ChatSessionRetrievalRequest()
        order_column = "updated_at" if req.sort_by == "updated_at" else "created_at"
        order_direction = "DESC" if req.reverse else "ASC"

        limit = max(req.limit, 0) if req.limit is not None else -1
        offset = max(req.offset, 0)

        total_cursor = self._conn.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE project_id = ?",
            (str(project_id),),
        )
        total: int = total_cursor.fetchone()[0]

        query = _SESSIONS_QUERY.format(order_column=order_column, order_direction=order_direction)
        cursor = self._conn.execute(query, (str(project_id), limit, offset))

        results = []
        for row in cursor.fetchall():
            session = ChatSession(
                id=ChatSessionID(row["id"]),
                project_id=ProjectID(row["project_id"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            preview = self._extract_preview(row["first_message_json"])
            results.append(
                ChatSessionListItem(
                    session=session,
                    message_count=row["message_count"],
                    preview=preview,
                )
            )

        if req.limit is None:
            next_offset: int | None = None
        else:
            next_candidate = offset + limit
            next_offset = next_candidate if next_candidate < total else None

        return ChatSessionRetrievalResponse(results=results, total=total, next_offset=next_offset)

    @staticmethod
    def _extract_preview(first_message_json: str | None) -> str | None:
        if not first_message_json:
            return None
        try:
            message = _LLM_MESSAGE_TA.validate_python(json.loads(first_message_json))
        except Exception:
            return None
        if message.get("role") != "user":
            return None
        text = "".join(part["text"] for part in message.get("parts", ()) if part["type"] == "text")
        text = re.sub(r"\s+", " ", text).strip()
        return text or None

    def count_messages_by_session_id(
        self,
        session_id: ChatSessionID,
        query: str | None = None,
    ) -> int:
        if not query:
            cursor = self._conn.execute(_COUNT_MESSAGES_BY_SESSION, (int(session_id),))
            return cursor.fetchone()[0]
        cursor = self._conn.execute(
            "SELECT message FROM chat_messages WHERE session_id = ?",
            (int(session_id),),
        )
        return sum(
            1
            for row in cursor.fetchall()
            if self._message_matches_query(_LLM_MESSAGE_TA.validate_python(json.loads(row["message"])), query)
        )

    def count_messages_by_project_id(
        self,
        project_id: ProjectID,
        query: str | None = None,
    ) -> int:
        if not query:
            cursor = self._conn.execute(_COUNT_MESSAGES_BY_PROJECT, (str(project_id),))
            return cursor.fetchone()[0]
        cursor = self._conn.execute(
            """
            SELECT m.message
            FROM chat_messages AS m
            INNER JOIN chat_sessions AS s ON s.id = m.session_id
            WHERE s.project_id = ?
            """,
            (str(project_id),),
        )
        return sum(
            1
            for row in cursor.fetchall()
            if self._message_matches_query(_LLM_MESSAGE_TA.validate_python(json.loads(row["message"])), query)
        )

    @staticmethod
    def _message_matches_query(message: LLMMessage, query: str) -> bool:
        query = query.strip().lower()
        if not query:
            return True
        return any(part["text"].lower().find(query) >= 0 for part in message.get("parts", ()))

    def _build_chat_message(self, row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            id=ChatMessageID(row["id"]),
            session_id=ChatSessionID(row["session_id"]),
            message=_LLM_MESSAGE_TA.validate_python(json.loads(row["message"])),
            kind=row["kind"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_messages_by_session_id(
        self,
        session_id: ChatSessionID,
        request: ChatMessageRetrievalRequest | None = None,
    ) -> ChatMessageRetrievalResponse:
        req = request or ChatMessageRetrievalRequest()
        cursor = self._conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
            (int(session_id),),
        )
        all_messages = [self._build_chat_message(row) for row in cursor.fetchall()]
        return self._build_message_response(all_messages, req)

    def get_messages_by_project_id(
        self,
        project_id: ProjectID,
        request: ChatMessageRetrievalRequest | None = None,
    ) -> ChatMessageRetrievalResponse:
        req = request or ChatMessageRetrievalRequest()
        cursor = self._conn.execute(
            """
            SELECT m.*
            FROM chat_messages AS m
            INNER JOIN chat_sessions AS s ON s.id = m.session_id
            WHERE s.project_id = ?
            ORDER BY m.created_at ASC, m.session_id ASC, m.id ASC
            """,
            (str(project_id),),
        )
        all_messages = [self._build_chat_message(row) for row in cursor.fetchall()]
        return self._build_message_response(all_messages, req)

    def _build_message_response(
        self,
        all_messages: list[ChatMessage],
        request: ChatMessageRetrievalRequest,
    ) -> ChatMessageRetrievalResponse:
        offset = max(request.offset, 0)

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
        if request.limit is None:
            results = filtered_messages[offset:]
        else:
            limit = max(request.limit, 0)
            results = filtered_messages[offset : offset + limit]

        if request.limit is None:
            next_offset = None
        else:
            next_candidate = offset + max(request.limit, 0)
            next_offset = next_candidate if next_candidate < total else None
        return ChatMessageRetrievalResponse(results=results, total=total, next_offset=next_offset)
