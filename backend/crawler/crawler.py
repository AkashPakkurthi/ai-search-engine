"""
Async web crawler that extracts text content from web pages.
Supports depth-limited crawling with concurrent requests.
"""

import asyncio
import logging
from urllib.parse import urljoin, urlparse
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "AISearchBot/1.0 (+https://github.com/ai-search-engine)"
}

IGNORED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".mp4", ".mp3",
    ".zip", ".tar", ".gz", ".exe", ".dmg", ".css", ".js", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
}


def should_skip_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in IGNORED_EXTENSIONS)


def extract_text(html: str, url: str) -> dict:
    """Extract title, text content, and outgoing links from HTML."""
    soup = BeautifulSoup(html, "lxml")

    # Remove script and style elements
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = " ".join(text.split())

    # Extract links
    links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        absolute = urljoin(url, href)
        parsed = urlparse(absolute)
        if parsed.scheme in ("http", "https") and not should_skip_url(absolute):
            # Remove fragment
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            links.add(clean_url)

    return {"title": title, "content": text, "links": links}


async def fetch_page(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Fetch a single page, return HTML or None on failure."""
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return None
            return await resp.text(errors="replace")
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


async def crawl(
    seed_url: str,
    max_pages: int = 50,
    max_depth: int = 2,
    concurrency: int = 10,
    progress_callback=None,
) -> list[dict]:
    """
    Crawl starting from seed_url up to max_pages pages and max_depth link depth.
    Returns list of dicts with keys: url, title, content, domain.
    progress_callback(pages_crawled) is called after each page.
    """
    visited = set()
    results = []
    # Queue items: (url, depth)
    queue = asyncio.Queue()
    await queue.put((seed_url, 0))
    visited.add(seed_url)

    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession() as session:
        while not queue.empty() and len(results) < max_pages:
            # Drain up to `concurrency` items from queue
            batch = []
            while not queue.empty() and len(batch) < concurrency:
                batch.append(await queue.get())

            async def process(url: str, depth: int):
                async with sem:
                    html = await fetch_page(session, url)
                    if html is None:
                        return
                    data = extract_text(html, url)
                    if len(data["content"]) < 50:
                        return  # Skip near-empty pages
                    domain = urlparse(url).netloc
                    results.append({
                        "url": url,
                        "title": data["title"],
                        "content": data["content"][:50000],  # Limit content size
                        "domain": domain,
                    })
                    if progress_callback:
                        progress_callback(len(results))

                    # Enqueue child links
                    if depth < max_depth and len(results) < max_pages:
                        for link in data["links"]:
                            if link not in visited and len(visited) < max_pages * 2:
                                visited.add(link)
                                await queue.put((link, depth + 1))

            tasks = [process(url, depth) for url, depth in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"Crawl complete: {len(results)} pages from {seed_url}")
    return results
