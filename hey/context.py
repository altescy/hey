import datetime
from os import PathLike
from types import TracebackType
from typing import Sequence, cast

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionRole
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, desc, select
from sqlmodel.sql.expression import Select


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: int | None = Field(default=None, primary_key=True)
    context_id: int = Field(foreign_key="contexts.id")
    role: str
    content: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.now)

    context: "Context" = Relationship(back_populates="messages")

    def to_message_param(self) -> ChatCompletionMessageParam:
        param = {
            "role": cast(ChatCompletionRole, self.role),
            "content": self.content,
        }
        return cast(ChatCompletionMessageParam, param)


class Context(SQLModel, table=True):
    __tablename__ = "contexts"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)

    messages: list[Message] = Relationship(back_populates="context", sa_relationship_kwargs={"cascade": "all, delete"})


class ContextClient:
    def __init__(self, sqlite_filename: str | PathLike) -> None:
        self._engine = create_engine(f"sqlite:///{sqlite_filename}")
        SQLModel.metadata.create_all(self._engine)

        self._internal_session: Session | None = None

    def __enter__(self) -> "ContextClient":
        if self._internal_session is not None:
            raise RuntimeError("Already in a session")
        self._internal_session = Session(self._engine)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._internal_session is None:
            raise RuntimeError("Not in a session")
        self._internal_session.close()
        self._internal_session = None

    @property
    def _session(self) -> Session:
        if self._internal_session is None:
            raise RuntimeError("Not in a session")
        return self._internal_session

    def create_context(
        self,
        title: str,
        prompt: Sequence[ChatCompletionMessageParam] = (),
    ) -> Context:
        context = Context(title=title)
        self._session.add(context)
        self._session.commit()
        self._session.refresh(context)
        if prompt:
            self.add_messages(context, prompt)
        return context

    def delete_context(self, context: int | Context) -> Context | None:
        if isinstance(context, int):
            _context = self._session.get(Context, context)
            if _context is None:
                return None
            context = _context
        self._session.delete(context)
        self._session.commit()
        return context

    def add_message(
        self,
        context: Context,
        message: Message | ChatCompletionMessageParam,
    ) -> Message:
        if not isinstance(message, Message):
            message = Message(
                name=message.get("name"),
                role=message["role"],
                content=message["content"],
            )
        self._session.add(message)
        self._session.commit()
        self._session.refresh(message)
        return message

    def add_messages(
        self,
        context: Context,
        messages: Sequence[Message | ChatCompletionMessageParam],
    ) -> Sequence[Message]:
        assert context.id is not None
        _messages = []
        for message in messages:
            if not isinstance(message, Message):
                message = Message(
                    name=message.get("name"),
                    role=message["role"],
                    content=message["content"],
                    context_id=context.id,
                )
            message.context_id = context.id
            self._session.add(message)
            _messages.append(message)
        self._session.commit()
        return _messages

    def delete_last_message(self, context: int | Context) -> Message | None:
        if isinstance(context, Context):
            assert context.id is not None
            context = context.id
        query = select(Message).where(Message.context_id == context).order_by(desc(Message.created_at))
        message = self._session.exec(query).first()
        if message is None:
            return None
        self._session.delete(message)
        self._session.commit()
        return message

    def get_context(self, context_id: int) -> Context | None:
        return self._session.get(Context, context_id)

    def get_latest_context(self) -> Context | None:
        query = select(Context).order_by(desc(Context.created_at))
        context = self._session.exec(query).first()
        return context

    def get_messages(
        self,
        context: int | Context,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Sequence[Message]:
        if isinstance(context, Context):
            assert context.id is not None
            context = context.id
        query = cast(Select[Message], select(Message).where(Message.context_id == context))
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        messages = self._session.exec(query).all()
        return messages

    def get_contexts(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Sequence[Context]:
        query = cast(Select[Context], select(Context))
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        contexts = self._session.exec(query).all()
        return contexts

    def search_contexts(
        self,
        text: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Sequence[Context]:
        query = cast(Select[Context], select(Context).where(select(Message).where(Message.context_id == Context.id).where(Message.content.like(f"%{text}%")).exists()))  # type: ignore[attr-defined]
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        contexts = self._session.exec(query).all()
        return contexts

    def rename_context(self, context: int | Context, title: str) -> Context:
        if isinstance(context, int):
            _context = self._session.get(Context, context)
            if _context is None:
                raise ValueError(f"Context {context} not found")
            context = _context
        context.title = title
        self._session.add(context)
        self._session.commit()
        self._session.refresh(context)
        return context
