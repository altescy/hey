import argparse
import asyncio
import sys
from functools import partial

from rich.console import Console

from hey.domain.entities.llm import EmitLLMMessage, EmitLLMSignal, EmitToolResult
from hey.domain.services.project import get_hey_dot_directory
from hey.infrastructure.chat import InMemoryChatRepository, SQLiteChatRepository
from hey.infrastructure.llm import get_litellm_spec
from hey.infrastructure.project import LocalProjectRepository
from hey.infrastructure.tool import BuiltinToolRepository
from hey.usecases.chat import AgentChatUseCase
from hey.usecases.project import ProjectUseCase

from ..display.chat import ChatDisplay, ask_permission


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("prompt", nargs="*", help="The prompt to send to the LLM.")
    _add_options(parser)


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--temporary", action="store_true", help="Use temporary in-memory storage for chat history.")
    parser.add_argument(
        "--new-session", action="store_true", help="Start a new chat session instead of resuming the latest one."
    )


def run(args: argparse.Namespace) -> None:
    prompt = " ".join(args.prompt)
    temporary = args.temporary
    new_session = args.new_session

    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read()
        if stdin_content:
            prompt = f"{prompt}\n---\n{stdin_content}" if prompt else stdin_content

    asyncio.run(_run_chat(prompt, temporary, new_session))


async def _run_chat(prompt: str, temporary: bool, new_session: bool) -> None:
    project_use_case = ProjectUseCase(project_repository=LocalProjectRepository())
    project = project_use_case.get_project(path=".")

    console = Console()
    display = ChatDisplay(console)

    if temporary:
        chat_repository = InMemoryChatRepository()
    else:
        chat_repository = SQLiteChatRepository(get_hey_dot_directory(project.directory) / "hey.db")

    chat_use_case = AgentChatUseCase(
        permission=project.config.chat.permission,
        llm_spec=get_litellm_spec(model=project.config.chat.model, instructions=project.config.chat.instructions),
        chat_repository=chat_repository,
        tool_repository=BuiltinToolRepository(),
        ask_permission=partial(ask_permission, display, console),
    )

    if new_session or temporary:
        session = await chat_use_case.create_session(project_id=project.id)
    else:
        session = await chat_use_case.get_or_create_session(
            project_id=project.id,
            session_timeout=project.config.chat.session_timeout,
        )

    with display:
        async with chat_use_case.run(session_id=session.id, prompt=prompt) as response:
            async for event in response.events():
                match event:
                    case EmitLLMSignal(signal={"type": "text_delta", "delta": delta}):
                        display.append_text_delta(delta)
                    case EmitLLMMessage(message=message):
                        display.commit_message(message)
                        if message["role"] == "assistant":
                            for record in message["tool_calls"]:
                                display.add_pending_tool_call(record)
                    case EmitToolResult(message=message, status=status, markdown=markdown):
                        display.finish_tool_call(message, status, markdown)

    await response.collect()
