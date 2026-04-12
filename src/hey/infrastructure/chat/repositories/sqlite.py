import json
import sqlite3
from pathlib import Path
from typing import Final, Self

from pydantic import TypeAdapter

from hey.domain.entities.chat import ChatMessage, ChatMessageID, ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMMessage
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.chat import get_chat_timestamp

_LLM_MESSAGE_TA: Final[TypeAdapter[LLMMessage]] = TypeAdapter(LLMMessage)

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

    def create_message(self, session_id: ChatSessionID, message: LLMMessage) -> ChatMessage:
        timestamp = get_chat_timestamp()
        message_json = json.dumps(_LLM_MESSAGE_TA.dump_python(message))
        cursor = self._conn.execute(
            "INSERT INTO chat_messages (session_id, message, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (int(session_id), message_json, timestamp.isoformat(), timestamp.isoformat()),
        )
        message_id = ChatMessageID(cursor.lastrowid)  # type: ignore[arg-type]
        return ChatMessage(
            id=message_id,
            session_id=session_id,
            message=message,
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

    def get_messages_by_session_id(self, session_id: ChatSessionID) -> list[ChatMessage]:
        cursor = self._conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
            (int(session_id),),
        )
        return [
            ChatMessage(
                id=ChatMessageID(row["id"]),
                session_id=ChatSessionID(row["session_id"]),
                message=_LLM_MESSAGE_TA.validate_python(json.loads(row["message"])),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]
