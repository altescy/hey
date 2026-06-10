import fnmatch
import re
from pathlib import Path

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable
from hey.infrastructure.tool.builtins.dependencies import ToolDependencies
from hey.infrastructure.tool.builtins.path_guard import assert_path_access, resolve_tool_path

_DESCRIPTION = """\
Search file contents using a regular expression, returning matching file paths \
and line numbers sorted by modification time (newest first).

Notes:
- `pattern` is a Python regular expression (e.g. `def\\s+\\w+`, `TODO:.*`).
- `path` restricts the search to a directory; omit it to search from the \
  current working directory.
- `include` is an optional glob pattern that filters which files are searched \
  (e.g. `*.py`, `*.{ts,tsx}`).
- Results are grouped by file and capped at 100 matching lines. \
  If results are truncated, use a more specific pattern, path, or include filter.
- Only text files are searched; binary files are silently skipped.
""".strip()

_LIMIT = 100
_MAX_LINE_LENGTH = 2000


def is_available() -> bool:
    return True


def create_tool_spec(dependencies: ToolDependencies | None = None) -> ToolSpec:
    async def grep(pattern: str, path: str | None = None, include: str | None = None) -> str:
        """Search file contents with a regex, returning matching lines grouped by file."""
        project_directory = dependencies.project_directory if dependencies is not None else Path.cwd()
        root = resolve_tool_path(path, project_directory=project_directory)
        if dependencies is not None:
            assert_path_access(root, profile=dependencies.permission_profile, access="read")
        if not root.exists():
            raise FileNotFoundError(f"Path not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc

        # Collect candidate files
        candidates: list[Path] = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if include and not fnmatch.fnmatch(p.name, include):
                continue
            candidates.append(p)

        # Sort newest-first so matches from recently modified files come first
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # Search each file
        class _Match:
            __slots__ = ("path", "mtime", "line_num", "line_text")

            def __init__(self, path: Path, mtime: float, line_num: int, line_text: str) -> None:
                self.path = path
                self.mtime = mtime
                self.line_num = line_num
                self.line_text = line_text

        all_matches: list[_Match] = []
        for candidate in candidates:
            try:
                text = candidate.read_text(errors="strict")
            except (UnicodeDecodeError, PermissionError):
                continue
            mtime = candidate.stat().st_mtime
            for line_num, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    all_matches.append(_Match(candidate, mtime, line_num, line))

        if not all_matches:
            return "No matches found."

        total = len(all_matches)
        truncated = total > _LIMIT
        shown = all_matches[:_LIMIT]

        # Group by file, preserving newest-first order
        seen_files: list[Path] = []
        by_file: dict[Path, list[_Match]] = {}
        for m in shown:
            if m.path not in by_file:
                seen_files.append(m.path)
                by_file[m.path] = []
            by_file[m.path].append(m)

        header = f"Found {total} match{'es' if total != 1 else ''}" + (
            f" (showing first {_LIMIT})" if truncated else ""
        )
        lines = [header]
        for file_path in seen_files:
            lines.append("")
            lines.append(f"{file_path}:")
            for m in by_file[file_path]:
                text = m.line_text
                if len(text) > _MAX_LINE_LENGTH:
                    text = text[:_MAX_LINE_LENGTH] + "..."
                lines.append(f"  Line {m.line_num}: {text}")

        if truncated:
            lines.append("")
            lines.append(
                f"(Truncated: showing {_LIMIT} of {total} matches "
                f"({total - _LIMIT} hidden). Use a more specific pattern, path, or include filter.)"
            )

        return "\n".join(lines)

    return generate_tool_spec_from_callable(
        grep,
        name="grep",
        description=_DESCRIPTION,
        permission={"pattern.*": "allow"},
    )
