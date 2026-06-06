# :wave: hey

[![CI](https://github.com/altescy/hey/actions/workflows/ci.yaml/badge.svg)](https://github.com/altescy/hey/actions/workflows/ci.yaml)
[![Release](https://img.shields.io/github/v/release/altescy/hey)](https://github.com/altescy/hey/releases)
[![License](https://img.shields.io/github/license/altescy/hey)](https://github.com/altescy/hey/blob/main/LICENSE)

**hey** is a lightweight, project-aware AI agent for your terminal. Run `hey <your request>` and the agent reads files, edits code, executes shell commands, and fetches the web — all within a persistent, per-project conversation that picks up where you left off.

```text
hey add a docstring to every public function in src/hey/core/agent/runtime.py
```

## Features

- **Persistent sessions** — conversation history is stored in `.hey/hey.db` (SQLite) per project, automatically resumed within the session timeout
- **Multiple LLM backends** — litellm (OpenAI, Anthropic, Gemini, …), GitHub Copilot, OpenAI Codex, OpenCode, AWS Bedrock; change the model with one line in `hey.yaml`
- **Built-in tools** — `bash`, `edit`, `read`, `grep`, `glob`, `ls`, `web_fetch`, `web_search`, `search_chat_messages`
- **MCP support** — attach any MCP server (stdio or Streamable HTTP) in `hey.yaml`; tool names are auto-namespaced as `mcp_<server>_<tool>`
- **Fine-grained permissions** — per-tool allow / deny / ask rules based on argument patterns, configured per project
- **Chat compaction** — automatic context summarization before hitting the context window limit
- **Pipe-friendly** — `git diff | hey "write a commit message"` works out of the box
- **History viewer** — `hey --history` replays any past session in the terminal

## Design

- **One command, one turn.** hey does not open a dedicated chat screen. Each invocation sends one prompt, the agent works, and control returns to your shell. To continue the conversation, just run `hey` again — sessions are automatically resumed within the same project.
- **Config-only permissions.** Tool permissions are defined entirely in `hey.yaml`. hey has no interactive "remember this choice" mechanism. Because the allowed behaviour lives only in the config file, it is easy to review and version-control what the agent is permitted to do.

## Installation

### From GitHub using uv (recommended)

You can install the latest release of hey directly from GitHub using `uv`:

```bash
uv tool install "hey[all] @ git+https://github.com/altescy/hey"
```

After installation, the `hey` command is available system-wide.

### Available extras

| Extra | Enables |
| --- | --- |
| `all` | All extras (litellm, copilot, codex, opencode, bedrock, web) |
| `litellm` | Default backend — OpenAI, Anthropic, Gemini, Mistral, and [100+ others](https://docs.litellm.ai/docs/providers) |
| `copilot` | GitHub Copilot backend (`github-copilot/<model>`) |
| `codex` | OpenAI Codex CLI backend (`codex/<model>`) |
| `bedrock` | AWS Bedrock via litellm + boto3 |
| `web` | `web_fetch` (markitdown) and `web_search` (ddgs) built-in tools |

## Quick start

```bash
# Set your API key (example: OpenAI via litellm)
export OPENAI_API_KEY=sk-...

# Configure the model for this project
cat > hey.yaml <<'YAML'
chat:
  model: openai/gpt-5.3
YAML

# Ask something in the current directory
hey "what does this project do?"

# Pipe content into the agent
git diff HEAD~1 | hey "summarize the changes"

# Start a fresh session
hey --new-session refactor the authentication module

# Review the conversation history
hey --history

# Compact the context of the current session (frees up context window)
hey --compact
```

## Configuration

hey auto-discovers the project root by walking up from the current directory
until it finds `hey.yaml` or `.git`. A `hey.yaml` with `chat.model` is required
because available providers depend on your environment and credentials:

```yaml
chat:
  model: openai/gpt-5.3          # any model string supported by your backend
  instructions: "You are a helpful assistant for this Python project."
  session_timeout: 3600          # seconds of inactivity before a new session starts

  # MCP servers
  mcp:
    my-server:
      transport: stdio
      command: ["npx", "-y", "@my-org/mcp-server"]
    remote-docs:
      transport: streamable_http
      url: https://example.com/mcp

  # Tool permissions (last matching pattern wins; default: allow)
  permission:
    bash:
      "command.*": "ask"        # ask before any shell command …
      "command.ls *": "allow"   # … except ls
    edit:
      "file_path.*\\.py": "allow"
      "file_path.*": "ask"
```

Runtime state is stored in `<project>/.hey/hey.db`. Add `.hey/` to `.gitignore`
if you don't want to commit the chat database.

### Model selection examples

```yaml
# OpenAI via litellm
model: openai/gpt-4o

# Anthropic via litellm
model: anthropic/claude-opus-4-7

# GitHub Copilot
model: github-copilot/claude-3.7-sonnet

# AWS Bedrock via litellm
model: bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
```

## Usage reference

```text
hey [prompt] [options]

Options:
  --new-session    Start a fresh session instead of resuming the latest one
  --temporary      Use in-memory storage; nothing is persisted
  --compact        Summarize the current session and exit
  --history        Show the conversation history for the current session
  --session ID     (with --history) show a specific session by ID
  --version        Print the version and exit
```

## Developer setup

Requires Python 3.12–3.13 and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/altescy/hey
cd hey
uv sync --all-extras
```

Common tasks via `make`:

```bash
make format   # ruff import sort + format
make lint     # ruff check + pyright
make test     # pytest
make all      # format + lint + test
```

Run a single test:

```bash
uv run pytest tests/unit/path/to/test_file.py::test_name
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed description of the layered
architecture and how to extend the agent with new tools, backends, or CLI commands.

## License

[MIT](LICENSE)
