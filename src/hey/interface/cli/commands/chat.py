import argparse
import asyncio
import sys
from contextlib import suppress

from rich.console import Console

from hey.application.dto import (
    CompactChatInput,
    CreateSessionInput,
    GetOrCreateSessionInput,
    GetProjectInput,
    RunChatInput,
)
from hey.bootstrap.container import Container
from hey.core.workflow.events import WorkflowNodeFinishedEvent, WorkflowNodeStartedEvent
from hey.domain.entities.llm import EmitLLMMessage, EmitLLMSignal, EmitToolResult

from ..display.chat import ChatDisplay


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("prompt", nargs="*", help="The prompt to send to the LLM.")
    _add_options(parser)


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--temporary", action="store_true", help="Use temporary in-memory storage for chat history.")
    parser.add_argument("--compact", action="store_true", help="Compact the latest chat session and exit.")
    parser.add_argument(
        "--new-session", action="store_true", help="Start a new chat session instead of resuming the latest one."
    )


def run(args: argparse.Namespace) -> None:
    prompt = " ".join(args.prompt)
    temporary = args.temporary
    new_session = args.new_session
    compact = args.compact

    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read()
        if stdin_content:
            prompt = f"{prompt}\n---\n{stdin_content}" if prompt else stdin_content

    if compact:
        if prompt.strip():
            raise SystemExit("--compact cannot be used with a prompt or stdin input.")
        if temporary:
            raise SystemExit("--compact cannot be used with --temporary.")
        if new_session:
            raise SystemExit("--compact cannot be used with --new-session.")

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_chat(prompt, temporary, new_session, compact))
    except (KeyboardInterrupt, asyncio.CancelledError):
        console = Console()
        console.show_cursor(True)
        console.print()
        raise SystemExit(130)
    finally:
        _shutdown_loop(loop)
        asyncio.set_event_loop(None)
        loop.close()


def _shutdown_loop(loop: asyncio.AbstractEventLoop) -> None:
    _shutdown_pending_tasks(loop)
    with suppress(asyncio.CancelledError, KeyboardInterrupt):
        loop.run_until_complete(loop.shutdown_asyncgens())
    with suppress(asyncio.CancelledError, KeyboardInterrupt):
        loop.run_until_complete(loop.shutdown_default_executor())


def _shutdown_pending_tasks(loop: asyncio.AbstractEventLoop) -> None:
    pending = {t for t in asyncio.all_tasks(loop) if not t.done()}
    if not pending:
        return

    for t in pending:
        t.cancel()

    async def _wait() -> None:
        await asyncio.gather(*pending, return_exceptions=True)

    with suppress(asyncio.CancelledError, KeyboardInterrupt):
        loop.run_until_complete(_wait())

    for t in pending:
        if t.done() and not t.cancelled():
            with suppress(BaseException):
                t.exception()
        else:
            # Suppress asyncio "Task was destroyed but it is pending!" warning
            # for cancelled tasks that may be GC'd before they fully finish.
            t._log_destroy_pending = False  # type: ignore[attr-defined]


async def _run_chat(prompt: str, temporary: bool, new_session: bool, compact: bool) -> None:
    console = Console()
    display = ChatDisplay(console)

    container = Container.build(
        temporary=temporary,
        ask_permission=display.ask_permission,
    )
    chat_usecase = container.chat_usecase
    project_usecase = container.project_usecase

    output = project_usecase.get_project(GetProjectInput(path="."))
    project = output["project"]

    is_new = True
    if new_session or temporary:
        session = (await chat_usecase.create_session(CreateSessionInput(project_id=project.id)))["session"]
    else:
        result = await chat_usecase.get_or_create_session(
            GetOrCreateSessionInput(project_id=project.id, session_timeout=project.config.chat.session_timeout)
        )
        session, is_new = result["session"], result["is_new"]

    if is_new and not temporary:
        display.show_session_start(str(session.id))

    try:
        if compact:
            with console.status("[dim]Compacting session...[/dim]", spinner="dots"):
                output = await chat_usecase.compact(CompactChatInput(session_id=session.id))
            if output["compacted"]:
                console.print("[dim]Session compacted.[/dim]")
            else:
                console.print("[dim]Nothing to compact.[/dim]")
            return

        display.show_waiting()
        async with chat_usecase.run(RunChatInput(session_id=session.id, prompt=prompt)) as response:
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
                    case WorkflowNodeStartedEvent(node_name="maybe_compact"):
                        display.show_compacting()
                    case WorkflowNodeFinishedEvent(node_name="maybe_compact"):
                        display.hide_compacting()
        await response.collect()
    finally:
        display.done()
