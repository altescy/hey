import dataclasses
from pathlib import Path

from hey.domain.entities.project import ProjectID
from hey.domain.entities.sandbox import PermissionProfile
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.sandbox import ISandboxRunner


@dataclasses.dataclass(frozen=True, slots=True)
class ToolDependencies:
    chat_repository: IChatRepository
    project_id: ProjectID
    project_directory: Path
    sandbox_runner: ISandboxRunner
    permission_profile: PermissionProfile
