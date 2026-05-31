from os import PathLike
from pathlib import Path
from typing import Final

from hey.domain.entities.project import ProjectID

HEY_CONFIG_FILENAME: Final[str] = "hey.yaml"
HEY_DOT_DIRECTORY_NAME: Final[str] = ".hey"


def get_project_id_from_path(path: str | PathLike) -> ProjectID:
    return ProjectID(str(Path(path).resolve().expanduser().absolute()))


def get_project_directory(path: str | PathLike) -> Path:
    start = Path(path).resolve()
    current = start if start.is_dir() else start.parent
    markers = {
        HEY_CONFIG_FILENAME,
        ".git",
    }
    for directory in (current, *current.parents):
        if any((directory / marker).exists() for marker in markers):
            return directory
    return current


def get_hey_config_path(project_directory: Path) -> Path:
    return project_directory / HEY_CONFIG_FILENAME


def get_hey_dot_directory(project_directory: Path) -> Path:
    return project_directory / HEY_DOT_DIRECTORY_NAME
