from hey.application.defaults import DEFAULT_CHAT_INSTRUCTIONS
from hey.bootstrap.factories import _resolve_chat_instructions
from hey.domain.entities.config import ChatConfig


def test_resolve_chat_instructions_uses_application_default_when_unset() -> None:
    instructions = _resolve_chat_instructions(ChatConfig(model="codex/gpt-5.5"))

    assert instructions == DEFAULT_CHAT_INSTRUCTIONS
    assert "continue until it is handled end to end" in instructions
    assert "Never overwrite, revert, or discard user changes" in instructions
    assert "When asked to review, prioritize bugs" in instructions


def test_resolve_chat_instructions_uses_config_value_when_set() -> None:
    assert _resolve_chat_instructions(ChatConfig(model="codex/gpt-5.5", instructions="custom instructions")) == (
        "custom instructions"
    )


def test_resolve_chat_instructions_prepends_agents_md(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("project instructions")

    instructions = _resolve_chat_instructions(ChatConfig(model="codex/gpt-5.5"), project_directory=tmp_path)

    assert instructions.startswith("Instructions from:")
    assert "project instructions" in instructions
    assert instructions.endswith(DEFAULT_CHAT_INSTRUCTIONS)
