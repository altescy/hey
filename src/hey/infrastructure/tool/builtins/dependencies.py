import dataclasses

from hey.domain.entities.project import ProjectID
from hey.domain.repositories.chat import IChatRepository


@dataclasses.dataclass(frozen=True, slots=True)
class ToolDependencies:
    chat_repository: IChatRepository
    project_id: ProjectID
