import datetime

from hey.application.usecases.chat import _compacted_llm_messages, _select_compaction_messages
from hey.domain.entities.chat import ChatMessage, ChatMessageID, ChatSessionID
from hey.domain.entities.config import ChatCompactionConfig
from hey.domain.entities.llm import AssistantMessage, SystemMessage, TextContent, UserMessage

_TS = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_SESSION_ID = ChatSessionID(1)


def _user(message_id: int, text: str) -> ChatMessage:
    return ChatMessage(
        id=ChatMessageID(message_id),
        session_id=_SESSION_ID,
        message=UserMessage(role="user", parts=(TextContent(type="text", text=text),)),
        created_at=_TS,
        updated_at=_TS,
    )


def _assistant(message_id: int, text: str) -> ChatMessage:
    return ChatMessage(
        id=ChatMessageID(message_id),
        session_id=_SESSION_ID,
        message=AssistantMessage(role="assistant", parts=(TextContent(type="text", text=text),), tool_calls=()),
        created_at=_TS,
        updated_at=_TS,
    )


def _summary(message_id: int, text: str, tail_start_message_id: int) -> ChatMessage:
    return ChatMessage(
        id=ChatMessageID(message_id),
        session_id=_SESSION_ID,
        message=SystemMessage(role="system", parts=(TextContent(type="text", text=text),)),
        kind="summary",
        metadata={"tail_start_message_id": tail_start_message_id},
        created_at=_TS,
        updated_at=_TS,
    )


def test_compacted_llm_messages_uses_latest_summary_and_tail() -> None:
    messages = (
        _user(1, "old user"),
        _assistant(2, "old assistant"),
        _summary(3, "summary", tail_start_message_id=4),
        _user(4, "recent user"),
        _assistant(5, "recent assistant"),
    )

    llm_messages = _compacted_llm_messages(messages)

    assert [message["role"] for message in llm_messages] == ["system", "user", "assistant"]
    assert llm_messages[0]["parts"][0]["text"] == "summary"
    assert llm_messages[1]["parts"][0]["text"] == "recent user"


def test_select_compaction_messages_keeps_recent_tail_turns() -> None:
    messages = (
        _user(1, "turn 1"),
        _assistant(2, "answer 1"),
        _user(3, "turn 2"),
        _assistant(4, "answer 2"),
        _user(5, "turn 3"),
        _assistant(6, "answer 3"),
    )

    selection = _select_compaction_messages(messages, ChatCompactionConfig(tail_turns=2))

    assert selection is not None
    assert [int(message.id) for message in selection.head] == [1, 2]
    assert selection.tail_start_message_id == 3


def test_select_compaction_messages_uses_previous_summary_as_anchor() -> None:
    messages = (
        _user(1, "old turn"),
        _summary(2, "previous summary", tail_start_message_id=3),
        _user(3, "tail turn"),
        _assistant(4, "tail answer"),
        _user(5, "new turn"),
        _assistant(6, "new answer"),
    )

    selection = _select_compaction_messages(messages, ChatCompactionConfig(tail_turns=1))

    assert selection is not None
    assert selection.previous_summary == "previous summary"
    assert [int(message.id) for message in selection.head] == [3, 4]
    assert selection.tail_start_message_id == 5
