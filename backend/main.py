"""
FastAPI application — the main entry point for the AI Search Engine.
Serves both the API and the frontend templates.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import init_db, get_db
from backend.models.schemas import (
    Page, CrawlJob,
    SearchRequest, SearchResponse, SearchResult,
    CrawlRequest, CrawlStatusResponse, StatsResponse,
)
from backend.search.engine import SearchEngine
from backend.ai.summarizer import enhance_query, summarize_results
from backend.crawler.tasks import crawl_website
from backend.cache import get_cached_search, set_cached_search, invalidate_search_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="AI-Powered Distributed Search Engine",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))


# ──────────────────────────── Frontend Routes ────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = "", mode: str = "hybrid"):
    return templates.TemplateResponse("search.html", {
        "request": request, "query": q, "mode": mode,
    })


@app.get("/crawl", response_class=HTMLResponse)
async def crawl_page(request: Request):
    return templates.TemplateResponse("crawl.html", {"request": request})


@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", {"request": request})


# ──────────────────────────── API: Search ────────────────────────────

@app.post("/api/search", response_model=SearchResponse)
async def api_search(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    cached = get_cached_search(req.query, req.mode, req.page, req.per_page)
    if cached is not None:
        return cached

    # Enhance query with AI
    enhanced_query = await enhance_query(req.query)

    # Run search using sync session (search engine uses sync SQLAlchemy)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    sync_engine = create_engine(settings.database_url)
    SyncSession = sessionmaker(bind=sync_engine)
    sync_db = SyncSession()

    try:
        engine = SearchEngine(sync_db)
        raw_results = engine.search(enhanced_query, mode=req.mode, top_k=req.per_page * 2)

        # Paginate
        start = (req.page - 1) * req.per_page
        end = start + req.per_page
        page_results = raw_results[start:end]

        # Generate AI summary for the results
        ai_summary = await summarize_results(req.query, page_results)

        results = []
        for r in page_results:
            results.append(SearchResult(
                url=r["url"],
                title=r.get("title", ""),
                snippet=r.get("snippet", "")[:300],
                score=round(r["score"], 4),
                ai_summary=None,
            ))

        # Attach the AI summary to the first result if available
        if results and ai_summary:
            results[0].ai_summary = ai_summary

        response = SearchResponse(
            query=req.query,
            ai_enhanced_query=enhanced_query if enhanced_query != req.query else None,
            results=results,
            total=len(raw_results),
            page=req.page,
            per_page=req.per_page,
            mode=req.mode,
        )
        set_cached_search(req.query, req.mode, req.page, req.per_page, response)
        return response
    finally:
        sync_db.close()


# ──────────────────────────── API: Crawl ────────────────────────────

@app.post("/api/crawl")
async def api_start_crawl(req: CrawlRequest, db: AsyncSession = Depends(get_db)):
    # Create job record
    job = CrawlJob(
        seed_url=req.url,
        max_pages=req.max_pages,
        depth=req.depth,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch to Celery
    crawl_website.delay(job.id, req.url, req.max_pages, req.depth)

    return {
        "job_id": job.id,
        "status": "pending",
        "message": f"Crawl job started for {req.url}",
    }


@app.get("/api/crawl/{job_id}", response_model=CrawlStatusResponse)
async def api_crawl_status(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(CrawlJob, job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Crawl job not found")

    return CrawlStatusResponse(
        job_id=job.id,
        seed_url=job.seed_url,
        status=job.status,
        pages_crawled=job.pages_crawled,
        max_pages=job.max_pages,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


@app.get("/api/crawl", response_model=list[CrawlStatusResponse])
async def api_list_crawls(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(
        select(CrawlJob).order_by(desc(CrawlJob.created_at)).limit(20)
    )
    jobs = result.scalars().all()
    return [
        CrawlStatusResponse(
            job_id=j.id,
            seed_url=j.seed_url,
            status=j.status,
            pages_crawled=j.pages_crawled,
            max_pages=j.max_pages,
            created_at=j.created_at,
            finished_at=j.finished_at,
        )
        for j in jobs
    ]


# ──────────────────────────── API: Stats ────────────────────────────

@app.get("/api/stats", response_model=StatsResponse)
async def api_stats(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    total_pages_result = await db.execute(select(func.count(Page.id)))
    total_pages = total_pages_result.scalar() or 0

    total_domains_result = await db.execute(
        select(func.count(func.distinct(Page.domain)))
    )
    total_domains = total_domains_result.scalar() or 0

    total_jobs_result = await db.execute(select(func.count(CrawlJob.id)))
    total_jobs = total_jobs_result.scalar() or 0

    recent_result = await db.execute(
        select(CrawlJob).order_by(desc(CrawlJob.created_at)).limit(5)
    )
    recent_jobs = recent_result.scalars().all()

    return StatsResponse(
        total_pages=total_pages,
        total_domains=total_domains,
        total_crawl_jobs=total_jobs,
        recent_crawls=[
            CrawlStatusResponse(
                job_id=j.id,
                seed_url=j.seed_url,
                status=j.status,
                pages_crawled=j.pages_crawled,
                max_pages=j.max_pages,
                created_at=j.created_at,
                finished_at=j.finished_at,
            )
            for j in recent_jobs
        ],
    )


# ──────────────────────────── API: Index Management ────────────────────────────

@app.post("/api/reindex")
async def api_reindex():
    """Manually trigger a search index rebuild."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    sync_engine = create_engine(settings.database_url)
    SyncSession = sessionmaker(bind=sync_engine)
    sync_db = SyncSession()
    try:
        engine = SearchEngine(sync_db)
        engine.build_index()
        invalidate_search_cache()
        return {"message": "Index rebuilt successfully"}
    finally:
        sync_db.close()
