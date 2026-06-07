from pathlib import Path
from typing import Any

import yaml

from hey.domain.entities.config import HeyConfig
from hey.domain.entities.project import Project
from hey.domain.repositories.project import IProjectRepository
from hey.domain.services.project import get_hey_config_path, get_project_id_from_path
from hey.infrastructure.paths import global_config_path as _default_global_config_path


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


class LocalProjectRepository(IProjectRepository):
    def __init__(self, global_config_path: Path | None = None) -> None:
        self._global_config_path = global_config_path or _default_global_config_path()

    def get_project(self, directory: Path) -> Project:
        project_id = get_project_id_from_path(directory)
        local_config_path = get_hey_config_path(directory)

        merged: dict[str, Any] = {}
        if self._global_config_path.is_file():
            with self._global_config_path.open() as f:
                merged = yaml.safe_load(f) or {}

        if local_config_path.is_file():
            with local_config_path.open() as f:
                local = yaml.safe_load(f) or {}
            merged = _deep_merge(merged, local)
        elif not merged:
            raise FileNotFoundError(f"{local_config_path} is required and must define chat.model")

        config = HeyConfig.model_validate(merged)
        return Project(id=project_id, directory=directory, config=config)

    def save_config(self, project: Project, config: HeyConfig) -> Project:
        config_path = get_hey_config_path(project.directory)
        with config_path.open("w") as yaml_file:
            yaml.safe_dump(config.model_dump(), yaml_file)

        return project.model_copy(update={"config": config})
