import dataclasses

from hey.domain.entities.project import ProjectID
from hey.domain.entities.sandbox import PermissionProfile
from hey.domain.repositories.chat import IChatRepository
from hey.infrastructure.sandbox.protocol import SandboxRunner


@dataclasses.dataclass(frozen=True, slots=True)
class ToolDependencies:
    chat_repository: IChatRepository
    project_id: ProjectID
    sandbox_runner: SandboxRunner
    permission_profile: PermissionProfile
