"""Web search integration for TheCouncil agents.

Uses the Tavily API (tavily-python) as the search provider.
All HTTP calls originate from the backend — the TAVILY_API_KEY is never
sent to the client.

Access is tier-gated: Pro, Ultra, and Enterprise only.
"""

from __future__ import annotations

import os
from typing import Any


class WebSearchDisabledError(RuntimeError):
    """Raised when web search is unavailable (missing key or tier check failed)."""


async def web_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
    """Perform a Tavily web search and return structured results.

    Args:
        query:       The search query string.
        max_results: Maximum number of result items to return (default 5).

    Returns:
        A dict with keys:
          - ``query``    — the original query
          - ``results``  — list of {title, url, content} dicts
          - ``answer``   — Tavily's synthesised answer (may be empty)
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        raise WebSearchDisabledError("TAVILY_API_KEY is not set.")

    try:
        from tavily import AsyncTavilyClient  # type: ignore[import]
    except Exception as exc:  # pragma: no cover
        raise WebSearchDisabledError(f"tavily-python SDK unavailable: {exc}") from exc

    client = AsyncTavilyClient(api_key=api_key)

    # Perform the search; include_answer gives a short synthesised summary.
    raw = await client.search(
        query=query,
        max_results=max_results,
        include_answer=True,
        search_depth="basic",
    )

    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in raw.get("results", [])
    ]

    return {
        "query": query,
        "results": results,
        "answer": raw.get("answer", ""),
    }


def build_web_search_tool_spec() -> dict[str, Any]:
    """Return an Anthropic-compatible tool specification for the web_search tool.

    Agents can call this tool to retrieve real-time information during deliberation.
    """
    return {
        "name": "web_search",
        "description": (
            "Search the web for up-to-date information on a topic. "
            "Use this when you need current facts, recent events, or data "
            "that may not be in your training knowledge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up.",
                },
            },
            "required": ["query"],
        },
    }
