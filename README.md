# Libra - OLD readme

> Job scraping and sponsorship detection API — v2
> ## Join our Discord to work with us [link](https://discord.gg/Uuy5BwxGzU)
<p align="center">
  <img src="./logo.svg" alt="Libra logo" width="240" />
</p>

---

## Overview

Libra is a FastAPI-based service that aggregates internship and full-time job listings from multiple sources, enriches them with structured data extracted via LLM, and exposes them through a read-only REST API. Its primary focus is tagging jobs with H-1B visa sponsorship signals extracted directly from job descriptions.

**Live API:** `http://libra.austindwomoh.xyz`  
**Interactive docs:** `http://libra.austindwomoh.xyz/docs`  
**Author:** Austin Dwomoh

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        Scrape Phase                             │
│  Simplify (GitHub README) + JSearch API + RemoteOK API          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ List[Job]
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Deduplication                               │
│  Set-based using __hash__ on (title, company, apply_url)        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ unique valid jobs
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Database Upsert                              │
│  Bulk insert into job_list — ON CONFLICT DO UPDATE with         │
│  COALESCE to preserve existing non-null values on re-scrapes    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ enriched=false rows
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Enrichment Pipeline                           │
│  Groq LLM extracts: title, location, remote status, role type,  │
│  pay range, skills tags, and sponsorship from descriptions      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ enriched=true
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      REST API                                   │
│  FastAPI serves read-only queries: /jobs, /company, /search,    │
│  /sponsor                                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
libra/
├── main.py                    # FastAPI app, route definitions, lifespan
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables (not committed)
│
├── Service/
│   ├── db.py                  # Async PostgreSQL connection pool + CRUD helpers
│   └── azalea.py              # Main orchestrator: fetch → dedup → insert → enrich
│
├── JobSource/
│   ├── simplify.py            # Scrapes Simplify's GitHub internship README
│   ├── jsearch.py             # JSearch API integration (OpenWebNinja)
│   └── remote.py              # RemoteOK API integration
│
├── Refine/
│   ├── refine.py              # Enrichment orchestrator: batches unenriched jobs
│   ├── llm.py                 # LLM provider abstraction (GroqProvider)
│   └── extractor.py           # Regex-based pre-processing before LLM
│
├── Utils/
│   ├── models.py              # Dataclasses: Job, Company, JobStats
│   ├── constants.py           # Enums, config classes, env loading, utilities
│   └── notify.py              # Discord webhook notifications
│
├── Tasks/
│   ├── scrape.py              # CLI entry point: runs full scrape + enrich cycle
│   └── enrich.py              # Standalone enrichment task
│
└── Resources/
    └── scraped_jobs.json      # JSON backup written after each scrape run
```

---

## Tech Stack

| Layer | Library | Purpose |
|---|---|---|
| Web framework | FastAPI 0.117 | REST API, routing, middleware |
| ASGI server | uvicorn 0.37 | Serve the FastAPI app |
| Database | asyncpg 0.31 | Async PostgreSQL driver with connection pooling |
| Scraping | BeautifulSoup4, requests | Parse Simplify GitHub README |
| Browser automation | Playwright 1.58 | Extract job descriptions from apply pages |
| LLM enrichment | Groq 1.0 | Structured JSON extraction from descriptions |
| Data processing | pandas 3.0, RapidFuzz 3.14 | Data manipulation, fuzzy deduplication |
| Validation | Pydantic | Request/response models |

---

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL database
- API keys (see Environment Variables below)

### Install

```bash
git clone https://github.com/austindwomoh23/libra.git
cd libra
pip install -r requirements.txt
playwright install chromium   # for job description scraping
```

### Environment Variables

Create a `.env` file in the project root:

```env
# PostgreSQL
DB_HOST=your_db_host
DB_PORT=5432
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password

# Job source APIs
JSearch_API_Key=your_jsearch_api_key

# LLM enrichment
GROQ_API_KEY=your_groq_api_key

# Notifications
DISCORD_WEBHOOK_URL=your_discord_webhook_url

# Optional: alternate enrichment providers
GEMINI_KEY=
GOOGLE_API_KEY=
GOOGLE_CX=
```

### Database

Libra expects two tables in your PostgreSQL database:

```sql
CREATE TABLE company (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    company_url TEXT
);

CREATE TABLE job_list (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    company UUID REFERENCES company(id),
    location TEXT,
    is_remote BOOLEAN,
    description TEXT,
    apply_url TEXT,
    role_type TEXT,
    pay_range JSONB,
    source TEXT,
    tags JSONB DEFAULT '{}',
    enriched BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (title, company, apply_url)
);
```

---

## Running Locally

### Start the API server

```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

The API will be available at `http://localhost:5000`.

### Run a full scrape + enrich cycle

```bash
python Tasks/scrape.py
```

This will:
1. Fetch jobs from all configured sources
2. Deduplicate by (title, company, apply_url)
3. Write a JSON backup to `Resources/scraped_jobs.json`
4. Bulk upsert to the database
5. Run the enrichment pipeline on unenriched rows
6. Send a Discord notification with completion stats

### Run enrichment only

```bash
python Tasks/enrich.py
```

Processes all rows where `enriched = false` in batches of 20.

---

## API Reference

Base URL: `http://libra.austindwomoh.xyz`

All responses follow the shape:

```json
{
  "success": true,
  "params": { ... },
  "jobs": [ ... ]
}
```

---

### `GET /`

Returns API metadata and a list of available endpoints.

**Response:**

```json
{
  "api": {
    "name": "Libra",
    "version": "2.0",
    "description": "Libra - Job Scraping API powered by FastAPI",
    "author": "Austin Dwomoh",
    "base_url": "/"
  },
  "endpoints": {
    "GET /": "API documentation and metadata",
    "GET /jobs": "Retrieve jobs with optional query parameters: limit(?limit=10)",
    "GET /company/{company_name}": "Get jobs by company name with optional limit",
    "GET /search/{keyword}": "Search jobs by keyword in title",
    "GET /sponsor": "Get all jobs with likely sponsorship"
  },
  "notes": [
    "All data is read-only and updated by background scrapers.",
    "Query parameters are case-insensitive where applicable.",
    "Use /docs for interactive Swagger UI and /redoc for ReDoc documentation."
  ]
}
```

---

### `GET /jobs`

Returns all jobs ordered by most recently created.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | No | Maximum number of results to return |

**Example:** `GET /jobs?limit=2`

**Response:**

```json
{
  "success": true,
  "params": { "limit": 2 },
  "jobs": [
    {
      "id": "dcf8edc2-05b4-456c-b24e-b27b9ee20ee8",
      "company": "spectrum control",
      "title": "Engineering Intern/Co-op",
      "location": "Philadelphia, PA",
      "link": "https://spectrumcontrol.wd1.myworkdayjobs.com/...",
      "source": "simplify",
      "remote": false,
      "date_posted": null,
      "description": null,
      "tags": {},
      "created_at": "2026-03-10T11:02:53.371494",
      "updated_at": "2026-03-10T11:02:53.371494"
    }
  ]
}
```

---

### `GET /company/{company_name}`

Returns all jobs from a specific company. Company name must be lowercase.

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `company_name` | string | Lowercase company name (e.g. `walmart`) |

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | No | Maximum number of results to return |

**Example:** `GET /company/walmart?limit=5`

**Response:**

```json
{
  "success": true,
  "params": { "company_name": "walmart", "limit": 5 },
  "jobs": [ ... ]
}
```

---

### `GET /search/{keyword}`

Full-text search across job titles (case-insensitive `LIKE` match).

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `keyword` | string | Search term to match against job titles |

**Example:** `GET /search/software`

**Response:**

```json
{
  "success": true,
  "params": { "keyword": "software" },
  "jobs": [ ... ]
}
```

---

### `GET /sponsor`

Returns jobs tagged with `sponsorship: true` — jobs where the description indicates the company sponsors H-1B visas.

**Example:** `GET /sponsor`

**Response:**

```json
{
  "success": true,
  "params": { "sponsorship": "likely sponsorship" },
  "jobs": [
    {
      "id": "ed0b2104-...",
      "company": "copart",
      "title": "Software Engineering Intern",
      "location": "Dallas, TX",
      "tags": { "sponsorship": "true" },
      ...
    }
  ]
}
```

---

## Key Modules

### `Service/db.py` — Database Layer

`JobDatabase` is a singleton that manages an async PostgreSQL connection pool (min 2, max 10 connections) with SSL support.

Key methods:

| Method | Description |
|---|---|
| `create()` | Class method; initializes the pool |
| `select(table, ...)` | SELECT with optional WHERE, ORDER BY, LIMIT |
| `selectOne(table, ...)` | Returns a single row or None |
| `upsert(table, data, conflict_column)` | INSERT … ON CONFLICT DO UPDATE with COALESCE |
| `bulk_upsert(table, rows, conflict_column)` | Batch version of upsert |
| `delete(table, where)` | DELETE with parameterized WHERE clause |

The `COALESCE` pattern on upsert ensures that re-scraping a job never overwrites enriched fields (like `description` or `pay_range`) with `NULL`.

---

### `Service/azalea.py` — Orchestrator

`Azalea` coordinates the full scrape-to-database cycle:

1. Instantiates all job source helpers
2. Calls each source's fetch method concurrently
3. Deduplicates using a Python `set()` (relies on `Job.__hash__` and `Job.__eq__`)
4. Validates each job (`Job.is_valid()` checks required fields)
5. Bulk upserts to `job_list`
6. Hands off unenriched jobs to the enrichment pipeline
7. Tracks per-source stats and sends a Discord notification

---

### `Refine/llm.py` — LLM Enrichment

`GroqProvider` wraps the Groq API and sends structured prompts asking for JSON output with the following fields extracted from a job description:

- `title` — normalized job title
- `location` — city/state or "Remote"
- `is_remote` — boolean
- `role_type` — "internship", "fulltime", "parttime", "contract"
- `pay_range` — `[min, max]` normalized to annual USD
- `tags` — list of skill keywords
- `sponsorship` — `"true"` / `"false"` / `"unknown"`

---

### `Utils/models.py` — Data Models

**`Job`** — core data class for a job posting:

| Field | Type | Notes |
|---|---|---|
| `title` | str | Required |
| `company` | UUID | Required — references company table |
| `location` | str | Required |
| `apply_url` | str | Required if no description |
| `description` | str | Required if no apply_url |
| `source` | JobSource enum | simplify, jsearch, remoteok |
| `is_remote` | bool | |
| `role_type` | str | |
| `pay_range` | list | `[min, max]` in annual USD |
| `tags` | dict | Arbitrary key-value metadata |

`Job.is_valid()` requires title, company UUID, location, and at least one of apply_url or description.

---

## Error Responses

| Status | Body |
|---|---|
| 404 | `{"success": false, "detail": "Endpoint not found"}` |
| 500 | `{"success": false, "detail": "Internal server error"}` |

---

## Deployment

Libra is deployed via GitHub Actions on push to `master`. The server pulls the latest commit, restarts the uvicorn process, and the background scraping task runs on a schedule.

The API server runs on port 5000 and is proxied through a reverse proxy at `libra.austindwomoh.xyz`.
