import asyncio
import io
from typing import Optional

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable

_DESCRIPTION = """\
Fetch content from a URL and return it converted to Markdown.

Uses httpx for async HTTP requests and markitdown for content conversion.
HTML pages are converted to clean Markdown. Other supported formats
(PDF, plain text, RSS, etc.) are also handled automatically.

Parameters:
- url: The URL to fetch. Must start with http:// or https://.
- timeout: Request timeout in seconds (default: 30, max: 120).
- max_bytes: Maximum response body size in bytes (default: 5242880 = 5MB).

Notes:
- Requires the [web] optional dependencies: pip install 'hey[web]'
- Binary content (images, etc.) that cannot be converted to text will raise an error.
- If a page requires JavaScript rendering, the returned content may be incomplete.
""".strip()

_MAX_BYTES_DEFAULT = 5 * 1024 * 1024  # 5MB
_TIMEOUT_DEFAULT = 30
_TIMEOUT_MAX = 120

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/markdown, text/html;q=0.9, text/plain;q=0.8, */*;q=0.1",
    "Accept-Language": "en-US,en;q=0.9",
}


def is_available() -> bool:
    try:
        import httpx  # noqa: F401
        import markitdown  # noqa: F401
    except ImportError:
        return False
    return True


def create_tool_spec() -> ToolSpec:
    async def web_fetch(
        url: str,
        timeout: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> str:
        """Fetch a URL and return its content as Markdown."""
        try:
            import httpx
            from markitdown import MarkItDown
            from markitdown._stream_info import StreamInfo
        except ImportError as e:
            raise RuntimeError(
                "web_fetch requires the [web] optional dependencies. Install them with: pip install 'hey[web]'"
            ) from e

        if not url.startswith("http://") and not url.startswith("https://"):
            raise ValueError("URL must start with http:// or https://")

        _timeout = min(timeout if timeout is not None else _TIMEOUT_DEFAULT, _TIMEOUT_MAX)
        _max_bytes = max_bytes if max_bytes is not None else _MAX_BYTES_DEFAULT

        async with httpx.AsyncClient(follow_redirects=True, headers=_HEADERS) as client:
            async with client.stream("GET", url, timeout=_timeout) as response:
                response.raise_for_status()

                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > _max_bytes:
                    raise RuntimeError(
                        f"Response too large: Content-Length {content_length} exceeds limit of {_max_bytes} bytes"
                    )

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > _max_bytes:
                        raise RuntimeError(f"Response too large: exceeded limit of {_max_bytes} bytes while reading")
                    chunks.append(chunk)

                body = b"".join(chunks)
                content_type = response.headers.get("content-type", "")
                final_url = str(response.url)

        mimetype = content_type.split(";")[0].strip() or None
        charset_part = next(
            (p.strip() for p in content_type.split(";")[1:] if "charset=" in p.lower()),
            None,
        )
        charset = charset_part.split("=", 1)[1].strip() if charset_part else None

        stream_info = StreamInfo(mimetype=mimetype, charset=charset, url=final_url)
        md = MarkItDown(enable_plugins=False)

        result = await asyncio.to_thread(
            md.convert_stream,
            io.BytesIO(body),
            stream_info=stream_info,
        )

        text = result.text_content.strip()
        if not text:
            raise RuntimeError(f"No text content could be extracted from {url}")
        return text

    return generate_tool_spec_from_callable(
        web_fetch,
        name="web_fetch",
        description=_DESCRIPTION,
        permission={"url.*": "ask"},
    )
