"""
Celery tasks for distributed crawling.
Each crawl job runs as a Celery task so multiple workers can crawl in parallel.
"""

import asyncio
import logging
from datetime import datetime

from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings
from backend.models.schemas import Base, Page, CrawlJob
from backend.crawler.crawler import crawl
from backend.cache import invalidate_search_cache

logger = logging.getLogger(__name__)
settings = get_settings()

# Celery app
celery_app = Celery("crawler", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# Synchronous engine for Celery workers (they run in their own processes)
sync_engine = create_engine(settings.database_url, echo=False)
SyncSession = sessionmaker(bind=sync_engine)


def ensure_tables():
    Base.metadata.create_all(sync_engine)


@celery_app.task(bind=True, name="crawl_website")
def crawl_website(self, job_id: int, seed_url: str, max_pages: int = 50, depth: int = 2):
    """Execute a crawl job: crawl the site, store pages in DB, update job status."""
    ensure_tables()
    db = SyncSession()

    try:
        # Mark job as running
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if not job:
            logger.error(f"CrawlJob {job_id} not found")
            return
        job.status = "running"
        db.commit()

        # Progress callback updates the job's pages_crawled
        def on_progress(count):
            try:
                job.pages_crawled = count
                db.commit()
            except Exception:
                db.rollback()

        # Run the async crawler in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            pages = loop.run_until_complete(
                crawl(seed_url, max_pages=max_pages, max_depth=depth, progress_callback=on_progress)
            )
        finally:
            loop.close()

        # Store crawled pages
        for page_data in pages:
            existing = db.query(Page).filter(Page.url == page_data["url"]).first()
            if existing:
                existing.title = page_data["title"]
                existing.content = page_data["content"]
                existing.domain = page_data["domain"]
                existing.crawled_at = datetime.utcnow()
                existing.status = "crawled"
            else:
                page = Page(
                    url=page_data["url"],
                    title=page_data["title"],
                    content=page_data["content"],
                    domain=page_data["domain"],
                    status="crawled",
                )
                db.add(page)
        db.commit()

        # Trigger index rebuild
        from backend.search.engine import SearchEngine
        engine = SearchEngine(db)
        engine.build_index()

        # Invalidate cached search results since the index changed
        invalidate_search_cache()

        # Mark job complete
        job.status = "completed"
        job.pages_crawled = len(pages)
        job.finished_at = datetime.utcnow()
        db.commit()

        logger.info(f"Job {job_id}: crawled {len(pages)} pages from {seed_url}")
        return {"job_id": job_id, "pages_crawled": len(pages)}

    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if job:
            job.status = "failed"
            db.commit()
        raise
    finally:
        db.close()
