"""
AI-powered features using OpenAI API:
1. Query enhancement - expand/refine user search queries
2. Result summarization - generate AI summaries of search results
3. Page summarization - summarize individual crawled pages
"""

import logging
from openai import OpenAI

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        kwargs = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        _client = OpenAI(**kwargs)
    return _client


def _chat(prompt: str, max_tokens: int) -> str:
    response = get_client().chat.completions.create(
        model=settings.openai_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


async def enhance_query(query: str) -> str:
    """Use the LLM to expand a search query into a more effective search string."""
    if not settings.openai_api_key:
        return query

    try:
        prompt = (
            f"Rewrite this search query to be more effective for finding relevant results. "
            f"Return ONLY the improved query, nothing else.\n\n"
            f"Original query: {query}"
        )
        enhanced = _chat(prompt, max_tokens=150).strip('"')
        logger.info(f"Query enhanced: '{query}' -> '{enhanced}'")
        return enhanced
    except Exception as e:
        logger.warning(f"Query enhancement failed: {e}")
        return query


async def summarize_results(query: str, results: list[dict]) -> str:
    """Generate an AI summary that synthesizes the top search results for a query."""
    if not settings.openai_api_key or not results:
        return ""

    try:
        context_parts = []
        for i, r in enumerate(results[:5], 1):
            snippet = r.get("snippet", "")[:500]
            context_parts.append(f"[{i}] {r.get('title', 'Untitled')} ({r.get('url', '')})\n{snippet}")
        context = "\n\n".join(context_parts)

        prompt = (
            f"Based on these search results for the query \"{query}\", provide a concise, "
            f"helpful summary that directly answers the query. Reference the sources by number. "
            f"Keep it under 3 paragraphs.\n\n"
            f"Search Results:\n{context}"
        )
        return _chat(prompt, max_tokens=400)
    except Exception as e:
        logger.warning(f"Result summarization failed: {e}")
        return ""


async def summarize_page(content: str, title: str = "") -> str:
    """Generate a short summary of a single crawled page."""
    if not settings.openai_api_key:
        return ""

    try:
        prompt = (
            f"Summarize this web page in 2-3 sentences.\n\n"
            f"Title: {title}\n"
            f"Content: {content[:3000]}"
        )
        return _chat(prompt, max_tokens=200)
    except Exception as e:
        logger.warning(f"Page summarization failed: {e}")
        return ""
