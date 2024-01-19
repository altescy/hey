import argparse
import datetime
import sys

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
)
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table

from hey import __version__
from hey.context import Context, ContextClient
from hey.settings import HEY_CURRENT_CONTEXT_FILE, HEY_ROOT_CONTEXT_FILE, Profile, load_settings

_DEFAULT_MODEL = "gpt-3.5-turbo"


def _truncate_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[: max_lines - 1]) + "..."


def _parse_range_param(rangeparam: str) -> slice:
    if ":" not in rangeparam or rangeparam.count(":") > 1:
        raise ValueError("Invalid range parameter")
    start_str, end_str = rangeparam.split(":")
    start = int(start_str) if start_str else None
    end = int(end_str) if end_str else None
    return slice(start, end)


def _get_context(
    client: ContextClient,
    profile: Profile,
    *,
    new_name: str | None = None,
    context_id: int | None = None,
) -> Context:
    if new_name is not None:
        title = new_name or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        context = client.create_context(title, profile.prompt)
        _switch_context(client, context)
        return context

    if context_id is None and HEY_CURRENT_CONTEXT_FILE.exists():
        context_id = int(HEY_CURRENT_CONTEXT_FILE.read_text())

    if context_id is not None:
        context_or_not = client.get_context(context_id)
        if context_or_not is None:
            print(f"Context {context_id} not found.", file=sys.stderr)
            sys.exit(1)
        return context_or_not

    context_or_not = client.get_latest_context()
    if context_or_not is None:
        title = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        context_or_not = client.create_context(title, profile.prompt)
    return context_or_not


def _get_prompt(client: ContextClient, context: Context) -> list[ChatCompletionMessageParam]:
    messages = client.get_messages(context)
    prompt = [message.to_message_param() for message in messages]
    return prompt


def _show_history(context: Context, messages: list[ChatCompletionMessageParam]) -> None:
    console = Console()
    console.print(f"[bold][{context.id}: {context.title}][/bold]")
    console.print()
    for message in messages:
        role = message["role"]
        content = message["content"]
        if not content or not isinstance(content, str):
            continue
        console.print(role, style="bold", end=":\n")
        console.print(Padding(Markdown(content), (0, 4)))
        console.print()


def _list_contexts(client: ContextClient, rangeparam: str) -> None:
    slice_ = _parse_range_param(rangeparam)

    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Summary")
    table.add_column("Created At")

    for context in client.get_contexts()[slice_]:
        messages = client.get_messages(context, limit=3)
        summary = _truncate_lines(
            "\n\n".join(f"**{message.role}**: {message.content}" for message in messages if message.content),
            max_lines=5,
        )
        table.add_row(
            str(context.id),
            str(context.title),
            Markdown(summary),
            str(context.created_at.strftime("%Y-%m-%d %H:%M:%S")),
        )

    console.print(table)


def _search_contexts(client: ContextClient, query: str) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Messages")
    table.add_column("Created At")

    for context in client.search_contexts(query):
        messages = client.get_messages(context)
        result = ""
        for message in messages:
            if message.content and query in message.content:
                content = message.content
                position = message.content.index(query)
                if position > 10:
                    content = "..." + content[position - 10 :]
                if len(content) > 100:
                    content = content[:100] + "..."
                result += f"- **{message.role}**: {content}\n"
        table.add_row(
            str(context.id),
            str(context.title),
            Markdown(result.strip()),
            str(context.created_at.strftime("%Y-%m-%d %H:%M:%S")),
        )

    console.print(table)


def _delete_contexts(client: ContextClient, context_ids: list[int]) -> None:
    for context_id in context_ids:
        client.delete_context(context_id)
    if HEY_CURRENT_CONTEXT_FILE.exists():
        current_context_id = int(HEY_CURRENT_CONTEXT_FILE.read_text())
        if current_context_id in context_ids:
            HEY_CURRENT_CONTEXT_FILE.unlink()


def _undo(client: ContextClient, context: Context) -> None:
    message = client.delete_last_message(context)
    while message is not None and message.role != "user":
        message = client.delete_last_message(context)


def _rename_context(client: ContextClient, context: Context, new_name: str) -> None:
    client.rename_context(context, new_name)


def _switch_context(client: ContextClient, context: int | Context) -> None:
    if isinstance(context, int):
        _context = client.get_context(context)
        if _context is None:
            print(f"Context {context} not found.", file=sys.stderr)
            sys.exit(1)
        context = _context
    HEY_CURRENT_CONTEXT_FILE.write_text(str(context.id))


def run(prog: str | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="*", help="input messages")
    parser.add_argument(
        "--new",
        nargs="?",
        const="",
        default=None,
        help="create a new context (with optional context name)",
    )
    parser.add_argument(
        "--context",
        type=int,
        help="context id",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="show history",
    )
    parser.add_argument(
        "--list",
        nargs="?",
        const=":",
        default=None,
        help="list contexts (with optional range parameter: [start:end])",
    )
    parser.add_argument(
        "--search",
        help="search contexts",
    )
    parser.add_argument(
        "--delete",
        type=int,
        default=[],
        action="append",
        help="delete contexts",
    )
    parser.add_argument(
        "--switch",
        type=int,
        help="switch context",
    )
    parser.add_argument(
        "--undo",
        action="store_true",
        help="delete last message and response",
    )
    parser.add_argument(
        "--rename",
        help="rename context",
    )
    parser.add_argument(
        "--model",
        help="model name",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="sampling temperature",
    )
    parser.add_argument(
        "--profile",
        default="default",
        help="profile name",
    )
    parser.add_argument(
        "--config",
        help="path to config file",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s " + __version__,
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    profile = settings.profiles[args.profile]

    context_client = ContextClient(HEY_ROOT_CONTEXT_FILE)

    if args.switch is not None:
        _switch_context(context_client, args.switch)
        return

    if args.delete:
        _delete_contexts(context_client, args.delete)
        return

    if args.search:
        _search_contexts(context_client, args.search)
        return

    if args.list:
        _list_contexts(context_client, args.list)
        return

    context = _get_context(
        context_client,
        profile,
        new_name=args.new,
        context_id=args.context,
    )
    prompt = _get_prompt(context_client, context)

    if args.undo:
        _undo(context_client, context)
        return

    if args.rename:
        _rename_context(context_client, context, args.rename)
        return

    if args.history:
        _show_history(context, prompt)
        return

    if not args.inputs:
        return

    openai_client = OpenAI(
        base_url=profile.base_url,  # type: ignore[arg-type]
        api_key=profile.api_key,
    )

    text = " ".join(args.inputs)
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": text}
    prompt.append(user_message)

    response = ""

    completion = openai_client.chat.completions.create(
        model=args.model or profile.model or _DEFAULT_MODEL,
        messages=prompt,
        temperature=args.temperature or profile.temperature,
        stream=True,
    )

    console = Console()
    with Live(Markdown(response), console=console, refresh_per_second=10) as live:
        for chunk in completion:
            content = chunk.choices[0].delta.content
            if content is not None:
                response += content
                live.update(Markdown(response))

    system_message: ChatCompletionAssistantMessageParam = {"role": "assistant", "content": response}
    context_client.add_messages(context, [user_message, system_message])
