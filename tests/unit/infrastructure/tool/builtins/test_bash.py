from hey.infrastructure.tool.builtins.bash import create_tool_spec


async def test_render_markdown_uses_default_code_fence() -> None:
    spec = create_tool_spec()
    assert spec.render is not None

    markdown = await spec.render("hello", command="echo hello")

    assert markdown == "```\n$ echo hello\n\nhello\n```"


async def test_render_markdown_uses_longer_fence_when_output_contains_code_block() -> None:
    spec = create_tool_spec()
    assert spec.render is not None

    markdown = await spec.render("```python\nprint('hello')\n```", command="cat script.md")

    assert markdown == "````\n$ cat script.md\n\n```python\nprint('hello')\n```\n````"


async def test_render_markdown_accounts_for_backticks_in_command() -> None:
    spec = create_tool_spec()
    assert spec.render is not None

    markdown = await spec.render("ok", command="printf '````'")

    assert markdown == "`````\n$ printf '````'\n\nok\n`````"
