import datetime
from os import PathLike
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
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

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
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

    messages: list[Message] = Relationship(back_populates="context", sa_relationship_kwargs={"cascade": "all, delete"})


class ContextClient:
    def __init__(self, sqlite_filename: str | PathLike) -> None:
        self._engine = create_engine(f"sqlite:///{sqlite_filename}")
        SQLModel.metadata.create_all(self._engine)

    def create_context(
        self,
        title: str,
        prompt: Sequence[ChatCompletionMessageParam] = (),
    ) -> Context:
        with Session(self._engine) as session:
            context = Context(title=title)
            session.add(context)
            session.commit()
            session.refresh(context)
        if prompt:
            self.add_messages(context, prompt)
        return context

    def delete_context(self, context: int | Context) -> None:
        with Session(self._engine) as session:
            if isinstance(context, int):
                _context = session.get(Context, context)
                if _context is None:
                    return
                context = _context
            session.delete(context)
            session.commit()

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
        with Session(self._engine) as session:
            session.add(message)
            session.commit()
            session.refresh(message)
        return message

    def add_messages(
        self,
        context: Context,
        messages: Sequence[Message | ChatCompletionMessageParam],
    ) -> Sequence[Message]:
        assert context.id is not None
        with Session(self._engine) as session:
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
                session.add(message)
                _messages.append(message)
            session.commit()
        return _messages

    def get_context(self, context_id: int) -> Context | None:
        with Session(self._engine) as session:
            context = session.get(Context, context_id)
        return context

    def get_latest_context(self) -> Context | None:
        with Session(self._engine) as session:
            query = select(Context).order_by(desc(Context.created_at))
            context = session.exec(query).first()
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
        with Session(self._engine) as session:
            query = cast(Select[Message], select(Message).where(Message.context_id == context))
            if offset is not None:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            messages = session.exec(query).all()
        return messages

    def get_contexts(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Sequence[Context]:
        with Session(self._engine) as session:
            query = cast(Select[Context], select(Context))
            if offset is not None:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            contexts = session.exec(query).all()
        return contexts

    def search_contexts(
        self,
        text: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Sequence[Context]:
        with Session(self._engine) as session:
            query = cast(Select[Context], select(Context).where(select(Message).where(Message.context_id == Context.id).where(Message.content.like(f"%{text}%")).exists()))  # type: ignore[attr-defined]
            if offset is not None:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            contexts = session.exec(query).all()
        return contexts
