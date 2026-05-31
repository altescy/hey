import asyncio
import json
import threading
from collections.abc import Coroutine, Mapping
from typing import Any

from hey.core.mcp import MCPClient, MCPTransport, StdioTransport, StreamableHTTPTransport
from hey.core.mcp.client import CallToolResult, JsonValue
from hey.domain.entities.config import MCPServerConfig
from hey.domain.entities.tool import ToolName, ToolSpec
from hey.domain.repositories.tool import IToolRepository
from hey.version import VERSION


class MCPToolRepository(IToolRepository):
    def __init__(self, servers: Mapping[str, MCPServerConfig]) -> None:
        enabled_servers = {name: server for name, server in servers.items() if server.enabled}
        self._tools = _run_coro_sync(_load_tools(enabled_servers)) if enabled_servers else {}

    def get_all_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_spec_by_name(self, name: ToolName) -> ToolSpec:
        return self._tools[name]


async def _load_tools(servers: Mapping[str, MCPServerConfig]) -> dict[ToolName, ToolSpec]:
    specs: dict[ToolName, ToolSpec] = {}
    for name, server in servers.items():
        transport = _build_transport(server)
        try:
            async with MCPClient(transport) as client:
                await client.initialize(client_name="hey", client_version=VERSION)
                cursor: str | None = None
                while True:
                    page = await client.list_tools(cursor=cursor)
                    for tool in page.tools:
                        spec = _convert_mcp_tool_to_spec(name, server, tool.name, tool.description, tool.input_schema)
                        specs[spec.name] = spec
                    if not page.next_cursor:
                        break
                    cursor = page.next_cursor
        except Exception:
            continue
    return specs


def _build_transport(server: MCPServerConfig) -> MCPTransport:
    if server.transport == "stdio":
        return StdioTransport(command=server.command, cwd=server.cwd, env=server.env)
    assert server.url is not None
    return StreamableHTTPTransport(endpoint=server.url, timeout=server.timeout)


def _convert_mcp_tool_to_spec(
    server_name: str,
    server: MCPServerConfig,
    tool_name: str,
    description: str | None,
    input_schema: Mapping[str, JsonValue],
) -> ToolSpec:
    namespaced_name = ToolName(f"mcp_{server_name}_{tool_name}")

    async def _invoke(**kwargs: Any) -> str:
        transport = _build_transport(server)
        async with MCPClient(transport) as client:
            await client.initialize(client_name="hey", client_version=VERSION)
            result = await client.call_tool(name=tool_name, arguments=kwargs)
        return _render_call_result(result)

    return ToolSpec(
        name=namespaced_name,
        description=description or f"MCP tool '{tool_name}' from server '{server_name}'",
        func=_invoke,
        permission={},
        parameters_annotation=dict[str, Any],
        return_annotation=str,
        parameters_schema=input_schema,
    )


def _render_call_result(result: CallToolResult) -> str:
    if result.structured_content is not None:
        text = json.dumps(result.structured_content, ensure_ascii=False)
    else:
        text_parts = [part.text for part in result.content if part.type == "text" and part.text is not None]
        text = "\n".join(text_parts).strip()
    if result.is_error:
        raise RuntimeError(text or "MCP tool returned an error")
    return text


def _run_coro_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[T] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if error:
        raise error[0]
    return result[0]
