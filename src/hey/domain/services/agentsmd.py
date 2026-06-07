"""Discovery and loading of AGENTS.md files.

Mirrors the behaviour of OpenCode's ``Instruction.Service``:

1. Walk upward from the current directory to the project root looking for
   ``AGENTS.md``.  The first match wins (ancestors are not stacked).
2. Fall back to a global file (platform-appropriate location, e.g.
   ``~/.config/hey/AGENTS.md`` on Linux).
3. Contents are formatted as ``Instructions from: <path>\n<content>`` and
   concatenated.
"""

from __future__ import annotations

from pathlib import Path

from hey.domain.services.paths import global_agents_md_path

AGENTS_MD_FILENAME: str = "AGENTS.md"


def _find_up(start: Path, root: Path, filename: str) -> Path | None:
    """Walk upward from *start* to *root* (inclusive) looking for *filename*."""
    current = start.resolve()
    resolved_root = root.resolve()
    for directory in (current, *current.parents):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
        if directory == resolved_root:
            break
    return None


def find_project_agents_md(project_directory: Path) -> Path | None:
    """Return the path to the nearest ``AGENTS.md`` inside the project."""
    resolved = project_directory.resolve()
    return _find_up(resolved, resolved, AGENTS_MD_FILENAME)


def find_global_agents_md() -> Path | None:
    """Return the path to the global AGENTS.md if it exists."""
    candidate = global_agents_md_path()
    return candidate if candidate.is_file() else None


def load_agents_md(path: Path) -> str | None:
    """Read the file and return formatted instructions, or ``None`` on error."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not content.strip():
        return None
    return f"Instructions from: {path}\n{content}"


def build_agents_instructions(project_directory: Path) -> str | None:
    """Load all relevant ``AGENTS.md`` files and return combined instructions."""
    parts: list[str] = []

    # 1. Project-local AGENTS.md (nearest to cwd / project root)
    local = find_project_agents_md(project_directory)
    if local is not None:
        loaded = load_agents_md(local)
        if loaded is not None:
            parts.append(loaded)

    # 2. Global AGENTS.md
    global_ = find_global_agents_md()
    if global_ is not None:
        loaded = load_agents_md(global_)
        if loaded is not None:
            parts.append(loaded)

    if not parts:
        return None

    return "\n\n".join(parts)
