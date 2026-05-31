from os import PathLike
from typing import TypedDict

from hey.domain.entities.chat import ChatSession, ChatSessionID
from hey.domain.entities.llm import LLMState
from hey.domain.entities.project import Project, ProjectID


class GetLLMStateInput(TypedDict):
    session_id: ChatSessionID


class GetLLMStateOutput(TypedDict):
    state: LLMState


class CreateSessionInput(TypedDict):
    project_id: ProjectID


class CreateSessionOutput(TypedDict):
    session: ChatSession


class GetOrCreateSessionInput(TypedDict):
    project_id: ProjectID
    session_timeout: float


class GetOrCreateSessionOutput(TypedDict):
    session: ChatSession
    is_new: bool


class ResumeSessionInput(TypedDict):
    session_id: ChatSessionID


class ResumeSessionOutput(TypedDict):
    session: ChatSession


class RunChatInput(TypedDict):
    session_id: ChatSessionID
    prompt: str


class GetProjectInput(TypedDict):
    path: str | PathLike


class GetProjectOutput(TypedDict):
    project: Project
