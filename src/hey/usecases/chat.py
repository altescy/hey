from contextlib import asynccontextmanager
from typing import AsyncIterator

from hey.core.agent import make_agent_runtime, run_agent_loop
from hey.core.workflow import WorkflowResponse
from hey.domain.entities.chat import ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMEvent, LLMSpec, LLMState
from hey.domain.entities.project import ProjectID
from hey.domain.entities.tool import AskPermissionFunc, ToolPermission
from hey.domain.repositories.chat import IChatRepository
from hey.domain.repositories.tool import IToolRepository
from hey.domain.services.llm import (
    EmitLLMMessage,
    EmitToolResult,
    LLMAgentFinalizer,
    LLMAgentInterpreter,
    LLMAgentReducer,
    LLMAgentUpdater,
    append_user_message,
)
from hey.domain.services.tool import generate_tool_definition_from_spec, override_tool_permission, set_ask_permission


class AgentChatUseCase:
    def __init__(
        self,
        permission: ToolPermission,
        llm_spec: LLMSpec,
        chat_repository: IChatRepository,
        tool_repository: IToolRepository,
        ask_permission: AskPermissionFunc | None = None,
    ) -> None:
        self._llm_spec = llm_spec
        self._chat_repository = chat_repository
        self._tool_repository = tool_repository

        tool_specs = {spec.name: spec for spec in self._tool_repository.get_all_specs()}
        for tool_name, tool_spec in tool_specs.items():
            if param_permission := permission.get(tool_name):
                tool_spec = override_tool_permission(tool_spec, param_permission)
            if ask_permission is not None:
                tool_spec = set_ask_permission(tool_specs[tool_name], ask_permission)
            tool_specs[tool_name] = tool_spec

        self._agent_reducer = LLMAgentReducer()
        self._agent_updater = LLMAgentUpdater()
        self._agent_interpreter = LLMAgentInterpreter(tool_specs)
        self._agent_finalizer = LLMAgentFinalizer(tool_specs)

    async def get_llm_state(self, session_id: ChatSessionID) -> LLMState:
        tool_specs = self._tool_repository.get_all_specs()
        tool_definitions = tuple(generate_tool_definition_from_spec(spec) for spec in tool_specs)
        chat_messages = self._chat_repository.get_messages_by_session_id(session_id)
        llm_messages = tuple(message.message for message in chat_messages)
        return LLMState(
            history=llm_messages,
            tools=tool_definitions,
        )

    async def create_session(self, project_id: ProjectID) -> ChatSession:
        return self._chat_repository.create_session(project_id)

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
        state = await self.get_llm_state(session_id)
        state = append_user_message(state, prompt)
        runtime = make_agent_runtime(self._llm_spec.engine, self._agent_reducer, self._llm_spec.contextualizer)

        async def on_event(event: LLMEvent) -> None:
            match event:
                case EmitLLMMessage(message=message) | EmitToolResult(message=message):
                    self._chat_repository.save_message(
                        self._chat_repository.create_message(session_id=session_id, message=message)
                    )

        with self._chat_repository:
            yield run_agent_loop(
                state,
                runtime=runtime,
                update=self._agent_updater,
                interpret=self._agent_interpreter,
                is_done=self._agent_finalizer.is_done,
                finish=self._agent_finalizer.finalize,
                on_event=on_event,
            )
