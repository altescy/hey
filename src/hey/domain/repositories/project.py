from pathlib import Path
from typing import Protocol

from hey.domain.entities.config import HeyConfig
from hey.domain.entities.project import Project


class IProjectRepository(Protocol):
    def get_project(self, directory: Path) -> Project: ...
    def save_config(self, project: Project, config: HeyConfig) -> Project: ...
