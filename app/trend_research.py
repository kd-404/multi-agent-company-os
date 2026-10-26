"""
Shared Tavily trend-research call - used by the design agent (one design's
worth of research -> image prompt) and now the marketing agent's trend
radar (does the catalog already cover what's trending right now?). Pulled
out once here so both callers hit Tavily the exact same way instead of
drifting apart, same pattern as image_client.py / vision_client.py.
"""
import httpx

from .config import settings
from .retry import with_retry


def _call_tavily(query: str) -> dict:
    resp = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {settings.TAVILY_API_KEY}"},
        json={
            "query": query,
            "search_depth": "advanced",
            "max_results": 5,
            "topic": "general",
            "include_answer": "advanced",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def research_trend(query: str) -> tuple[str, list[str]]:
    """Calls Tavily directly (with retry/backoff on timeouts/5xx/429 - see
    app/retry.py); returns (written summary, source URLs)."""
    data = with_retry(lambda: _call_tavily(query), label="tavily_search")
    summary = data.get("answer") or ""
    if not summary:
        # Fall back to stitching result snippets together if Tavily didn't
        # return a synthesized answer for some reason.
        summary = " ".join(r.get("content", "") for r in data.get("results", [])[:3])
    sources = [r["url"] for r in data.get("results", []) if r.get("url")]
    return summary, sources
