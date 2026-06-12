from pathlib import Path

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.file import use_file_time
from hey.domain.services.tool import generate_tool_spec_from_callable

from ..dependencies import ToolDependencies
from ..path_guard import assert_path_access, resolve_tool_path

_DEFAULT_LIMIT = 2000
_MAX_LINE_LENGTH = 2000
_MAX_BYTES = 50 * 1024  # 50 KB

_DESCRIPTION = f"""\
Read a text file, with optional pagination via line offset and limit.

Each output line is prefixed with its line number (e.g. `42: content`). \
Reading a file is required before editing it — the tool records the file's \
state at read time and the edit tool uses that record to detect concurrent \
modifications.

Notes:
- `offset` is 1-indexed; omit it to start from the first line.
- `limit` defaults to {_DEFAULT_LIMIT} lines. Increase it only when you need \
  a larger window; prefer smaller reads and use the returned offset hint to \
  continue.
- Output is capped at {_MAX_BYTES // 1024} KB per call. If the file is larger, \
  a continuation hint with the next offset is included at the end.
- Lines longer than {_MAX_LINE_LENGTH} characters are truncated.
- Binary files are not supported and will produce an error.
- Use `grep` to search for specific content, or `glob` to locate files by name."""


def is_available() -> bool:
    return True


def create_tool_spec(dependencies: ToolDependencies | None = None) -> ToolSpec:
    async def read(file_path: str, offset: int = 1, limit: int = _DEFAULT_LIMIT) -> str:
        """Read a text file with optional offset/limit pagination."""
        if offset < 1:
            raise ValueError("offset must be >= 1")
        if limit < 1:
            raise ValueError("limit must be >= 1")

        project_directory = dependencies.project_directory if dependencies is not None else Path.cwd()
        path = resolve_tool_path(file_path, project_directory=project_directory)
        if dependencies is not None:
            assert_path_access(path, profile=dependencies.permission_profile, access="read")

        async with use_file_time(path) as file_time:
            path = file_time.path
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            # Binary detection via null-byte sampling
            raw_bytes = path.read_bytes()
            if b"\x00" in raw_bytes[:8192]:
                raise ValueError(f"Binary file not supported: {path}")

            try:
                full_text = raw_bytes.decode()
            except UnicodeDecodeError as exc:
                raise ValueError(f"Cannot decode file as UTF-8: {path}") from exc

            all_lines = full_text.splitlines()
            total_lines = len(all_lines)

            start = offset - 1  # convert to 0-indexed
            if start > total_lines:
                raise ValueError(f"offset {offset} exceeds file length ({total_lines} lines)")

            # Collect lines up to limit, enforcing byte cap
            output_lines: list[str] = []
            byte_count = 0
            byte_capped = False
            for raw_line in all_lines[start : start + limit]:
                line = raw_line if len(raw_line) <= _MAX_LINE_LENGTH else raw_line[:_MAX_LINE_LENGTH] + "…"
                encoded = (line + "\n").encode()
                if byte_count + len(encoded) > _MAX_BYTES:
                    byte_capped = True
                    break
                output_lines.append(line)
                byte_count += len(encoded)

            # Build numbered output
            lines_with_numbers = [f"{offset + i}: {line}" for i, line in enumerate(output_lines)]

            last_line = offset + len(output_lines) - 1
            next_offset = last_line + 1
            more = byte_capped or (start + len(output_lines) < total_lines)

            if byte_capped:
                footer = (
                    f"(Output capped at {_MAX_BYTES // 1024} KB. "
                    f"Showing lines {offset}-{last_line}. "
                    f"Use offset={next_offset} to continue.)"
                )
            elif more:
                footer = f"(Showing lines {offset}-{last_line} of {total_lines}. Use offset={next_offset} to continue.)"
            else:
                footer = f"(End of file — total {total_lines} lines)"

            lines_with_numbers.append(footer)
            result = "\n".join(lines_with_numbers)

            file_time.read()  # record file state for edit conflict detection
            return result

    return generate_tool_spec_from_callable(
        read,
        name="read",
        description=_DESCRIPTION,
        permission={"file_path.*": "ask"},
    )
