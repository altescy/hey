from hey.domain.entities.tool import ToolSpec
from hey.domain.services.file import use_file_time
from hey.domain.services.tool import generate_tool_spec_from_callable

_DESCRIPTION = """\
Read a text file
""".strip()


def create_read_tool_spec() -> ToolSpec:
    async def edit(file_path: str) -> str:
        async with use_file_time(file_path) as file_time:
            content = file_time.path.read_text()
            file_time.read()  # Update the file time state after writing
            return content

    return generate_tool_spec_from_callable(
        edit,
        name="read",
        description=_DESCRIPTION,
        permission={"file_path.*": "ask"},
    )
