import pytest
from pydantic import ValidationError

from hey.infrastructure.repositories.project import LocalProjectRepository


def test_get_project_requires_hey_yaml_when_no_global_config(tmp_path) -> None:
    repository = LocalProjectRepository(global_config_path=tmp_path / "nonexistent" / "global.yaml")

    with pytest.raises(FileNotFoundError, match="hey.yaml.*chat.model"):
        repository.get_project(tmp_path)


def test_get_project_requires_chat_model_in_hey_yaml(tmp_path) -> None:
    (tmp_path / "hey.yaml").write_text("chat: {}\n")
    repository = LocalProjectRepository(global_config_path=tmp_path / "nonexistent" / "global.yaml")

    with pytest.raises(ValidationError):
        repository.get_project(tmp_path)


def test_get_project_loads_config_with_required_model(tmp_path) -> None:
    (tmp_path / "hey.yaml").write_text("chat:\n  model: codex/gpt-5.5\n")
    repository = LocalProjectRepository(global_config_path=tmp_path / "nonexistent" / "global.yaml")

    project = repository.get_project(tmp_path)

    assert project.config.chat.model == "codex/gpt-5.5"


def test_global_config_alone_is_sufficient(tmp_path) -> None:
    global_path = tmp_path / "global.yaml"
    global_path.write_text("chat:\n  model: codex/gpt-5.5\n")
    repository = LocalProjectRepository(global_config_path=global_path)

    project = repository.get_project(tmp_path)

    assert project.config.chat.model == "codex/gpt-5.5"


def test_local_config_overrides_global(tmp_path) -> None:
    global_path = tmp_path / "global.yaml"
    global_path.write_text("chat:\n  model: global-model\n  instructions: global-inst\n")
    (tmp_path / "hey.yaml").write_text("chat:\n  model: local-model\n")
    repository = LocalProjectRepository(global_config_path=global_path)

    project = repository.get_project(tmp_path)

    assert project.config.chat.model == "local-model"
    assert project.config.chat.instructions == "global-inst"


def test_local_config_deep_merges_with_global(tmp_path) -> None:
    global_path = tmp_path / "global.yaml"
    global_path.write_text(
        "chat:\n  model: m\n  compaction:\n    enabled: true\n    auto: true\n"
        "  permission:\n    echo:\n      '.*': allow\n"
    )
    (tmp_path / "hey.yaml").write_text("chat:\n  compaction:\n    auto: false\n")
    repository = LocalProjectRepository(global_config_path=global_path)

    project = repository.get_project(tmp_path)

    assert project.config.chat.model == "m"
    assert project.config.chat.compaction.enabled is True
    assert project.config.chat.compaction.auto is False
    assert project.config.chat.permission == {"echo": {".*": "allow"}}
