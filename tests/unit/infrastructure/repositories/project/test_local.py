import pytest
from pydantic import ValidationError

from hey.infrastructure.repositories.project import LocalProjectRepository


def test_get_project_requires_hey_yaml(tmp_path) -> None:
    repository = LocalProjectRepository()

    with pytest.raises(FileNotFoundError, match="hey.yaml.*chat.model"):
        repository.get_project(tmp_path)


def test_get_project_requires_chat_model_in_hey_yaml(tmp_path) -> None:
    (tmp_path / "hey.yaml").write_text("chat: {}\n")
    repository = LocalProjectRepository()

    with pytest.raises(ValidationError):
        repository.get_project(tmp_path)


def test_get_project_loads_config_with_required_model(tmp_path) -> None:
    (tmp_path / "hey.yaml").write_text("chat:\n  model: codex/gpt-5.5\n")
    repository = LocalProjectRepository()

    project = repository.get_project(tmp_path)

    assert project.config.chat.model == "codex/gpt-5.5"
