"""Unit tests for IChatRepository implementations.

Shared contract tests live in ``ChatRepositoryContractTests`` and are
inherited by each concrete test class so every implementation is exercised
against the same expectations.
"""

import datetime
from abc import abstractmethod
from pathlib import Path
from unittest.mock import patch

import pytest

from hey.domain.entities.chat import ChatSessionID
from hey.domain.entities.llm import UserMessage
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import ChatMessageRetrievalRequest, IChatRepository
from hey.infrastructure.repositories.chat.inmemory import InMemoryChatRepository
from hey.infrastructure.repositories.chat.sqlite import SQLiteChatRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_A = ProjectID("project-a")
_PROJECT_B = ProjectID("project-b")

_TS_OLD = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
_TS_NEW = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)


def _user_message(text: str) -> UserMessage:
    return UserMessage(role="user", parts=({"type": "text", "text": text},))


# ---------------------------------------------------------------------------
# Shared contract tests
# ---------------------------------------------------------------------------


class ChatRepositoryContractTests:
    """Mixin that defines the contract every IChatRepository must satisfy.

    Subclasses must implement ``make_repository`` to return a fresh instance.
    """

    @abstractmethod
    def make_repository(self) -> IChatRepository: ...

    # ------------------------------------------------------------------
    # create_session / get_session_by_id
    # ------------------------------------------------------------------

    def test_create_session_returns_session_with_correct_project_id(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        assert session.project_id == _PROJECT_A

    def test_create_session_assigns_unique_ids(self) -> None:
        repo = self.make_repository()
        s1 = repo.create_session(_PROJECT_A)
        s2 = repo.create_session(_PROJECT_A)
        assert s1.id != s2.id

    def test_get_session_by_id_returns_created_session(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        fetched = repo.get_session_by_id(session.id)
        assert fetched is not None
        assert fetched.id == session.id
        assert fetched.project_id == _PROJECT_A

    def test_get_session_by_id_returns_none_for_unknown_id(self) -> None:
        repo = self.make_repository()
        assert repo.get_session_by_id(ChatSessionID(9999)) is None

    # ------------------------------------------------------------------
    # get_latest_session_by_project_id
    # ------------------------------------------------------------------

    def test_get_latest_session_returns_none_when_no_sessions(self) -> None:
        repo = self.make_repository()
        assert repo.get_latest_session_by_project_id(_PROJECT_A) is None

    def test_get_latest_session_returns_only_session(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        latest = repo.get_latest_session_by_project_id(_PROJECT_A)
        assert latest is not None
        assert latest.id == session.id

    def test_get_latest_session_returns_most_recently_created(self) -> None:
        repo = self.make_repository()
        _chat_svc = "hey.infrastructure.repositories.chat.inmemory.get_chat_timestamp"
        _chat_svc_sqlite = "hey.infrastructure.repositories.chat.sqlite.get_chat_timestamp"

        with patch(_chat_svc, return_value=_TS_OLD), patch(_chat_svc_sqlite, return_value=_TS_OLD):
            repo.create_session(_PROJECT_A)
        with patch(_chat_svc, return_value=_TS_NEW), patch(_chat_svc_sqlite, return_value=_TS_NEW):
            s_new = repo.create_session(_PROJECT_A)

        latest = repo.get_latest_session_by_project_id(_PROJECT_A)
        assert latest is not None
        assert latest.id == s_new.id

    def test_get_latest_session_ignores_other_projects(self) -> None:
        repo = self.make_repository()
        repo.create_session(_PROJECT_A)
        assert repo.get_latest_session_by_project_id(_PROJECT_B) is None

    # ------------------------------------------------------------------
    # create_message / get_messages_by_session_id
    # ------------------------------------------------------------------

    def test_create_message_returns_message_with_correct_content(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        msg = _user_message("hello")
        chat_msg = repo.create_message(session.id, msg)
        assert chat_msg.session_id == session.id
        assert chat_msg.message["role"] == "user"

    def test_create_message_persists_kind_and_metadata(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        msg = _user_message("summary")

        chat_msg = repo.create_message(
            session.id,
            msg,
            kind="summary",
            metadata={"tail_start_message_id": 3},
        )

        assert chat_msg.kind == "summary"
        assert chat_msg.metadata == {"tail_start_message_id": 3}

        messages = repo.get_messages_by_session_id(session.id).results
        assert messages[0].kind == "summary"
        assert messages[0].metadata == {"tail_start_message_id": 3}

    def test_get_messages_by_session_id_returns_messages_in_order(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        texts = ["first", "second", "third"]
        for t in texts:
            repo.create_message(session.id, _user_message(t))

        messages = repo.get_messages_by_session_id(session.id).results
        assert len(messages) == 3
        for msg, expected in zip(messages, texts):
            parts = msg.message["parts"]
            assert parts[0]["text"] == expected

    def test_get_messages_by_session_id_returns_empty_for_unknown_session(self) -> None:
        repo = self.make_repository()
        response = repo.get_messages_by_session_id(ChatSessionID(9999))
        assert response.results == []
        assert response.total == 0
        assert response.next_offset is None

    def test_messages_are_isolated_between_sessions(self) -> None:
        repo = self.make_repository()
        s1 = repo.create_session(_PROJECT_A)
        s2 = repo.create_session(_PROJECT_A)
        repo.create_message(s1.id, _user_message("for s1"))
        repo.create_message(s2.id, _user_message("for s2"))

        assert len(repo.get_messages_by_session_id(s1.id).results) == 1
        assert len(repo.get_messages_by_session_id(s2.id).results) == 1

    def test_get_messages_by_session_id_supports_pagination(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        for i in range(5):
            repo.create_message(session.id, _user_message(f"message-{i}"))

        first_page = repo.get_messages_by_session_id(
            session.id,
            ChatMessageRetrievalRequest(offset=0, limit=2),
        )
        assert first_page.total == 5
        assert first_page.next_offset == 2
        assert [m.message["parts"][0]["text"] for m in first_page.results] == ["message-0", "message-1"]

        second_page = repo.get_messages_by_session_id(
            session.id,
            ChatMessageRetrievalRequest(offset=first_page.next_offset or 0, limit=2),
        )
        assert second_page.total == 5
        assert second_page.next_offset == 4
        assert [m.message["parts"][0]["text"] for m in second_page.results] == ["message-2", "message-3"]

        last_page = repo.get_messages_by_session_id(
            session.id,
            ChatMessageRetrievalRequest(offset=second_page.next_offset or 0, limit=2),
        )
        assert last_page.total == 5
        assert last_page.next_offset is None
        assert [m.message["parts"][0]["text"] for m in last_page.results] == ["message-4"]

    def test_get_messages_by_session_id_supports_query_filter(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        repo.create_message(session.id, _user_message("apple pie"))
        repo.create_message(session.id, _user_message("banana split"))
        repo.create_message(session.id, _user_message("green apple"))

        response = repo.get_messages_by_session_id(
            session.id,
            ChatMessageRetrievalRequest(query="APPLE"),
        )

        assert response.total == 2
        assert response.next_offset is None
        assert [m.message["parts"][0]["text"] for m in response.results] == ["apple pie", "green apple"]

    def test_get_messages_by_session_id_applies_query_before_pagination(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        repo.create_message(session.id, _user_message("apple one"))
        repo.create_message(session.id, _user_message("banana"))
        repo.create_message(session.id, _user_message("apple two"))
        repo.create_message(session.id, _user_message("apple three"))

        response = repo.get_messages_by_session_id(
            session.id,
            ChatMessageRetrievalRequest(query="apple", offset=1, limit=1),
        )

        assert response.total == 3
        assert response.next_offset == 2
        assert [m.message["parts"][0]["text"] for m in response.results] == ["apple two"]

    def test_get_messages_by_project_id_searches_across_sessions(self) -> None:
        repo = self.make_repository()
        s1 = repo.create_session(_PROJECT_A)
        s2 = repo.create_session(_PROJECT_A)
        s_other = repo.create_session(_PROJECT_B)
        repo.create_message(s1.id, _user_message("alpha one"))
        repo.create_message(s2.id, _user_message("beta two"))
        repo.create_message(s_other.id, _user_message("alpha other project"))

        response = repo.get_messages_by_project_id(
            _PROJECT_A,
            ChatMessageRetrievalRequest(query="alpha"),
        )

        assert response.total == 1
        assert response.next_offset is None
        assert len(response.results) == 1
        assert response.results[0].session_id == s1.id
        assert response.results[0].message["parts"][0]["text"] == "alpha one"

    def test_get_messages_by_project_id_supports_pagination(self) -> None:
        repo = self.make_repository()
        s1 = repo.create_session(_PROJECT_A)
        s2 = repo.create_session(_PROJECT_A)
        repo.create_message(s1.id, _user_message("project-a 1"))
        repo.create_message(s2.id, _user_message("project-a 2"))
        repo.create_message(s1.id, _user_message("project-a 3"))

        page = repo.get_messages_by_project_id(
            _PROJECT_A,
            ChatMessageRetrievalRequest(offset=1, limit=1),
        )

        assert page.total == 3
        assert page.next_offset == 2
        assert [m.message["parts"][0]["text"] for m in page.results] == ["project-a 2"]

    # ------------------------------------------------------------------
    # transaction (__enter__ / __exit__)
    # ------------------------------------------------------------------

    def test_transaction_commits_on_success(self) -> None:
        repo = self.make_repository()
        with repo:
            repo.create_session(_PROJECT_A)
        assert repo.get_latest_session_by_project_id(_PROJECT_A) is not None

    def test_message_ids_are_unique_within_session(self) -> None:
        repo = self.make_repository()
        session = repo.create_session(_PROJECT_A)
        ids = [repo.create_message(session.id, _user_message(f"msg{i}")).id for i in range(5)]
        assert len(set(ids)) == 5


# ---------------------------------------------------------------------------
# InMemoryChatRepository
# ---------------------------------------------------------------------------


class TestInMemoryChatRepository(ChatRepositoryContractTests):
    def make_repository(self) -> InMemoryChatRepository:
        return InMemoryChatRepository()

    def test_transaction_has_no_effect_on_writes(self) -> None:
        # InMemory is not transactional; __exit__ is a no-op so writes are
        # always visible regardless of exceptions.
        repo = self.make_repository()
        try:
            with repo:
                repo.create_session(_PROJECT_A)
                raise RuntimeError("forced failure")
        except RuntimeError:
            pass
        assert repo.get_latest_session_by_project_id(_PROJECT_A) is not None


# ---------------------------------------------------------------------------
# SQLiteChatRepository
# ---------------------------------------------------------------------------


class TestSQLiteChatRepository(ChatRepositoryContractTests):
    @pytest.fixture(autouse=True)
    def _tmp_db(self, tmp_path: Path) -> None:
        self._db_path = tmp_path / "test.db"

    def make_repository(self) -> SQLiteChatRepository:
        return SQLiteChatRepository(self._db_path)

    def test_transaction_rolls_back_on_exception(self) -> None:
        repo = self.make_repository()
        try:
            with repo:
                repo.create_session(_PROJECT_A)
                raise RuntimeError("forced failure")
        except RuntimeError:
            pass
        assert repo.get_latest_session_by_project_id(_PROJECT_A) is None

    def test_data_persists_across_instances(self) -> None:
        repo1 = self.make_repository()
        session = repo1.create_session(_PROJECT_A)
        repo1.create_message(session.id, _user_message("persisted"))

        repo2 = self.make_repository()
        messages = repo2.get_messages_by_session_id(session.id).results
        assert len(messages) == 1
        assert messages[0].message["parts"][0]["text"] == "persisted"
