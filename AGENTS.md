# AGENTS.md

CLI chat agent (`hey`). Python 3.12–3.13, managed with `uv`. Layout is `src/`-style with a layered architecture (interface → application → domain / core / infrastructure), wired through `bootstrap/`.

## Commands

Always use `uv` and the `Makefile`; do not invoke `python`/`pytest`/`ruff`/`pyright` directly.

- `make format` — `ruff check --select I --fix` then `ruff format`
- `make lint` — `ruff check` + `pyright` (must both pass; CI runs this)
- `make test` — `pytest`
- `make all` — format + lint + test
- Single test: `uv run pytest tests/unit/path/to/test_file.py::test_name`
- Install/refresh deps: `uv sync --all-extras` (CI uses `--all-extras`)

`Makefile` exports `PYTHONPATH=$(PWD)` for every target, but imports resolve via the editable install from `uv sync` (the package lives in `src/hey/`). If imports fail, run `uv sync` first.

Ruff line length is 120. Pytest uses `asyncio_mode = "auto"` (don't add `@pytest.mark.asyncio`).

## Entrypoint and architecture

- Console script `hey = hey.__main__:run` → `hey.interface.cli.main` (`src/hey/interface/cli/app.py`). Subcommands live in `src/hey/interface/cli/commands/` (`chat.py`, `history.py`).
- **Stale dir**: `src/hey/cli/` exists but is empty (only `__pycache__`). The real CLI is under `src/hey/interface/cli/`. Don't add code to `src/hey/cli/`.
- Wiring: `hey.bootstrap.Container.build(...)` (`src/hey/bootstrap/container.py`) constructs repositories, tools, agent spec, and use cases via `bootstrap/factories.py`. Use this as the entrypoint when adding new dependencies — don't instantiate use cases ad hoc.
- Layers:
  - `domain/` — entities, repository protocols, domain services (no I/O).
  - `application/` — use cases + DTOs that orchestrate domain.
  - `core/` — engine pieces: `agent/`, `workflow/` (graph/executor), `mcp/`, `schema/`, `pattern/`, `markdown/`.
  - `infrastructure/` — concrete adapters: `llm/` (`litellm.py`, `copilot.py`, `codex.py`, `opencode.py`), `repositories/` (SQLite chat store), `chat/`, `project/`, `tool/`.
- LLM backends are optional extras: `litellm`, `copilot`, `codex`, `opencode`, `bedrock`, `web`. Code in `infrastructure/llm/` and tool factories must keep these imports lazy/guarded.
- Model routing is prefix-based: see `bootstrap/constants.py` (`github-copilot/`, `codex/`, `opencode/`, `opencode-go/`). Anything else falls through to litellm.
- System prompt = AGENTS.md files (nearest in project tree, then `~/.config/hey/AGENTS.md`) merged with `ChatConfig.instructions`. Loading is handled by `domain/services/agentsmd.py`.

## Project / runtime data

- A "project" is auto-discovered by walking up from `cwd` looking for `hey.yaml` or `.git` (`domain/services/project.py:get_project_directory`). Tests/scripts run from the repo root will resolve this repo as the project.
- Per-project state lives in `<project>/.hey/hey.db` (SQLite, `SQLiteChatRepository`). The repo's own `.hey/hey.db` is a real dev artifact — do not commit changes to it, do not delete it casually.
- Project config: `hey.yaml` at repo root. It configures the chat agent (MCP servers, tool permissions). When changing chat/tool wiring, verify against this file.

## Tests

- Only `tests/unit/` has real tests; `tests/integration/` is a stub (`__init__.py` only).
- Shared fixtures and message/tool factories are in `tests/unit/conftest.py` — reuse `make_user_message`, `make_assistant_message`, `make_tool_call_record`, `make_tool_spec` instead of constructing entities by hand.
- `pytest-asyncio` auto mode: declare async tests as plain `async def`.

## Conventions

- Public types use `pydantic` v2 models / dataclasses; preserve the strict layering (don't import `infrastructure` from `domain` or `application`).
- Repository implementations live under `infrastructure/repositories/<name>/`; protocols under `domain/repositories/`.
- New CLI subcommands: add a module under `src/hey/interface/cli/commands/`, then register it in `interface/cli/app.py` (mirroring `chat`/`history`).
- New tools/LLM backends: add behind an optional extra in `pyproject.toml` and gate imports in factories.


<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

When running shell commands, **always prefix with `rtk`**. This reduces context
usage by 60-90% with zero behavior change. If rtk has no filter for a command,
it passes through unchanged — so it is always safe to use.

## Key Commands
```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, prefix each segment: `rtk git add . && rtk git commit -m "msg"`
- For debugging, use raw command without rtk prefix
- `rtk proxy <cmd>` runs command without filtering but tracks usage
<!-- /headroom:rtk-instructions -->
