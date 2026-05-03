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
  - `infrastructure/` — concrete adapters: `llm/` (`litellm.py`, `copilot.py`, `codex.py`), `repositories/` (SQLite chat store), `chat/`, `project/`, `tool/`.
- LLM backends are optional extras: `litellm`, `copilot`, `codex`, `bedrock`, `web`. Code in `infrastructure/llm/` and tool factories must keep these imports lazy/guarded.
- Model routing is prefix-based: see `bootstrap/constants.py` (`github-copilot/`, `codex/`).

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
