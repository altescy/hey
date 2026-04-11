from pathlib import Path
from typing import NewType

from pydantic import BaseModel

ProjectID = NewType("ProjectID", int)


class Project(BaseModel):
    id: ProjectID
    directory: Path
