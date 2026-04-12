import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

from hey.domain.entities.chat import ChatMessage
from hey.domain.services.project import get_hey_dot_directory
from hey.infrastructure.chat import SQLiteChatRepository
from hey.infrastructure.project import LocalProjectRepository
from hey.usecases.project import ProjectUseCase

from ..display.console import render_tool_call, render_user_message_panel


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session",
        type=int,
        default=None,
        metavar="ID",
        help="Session ID to display. Defaults to the latest session.",
    )


def run(args: argparse.Namespace) -> None:
    project_use_case = ProjectUseCase(project_repository=LocalProjectRepository())
    project = project_use_case.get_project(path=".")

    db_path = get_hey_dot_directory(project.directory) / "hey.db"
    chat_repository = SQLiteChatRepository(db_path)

    if args.session is not None:
        from hey.domain.entities.chat import ChatSessionID

        session = chat_repository.get_session_by_id(ChatSessionID(args.session))
        if session is None:
            raise SystemExit(f"Session {args.session} not found.")
    else:
        session = chat_repository.get_latest_session_by_project_id(project.id)
        if session is None:
            raise SystemExit("No chat history found.")

    messages: list[ChatMessage] = chat_repository.get_messages_by_session_id(session.id)

    console = Console()
    console.print(
        Rule(
            f"[dim]Session {session.id}  ·  started {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
            style="dim",
        )
    )
    console.print()

    for chat_message in messages:
        msg = chat_message.message
        ts = chat_message.created_at.strftime("%Y-%m-%d %H:%M:%S")

        match msg:
            case {"role": "user"}:
                console.print(render_user_message_panel(msg, ts))
                console.print()

            case {"role": "assistant", "parts": parts, "tool_calls": tool_calls}:
                text = "".join(part["text"] for part in parts)
                if text:
                    console.print(Markdown(text))
                for record in tool_calls:
                    console.print(f"  {render_tool_call(record)}")
                console.print()

            case {"role": "tool_result", "parts": parts}:
                text = "".join(part["text"] for part in parts)
                console.print(f"  [dim]╰─ {text[:120]}{'…' if len(text) > 120 else ''}[/dim]")
                console.print()

            case {"role": "system"}:
                pass  # system メッセージは表示しない
