import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

from hey.domain.entities.chat import ChatMessage
from hey.domain.entities.llm import ToolResultMessage
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

    i = 0
    while i < len(messages):
        chat_message = messages[i]
        msg = chat_message.message
        ts = chat_message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        i += 1

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

                for record in tool_calls:
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
