import abc
import asyncio
import contextlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

LATEST_PROTOCOL_VERSION = "2025-11-25"


class MCPError(RuntimeError):
    pass


class MCPTransportError(MCPError):
    pass


class MCPProtocolError(MCPError):
    pass


class MCPRemoteError(MCPError):
    def __init__(self, code: int, message: str, data: JsonValue | None = None) -> None:
        self.code = code
        self.data = data
        super().__init__(f"MCP error {code}: {message}")


class MCPModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ClientInfo(MCPModel):
    name: str
    version: str
    title: str | None = None
    description: str | None = None


class InitializeParams(MCPModel):
    protocol_version: str = Field(alias="protocolVersion")
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)
    client_info: ClientInfo = Field(alias="clientInfo")


class InitializeResult(MCPModel):
    protocol_version: str = Field(alias="protocolVersion")
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)
    server_info: dict[str, JsonValue] = Field(alias="serverInfo")
    instructions: str | None = None


class ToolExecution(MCPModel):
    task_support: Literal["forbidden", "optional", "required"] = Field(default="forbidden", alias="taskSupport")


class ToolDefinition(MCPModel):
    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, JsonValue] = Field(alias="inputSchema")
    output_schema: dict[str, JsonValue] | None = Field(default=None, alias="outputSchema")
    execution: ToolExecution | None = None
    annotations: dict[str, JsonValue] | None = None


class ListToolsResult(MCPModel):
    tools: list[ToolDefinition]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class ContentBlock(MCPModel):
    type: str
    text: str | None = None


class CallToolResult(MCPModel):
    content: list[ContentBlock] = Field(default_factory=list)
    structured_content: dict[str, JsonValue] | None = Field(default=None, alias="structuredContent")
    is_error: bool = Field(default=False, alias="isError")


class JsonRpcError(MCPModel):
    code: int
    message: str
    data: JsonValue | None = None


class JsonRpcEnvelope(MCPModel):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str | None = None
    params: dict[str, JsonValue] | None = None
    result: JsonValue | None = None
    error: JsonRpcError | None = None


_ENVELOPE_ADAPTER = TypeAdapter(JsonRpcEnvelope)


class MCPTransport(abc.ABC):
    @abc.abstractmethod
    async def send(self, payload: Mapping[str, Any], expect_response: bool) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    def on_initialized(self, *, protocol_version: str) -> None:
        return None


class StreamableHTTPTransport(MCPTransport):
    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._protocol_version: str | None = None
        self._session_id: str | None = None

    def on_initialized(self, *, protocol_version: str) -> None:
        self._protocol_version = protocol_version

    async def send(self, payload: Mapping[str, Any], expect_response: bool) -> dict[str, Any] | None:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._protocol_version
        if self._session_id is not None:
            headers["MCP-Session-Id"] = self._session_id

        response = await self._client.post(self._endpoint, headers=headers, json=payload)

        if self._session_id is None and "MCP-Session-Id" in response.headers:
            self._session_id = response.headers["MCP-Session-Id"]

        if not expect_response:
            if response.status_code != 202:
                raise MCPTransportError(f"notification rejected: HTTP {response.status_code} {response.text}")
            return None

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type == "application/json":
            body = response.json()
            if not isinstance(body, dict):
                raise MCPTransportError("invalid JSON-RPC response: expected object")
            return body
        if content_type == "text/event-stream":
            return _parse_sse_response(response.text, expected_id=payload.get("id"))
        raise MCPTransportError(f"unsupported content type: {content_type}")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class StdioTransport(MCPTransport):
    def __init__(self, command: Sequence[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self._command = tuple(command)
        self._cwd = cwd
        self._env = dict(env) if env is not None else None
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self._process is not None:
            return self._process
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
        )
        return self._process

    async def send(self, payload: Mapping[str, Any], expect_response: bool) -> dict[str, Any] | None:
        process = await self._ensure_process()
        if process.stdin is None or process.stdout is None:
            raise MCPTransportError("stdio transport is not ready")

        async with self._lock:
            process.stdin.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
            await process.stdin.drain()

            if not expect_response:
                return None

            expected_id = payload.get("id")
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    raise MCPTransportError("stdio stream closed before response")
                message = _parse_json_object(raw.decode("utf-8").strip())
                if message.get("id") == expected_id:
                    return message
                if "id" not in message:
                    continue
                raise MCPProtocolError("server request handling is not supported by this transport")

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return

        if process.stdin is not None:
            process.stdin.close()
            with contextlib.suppress(Exception):
                await process.stdin.wait_closed()

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5)
            return
        process.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5)
            return
        process.kill()
        await process.wait()


class MCPClient:
    def __init__(self, transport: MCPTransport) -> None:
        self._transport = transport
        self._request_id = 0
        self._initialized = False

    async def initialize(
        self,
        *,
        client_name: str,
        client_version: str,
        client_capabilities: Mapping[str, JsonValue] | None = None,
        protocol_version: str = LATEST_PROTOCOL_VERSION,
    ) -> InitializeResult:
        result = await self.request(
            "initialize",
            InitializeParams(
                protocolVersion=protocol_version,
                capabilities=dict(client_capabilities or {}),
                clientInfo=ClientInfo(name=client_name, version=client_version),
            ).model_dump(by_alias=True, exclude_none=True),
            result_model=InitializeResult,
        )
        await self.notify("notifications/initialized")
        self._transport.on_initialized(protocol_version=result.protocol_version)
        self._initialized = True
        return result

    async def list_tools(self, *, cursor: str | None = None) -> ListToolsResult:
        params: dict[str, JsonValue] = {}
        if cursor is not None:
            params["cursor"] = cursor
        return await self.request("tools/list", params or None, result_model=ListToolsResult)

    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue] | None = None) -> CallToolResult:
        params: dict[str, JsonValue] = {"name": name}
        if arguments is not None:
            params["arguments"] = dict(arguments)
        return await self.request("tools/call", params, result_model=CallToolResult)

    async def request[T: BaseModel](
        self,
        method: str,
        params: Mapping[str, JsonValue] | None,
        *,
        result_model: type[T],
    ) -> T:
        self._request_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = dict(params)

        response = await self._transport.send(payload, expect_response=True)
        if response is None:
            raise MCPTransportError("request did not return a response")
        envelope = _validate_envelope(response)
        if envelope.error is not None:
            raise MCPRemoteError(envelope.error.code, envelope.error.message, envelope.error.data)
        if envelope.result is None:
            raise MCPProtocolError("JSON-RPC response does not contain result")
        try:
            return result_model.model_validate(envelope.result)
        except ValidationError as e:
            raise MCPProtocolError(f"invalid result for {method}: {e}") from e

    async def notify(self, method: str, params: Mapping[str, JsonValue] | None = None) -> None:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = dict(params)
        await self._transport.send(payload, expect_response=False)

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> "MCPClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()


def _parse_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise MCPProtocolError("received empty JSON-RPC line")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise MCPProtocolError("received non-object JSON-RPC message")
    return payload


def _parse_sse_response(text: str, *, expected_id: str | int | None) -> dict[str, Any]:
    data_lines: list[str] = []
    for line in text.splitlines():
        if not line:
            if not data_lines:
                continue
            data = "\n".join(data_lines).strip()
            data_lines.clear()
            if not data:
                continue
            message = _parse_json_object(data)
            if message.get("id") == expected_id:
                return message
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    raise MCPProtocolError("SSE stream ended without matching response")


def _validate_envelope(response: Mapping[str, Any]) -> JsonRpcEnvelope:
    try:
        return _ENVELOPE_ADAPTER.validate_python(response)
    except ValidationError as e:
        raise MCPProtocolError(f"invalid JSON-RPC envelope: {e}") from e
