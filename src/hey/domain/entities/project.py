from pathlib import Path
from typing import NewType

from pydantic import BaseModel

from hey.domain.entities.config import HeyConfig

ProjectID = NewType("ProjectID", str)


class Project(BaseModel):
    id: ProjectID
    directory: Path
    config: HeyConfig
