from hey.domain.entities.chat import ChatSessionID
from hey.domain.entities.llm import LLMMessage
from hey.domain.entities.tool import ToolSpec
from hey.domain.repositories.chat import ChatMessageRetrievalRequest
from hey.domain.services.tool import generate_tool_spec_from_callable
from hey.infrastructure.tool.builtins.dependencies import ToolDependencies

_DESCRIPTION = """\
Search stored chat messages in the current project.

By default, this searches across all sessions in the project. You can pass a
specific `session_id` to scope results to one session.

Notes:
- `query` is optional; when provided, case-insensitive substring match is used
  against message text parts.
- `offset` starts at 0.
- `limit` defaults to 20 and caps results per call.
- Returns matching messages with session id, role, timestamp, and text excerpt.
""".strip()

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_MAX_TEXT_LENGTH = 240


def is_available() -> bool:
    return True


def _message_to_text(message: LLMMessage) -> str:
    parts = message.get("parts", ())
    text = "".join(part.get("text", "") for part in parts)
    return text.strip()


def create_tool_spec(dependencies: ToolDependencies) -> ToolSpec:
    async def search_chat_messages(
        query: str | None = None,
        session_id: int | None = None,
        offset: int = 0,
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        """Search chat messages in the current project."""
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1:
            raise ValueError("limit must be >= 1")

        effective_limit = min(limit, _MAX_LIMIT)
        repository = dependencies.chat_repository
        normalized_query = query.strip() if query is not None else None
        request = ChatMessageRetrievalRequest(
            query=normalized_query or None,
            offset=offset,
            limit=effective_limit,
        )
        if session_id is None:
            response = repository.get_messages_by_project_id(dependencies.project_id, request)
            scope = f"project ({dependencies.project_id})"
        else:
            response = repository.get_messages_by_session_id(ChatSessionID(session_id), request)
            scope = f"session {session_id}"

        query_label = normalized_query if normalized_query else "<none>"
        if not response.results:
            return f"No chat messages found for query '{query_label}' in {scope}."

        lines = [
            f"Found {response.total} matching message{'s' if response.total != 1 else ''} in {scope}.",
            f"Showing {len(response.results)} result{'s' if len(response.results) != 1 else ''} from offset {offset}.",
            "",
        ]
        for message in response.results:
            text = _message_to_text(message.message)
            if len(text) > _MAX_TEXT_LENGTH:
                text = text[:_MAX_TEXT_LENGTH] + "..."
            if not text:
                text = "<no text content>"
            lines.append(
                f"- session={int(message.session_id)} role={message.message['role']} "
                f"time={message.created_at.isoformat()} text={text}"
            )

        if response.next_offset is not None:
            lines.append("")
            lines.append(f"Next offset: {response.next_offset}")

        return "\n".join(lines)

    return generate_tool_spec_from_callable(
        search_chat_messages,
        name="search_chat_messages",
        description=_DESCRIPTION,
        permission={"query": "allow", "session_id": "allow", "offset": "allow", "limit": "allow"},
    )
