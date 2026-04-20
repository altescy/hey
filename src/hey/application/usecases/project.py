from hey.application.dto import GetProjectInput, GetProjectOutput
from hey.domain.repositories.project import IProjectRepository
from hey.domain.services.project import get_project_directory


class ProjectUseCase:
    def __init__(self, project_repository: IProjectRepository):
        self._project_repository = project_repository

    def get_project(self, input: GetProjectInput) -> GetProjectOutput:
        return GetProjectOutput(project=self._project_repository.get_project(get_project_directory(input["path"])))
