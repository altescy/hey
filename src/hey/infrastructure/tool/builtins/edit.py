from difflib import unified_diff
from pathlib import Path
from typing import NamedTuple

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.file import use_file_time
from hey.domain.services.tool import generate_tool_spec_from_callable

from ..dependencies import ToolDependencies
from ..path_guard import assert_path_access, resolve_tool_path

_DESCRIPTION = """\
Overwrite a specific substring in a file with new content.

The tool locates `old_string` in the file and replaces it with `new_string`, \
then returns a unified diff of the change.

Usage:
- You must call the `read` tool on the file at least once before editing. \
  Editing without a prior read will raise an error.
- `old_string` must match the file content exactly, including whitespace and \
  indentation. Include enough surrounding lines to make the match unique.
- If `old_string` appears more than once and `replace_all` is false, the tool \
  raises an error. Either broaden the context in `old_string` or set \
  `replace_all=true` to replace every occurrence.
- If the file has been modified externally since the last read, the tool \
  raises an error. Re-read the file and retry."""


class _EditResult(NamedTuple):
    diff: str


def is_available() -> bool:
    return True


def create_tool_spec(dependencies: ToolDependencies | None = None) -> ToolSpec:
    async def edit(
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> _EditResult:
        project_directory = dependencies.project_directory if dependencies is not None else Path.cwd()
        path = resolve_tool_path(file_path, project_directory=project_directory)
        if dependencies is not None:
            assert_path_access(path, profile=dependencies.permission_profile, access="write")

        async with use_file_time(path) as file_time:
            if file_time.has_changed():
                raise RuntimeError(
                    "File has changed since it was last read. Please read the file again to get the latest content before editing."
                )
            content = file_time.path.read_text()
            if old_string not in content:
                raise ValueError("old_string not found in content")
            if not replace_all and content.count(old_string) > 1:
                raise ValueError(
                    "Found multiple matches for old_string. Provide more surrounding lines in old_string to identify the correct match."
                )
            new_content = (
                content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
            )
            file_time.path.write_text(new_content)
            file_time.read()  # Update the file time state after writing

            diff = unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=file_path,
                tofile=file_path,
            )
            return _EditResult(diff="".join(diff))

    async def render_markdown(
        result: _EditResult,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        del file_path, old_string, new_string, replace_all
        return f"""```diff\n{result.diff}```"""

    return generate_tool_spec_from_callable(
        edit,
        name="edit",
        description=_DESCRIPTION,
        permission={"file_path.*": "ask"},
        render=render_markdown,
    )
