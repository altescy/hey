from __future__ import annotations

import os
from datetime import timedelta
from os import PathLike
from pathlib import Path
from typing import Final, Sequence

import yaml
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

HEY_ROOT_CONFIG_DIR: Final = Path.home() / ".hey"
HEY_ROOT_CONFIG_FILE: Final = HEY_ROOT_CONFIG_DIR / "config.yml"
HEY_ROOT_CONTEXT_FILE: Final = HEY_ROOT_CONFIG_DIR / "context.db"
HEY_CURRENT_CONTEXT_FILE: Final = HEY_ROOT_CONFIG_DIR / "CURRENT_CONTEXT"
HEY_DEFAULT_MODEL_NAME: Final = "gpt-3.5-turbo"
HYE_DEFAULT_PROFILE_NAME: Final = os.getenv("HEY_PROFILE", "default")


class Profile(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    prompt: Sequence[ChatCompletionMessageParam] = ()


class Settings(BaseModel):
    profiles: dict[str, Profile] = {}
    suggest_new_context_after: timedelta | None = None


_DEFAULT_PROFILE = Profile()
_DEFAULT_SETTINGS: Final = Settings(
    profiles={
        "default": _DEFAULT_PROFILE,
    },
)


def init_settings() -> None:
    HEY_ROOT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_settings(filename: str | PathLike | None = None) -> Settings:
    settings: Settings
    if filename is None:
        if not HEY_ROOT_CONFIG_FILE.exists():
            settings = _DEFAULT_SETTINGS.copy()
            return settings
        filename = HEY_ROOT_CONFIG_FILE
    with open(filename) as f:
        settings = Settings(**yaml.safe_load(f))
        if "default" not in settings.profiles:
            settings.profiles["default"] = _DEFAULT_PROFILE.copy()
        return settings
