"""
Redis-backed cache for search results.

Cache keys: search:<sha1(query|mode|page|per_page)>
Invalidated on every crawl completion and manual /api/reindex.
TTL of 1 hour is a safety net in case explicit invalidation is missed.
"""

import hashlib
import logging
from typing import Optional

import redis

from backend.config import get_settings
from backend.models.schemas import SearchResponse

logger = logging.getLogger(__name__)
settings = get_settings()

SEARCH_CACHE_TTL = 3600
SEARCH_KEY_PREFIX = "search:"

_client: Optional[redis.Redis] = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _search_cache_key(query: str, mode: str, page: int, per_page: int) -> str:
    raw = f"{query}|{mode}|{page}|{per_page}"
    return SEARCH_KEY_PREFIX + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_cached_search(query: str, mode: str, page: int, per_page: int) -> Optional[SearchResponse]:
    try:
        cached = get_client().get(_search_cache_key(query, mode, page, per_page))
        if cached is None:
            return None
        return SearchResponse.model_validate_json(cached)
    except Exception as e:
        logger.warning(f"Search cache read failed: {e}")
        return None


def set_cached_search(query: str, mode: str, page: int, per_page: int, response: SearchResponse) -> None:
    try:
        get_client().setex(
            _search_cache_key(query, mode, page, per_page),
            SEARCH_CACHE_TTL,
            response.model_dump_json(),
        )
    except Exception as e:
        logger.warning(f"Search cache write failed: {e}")


def invalidate_search_cache() -> int:
    try:
        client = get_client()
        deleted = 0
        for key in client.scan_iter(match=SEARCH_KEY_PREFIX + "*"):
            client.delete(key)
            deleted += 1
        logger.info(f"Invalidated {deleted} search cache entries")
        return deleted
    except Exception as e:
        logger.warning(f"Search cache invalidation failed: {e}")
        return 0
