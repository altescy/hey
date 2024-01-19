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
from rich.text import Text

from hey import __version__
from hey.context import Context, ContextClient
from hey.settings import (
    HEY_CURRENT_CONTEXT_FILE,
    HEY_DEFAULT_MODEL_NAME,
    HEY_ROOT_CONTEXT_FILE,
    HYE_DEFAULT_PROFILE_NAME,
    Profile,
    init_settings,
    load_settings,
)


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


def _exit_with_error(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def _create_context(
    client: ContextClient,
    profile: Profile,
    title: str,
) -> Context:
    title = title or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    with client:
        context = client.create_context(title, profile.prompt)
    return context


def _get_context(
    client: ContextClient,
    context_id: int | None = None,
) -> Context | None:
    if context_id is None and HEY_CURRENT_CONTEXT_FILE.exists():
        context_id = int(HEY_CURRENT_CONTEXT_FILE.read_text())

    if context_id is not None:
        with client:
            context_or_not = client.get_context(context_id)
        if context_or_not is None:
            _exit_with_error(f"Context {context_id} not found.")
            return None
        return context_or_not

    with client:
        context_or_not = client.get_latest_context()
    return context_or_not


def _get_prompt(client: ContextClient, context: Context) -> list[ChatCompletionMessageParam]:
    with client:
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

    with client:
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

    with client:
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


def _delete_context(client: ContextClient, context: int | Context) -> None:
    if isinstance(context, Context):
        assert context.id is not None
        context = context.id
    with client:
        client.delete_context(context)
        if HEY_CURRENT_CONTEXT_FILE.exists():
            current_context_id = int(HEY_CURRENT_CONTEXT_FILE.read_text())
            if current_context_id == context:
                HEY_CURRENT_CONTEXT_FILE.unlink()


def _undo(client: ContextClient, context: Context) -> None:
    with client:
        message = client.delete_last_message(context)
        while message is not None and message.role != "user":
            message = client.delete_last_message(context)


def _rename_context(client: ContextClient, context: Context, new_name: str) -> None:
    with client:
        client.rename_context(context, new_name)


def _switch_context(client: ContextClient, context: int | Context) -> None:
    with client:
        if isinstance(context, int):
            _context = client.get_context(context)
            if _context is None:
                _exit_with_error(f"Context {context} not found.")
                return
            context = _context
        HEY_CURRENT_CONTEXT_FILE.write_text(str(context.id))


def main(prog: str | None = None) -> None:
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
        action="store_true",
        help="delete context",
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
        "--plain",
        action="store_true",
        help="plain text mode",
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
        default=HYE_DEFAULT_PROFILE_NAME,
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

    init_settings()

    settings = load_settings(args.config)
    if args.profile not in settings.profiles:
        _exit_with_error(f"Profile {args.profile} not found.")
        return
    profile = settings.profiles[args.profile]

    context_client = ContextClient(HEY_ROOT_CONTEXT_FILE)

    if args.list:
        _list_contexts(context_client, args.list)
        return

    if args.search:
        _search_contexts(context_client, args.search)
        return

    if args.switch is not None:
        _switch_context(context_client, args.switch)
        return

    if args.new is not None:
        context = _create_context(context_client, profile, args.new)
        _switch_context(context_client, context)
    else:
        context_or_not = _get_context(
            context_client,
            context_id=args.context,
        )
        if context_or_not is None:
            _exit_with_error("No context found.")
            return
        context = context_or_not

    prompt = _get_prompt(context_client, context)

    if args.history:
        _show_history(context, prompt)
        return

    if args.rename:
        _rename_context(context_client, context, args.rename)
        return

    if args.undo:
        _undo(context_client, context)
        return

    if args.delete:
        _delete_context(context_client, context)
        return

    if not args.inputs:
        return

    if args.inputs == ["-"]:
        args.inputs = sys.stdin.readlines()

    openai_client = OpenAI(
        base_url=profile.base_url,  # type: ignore[arg-type]
        api_key=profile.api_key,
    )

    text = " ".join(args.inputs)
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": text}
    prompt.append(user_message)

    response = ""

    completion = openai_client.chat.completions.create(
        model=args.model or profile.model or HEY_DEFAULT_MODEL_NAME,
        messages=prompt,
        temperature=args.temperature or profile.temperature,
        stream=True,
    )

    console = Console()
    render = Text if args.plain else Markdown
    with Live(render(response), console=console, refresh_per_second=10) as live:
        for chunk in completion:
            content = chunk.choices[0].delta.content
            if content is not None:
                response += content
                live.update(render(response))

    system_message: ChatCompletionAssistantMessageParam = {"role": "assistant", "content": response}
    with context_client:
        context_client.add_messages(context, [user_message, system_message])
