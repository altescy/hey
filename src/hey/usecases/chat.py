import datetime
from contextlib import asynccontextmanager
from typing import AsyncIterator

from hey.core.workflow import WorkflowResponse
from hey.domain.entities.chat import ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMEvent, LLMState
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.chat import TIMEZONE
from hey.domain.services.llm import (
    EmitLLMMessage,
    EmitToolResult,
    append_user_message,
)
from hey.domain.services.workflow import LLMAgent


class AgentChatUseCase:
    def __init__(
        self,
        agent: LLMAgent,
        chat_repository: IChatRepository,
    ) -> None:
        self._agent = agent
        self._chat_repository = chat_repository

    async def get_llm_state(self, session_id: ChatSessionID) -> LLMState:
        chat_messages = self._chat_repository.get_messages_by_session_id(session_id)
        llm_messages = tuple(message.message for message in chat_messages)
        return self._agent.make_state(history=llm_messages)

    async def create_session(self, project_id: ProjectID) -> ChatSession:
        with self._chat_repository:
            return self._chat_repository.create_session(project_id)

    async def get_or_create_session(self, project_id: ProjectID, session_timeout: float) -> tuple[ChatSession, bool]:
        """Return (session, is_new). is_new is True when a fresh session was created."""
        session = self._chat_repository.get_latest_session_by_project_id(project_id)
        if session is not None:
            elapsed = (datetime.datetime.now(TIMEZONE) - session.updated_at).total_seconds()
            if elapsed <= session_timeout:
                return session, False
        with self._chat_repository:
            return self._chat_repository.create_session(project_id), True

    async def resume_session(self, session_id: ChatSessionID) -> ChatSession:
        session = self._chat_repository.get_session_by_id(session_id)
        if session is None:
            raise ValueError(f"Chat session with ID {session_id} not found")
        return session

    @asynccontextmanager
    async def run(
        self,
        session_id: ChatSessionID,
        prompt: str,
    ) -> AsyncIterator[WorkflowResponse[LLMEvent, LLMState, str]]:
        async def on_event(event: LLMEvent) -> None:
            match event:
                case EmitLLMMessage(message=message) | EmitToolResult(message=message):
                    self._chat_repository.create_message(session_id=session_id, message=message)

        state = await self.get_llm_state(session_id)
        state = append_user_message(state, prompt)
        self._chat_repository.create_message(session_id=session_id, message=state.history[-1])
        yield self._agent.run(prompt, state=state, on_event=on_event)
