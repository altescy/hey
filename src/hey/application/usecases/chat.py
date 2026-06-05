import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager, suppress
from typing import Any

from hey.application.dto import (
    CompactChatInput,
    CompactChatOutput,
    CreateSessionInput,
    CreateSessionOutput,
    GetLLMStateInput,
    GetLLMStateOutput,
    GetOrCreateSessionInput,
    GetOrCreateSessionOutput,
    ResumeSessionInput,
    ResumeSessionOutput,
    RunChatInput,
)
from hey.core.workflow import (
    BaseWorkflowHandler,
    Continue,
    Control,
    Stop,
    WorkflowExecutor,
    WorkflowGraph,
    WorkflowProgressEvent,
    WorkflowResponse,
)
from hey.core.workflow.events import BaseWorkflowProgressEvent
from hey.core.workflow.source import EventSource
from hey.domain.entities.agent import LLMAgentSpec
from hey.domain.entities.chat import ChatMessage, ChatSession, ChatSessionID
from hey.domain.entities.config import ChatCompactionConfig
from hey.domain.entities.llm import LLMEvent, LLMMessage, LLMState, SystemMessage, TextContent
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import (
    ChatMessageRetrievalRequest,
    ChatMessageRetrievalResponse,
    IChatRepository,
)
from hey.domain.services.agent import run_llm_agent
from hey.domain.services.chat import TIMEZONE
from hey.domain.services.llm import make_llm_state, make_on_event_callback_for_chat, make_user_message, update_llm_state

_SUMMARY_PROMPT = """Create an updated compact handoff summary for continuing this conversation.

Output exactly this Markdown structure and keep the section order unchanged:

## Goal
- [single-sentence task summary]

## Constraints & Preferences
- [user constraints, preferences, specs, or "(none)"]

## Progress
### Done
- [completed work or "(none)"]
### In Progress
- [current work or "(none)"]
### Blocked
- [blockers or "(none)"]

## Key Decisions
- [decision and why, or "(none)"]

## Next Steps
- [ordered next actions or "(none)"]

## Critical Context
- [important technical facts, exact errors, commands, identifiers, or "(none)"]

## Relevant Files
- [file or directory path: why it matters, or "(none)"]

Rules:
- Use terse bullets, not prose paragraphs.
- Preserve exact file paths, commands, error strings, field names, and identifiers when known.
- Preserve still-true details from the previous summary, remove stale details, and merge in new facts.
- Do not mention the summary process or that context was compacted.
"""


class AgentChatUseCase[QueryT, ResponseT]:
    def __init__(
        self,
        agent: LLMAgentSpec[QueryT, ResponseT],
        compaction_agent: LLMAgentSpec[str, str],
        compaction_config: ChatCompactionConfig,
        chat_repository: IChatRepository,
    ) -> None:
        self._agent = agent
        self._compaction_agent = compaction_agent
        self._compaction_config = compaction_config
        self._chat_repository = chat_repository

    async def get_llm_state(self, input: GetLLMStateInput) -> GetLLMStateOutput:
        chat_messages = self._chat_repository.get_messages_by_session_id(input["session_id"]).results
        llm_messages = _compacted_llm_messages(chat_messages)
        return GetLLMStateOutput(state=make_llm_state(llm_messages))

    async def create_session(self, input: CreateSessionInput) -> CreateSessionOutput:
        with self._chat_repository:
            return CreateSessionOutput(session=self._chat_repository.create_session(input["project_id"]))

    async def get_or_create_session(self, input: GetOrCreateSessionInput) -> GetOrCreateSessionOutput:
        """Return output with is_new=True when a fresh session was created."""
        session = self._chat_repository.get_latest_session_by_project_id(input["project_id"])
        if session is not None:
            elapsed = (datetime.datetime.now(TIMEZONE) - session.updated_at).total_seconds()
            if elapsed <= input["session_timeout"]:
                return GetOrCreateSessionOutput(session=session, is_new=False)
        with self._chat_repository:
            return GetOrCreateSessionOutput(
                session=self._chat_repository.create_session(input["project_id"]), is_new=True
            )

    async def resume_session(self, input: ResumeSessionInput) -> ResumeSessionOutput:
        session = self._chat_repository.get_session_by_id(input["session_id"])
        if session is None:
            raise ValueError(f"Chat session with ID {input['session_id']} not found")
        return ResumeSessionOutput(session=session)

    async def get_session_by_id(self, session_id: ChatSessionID) -> ChatSession | None:
        return self._chat_repository.get_session_by_id(session_id)

    async def get_latest_session_by_project_id(self, project_id: ProjectID) -> ChatSession | None:
        return self._chat_repository.get_latest_session_by_project_id(project_id)

    async def get_messages_by_session_id(
        self,
        session_id: ChatSessionID,
        request: ChatMessageRetrievalRequest | None = None,
    ) -> ChatMessageRetrievalResponse:
        return self._chat_repository.get_messages_by_session_id(session_id, request)

    async def get_messages_by_project_id(
        self,
        project_id: ProjectID,
        request: ChatMessageRetrievalRequest | None = None,
    ) -> ChatMessageRetrievalResponse:
        return self._chat_repository.get_messages_by_project_id(project_id, request)

    async def compact(self, input: CompactChatInput) -> CompactChatOutput:
        if not self._compaction_config.enabled:
            return CompactChatOutput(compacted=False, summary=None)

        chat_messages = self._chat_repository.get_messages_by_session_id(input["session_id"]).results
        selection = _select_compaction_messages(chat_messages, self._compaction_config)
        if selection is None:
            return CompactChatOutput(compacted=False, summary=None)

        prompt = _make_compaction_prompt(selection)
        response = run_llm_agent(
            spec=self._compaction_agent,
            prompt=prompt,
            state=make_llm_state(tuple(message.message for message in selection.head)),
        )
        _, summary = await response.collect()
        summary = summary.strip()
        if not summary:
            return CompactChatOutput(compacted=False, summary=None)

        self._chat_repository.create_message(
            session_id=input["session_id"],
            message=_make_summary_message(summary),
            kind="summary",
            metadata={"tail_start_message_id": selection.tail_start_message_id},
        )
        return CompactChatOutput(compacted=True, summary=summary)

    @asynccontextmanager
    async def run(
        self,
        input: RunChatInput,
    ) -> AsyncIterator[WorkflowResponse[LLMEvent, LLMState, ResponseT]]:
        state = (await self.get_llm_state(GetLLMStateInput(session_id=input["session_id"])))["state"]
        self._chat_repository.create_message(session_id=input["session_id"], message=make_user_message(input["prompt"]))
        graph = _make_agent_chat_workflow(
            agent=self._agent,
            prompt=input["prompt"],
            session_id=input["session_id"],
            chat_repository=self._chat_repository,
        )
        response = await WorkflowExecutor(handler=_ChatWorkflowHandler[ResponseT]())(
            graph,
            state,
        )
        yield _filter_chat_workflow_events(response)


def _make_agent_chat_workflow[QueryT, ResponseT](
    agent: LLMAgentSpec[QueryT, ResponseT],
    prompt: str,
    session_id: ChatSessionID,
    chat_repository: IChatRepository,
) -> WorkflowGraph[LLMState, LLMEvent, ResponseT]:
    async def run_agent(state: LLMState) -> AsyncIterator[Control[LLMEvent, ResponseT]]:
        response = run_llm_agent(
            spec=agent,
            prompt=prompt,
            state=state,
            on_event=make_on_event_callback_for_chat(session_id, chat_repository),
        )
        async for event in response.events():
            yield Continue(event)

        _, result = await response.collect()
        yield Stop(result)

    return WorkflowGraph[LLMState, LLMEvent, ResponseT]().add("agent", run_agent)


def _filter_chat_workflow_events[ResponseT](
    response: WorkflowResponse[LLMEvent | WorkflowProgressEvent, LLMState, ResponseT],
) -> WorkflowResponse[LLMEvent, LLMState, ResponseT]:
    source = EventSource[LLMEvent]()

    async def run() -> tuple[LLMState, ResponseT]:
        async def forward_events() -> None:
            try:
                async for event in response.events():
                    if isinstance(event, BaseWorkflowProgressEvent):
                        continue
                    await source.publish(event)
            except BaseException as exc:
                await source.aclose(exception=exc)
                raise
            else:
                await source.aclose()

        forward_task = asyncio.create_task(forward_events())
        try:
            result = await response.collect()
            await forward_task
            return result
        except BaseException:
            forward_task.cancel()
            with suppress(asyncio.CancelledError):
                await forward_task
            raise

    return WorkflowResponse(source, run)


@dataclasses.dataclass(frozen=True)
class _CompactionSelection:
    head: tuple[ChatMessage, ...]
    tail_start_message_id: int | None
    previous_summary: str | None


class _ChatWorkflowHandler[ResponseT](BaseWorkflowHandler[LLMState, LLMEvent, ResponseT]):
    def update(self, events: Sequence[LLMEvent], state: LLMState) -> LLMState:
        current_state = state
        for event in events:
            current_state, _ = update_llm_state((event,), current_state)
        return current_state

    def finish(self, state: LLMState) -> ResponseT:
        raise RuntimeError("chat workflow finished without an agent response")


def _compacted_llm_messages(chat_messages: Sequence[ChatMessage]) -> tuple[LLMMessage, ...]:
    latest_summary = next((message for message in reversed(chat_messages) if message.kind == "summary"), None)
    if latest_summary is None:
        return tuple(message.message for message in chat_messages if message.kind == "normal")

    tail_start_message_id = _metadata_int(latest_summary.metadata, "tail_start_message_id")
    tail = tuple(
        message.message
        for message in chat_messages
        if message.kind == "normal" and (tail_start_message_id is None or int(message.id) >= tail_start_message_id)
    )
    return (latest_summary.message, *tail)


def _select_compaction_messages(
    chat_messages: Sequence[ChatMessage],
    config: ChatCompactionConfig,
) -> _CompactionSelection | None:
    latest_summary = next((message for message in reversed(chat_messages) if message.kind == "summary"), None)
    previous_tail_start = _metadata_int(latest_summary.metadata, "tail_start_message_id") if latest_summary else None
    previous_summary = _message_text(latest_summary.message) if latest_summary else None

    normal_messages = tuple(
        message
        for message in chat_messages
        if message.kind == "normal" and (previous_tail_start is None or int(message.id) >= previous_tail_start)
    )
    if not normal_messages:
        return None

    if config.tail_turns == 0:
        return _CompactionSelection(head=normal_messages, tail_start_message_id=None, previous_summary=previous_summary)

    turn_starts = [index for index, message in enumerate(normal_messages) if message.message["role"] == "user"]
    if len(turn_starts) <= config.tail_turns:
        return None

    tail_start_index = turn_starts[-config.tail_turns]
    head = normal_messages[:tail_start_index]
    if not head:
        return None

    return _CompactionSelection(
        head=head,
        tail_start_message_id=int(normal_messages[tail_start_index].id),
        previous_summary=previous_summary,
    )


def _make_compaction_prompt(selection: _CompactionSelection) -> str:
    parts = [_SUMMARY_PROMPT]
    if selection.previous_summary:
        parts.extend(("Previous summary:", selection.previous_summary))
    parts.extend(
        ("Conversation history to summarize:", _format_transcript(message.message for message in selection.head))
    )
    return "\n\n".join(parts)


def _make_summary_message(summary: str) -> SystemMessage:
    return SystemMessage(
        role="system",
        parts=(TextContent(type="text", text=f"Conversation summary for continuity:\n\n{summary.strip()}"),),
    )


def _metadata_int(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _format_transcript(messages: Iterable[LLMMessage]) -> str:
    return "\n\n".join(f"{message['role']}:\n{_message_text(message)}" for message in messages)


def _message_text(message: LLMMessage) -> str:
    match message:
        case {"role": "assistant", "parts": parts, "tool_calls": tool_calls}:
            text = "\n".join(part["text"] for part in parts)
            calls = "\n".join(
                f"[tool_call id={record['id']} name={record['name']} args={record['args_json']}]"
                for record in tool_calls
            )
            return "\n".join(part for part in (text, calls) if part)
        case {"role": "tool_result", "tool_call_id": tool_call_id, "parts": parts}:
            text = "\n".join(part["text"] for part in parts)
            return f"[tool_result id={tool_call_id}]\n{text}"
        case {"parts": parts}:
            return "\n".join(part["text"] for part in parts)
    return ""
