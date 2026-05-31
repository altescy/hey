from pathlib import Path
from typing import NewType

from pydantic import BaseModel

from .config import HeyConfig

ProjectID = NewType("ProjectID", str)


class Project(BaseModel):
    id: ProjectID
    directory: Path
    config: HeyConfig
