from os import PathLike
from pathlib import Path


def get_project_directory(path: str | PathLike) -> Path:
    return Path(path).resolve()
