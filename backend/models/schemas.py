from pydantic import BaseModel
from datetime import datetime


# --- Database ORM Models ---
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Page(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(2048), unique=True, nullable=False, index=True)
    title = Column(String(512), default="")
    content = Column(Text, default="")
    summary = Column(Text, default="")
    domain = Column(String(256), default="")
    crawled_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="crawled")


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    seed_url = Column(String(2048), nullable=False)
    status = Column(String(20), default="pending")
    pages_crawled = Column(Integer, default=0)
    max_pages = Column(Integer, default=50)
    depth = Column(Integer, default=2)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


# --- API Schemas ---

class SearchRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # "keyword", "semantic", "hybrid"
    page: int = 1
    per_page: int = 10


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str
    score: float
    ai_summary: str | None = None


class SearchResponse(BaseModel):
    query: str
    ai_enhanced_query: str | None = None
    results: list[SearchResult]
    total: int
    page: int
    per_page: int
    mode: str


class CrawlRequest(BaseModel):
    url: str
    max_pages: int = 50
    depth: int = 2


class CrawlStatusResponse(BaseModel):
    job_id: int
    seed_url: str
    status: str
    pages_crawled: int
    max_pages: int
    created_at: datetime
    finished_at: datetime | None = None


class AISummaryRequest(BaseModel):
    query: str
    results: list[SearchResult]


class StatsResponse(BaseModel):
    total_pages: int
    total_domains: int
    total_crawl_jobs: int
    recent_crawls: list[CrawlStatusResponse]
