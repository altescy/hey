from os import PathLike
from pathlib import Path
from typing import Final

from hey.domain.entities.project import ProjectID

HEY_CONFIG_FILENAME: Final[str] = "hey.yaml"


def get_project_id_from_path(path: str | PathLike) -> ProjectID:
    return ProjectID(str(Path(path).resolve().expanduser().absolute()))


def get_project_directory(path: str | PathLike) -> Path:
    return Path(path).resolve()


def get_hey_config_path(project_directory: Path) -> Path:
    return project_directory / HEY_CONFIG_FILENAME
