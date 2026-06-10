from pathlib import Path

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable
from hey.infrastructure.tool.builtins.dependencies import ToolDependencies
from hey.infrastructure.tool.builtins.path_guard import assert_path_access, resolve_tool_path

_DESCRIPTION = """\
Find files whose paths match a glob pattern, sorted by modification time (newest first).

Supports standard glob syntax:
- `*` matches any sequence of characters within a single path component
- `**` matches across directory boundaries (e.g. `**/*.py`)
- `?` matches exactly one character
- `{a,b}` matches either `a` or `b`

Notes:
- Provide `path` to restrict the search to a specific directory; \
  omit it to search from the current working directory.
- Results are sorted newest-first and capped at 100 entries. \
  If results are truncated, use a more specific pattern or path.
- Use `grep` when you need to search by file *content* rather than file name.
""".strip()

_LIMIT = 100


def is_available() -> bool:
    return True


def create_tool_spec(dependencies: ToolDependencies | None = None) -> ToolSpec:
    async def glob(pattern: str, path: str | None = None) -> str:
        """Find files matching a glob pattern, sorted by modification time."""
        project_directory = dependencies.project_directory if dependencies is not None else Path.cwd()
        root = resolve_tool_path(path, project_directory=project_directory)
        if dependencies is not None:
            assert_path_access(root, profile=dependencies.permission_profile, access="read")
        if not root.exists():
            raise FileNotFoundError(f"Path not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        matches = [p for p in root.rglob(pattern) if p.is_file()]

        if not matches:
            return "No files found."

        truncated = len(matches) > _LIMIT
        matches = sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[:_LIMIT]

        lines = [str(p) for p in matches]
        if truncated:
            lines.append("")
            lines.append(
                f"(Truncated: showing first {_LIMIT} results. Use a more specific pattern or path to narrow results.)"
            )

        return "\n".join(lines)

    return generate_tool_spec_from_callable(
        glob,
        name="glob",
        description=_DESCRIPTION,
        permission={"pattern.*": "allow"},
    )
