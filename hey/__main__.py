import argparse
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
from hey.settings import HEY_ROOT_CONTEXT_FILE, Profile, load_settings


def _get_context(
    client: ContextClient,
    profile: Profile,
    *,
    create_new: bool = False,
    context_id: int | None = None,
) -> Context:
    if create_new:
        context = client.create_context()
        if profile.prompt:
            client.add_messages(context, profile.prompt)
        return context

    if context_id is not None:
        context_or_not = client.get_context(context_id)
        if context_or_not is None:
            print(f"Context {context_id} not found.", file=sys.stderr)
            sys.exit(1)
        return context_or_not

    context_or_not = client.get_latest_context()
    if context_or_not is None:
        context_or_not = client.create_context()
        client.add_messages(context, profile.prompt)
    return context_or_not


def _get_prompt(client: ContextClient, context: Context) -> list[ChatCompletionMessageParam]:
    messages = client.get_messages(context)
    prompt = [message.to_message_param() for message in messages]
    return prompt


def _show_history(messages: list[ChatCompletionMessageParam]) -> None:
    console = Console()
    for message in messages:
        role = message["role"]
        content = message["content"]
        if not content or not isinstance(content, str):
            continue
        console.print(role, style="bold", end=":\n")
        console.print(Padding(Markdown(content), (0, 4)))
        console.print()


def _list_contexts(client: ContextClient) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Summary")
    table.add_column("Created At")

    for context in client.get_contexts():
        messages = client.get_messages(context, limit=3)
        summary = "\n\n".join(f"**{message.role}**: {message.content}" for message in messages if message.content)
        table.add_row(
            str(context.id),
            Markdown(summary),
            str(context.created_at.strftime("%Y-%m-%d %H:%M:%S")),
        )

    console.print(table)


def _search_contexts(client: ContextClient, query: str) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Result")
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
            Markdown(result.strip()),
            str(context.created_at.strftime("%Y-%m-%d %H:%M:%S")),
        )

    console.print(table)


def run(prog: str | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="*", help="input messages")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--new", action="store_true", help="create a new context")
    parser.add_argument("--context", type=int, help="context id")
    parser.add_argument("--history", action="store_true", help="show history")
    parser.add_argument("--list", action="store_true", help="list contexts")
    parser.add_argument("--search", help="search contexts")
    parser.add_argument("--profile", "-p", default="default")
    parser.add_argument("--config", help="path to config file")
    args = parser.parse_args()

    settings = load_settings(args.config)
    profile = settings.profiles[args.profile]

    context_client = ContextClient(HEY_ROOT_CONTEXT_FILE)

    if args.search:
        _search_contexts(context_client, args.search)
        return

    if args.list:
        _list_contexts(context_client)
        return

    context = _get_context(
        context_client,
        profile,
        create_new=args.new,
        context_id=args.context,
    )
    prompt = _get_prompt(context_client, context)

    if args.history:
        _show_history(prompt)
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
        model=profile.model,
        messages=prompt,
        temperature=profile.temperature,
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
