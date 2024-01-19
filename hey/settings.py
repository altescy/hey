from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Final, Sequence

import yaml
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, HttpUrl

HEY_ROOT_CONFIG_DIR: Final = Path.home() / ".hey"
HEY_ROOT_CONFIG_FILE: Final = HEY_ROOT_CONFIG_DIR / "config.yml"
HEY_ROOT_CONTEXT_FILE: Final = HEY_ROOT_CONFIG_DIR / "context.db"


class Profile(BaseModel):
    base_url: HttpUrl | None = None
    api_key: str | None = None
    model: str = "gpt-3.5-turbo"
    temperature: float | None = None
    prompt: Sequence[ChatCompletionMessageParam] = ()


class Settings(BaseModel):
    profiles: dict[str, Profile] = {}


_DEFAULT_SETTINGS: Final = Settings(
    profiles={
        "default": Profile(),
    },
)


def load_settings(filename: str | PathLike | None = None) -> Settings:
    settings: Settings
    if filename is None:
        if not HEY_ROOT_CONFIG_FILE.exists():
            settings = _DEFAULT_SETTINGS.copy()
            return settings
        filename = HEY_ROOT_CONFIG_FILE
    with open(filename) as f:
        settings = Settings.parse_obj(yaml.safe_load(f))
        return settings
