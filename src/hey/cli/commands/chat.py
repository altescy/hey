import argparse
import asyncio
import sys
from functools import partial

from rich.console import Console
from rich.rule import Rule

from hey.bootstrap import build_agent_spec, build_chat_repository
from hey.domain.entities.llm import EmitLLMMessage, EmitLLMSignal, EmitToolResult
from hey.infrastructure.project import LocalProjectRepository
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
    project = ProjectUseCase(project_repository=LocalProjectRepository()).get_project(".")

    console = Console()
    display = ChatDisplay(console)
    permission_lock = asyncio.Lock()

    agent = build_agent_spec(
        project.config.chat,
        ask_permission=partial(ask_permission, display, console, permission_lock),
    )
    chat_repository = build_chat_repository(project.directory, temporary=temporary)

    chat_use_case = AgentChatUseCase(agent=agent, chat_repository=chat_repository)

    is_new = True
    if new_session or temporary:
        session = await chat_use_case.create_session(project_id=project.id)
    else:
        session, is_new = await chat_use_case.get_or_create_session(
            project_id=project.id,
            session_timeout=project.config.chat.session_timeout,
        )

    if is_new and not temporary:
        console.print(Rule(f"[dim]New session started  ·  Session {session.id}[/dim]", style="dim"))
        console.print()

    display.show_waiting()
    async with chat_use_case.run(session_id=session.id, prompt=prompt) as response:
        async for event in response.events():
            match event:
                case EmitLLMSignal(signal={"type": "thinking_delta", "delta": delta}):
                    display.append_thinking_delta(delta)
                case EmitLLMSignal(signal={"type": "thinking_part_done", "text": text}):
                    display.set_thinking_text(text)
                case EmitLLMSignal(signal={"type": "text_delta", "delta": delta}):
                    display.append_text_delta(delta)
                case EmitLLMMessage(message=message):
                    display.commit_message(message)
                    if message["role"] == "assistant":
                        for record in message["tool_calls"]:
                            display.add_pending_tool_call(record)
                case EmitToolResult(message=message, status=status, view=markdown):
                    display.finish_tool_call(message, status, markdown)
                    if not display.has_pending_tool_calls:
                        display.show_waiting()
    display.done()

    await response.collect()
