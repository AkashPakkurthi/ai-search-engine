# AI-Powered Distributed Search Engine

A full-stack search engine built with Python that combines distributed web crawling, hybrid search (keyword + semantic), and AI-powered result summarization using OpenAI.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Jinja2)                     │
│         Home  │  Search  │  Crawler  │  Stats            │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend                         │
│  /api/search  │  /api/crawl  │  /api/stats  │  /api/re… │
└──────┬────────────┬──────────────┬──────────────────────┘
       │            │              │
┌──────▼───┐  ┌─────▼─────┐  ┌────▼─────┐  ┌────────────┐
│  Search  │  │  Celery   │  │  SQLite  │  │  OpenAI    │
│  Engine  │  │  Workers  │  │   / DB   │  │  API (AI)  │
│          │  │           │  └──────────┘  └────────────┘
│ TF-IDF + │  │  Async    │
│ FAISS    │  │  Crawler  │
│ (Hybrid) │  │           │
└─────┬────┘  └─────┬─────┘
      │             │
      │       ┌─────▼─────────────┐
      └──────▶│      Redis        │
              │ (Broker + Cache)  │
              └───────────────────┘
```

## Features

### Hybrid Search Engine
- **Keyword Search** — TF-IDF with scikit-learn (bigram support, sublinear TF)
- **Semantic Search** — Sentence-transformers (`all-MiniLM-L6-v2`) + FAISS vector index
- **Hybrid Mode** — Reciprocal Rank Fusion (RRF) combining both for best results

### Distributed Web Crawler
- Async crawler using `aiohttp` + `BeautifulSoup`
- Celery task queue with Redis broker for parallel crawling
- Configurable depth and max pages per job
- Live progress tracking in the UI

### AI-Powered Features (OpenAI API)
- **Query Enhancement** — Rewrites search queries for better recall
- **Result Summarization** — Generates concise answers from top search results
- Works without an API key — AI features are gracefully skipped

### Search Result Caching
- **Redis-backed cache** for `/api/search` responses
- Repeated queries return in **<10ms** instead of 1–3s (no LLM call, no FAISS read)
- Keys are scoped per `(query, mode, page, per_page)` so different modes don't collide
- 1-hour TTL as a safety net
- **Auto-invalidated** after every crawl completion and `POST /api/reindex` — never serve stale results

### Frontend
- Dark-themed responsive UI
- Real-time crawl job monitoring with auto-refresh
- Search with pagination and mode selection
- Stats dashboard with index management

## Tech Stack

| Component        | Technology                          |
|------------------|-------------------------------------|
| Backend          | FastAPI, SQLAlchemy (async)         |
| Task Queue       | Celery + Redis                      |
| Cache            | Redis (search-result cache, 1h TTL) |
| Search (Keyword) | scikit-learn TF-IDF                 |
| Search (Semantic)| sentence-transformers + FAISS       |
| AI               | OpenAI API (or compatible: Groq, Ollama) |
| Crawler          | aiohttp + BeautifulSoup             |
| Database         | SQLite (default), PostgreSQL-ready  |
| Frontend         | Jinja2 + Vanilla JS                 |
| Deployment       | Docker + Docker Compose             |

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone and configure
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY (optional)

# Start all services
docker-compose up --build
```

### Option 2: Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start Redis
redis-server &

# Start Celery worker
celery -A backend.crawler.tasks worker --loglevel=info --concurrency=4 &

# Start the app
uvicorn backend.main:app --reload
```

Visit **http://localhost:8000**

## Usage

### 1. Crawl Websites
Go to `/crawl` and submit a seed URL:
- `https://en.wikipedia.org/wiki/Python_(programming_language)`
- `https://docs.python.org/3/`

Configure max pages (1–500) and link depth (1–5).

### 2. Search
Go to `/search` or use the home page search bar:
- **Hybrid** (default) — Best of both keyword and semantic
- **Semantic** — Finds conceptually similar results even without exact keyword matches
- **Keyword** — Traditional TF-IDF text matching

### 3. View Stats
Go to `/stats` to see indexed page counts, domains, and crawl history. Use the "Rebuild Search Index" button after manual DB changes.

## Configuration

All settings are in `.env`:

```env
# Required for AI features (optional — app works without it)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
# Optional: point at any OpenAI-compatible provider (Groq, Ollama, etc.)
# OPENAI_BASE_URL=https://api.groq.com/openai/v1

# Redis — used both as Celery's broker AND as the search-result cache
REDIS_URL=redis://localhost:6379/0

# Database (SQLite default, supports PostgreSQL)
DATABASE_URL=sqlite:///./search_engine.db

# Crawler defaults
CRAWL_DEPTH=2
MAX_PAGES=50
```

## API Endpoints

| Method | Endpoint             | Description                    |
|--------|----------------------|--------------------------------|
| POST   | `/api/search`        | Search with query, mode, page  |
| POST   | `/api/crawl`         | Start a new crawl job          |
| GET    | `/api/crawl`         | List recent crawl jobs         |
| GET    | `/api/crawl/{id}`    | Get crawl job status           |
| GET    | `/api/stats`         | Index statistics               |
| POST   | `/api/reindex`       | Rebuild the search index       |

### Search Request Example

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning", "mode": "hybrid", "page": 1, "per_page": 10}'
```

The first call computes results via TF-IDF + FAISS + LLM (~1–3s) and caches the JSON response in Redis under `search:<sha1(query|mode|page|per_page)>`. Subsequent identical calls hit the cache and return in <10ms. The cache is automatically wiped whenever a crawl finishes or `POST /api/reindex` runs, so stale results aren't served after the index changes.

## Project Structure

```
ai-search-engine/
├── backend/
│   ├── main.py              # FastAPI app + routes
│   ├── config.py            # Settings from .env
│   ├── database.py          # Async SQLAlchemy setup
│   ├── models/
│   │   └── schemas.py       # ORM models + API schemas
│   ├── crawler/
│   │   ├── crawler.py       # Async web crawler
│   │   └── tasks.py         # Celery distributed tasks
│   ├── search/
│   │   └── engine.py        # TF-IDF + FAISS hybrid search
│   ├── ai/
│   │   └── summarizer.py    # OpenAI query enhancement + summarization
│   └── cache.py             # Redis search-result cache + invalidation
├── frontend/
│   ├── templates/           # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── search.html
│   │   ├── crawl.html
│   │   └── stats.html
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```