import datetime
from contextlib import asynccontextmanager
from typing import AsyncIterator

from hey.application.dto import (
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
from hey.core.workflow import WorkflowResponse
from hey.domain.entities.agent import LLMAgentSpec
from hey.domain.entities.llm import LLMEvent, LLMState
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.agent import run_llm_agent
from hey.domain.services.chat import TIMEZONE
from hey.domain.services.llm import make_llm_state, make_on_event_callback_for_chat, make_user_message


class AgentChatUseCase[QueryT, ResponseT]:
    def __init__(
        self,
        agent: LLMAgentSpec[QueryT, ResponseT],
        chat_repository: IChatRepository,
    ) -> None:
        self._agent = agent
        self._chat_repository = chat_repository

    async def get_llm_state(self, input: GetLLMStateInput) -> GetLLMStateOutput:
        chat_messages = self._chat_repository.get_messages_by_session_id(input["session_id"])
        llm_messages = tuple(message.message for message in chat_messages)
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

    @asynccontextmanager
    async def run(
        self,
        input: RunChatInput,
    ) -> AsyncIterator[WorkflowResponse[LLMEvent, LLMState, ResponseT]]:

        state = (await self.get_llm_state(GetLLMStateInput(session_id=input["session_id"])))["state"]
        self._chat_repository.create_message(session_id=input["session_id"], message=make_user_message(input["prompt"]))
        yield run_llm_agent(
            spec=self._agent,
            prompt=input["prompt"],
            state=state,
            on_event=make_on_event_callback_for_chat(input["session_id"], self._chat_repository),
        )
