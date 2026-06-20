import argparse
import asyncio
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

from hey.application.dto import GetProjectInput
from hey.application.usecases.chat import AgentChatUseCase
from hey.bootstrap.container import Container
from hey.domain.entities.chat import ChatMessage, ChatSessionID
from hey.domain.entities.llm import ToolResultMessage
from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import ChatMessageRetrievalRequest, ChatSessionRetrievalRequest

from ..display.console import render_tool_call, render_user_message_panel
from ..display.history import (
    render_compact_messages,
    render_search_results,
    render_session_table,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session",
        type=int,
        default=None,
        metavar="ID",
        help="Session ID to display. Defaults to the latest session.",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List sessions instead of showing messages.",
    )
    parser.add_argument(
        "-s",
        "--search",
        default=None,
        metavar="QUERY",
        help="Search messages. Without --session, searches across the whole project.",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=None,
        metavar="N",
        help="Show only the latest N messages (cannot be combined with --offset/--limit).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        metavar="N",
        help="Skip the first N messages.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Show at most N messages.",
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="Show a compact, one-line-per-turn view.",
    )
    parser.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        help="Show newest messages first.",
    )


def _validate_args(args: argparse.Namespace) -> None:
    if args.list and args.session is not None:
        raise SystemExit("--list cannot be combined with --session.")
    if args.last is not None and args.last < 1:
        raise SystemExit("--last must be a positive integer.")
    if args.last is not None and (args.offset != 0 or args.limit is not None):
        raise SystemExit("--last cannot be combined with --offset or --limit.")
    if args.offset < 0:
        raise SystemExit("--offset must be non-negative.")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be a positive integer.")


async def _run_history(args: argparse.Namespace) -> None:
    _validate_args(args)

    container = Container.build()
    project_usecase = container.project_usecase
    chat_usecase = container.chat_usecase

    project = project_usecase.get_project(GetProjectInput(path="."))["project"]

    if args.list:
        await _run_list(chat_usecase, project.id, args)
        return

    if args.search is not None and args.session is None:
        await _run_search_project(chat_usecase, project.id, args)
        return

    session_id = await _resolve_session_id(chat_usecase, project.id, args)
    if args.search is not None:
        await _run_search_session(chat_usecase, session_id, args)
    else:
        await _run_show_session(chat_usecase, session_id, args)


async def _resolve_session_id(
    chat_usecase: AgentChatUseCase[Any, Any],
    project_id: ProjectID,
    args: argparse.Namespace,
) -> ChatSessionID:
    if args.session is not None:
        session = await chat_usecase.get_session_by_id(ChatSessionID(args.session))
        if session is None:
            raise SystemExit(f"Session {args.session} not found.")
        return session.id

    session = await chat_usecase.get_latest_session_by_project_id(project_id)
    if session is None:
        raise SystemExit("No chat history found.")
    return session.id


async def _run_list(
    chat_usecase: AgentChatUseCase[Any, Any],
    project_id: ProjectID,
    args: argparse.Namespace,
) -> None:
    request = ChatSessionRetrievalRequest(
        offset=args.offset,
        limit=args.limit,
        reverse=not args.reverse,  # default is newest-first; --reverse flips to oldest-first
    )
    response = await chat_usecase.list_sessions({"project_id": project_id, "request": request})

    console = Console()
    if not response["sessions"].results:
        console.print("[dim]No sessions found.[/dim]")
        return

    console.print(render_session_table(response["sessions"]))
    total = response["sessions"].total
    shown = len(response["sessions"].results)
    if shown < total:
        console.print(f"[dim]Showing {shown} of {total} sessions.[/dim]")


async def _run_search_project(
    chat_usecase: AgentChatUseCase[Any, Any],
    project_id: ProjectID,
    args: argparse.Namespace,
) -> None:
    offset, limit = await _resolve_offset_limit(
        chat_usecase,
        session_id=None,
        project_id=project_id,
        args=args,
    )
    request = ChatMessageRetrievalRequest(
        query=args.search,
        offset=offset,
        limit=limit,
    )
    message_response = await chat_usecase.get_messages_by_project_id(project_id, request)

    console = Console()
    if not message_response.results:
        console.print(f'[dim]No messages matching "{args.search}".[/dim]')
        return

    console.print(
        render_search_results(
            message_response.results,
            args.search,
            width=max(console.width - 20, 40),
        )
    )
    _print_paging_footer(console, message_response.total, len(message_response.results), message_response.next_offset)


async def _run_search_session(
    chat_usecase: AgentChatUseCase[Any, Any],
    session_id: ChatSessionID,
    args: argparse.Namespace,
) -> None:
    offset, limit = await _resolve_offset_limit(
        chat_usecase,
        session_id=session_id,
        project_id=None,
        args=args,
    )
    request = ChatMessageRetrievalRequest(
        query=args.search,
        offset=offset,
        limit=limit,
    )
    message_response = await chat_usecase.get_messages_by_session_id(session_id, request)

    console = Console()
    if not message_response.results:
        console.print(f'[dim]No messages matching "{args.search}" in session {session_id}.[/dim]')
        return

    console.print(
        Rule(
            f"[dim]Session {session_id}  ·  search: {args.search}[/dim]",
            style="dim",
        )
    )
    console.print(
        render_search_results(
            message_response.results,
            args.search,
            width=max(console.width - 20, 40),
        )
    )
    _print_paging_footer(console, message_response.total, len(message_response.results), message_response.next_offset)


async def _run_show_session(
    chat_usecase: AgentChatUseCase[Any, Any],
    session_id: ChatSessionID,
    args: argparse.Namespace,
) -> None:
    session = await chat_usecase.get_session_by_id(session_id)
    if session is None:
        raise SystemExit(f"Session {session_id} not found.")

    offset, limit = await _resolve_offset_limit(
        chat_usecase,
        session_id=session_id,
        project_id=None,
        args=args,
    )
    request = ChatMessageRetrievalRequest(offset=offset, limit=limit)
    message_response = await chat_usecase.get_messages_by_session_id(session_id, request)
    messages: list[ChatMessage] = message_response.results

    console = Console()
    console.print(
        Rule(
            f"[dim]Session {session.id}  ·  started {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
            style="dim",
        )
    )
    console.print()

    if args.compact:
        console.print(
            render_compact_messages(
                messages,
                reverse=args.reverse,
                width=max(console.width - 4, 40),
            )
        )
        _print_paging_footer(
            console,
            message_response.total,
            len(messages),
            message_response.next_offset,
        )
        return

    if args.reverse:
        messages = list(reversed(messages))

    _render_full_messages(console, messages)
    _print_paging_footer(
        console,
        message_response.total,
        len(messages),
        message_response.next_offset,
    )


async def _resolve_offset_limit(
    chat_usecase: AgentChatUseCase[Any, Any],
    session_id: ChatSessionID | None,
    project_id: ProjectID | None,
    args: argparse.Namespace,
) -> tuple[int, int | None]:
    if args.last is None:
        return args.offset, args.limit

    if session_id is not None:
        total = await chat_usecase.count_messages_by_session_id(session_id, query=args.search)
    else:
        assert project_id is not None
        total = await chat_usecase.count_messages_by_project_id(project_id, query=args.search)

    offset = max(0, total - args.last)
    return offset, args.last


def _print_paging_footer(
    console: Console,
    total: int,
    shown: int,
    next_offset: int | None,
) -> None:
    if shown < total or next_offset is not None:
        parts = [f"Showing {shown} of {total} messages"]
        if next_offset is not None:
            parts.append(f"--offset {next_offset} to continue")
        console.print(f"[dim]{'; '.join(parts)}.[/dim]")


def _render_full_messages(console: Console, messages: list[ChatMessage]) -> None:
    i = 0
    while i < len(messages):
        chat_message = messages[i]
        msg = chat_message.message
        ts = chat_message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        i += 1

        if chat_message.kind == "summary":
            tail_start = chat_message.metadata.get("tail_start_message_id")
            tail_text = f" · tail starts at message #{tail_start}" if tail_start is not None else ""
            console.print(Rule(f"[yellow]Compacted[/yellow] · [dim]{ts}{tail_text}[/dim]", style="yellow"))
            console.print()
            continue

        match msg:
            case {"role": "user"}:
                console.print(render_user_message_panel(msg, ts))
                console.print()

            case {"role": "assistant", "parts": parts, "tool_calls": tool_calls}:
                text = "".join(part["text"] for part in parts)
                if text:
                    console.print(Markdown(text))

                # Collect the tool_result messages that immediately follow this
                # assistant message, indexed by tool_call_id, so each tool call
                # can be paired with its result regardless of ordering.
                results_by_id: dict[str, ToolResultMessage] = {}
                j = i
                while j < len(messages) and messages[j].message.get("role") == "tool_result":
                    result_msg = messages[j].message
                    assert result_msg["role"] == "tool_result"
                    results_by_id[result_msg["tool_call_id"]] = result_msg
                    j += 1
                # Advance the outer cursor past all consumed tool_result messages.
                i = j

                if tool_calls:
                    console.print()

                for idx, record in enumerate(tool_calls):
                    if idx > 0:
                        console.print()
                    console.print(f"  {render_tool_call(record)}")
                    result = results_by_id.get(record["id"])
                    if result is not None:
                        text = "".join(part["text"] for part in result["parts"])
                        console.print(f"  [dim]╰─ {text[:120]}{'…' if len(text) > 120 else ''}[/dim]")

                console.print()

            case {"role": "tool_result"}:
                # Orphaned tool_result (should not happen in normal flow).
                text = "".join(part["text"] for part in msg["parts"])
                console.print(f"  [dim]╰─ {text[:120]}{'…' if len(text) > 120 else ''}[/dim]")
                console.print()

            case {"role": "system"}:
                pass  # system メッセージは表示しない


def run(args: argparse.Namespace) -> None:
    asyncio.run(_run_history(args))
