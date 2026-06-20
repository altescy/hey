import argparse

import pytest

from hey.bootstrap.container import Container
from hey.domain.entities.chat import ChatSessionID
from hey.domain.entities.llm import UserMessage
from hey.interface.cli.commands import history


def _user_message(text: str) -> UserMessage:
    return UserMessage(role="user", parts=({"type": "text", "text": text},))


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch) -> Container:
    monkeypatch.setenv("OPENCODE_API_KEY", "dummy-key")
    built = Container.build(temporary=True)
    monkeypatch.setattr("hey.interface.cli.commands.history.Container.build", lambda: built)
    return built


async def _make_session(container: Container) -> ChatSessionID:
    project = container.project_usecase.get_project({"path": "."})["project"]
    session = (await container.chat_usecase.create_session({"project_id": project.id}))["session"]
    return session.id


def _args(**kwargs: object) -> argparse.Namespace:
    defaults = {
        "session": None,
        "list": False,
        "search": None,
        "last": None,
        "offset": 0,
        "limit": None,
        "compact": False,
        "reverse": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


async def test_history_list_shows_sessions(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    session_id = await _make_session(container)
    repo = container.chat_usecase._chat_repository
    repo.create_message(session_id, _user_message("hello session"))

    await history._run_history(_args(list=True))

    captured = capsys.readouterr()
    assert str(session_id) in captured.out
    assert "hello session" in captured.out


async def test_history_show_session_with_limit_offset(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    session_id = await _make_session(container)
    repo = container.chat_usecase._chat_repository
    for i in range(5):
        repo.create_message(session_id, _user_message(f"message-{i}"))

    await history._run_history(_args(session=session_id, limit=2))
    captured = capsys.readouterr()
    assert "message-0" in captured.out
    assert "message-1" in captured.out
    assert "message-2" not in captured.out
    assert "Showing 2 of 5" in captured.out

    await history._run_history(_args(session=session_id, offset=2, limit=2))
    captured = capsys.readouterr()
    assert "message-2" in captured.out
    assert "message-3" in captured.out
    assert "message-0" not in captured.out


async def test_history_search_session(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    session_id = await _make_session(container)
    repo = container.chat_usecase._chat_repository
    repo.create_message(session_id, _user_message("apple pie"))
    repo.create_message(session_id, _user_message("banana split"))

    await history._run_history(_args(session=session_id, search="apple"))

    captured = capsys.readouterr()
    assert "apple pie" in captured.out
    assert "banana" not in captured.out


async def test_history_search_project(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    s1 = await _make_session(container)
    s2 = await _make_session(container)
    repo = container.chat_usecase._chat_repository
    repo.create_message(s1, _user_message("alpha one"))
    repo.create_message(s2, _user_message("beta two"))

    await history._run_history(_args(search="alpha"))

    captured = capsys.readouterr()
    assert "alpha one" in captured.out
    assert "beta" not in captured.out


async def test_history_compact(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    session_id = await _make_session(container)
    repo = container.chat_usecase._chat_repository
    for i in range(3):
        repo.create_message(session_id, _user_message(f"compact-{i}"))

    await history._run_history(_args(session=session_id, compact=True))

    captured = capsys.readouterr()
    assert "You:" in captured.out
    assert "compact-0" in captured.out


async def test_history_last(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    session_id = await _make_session(container)
    repo = container.chat_usecase._chat_repository
    for i in range(5):
        repo.create_message(session_id, _user_message(f"last-{i}"))

    await history._run_history(_args(session=session_id, last=2))

    captured = capsys.readouterr()
    assert "last-3" in captured.out
    assert "last-4" in captured.out
    assert "last-0" not in captured.out
    assert "last-1" not in captured.out


async def test_history_reverse_compact(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    session_id = await _make_session(container)
    repo = container.chat_usecase._chat_repository
    for i in range(3):
        repo.create_message(session_id, _user_message(f"rev-{i}"))

    await history._run_history(_args(session=session_id, compact=True, reverse=True))

    captured = capsys.readouterr()
    # Newest first, so the last created message appears before the first.
    assert captured.out.index("rev-2") < captured.out.index("rev-0")


async def test_history_list_pagination(container: Container, capsys: pytest.CaptureFixture[str]) -> None:
    for i in range(3):
        session_id = await _make_session(container)
        repo = container.chat_usecase._chat_repository
        repo.create_message(session_id, _user_message(f"page-{i}"))

    await history._run_history(_args(list=True, limit=2))
    captured = capsys.readouterr()
    assert "Showing 2 of 3" in captured.out
