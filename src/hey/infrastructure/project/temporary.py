from pathlib import Path

from hey.domain.entities.project import Project, ProjectID
from hey.domain.repositories.project import IProjectRepository


class TemporaryProjectRepository(IProjectRepository):
    def __init__(self):
        self._projects = {}

    def get_project(self, directory: Path) -> Project:
        if directory not in self._projects:
            self._projects[directory] = Project(id=ProjectID(len(self._projects) + 1), directory=directory)
        return self._projects[directory]
