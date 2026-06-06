from pathlib import Path

import yaml

from hey.domain.entities.config import HeyConfig
from hey.domain.entities.project import Project
from hey.domain.repositories.project import IProjectRepository
from hey.domain.services.project import get_hey_config_path, get_project_id_from_path


class LocalProjectRepository(IProjectRepository):
    def get_project(self, directory: Path) -> Project:
        project_id = get_project_id_from_path(directory)
        config_path = get_hey_config_path(directory)
        if config_path.is_file():
            with config_path.open() as yaml_file:
                config = HeyConfig.model_validate(yaml.safe_load(yaml_file))
        else:
            raise FileNotFoundError(f"{config_path} is required and must define chat.model")

        return Project(id=project_id, directory=directory, config=config)

    def save_config(self, project: Project, config: HeyConfig) -> Project:
        config_path = get_hey_config_path(project.directory)
        with config_path.open("w") as yaml_file:
            yaml.safe_dump(config.model_dump(), yaml_file)

        return project.model_copy(update={"config": config})
