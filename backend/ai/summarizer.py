"""
AI-powered features using Claude API:
1. Query enhancement - expand/refine user search queries
2. Result summarization - generate AI summaries of search results
3. Page summarization - summarize individual crawled pages
"""

import logging
from anthropic import Anthropic

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


async def enhance_query(query: str) -> str:
    """Use Claude to expand a search query into a more effective search string."""
    if not settings.anthropic_api_key:
        return query

    try:
        client = get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    f"Rewrite this search query to be more effective for finding relevant results. "
                    f"Return ONLY the improved query, nothing else.\n\n"
                    f"Original query: {query}"
                ),
            }],
        )
        enhanced = response.content[0].text.strip().strip('"')
        logger.info(f"Query enhanced: '{query}' -> '{enhanced}'")
        return enhanced
    except Exception as e:
        logger.warning(f"Query enhancement failed: {e}")
        return query


async def summarize_results(query: str, results: list[dict]) -> str:
    """Generate an AI summary that synthesizes the top search results for a query."""
    if not settings.anthropic_api_key or not results:
        return ""

    try:
        # Build context from top results
        context_parts = []
        for i, r in enumerate(results[:5], 1):
            snippet = r.get("snippet", "")[:500]
            context_parts.append(f"[{i}] {r.get('title', 'Untitled')} ({r.get('url', '')})\n{snippet}")
        context = "\n\n".join(context_parts)

        client = get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"Based on these search results for the query \"{query}\", provide a concise, "
                    f"helpful summary that directly answers the query. Reference the sources by number. "
                    f"Keep it under 3 paragraphs.\n\n"
                    f"Search Results:\n{context}"
                ),
            }],
        )
        summary = response.content[0].text.strip()
        return summary
    except Exception as e:
        logger.warning(f"Result summarization failed: {e}")
        return ""


async def summarize_page(content: str, title: str = "") -> str:
    """Generate a short summary of a single crawled page."""
    if not settings.anthropic_api_key:
        return ""

    try:
        client = get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize this web page in 2-3 sentences.\n\n"
                    f"Title: {title}\n"
                    f"Content: {content[:3000]}"
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Page summarization failed: {e}")
        return ""
