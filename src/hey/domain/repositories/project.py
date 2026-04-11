from pathlib import Path
from typing import Protocol

from hey.domain.entities.project import Project


class IProjectRepository(Protocol):
    def get_project(self, directory: Path) -> Project: ...
