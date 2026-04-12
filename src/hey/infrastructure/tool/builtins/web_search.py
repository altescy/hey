import asyncio
from typing import Optional

from hey.domain.entities.tool import ToolSpec
from hey.domain.services.tool import generate_tool_spec_from_callable

_DESCRIPTION = """\
Search the web using DuckDuckGo and return a list of results.

Each result includes a title, URL, and a short snippet of the page content.
No API key is required.

Parameters:
- query: The search query string.
- max_results: Maximum number of results to return (default: 10, max: 50).
- region: Region code for localised results, e.g. "us-en", "jp-jp" (default: no restriction).
- timelimit: Restrict results by recency: "d" (day), "w" (week), "m" (month), "y" (year).

Notes:
- Requires the [web] optional dependencies: pip install 'hey[web]'
- DuckDuckGo may rate-limit aggressive usage. Space out repeated calls if needed.
- Snippets are brief; use web_fetch to retrieve the full content of a specific page.
""".strip()

_MAX_RESULTS_DEFAULT = 10
_MAX_RESULTS_LIMIT = 50


def is_available() -> bool:
    try:
        import ddgs  # noqa: F401
    except ImportError:
        return False
    return True


def create_web_search_tool_spec() -> ToolSpec:
    async def web_search(
        query: str,
        max_results: Optional[int] = None,
        region: Optional[str] = None,
        timelimit: Optional[str] = None,
    ) -> str:
        """Search the web with DuckDuckGo and return formatted results."""
        try:
            from ddgs import DDGS
        except ImportError as e:
            raise RuntimeError(
                "web_search requires the [web] optional dependencies. Install them with: pip install 'hey[web]'"
            ) from e

        n = min(
            max_results if max_results is not None else _MAX_RESULTS_DEFAULT,
            _MAX_RESULTS_LIMIT,
        )

        def _search() -> list[dict[str, str]]:
            with DDGS() as ddgs:
                return ddgs.text(
                    query,
                    region=region,
                    timelimit=timelimit,
                    max_results=n,
                )

        results = await asyncio.to_thread(_search)

        if not results:
            return "No results found."

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "(no title)")
            href = r.get("href", "")
            body = r.get("body", "")
            lines.append(f"{i}. **{title}**")
            if href:
                lines.append(f"   URL: {href}")
            if body:
                lines.append(f"   {body}")
            lines.append("")

        return "\n".join(lines).strip()

    return generate_tool_spec_from_callable(
        web_search,
        name="web_search",
        description=_DESCRIPTION,
        permission={"query.*": "ask"},
    )
