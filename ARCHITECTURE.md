# Architecture

`hey` is a CLI chat agent. It is structured around a **clean / layered architecture** with explicit dependency rules, plus a small **engine core** (agent runtime, workflow graph, MCP, schema) that the application layer reuses. This document describes the runtime layout, key abstractions, and how a single `hey "<prompt>"` invocation actually flows through the system.

## Layers

```
src/hey/
├── interface/                # CLI: argparse, terminal rendering (rich)
│   └── cli/
├── application/              # Use cases + DTOs (TypedDict)
│   ├── usecases/
│   ├── defaults.py
│   └── dto.py
├── bootstrap/                # Composition root (Container, factories)
├── domain/                   # Pure domain (no I/O)
│   ├── entities/             # Data shapes
│   ├── exceptions/           # Domain-level exceptions (tool, sandbox)
│   ├── repositories/         # Persistence protocols
│   └── services/             # Domain logic + capability protocols
│                             #   (ISandboxRunner, AuthProvider live here)
├── core/                     # Reusable engine pieces (stdlib + pydantic only)
│   ├── agent/                # Generic agent runtime (Engine/Reducer/Contextualizer)
│   ├── workflow/             # WorkflowExecutor, WorkflowGraph, EventSource
│   ├── mcp/                  # MCP client + transports
│   ├── schema/               # JSON schema / Python signature inspection
│   ├── pattern/              # JSON pattern matching (used for permissions)
│   └── markdown/             # Markdown parser/reducer
└── infrastructure/           # Concrete adapters (I/O, side effects)
    ├── llm/
    │   ├── specs/            # Backend LLMSpecs (codex, copilot, litellm,
    │   │                     #   opencode, _openai_chat shared helpers)
    │   └── auth/             # Token providers and persistence
    │                         #   (CodexAuthProvider, CopilotAuthProvider, store)
    ├── sandbox/
    │   ├── manager.py        # Factory: build_sandbox_runner
    │   └── runners/          # ISandboxRunner implementations (macos, noop)
    ├── tool/
    │   ├── dependencies.py   # ToolDependencies DI bundle
    │   └── builtins/         # Per-tool modules (bash, edit, glob, …)
    ├── repositories/         # IChatRepository, IProjectRepository,
    │                         #   IToolRepository implementations
    └── paths.py              # I/O wrapper over domain/services/paths
```

Each `infrastructure/<subsystem>/` follows the same two-level pattern: top level holds the factory / DI bundle, sub-package holds concrete implementations. The exception is `repositories/`, which has no factory dispatch — selection happens in `bootstrap/factories.py`.

### Dependency rule

Allowed imports (one direction only):

```mermaid
graph LR
  interface --> application
  interface --> bootstrap
  application --> domain
  bootstrap --> application
  bootstrap --> infrastructure
  bootstrap --> domain
  infrastructure --> domain
  infrastructure --> core
  domain --> core
```

- `domain` and `application` MUST NOT import from `infrastructure` or `interface`.
- `core/` is generic engine code and only depends on the standard library / pydantic. It knows nothing about chat sessions, projects, or LLM-specific shapes.
- Concrete LLM backends and tool implementations live in `infrastructure/`. They are wired in only via `bootstrap/factories.py`.

## Composition root: `bootstrap.Container`

`hey.bootstrap.Container.build(...)` (`src/hey/bootstrap/container.py`) is the only place where concrete infrastructure is instantiated and handed to use cases. The CLI commands always go through it; new dependencies should be wired here, not built ad-hoc.

```mermaid
graph TD
  subgraph bootstrap
    C[Container.build]
    F1[build_project_repository]
    F2[build_chat_repository]
    F3[build_tool_repository]
    F4[build_agent_spec]
    F5[build_llm_spec]
  end

  C --> F1 --> ProjectRepo[LocalProjectRepository]
  C --> F2 --> ChatRepo[SQLiteChatRepository / InMemoryChatRepository]
  C --> F3 --> ToolRepo[CompositeToolRepository]
  ToolRepo --> Builtin[BuiltinToolRepository]
  ToolRepo --> MCP[MCPToolRepository]
  C --> F4 --> AgentSpec[LLMAgentSpec]
  F4 --> F5
  F5 --> LLMSpec[LLMSpec - litellm/copilot/codex]

  C --> PUC[ProjectUseCase]
  C --> CUC[AgentChatUseCase]
  PUC --> ProjectRepo
  CUC --> AgentSpec
  CUC --> ChatRepo
```

### Backend routing

`build_llm_spec` selects an `LLMSpec` by **model prefix** (`bootstrap/constants.py`):

| Prefix              | Backend module                                | Required extra |
|---------------------|-----------------------------------------------|----------------|
| `github-copilot/…`  | `infrastructure.llm.specs.copilot`            | `copilot`      |
| `codex/…`           | `infrastructure.llm.specs.codex`              | `codex`        |
| `opencode-go/…`     | `infrastructure.llm.specs.opencode`           | `opencode`     |
| `opencode/…`        | `infrastructure.llm.specs.opencode`           | `opencode`     |
| (anything else)     | `infrastructure.llm.specs.litellm` (default)  | `litellm`      |

Note: `opencode-go/…` routes to `https://opencode.ai/zen/go/v1/chat/completions`; `opencode/…` routes to `https://opencode.ai/zen/v1/chat/completions`. Both require the `OPENCODE_API_KEY` environment variable.

Backend imports are deferred to call time inside `build_llm_spec` so missing extras only fail when you actually try to use that backend. `infrastructure/llm/__init__.py` is intentionally empty for the same reason — eager re-exports would pull in optional spec modules at import time.

Copilot and Codex backends sit on top of token providers under `infrastructure/llm/auth/`:

- `CodexAuthProvider` (`auth/codex.py`) — browser/PKCE or device-code flow, silently refreshes before each call.
- `CopilotAuthProvider` (`auth/copilot.py`) — GitHub device-grant; long-lived tokens, no refresh.
- `auth/store.py` — JSON token persistence under `~/.config/hey/auth/<provider>.json` via `infrastructure.paths.global_auth_dir`.

Both providers structurally satisfy the `AuthProvider` protocol declared in `domain/services/auth.py`.

`build_llm_spec` also calls `build_agents_instructions(project_directory)` (`domain/services/agentsmd.py`) to load `AGENTS.md` files and prepend them to the system prompt. Discovery order: nearest `AGENTS.md` walking up from the project root, then `~/.config/hey/AGENTS.md`. The two sources are concatenated; the result is merged with `ChatConfig.instructions`.

### Tool registry

Tools come from a `CompositeToolRepository` that merges:

- `BuiltinToolRepository` — built-in tools (`bash`, `edit`, `glob`, `grep`, `ls`, `read`, `web_fetch`, `web_search`, `search_chat_messages`). Each builtin module exposes `is_available()` + `create_tool_spec(...)`; unavailable tools are silently skipped.
- `MCPToolRepository` — tools fetched from MCP servers declared in `hey.yaml`. Names are namespaced as `mcp_<server>_<tool>`.

Later repositories override earlier ones on name collision.

## Project & runtime data

A "project" is auto-discovered by walking up from `cwd` looking for `hey.yaml` or `.git` (`domain/services/project.py:get_project_directory`). Tests/scripts run from the repo root resolve this repo as the project.

```
<project>/
├── hey.yaml          # ChatConfig (model, instructions, permissions, mcp servers)
└── .hey/
    └── hey.db        # SQLite chat history (per project)
```

`Project.id = ProjectID(absolute_path)` — projects are keyed by absolute filesystem path.

## Domain entities (key types)

All defined under `domain/entities/`:

- `LLMMessage = SystemMessage | UserMessage | AssistantMessage | ToolResultMessage` — discriminated `TypedDict` union (pydantic Discriminator on `role`).
- `LLMSignal` — fine-grained streaming events from the LLM (`text_delta`, `tool_call_args_delta`, `thinking_delta`, `turn_done`, …).
- `LLMState` — frozen dataclass: `(history, tools, finalizer)`.
- `LLMEvent = EmitLLMSignal | EmitLLMMessage | EmitToolResult` — what the agent loop emits.
- `LLMCmd = RunToolCall` — what the agent loop asks the runtime to execute.
- `LLMSpec` — pairs a streaming `Engine[Query, LLMSignal]` with a `Contextualizer[Query, LLMState]` (state→query adapter).
- `LLMAgentSpec` — `LLMSpec` + tools + permissions + response format.
- `ToolSpec` — Python callable + permission map + parameter/return annotations (pydantic-derivable JSON schema). Permissions are `{ParamPattern: "allow" | "deny" | "ask"}`, evaluated last-match-wins via `core.pattern.json_match` against `args_json`.

## Agent runtime (`core/agent` + `domain/services/llm.py`)

The agent loop is built from three small protocols (`core/agent/protocols.py`):

- `Engine[Query, Signal]` — async context manager yielding low-level signals.
- `Reducer[Buffer, Signal, Event]` — folds signals into higher-level events.
- `Contextualizer[Query, State]` — derives the next `Query` from the current `State`.

`run_agent_loop` (`core/agent/runtime.py`) ties them together with four user-supplied callables: `update`, `interpret`, `is_done`, `finish`. It is fully generic and has no notion of "LLM" or "tool".

The LLM specialization lives in `domain/services/llm.py`:

- `reduce_llm_signal` — buffers signals per turn; on `turn_done` emits a single `EmitLLMMessage(AssistantMessage(...))` synthesized from the buffered text/tool-call parts.
- `update_llm_state` — appends emitted messages to `state.history`; for assistant tool calls, dispatches `RunToolCall` cmds (or emits an error tool-result if the tool name is unknown).
- `interpret_llm_cmds` — runs all tool calls of a turn concurrently in a `TaskGroup`. Per call: resolve permission via pattern match → optionally `ask_permission` → run `tool_spec.func(**params)` → JSON-encode result, truncate to 50 KiB, emit `EmitToolResult`. Tool failures and denials become tool-result text rather than crashing the loop.
- `is_llm_state_done` — finished when no `finalizer` and the last message is `assistant`, OR a finalizer tool was called.
- `finalize_llm` — extracts the final text or decodes the structured tool result of the finalizer call.

Per-turn flow:

```mermaid
sequenceDiagram
  autonumber
  participant State as LLMState
  participant Eng as Engine
  participant Red as reduce_llm_signal
  participant Runtime as run_agent_loop
  participant Tools as interpret_llm_cmds
  participant Sub as Subscribers

  Runtime->>State: Contextualizer derives Query from state
  Runtime->>Eng: open stream with Query
  Eng-->>Red: stream LLMSignal events
  Red-->>Runtime: LLMEvent - EmitLLMSignal per signal
  Red-->>Runtime: EmitLLMMessage on turn_done
  Runtime-->>Sub: publish each event via EventSource
  Runtime->>Runtime: update_llm_state appends history and yields cmds
  Runtime->>Tools: interpret cmds concurrently in TaskGroup
  Tools-->>Runtime: EmitToolResult per call
  Runtime->>Runtime: update_llm_state with tool results
  Runtime->>Runtime: repeat turns until is_llm_state_done
  Runtime->>Runtime: finalize_llm produces ResponseT
```

### `WorkflowResponse` (event delivery)

`run_agent_loop` returns a `WorkflowResponse[Event, State, Result]` (`core/workflow/response.py`). It bundles:

- An `EventSource[Event]` (multi-subscriber, bounded buffer; `DROP` policy on slow consumers by default).
- A coroutine producing the final `(state, result)`.

Callers can independently:

- `async for event in resp.events()` — subscribe to the live event stream (multiple subscribers OK).
- `await resp.collect()` — await the final `(state, result)`.

The CLI uses both: it iterates `events()` for streaming UI updates, then `await response.collect()` to wait for completion (see `interface/cli/commands/chat.py`).

`WorkflowResponse.events()` lazily starts the producing task on first subscribe, so creating a response is cheap and side-effect-free until something subscribes or collects.

## Workflow graph (`core/workflow`, `domain/services/workflow.py`)

A separate, larger orchestration primitive used to compose **multiple agent runs** as a DAG. Not used by the basic `hey "<prompt>"` chat path — that goes straight through `run_llm_agent` — but available for richer flows.

- `WorkflowGraph[State, Event, Terminal]` — list of `WorkflowNode`s with `deps`, optional `cond`/`until` predicates.
- `WorkflowExecutor` — validates the DAG (no cycles, no unknown deps), runs ready batches in parallel via `asyncio.TaskGroup`, applies `BaseWorkflowHandler.update` between batches, emits lifecycle events (`WorkflowStartedEvent`, `WorkflowNodeStartedEvent`, …), and supports early termination via `Stop`.
- `domain.services.workflow` provides helpers to wrap an `LLMAgentSpec` (or a plain async callable) as a `WorkflowNode`, threading `LLMWorkflowState` through the graph.

## Chat use case (`AgentChatUseCase`)

`application/usecases/chat.py` exposes session lifecycle and the streaming `run` context manager:

- `create_session` / `get_or_create_session` (with `session_timeout` from `ChatConfig`) / `resume_session` / `get_messages_by_*`.
- `run(RunChatInput)` is an `@asynccontextmanager` yielding a `WorkflowResponse[LLMEvent, LLMState, ResponseT]`. It:
  1. Loads prior `LLMState` from the chat repository for the session.
  2. Persists the new user message immediately.
  3. Calls `run_llm_agent(spec, prompt, state, on_event=...)`.
  4. The `on_event` callback (`make_on_event_callback_for_chat`) persists every assistant message and tool result into the repository as it is emitted.

The repository is reused as a **transaction boundary** via its context manager (`with self._chat_repository: ...`) for session creation. SQLite repository uses one connection in WAL mode with explicit `BEGIN/COMMIT/ROLLBACK` driven by `__enter__`/`__exit__`.

## CLI flow

Entry: `hey = hey.__main__:run` → `hey.interface.cli.main` (`src/hey/interface/cli/app.py`). Subcommands live in `src/hey/interface/cli/commands/` (`chat.py`, `history.py`).

End-to-end, a single `hey "what is X?"` invocation looks like:

```mermaid
sequenceDiagram
  autonumber
  participant User
  participant CLI as cli/commands/chat
  participant Cont as bootstrap.Container
  participant Proj as ProjectUseCase
  participant Chat as AgentChatUseCase
  participant Agent as run_llm_agent
  participant Repo as ChatRepository
  participant LLM as LLMSpec.engine
  participant Tools

  User->>CLI: hey prompt
  CLI->>Cont: Container.build with ask_permission
  Cont->>Proj: get_project walks up for hey.yaml or .git
  CLI->>Chat: get_or_create_session project_id timeout
  CLI->>Chat: run RunChatInput async context
  Chat->>Repo: load history into LLMState
  Chat->>Repo: persist user message
  Chat->>Agent: run_llm_agent spec prompt state on_event
  Agent->>LLM: stream signals each turn
  LLM-->>Agent: text_delta tool_call_part_done turn_done
  Agent-->>CLI: events stream EmitLLMSignal or EmitLLMMessage
  Agent->>Repo: on_event persists assistant message
  Agent->>Tools: interpret_llm_cmds concurrent per-call permission
  Tools-->>Agent: EmitToolResult
  Agent->>Repo: on_event persists tool result
  Agent->>Agent: repeat turns until is_llm_state_done
  Agent-->>CLI: response.collect resolves
  CLI->>User: rendered output
```

The CLI also reads `stdin` when not a TTY and appends it to the prompt (`chat.py:_run_chat`), so piping `cat file | hey "summarize"` works.

## Permissions

Two complementary layers:

1. **Per-tool permission map** on `ToolSpec.permission` — `{ParamPattern → action}`. Patterns are matched against the tool's `args_json` using `core.pattern.json_match`. Last matching pattern wins; default is `allow`.
2. **Project-level permission overrides** in `hey.yaml` (`ChatConfig.permission: {ToolName → ParamPattern → action}`), merged into specs by `setup_tool_permission` (`domain/services/tool.py`).

If the resolved action is `ask`, the use case calls the `ask_permission` callback wired via `Container.build(ask_permission=...)`. The CLI implementation prompts interactively via `interface/cli/display/chat.py:ask_permission`, serialized through an `asyncio.Lock` to avoid overlapping prompts when multiple tool calls in one turn need approval.

## Sandbox

Built-in tools that touch the filesystem run under a `PermissionProfile`. Enforcement happens on two layers:

- **In-process path guard** (`domain/services/sandbox.py`) — pure policy interpretation. `resolve_tool_path` normalizes user-supplied paths against the project directory; `assert_path_access` checks the resolved `Path` against the profile and raises `ToolCallDenied` on violation. Used by `read`, `edit`, `glob`, `grep`, `ls`.
- **Kernel-level sandbox** (`infrastructure/sandbox/runners/`) — `bash` runs through an `ISandboxRunner`. On macOS, `MacOSSandboxRunner` translates the `PermissionProfile` into a Seatbelt (SBPL) profile and execs the command via `/usr/bin/sandbox-exec`. `NoopSandboxRunner` is the fallback when enforcement is `disabled`.

```mermaid
graph LR
  Config[ChatConfig.sandbox]
  Builder[build_workspace_permission_profile]
  Profile[PermissionProfile]
  Manager[build_sandbox_runner]
  Runner[ISandboxRunner]
  Bash[bash tool]
  FileTools[read/edit/glob/grep/ls]

  Config --> Builder --> Profile
  Profile --> Manager --> Runner --> Bash
  Profile --> FileTools
```

Defaults: `enforcement="managed"`, `filesystem="workspace_write"`, `network="restricted"`. Protected names inside the workspace (`.git`, `.hey`, `.agents`, `.codex`) are denied even under workspace-write.

Domain owns the abstractions:
- `domain/entities/sandbox.py` — `PermissionProfile`, `FileSystemPolicy`, `NetworkPolicy`, `SandboxExecRequest`, `SandboxExecResult`.
- `domain/services/sandbox.py` — `ISandboxRunner` (Protocol), `build_workspace_permission_profile`, `resolve_tool_path`, `assert_path_access`.
- `domain/exceptions/sandbox.py` — `SandboxError`, `SandboxUnavailableError`.

Infrastructure provides the implementations:
- `infrastructure/sandbox/manager.py` — `build_sandbox_runner(profile)` picks a concrete runner by `profile.enforcement` and `platform.system()`.
- `infrastructure/sandbox/runners/{macos,noop}.py` — concrete `ISandboxRunner` implementations.

> Status: managed enforcement is currently only implemented on Darwin. On other platforms `build_sandbox_runner` raises `SandboxUnavailableError`. Linux/Windows support is planned; until then, set `chat.sandbox.enabled = false` to opt out.

## Optional dependencies

Optional extras gate entire backends/toolsets (`pyproject.toml`):

| Extra      | Enables                                                                       |
|------------|-------------------------------------------------------------------------------|
| `litellm`  | Default LLM backend (`infrastructure.llm.specs.litellm`).                     |
| `copilot`  | GitHub Copilot backend (`github-copilot/...` model prefix).                   |
| `codex`    | Codex backend (`codex/...` model prefix).                                     |
| `opencode` | OpenCode backend (`opencode/...` and `opencode-go/...` model prefixes).       |
| `bedrock`  | AWS Bedrock support (via litellm + boto3).                                    |
| `web`      | `web_fetch` (markitdown) and `web_search` (ddgs) built-in tools.              |

Imports of these packages MUST stay lazy (deferred to the factory or `is_available()` check). The matching `is_available()` in each builtin tool module is what decides whether the tool is registered at all. `infrastructure/llm/__init__.py` is intentionally empty so that importing the package does not eagerly pull in any spec module.

## Tests

- Real tests live only under `tests/unit/`; `tests/integration/` is a stub (`__init__.py` only).
- `pytest-asyncio` runs in `auto` mode (declare `async def test_...`, no `@pytest.mark.asyncio`).
- `tests/unit/conftest.py` provides factories for messages and tool specs (`make_user_message`, `make_assistant_message`, `make_tool_call_record`, `make_tool_spec`). Prefer these over hand-constructing entities — they keep tests resilient to entity-shape changes.

## Adding things — quick map

| Want to add…                  | Touch                                                                                       |
|-------------------------------|---------------------------------------------------------------------------------------------|
| New CLI subcommand            | `interface/cli/commands/<name>.py`, register in `interface/cli/app.py`.                     |
| New built-in tool             | `infrastructure/tool/builtins/<name>.py` (`is_available`, `create_tool_spec`); register in `infrastructure/repositories/tool/builtin.py` (`_BUILTIN_TOOL_ENTRIES` or `_DEPENDENCY_TOOL_ENTRIES`). File-touching tools must call `resolve_tool_path` + `assert_path_access` from `domain/services/sandbox`. |
| New LLM backend               | `infrastructure/llm/specs/<backend>.py` exposing `get_<backend>_spec(...)`; route via prefix in `bootstrap/factories.build_llm_spec` (keep the import inside the routing branch); add an optional extra in `pyproject.toml`. |
| New auth provider             | `infrastructure/llm/auth/<provider>.py`; implement `domain/services/auth.AuthProvider`; persist tokens via `auth/store.py`. |
| New sandbox runner            | `infrastructure/sandbox/runners/<platform>.py` implementing `domain/services/sandbox.ISandboxRunner`; dispatch in `infrastructure/sandbox/manager.build_sandbox_runner`. |
| New repository implementation | Protocol in `domain/repositories/<x>.py`; impl in `infrastructure/repositories/<x>/`; wire in `bootstrap/factories.py`. |
| New use case                  | `application/usecases/<name>.py` + DTOs in `application/dto.py`; expose via `Container`.     |
| New entity                    | `domain/entities/<name>.py`, kept I/O-free.                                                  |
| New capability protocol       | `domain/services/<name>.py` (alongside `ISandboxRunner`, `AuthProvider`).                    |
