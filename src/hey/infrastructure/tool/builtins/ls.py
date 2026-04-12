from pathlib import Path

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable

_DESCRIPTION = """\
List files and directories under a given path as an indented tree.

By default the listing starts from the current working directory. \
Directories known to be unimportant (e.g. .git, __pycache__, .venv, \
node_modules) are excluded automatically. Additional patterns to exclude \
can be passed via the `ignore` parameter.

Notes:
- Prefer `glob` when you already know the file name pattern you are looking \
  for, and `grep` when you want to find files by content. Use `ls` to get a \
  broad overview of an unfamiliar directory.
- Results are capped at 200 entries. If the tree is truncated, narrow the \
  search by passing a more specific `path`.
""".strip()

_DEFAULT_IGNORE: frozenset[str] = frozenset(
    [
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "dist",
        "build",
        "target",
        "vendor",
        ".cache",
        "cache",
        "tmp",
        "temp",
        "logs",
        "coverage",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    ]
)

_LIMIT = 200


def create_ls_tool_spec() -> ToolSpec:
    async def ls(path: str = ".", ignore: list[str] | None = None) -> str:
        """List files and directories under path as an indented tree."""
        root = Path(path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Path not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        extra_ignore: frozenset[str] = frozenset(ignore) if ignore else frozenset()
        blocked = _DEFAULT_IGNORE | extra_ignore

        def _is_ignored(p: Path) -> bool:
            return any(part in blocked for part in p.parts)

        # Collect all files (not dirs) up to the limit
        collected: list[Path] = []
        truncated = False
        for entry in sorted(root.rglob("*")):
            if entry.is_dir():
                continue
            rel = entry.relative_to(root)
            if _is_ignored(rel):
                continue
            collected.append(rel)
            if len(collected) > _LIMIT:
                truncated = True
                collected = collected[:_LIMIT]
                break

        # Build tree: dir → [filenames]
        dir_files: dict[Path, list[str]] = {}
        all_dirs: set[Path] = set()
        for rel in collected:
            parent = rel.parent
            # Register all ancestor dirs
            for ancestor in [parent, *parent.parents]:
                all_dirs.add(ancestor)
            dir_files.setdefault(parent, []).append(rel.name)

        def _render(directory: Path, depth: int) -> list[str]:
            lines: list[str] = []
            indent = "  " * depth

            # subdirectories first
            children = sorted(d for d in all_dirs if d.parent == directory and d != directory)
            for child in children:
                lines.append(f"{indent}{child.name}/")
                lines.extend(_render(child, depth + 1))

            # then files
            for name in sorted(dir_files.get(directory, [])):
                lines.append(f"{indent}{name}")

            return lines

        lines = [f"{root}/"] + _render(Path("."), 1)
        if truncated:
            lines.append("")
            lines.append(f"(Truncated: showing first {_LIMIT} entries. Use a more specific path to narrow results.)")

        return "\n".join(lines)

    return generate_tool_spec_from_callable(
        ls,
        name="ls",
        description=_DESCRIPTION,
        permission={"path.*": "allow"},
    )
