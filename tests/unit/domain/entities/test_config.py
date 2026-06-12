import pytest
from pydantic import ValidationError

from hey.domain.entities.config import ChatConfig


def test_chat_config_requires_model() -> None:
    with pytest.raises(ValidationError):
        ChatConfig.model_validate({})


def test_chat_config_rejects_blank_model() -> None:
    with pytest.raises(ValidationError):
        ChatConfig(model=" ")


def test_chat_config_allows_model_and_optional_instruction_values() -> None:
    config = ChatConfig(model="custom-model", instructions="custom instructions")

    assert config.model == "custom-model"
    assert config.instructions == "custom instructions"


def test_chat_config_enables_managed_workspace_sandbox_by_default() -> None:
    config = ChatConfig(model="custom-model")

    assert config.sandbox.enabled is True
    assert config.sandbox.enforcement == "managed"
    assert config.sandbox.filesystem == "workspace_write"
    assert config.sandbox.network == "restricted"
