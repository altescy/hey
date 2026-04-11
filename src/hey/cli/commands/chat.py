import asyncio

from hey.domain.entities.llm import EmitLLMSignal
from hey.infrastructure.chat import InMemoryChatRepository
from hey.infrastructure.llm import get_litellm_spec
from hey.infrastructure.project import TemporaryProjectRepository
from hey.infrastructure.tool import BuiltinToolRepository
from hey.usecases.chat import AgentChatUseCase
from hey.usecases.project import ProjectUseCase


async def _run_chat(prompt: str) -> None:
    project_use_case = ProjectUseCase(
        project_repository=TemporaryProjectRepository(),
    )
    chat_use_case = AgentChatUseCase(
        llm_spec=get_litellm_spec(model="gpt-5.2", instructions="You are a helpful assistant."),
        chat_repository=InMemoryChatRepository(),
        tool_repository=BuiltinToolRepository(),
    )
    project = project_use_case.get_project(path=".")
    session = await chat_use_case.create_session(project_id=project.id)
    async with chat_use_case.run(session_id=session.id, prompt=prompt) as response:
        async for event in response.events():
            match event:
                case EmitLLMSignal(signal=signal):
                    match signal["type"]:
                        case "text_delta":
                            print(signal["delta"], end="", flush=True)
        print()

    await response.collect()


def run_chat(prompt: str) -> None:
    asyncio.run(_run_chat(prompt))
