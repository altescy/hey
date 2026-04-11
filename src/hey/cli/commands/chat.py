import asyncio
import json
import textwrap
from contextlib import ExitStack

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.status import Status

from hey.domain.entities.llm import EmitLLMMessage, EmitLLMSignal, EmitToolResult, LLMMessage, ToolCallRecord
from hey.infrastructure.chat import InMemoryChatRepository
from hey.infrastructure.llm import get_litellm_spec
from hey.infrastructure.project import LocalProjectRepository
from hey.infrastructure.tool import BuiltinToolRepository
from hey.usecases.chat import AgentChatUseCase
from hey.usecases.project import ProjectUseCase


def _render_text(
    o: object,
    *,
    width: int | None = None,
    escape: bool = True,
) -> str:
    text = (repr(o)[1:-1] if escape else o) if isinstance(o, str) else repr(o)
    if width is not None:
        return textwrap.shorten(text, width=width, placeholder="…")
    return text


def _render_message(
    message: LLMMessage,
    *,
    width: int | None = None,
    escape: bool = True,
) -> str:
    content = "".join(part["text"] for part in message["parts"])
    return _render_text(content, width=width, escape=escape)


def _render_tool_call(
    record: ToolCallRecord,
    *,
    width: int | None = None,
) -> str:
    name = record["name"]
    params = ", ".join(
        f"{key}={_render_text(json.dumps(val), width=10)}" for key, val in json.loads(record["args_json"]).items()
    )
    return _render_text(f"[bold]{name}[/bold]: {params}", width=width)


async def _run_chat(prompt: str) -> None:
    project_use_case = ProjectUseCase(
        project_repository=LocalProjectRepository(),
    )
    project = project_use_case.get_project(path=".")

    chat_use_case = AgentChatUseCase(
        llm_spec=get_litellm_spec(
            model=project.config.chat.model,
            instructions=project.config.chat.instructions,
        ),
        chat_repository=InMemoryChatRepository(),
        tool_repository=BuiltinToolRepository(),
    )
    session = await chat_use_case.create_session(project_id=project.id)

    console = Console()
    markdown = Markdown("")
    tool_calls: dict[str, tuple[ToolCallRecord, Status]] = {}

    def _make_live(markdown: Markdown) -> Live:
        return Live(markdown, console=console, refresh_per_second=16)

    with ExitStack() as stack:
        live = stack.enter_context(_make_live(markdown))

        async with chat_use_case.run(session_id=session.id, prompt=prompt) as response:
            async for event in response.events():
                match event:
                    case EmitLLMSignal(signal=signal):
                        match signal["type"]:
                            case "text_delta":
                                markdown = Markdown(markdown.markup + signal["delta"])
                                live.update(markdown)
                    case EmitLLMMessage(message=message):
                        live.update(Markdown(_render_message(message, escape=False)))
                        stack.pop_all().close()
                        markdown = Markdown("")
                        live = stack.enter_context(_make_live(markdown))
                        match message["role"]:
                            case "assistant":
                                if message["tool_calls"]:
                                    for record in message["tool_calls"]:
                                        status = console.status(_render_tool_call(record))
                                        stack.enter_context(status)
                                        tool_calls[record["id"]] = (record, status)
                    case EmitToolResult(message=message, status=tool_call_status):
                        tool_call = tool_calls.pop(message["tool_call_id"], None)
                        if tool_call is not None:
                            record, status = tool_call
                            result = _render_message(message, width=60)
                            status.stop()
                            icon = "[green]✔[/green]" if tool_call_status == "success" else "[red]✘[/red]"
                            console.print(f"{icon} {_render_tool_call(record)}")
                            console.print(f"    [dim]╰─ {result}[/dim]\n")

    await response.collect()


def run_chat(prompt: str) -> None:
    asyncio.run(_run_chat(prompt))
