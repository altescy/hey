from os import PathLike

from hey.domain.entities.project import Project
from hey.domain.repositories.project import IProjectRepository
from hey.domain.services.project import get_project_directory


class ProjectUseCase:
    def __init__(self, project_repository: IProjectRepository):
        self._project_repository = project_repository

    def get_project(self, path: str | PathLike) -> Project:
        return self._project_repository.get_project(get_project_directory(path))
