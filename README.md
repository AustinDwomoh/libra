# Libra

> Job scraping and enrichment API — v2
> 
> Note: This doesnt fully explain local setup as it assumes all working on it are some contact with the creators
>
> Join our Discord to work with us [link](https://discord.gg/Uuy5BwxGzU)
>
> [![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green.svg)](LICENSE)

<p align="center">
  <img src="./logo.svg" alt="Libra logo" width="240" />
</p>

---

## Overview

Libra aggregates internship and full-time job listings from multiple sources, enriches them with structured data (pay range, remote status, role type, required skills, H-1B sponsorship signal), and serves them through a read-only FastAPI.

**Live API:** `http://libra.austindwomoh.xyz` · **Interactive docs:** `/docs` (Swagger) / `/redoc`
**Wiki:** see [`wiki/`](./wiki/Home.md) for architecture deep-dives, the enrichment pipeline, database schema, and deployment details.

---

## How it works

```
Simplify README + JSearch API + RemoteOK API
                │
                ▼  List[Job]
       Dedup (set() via Job.__hash__/__eq__)
                │
                ▼  valid, unique jobs
   bulk_upsert → job_list (ON CONFLICT + COALESCE)
                │
                ▼  enriched=false rows
        Enrichment pipeline (see below)
                │
                ▼  enriched=true
      FastAPI read-only routes (/jobs, /company, /search, /sponsor)
```

Scraping runs on a cron schedule (5x/day); enrichment runs once/day plus on manual dispatch, so it stays decoupled from scraping and Ollama usage stays bounded.

### Enrichment pipeline

Three stages, each only filling fields still missing (never overwrites existing data):

1. **Regex** (`Refine/extractor.py::RegexConstants`) — pay range, remote status, role type, years-of-experience, all from the description text. Includes anchor-keyword checks so bare number ranges (e.g. "3-5 years") aren't misread as salary.
2. **LLM** (`Refine/llm.py`) — currently **Ollama** running `deepseek-r1:8b` locally (Groq is present in the code but commented out — the project moved to a free/local model). Output is JSON-repaired if malformed (`_try_repair_json`, with an optional `json_repair` library assist) and run through `JobDataSanitizer` (`Utils/sanitate.py`) to coerce types, clamp text lengths, and normalize `role_type`/`is_remote` before touching the DB.
3. **Scrape fallback** (`Service/Scrapper.py::Pirate`) — Playwright-first (falls back to `requests`), checks for a schema.org `JobPosting` JSON-LD block first (treated as authoritative, vendor-supplied ground truth), detects expired/dead listings via known URL patterns and text signals, then re-runs regex/LLM on whatever text it recovered.

Jobs whose LLM output can't be parsed even after repair get `enrich_attempts` incremented and are retried up to `MAX_ENRICH_ATTEMPTS` (3) before being marked enriched anyway, so a persistently bad response doesn't loop forever.

> **Note:** the `enrich_attempts` column referenced in `Refine/refine.py` isn't in the `CREATE TABLE job_list` statement below — add it manually if your DB doesn't have it yet (`ALTER TABLE job_list ADD COLUMN enrich_attempts INT DEFAULT 0;`).

---

## Project structure

```
Libra/
├── main.py                    # FastAPI app, route definitions, lifespan
├── requirements.txt
│
├── Service/
│   ├── db.py                  # Async PostgreSQL pool + CRUD helpers (COALESCE upsert)
│   ├── azalea.py              # Orchestrator: fetch → dedup → insert → (enrich)
│   └── Scrapper.py             # Pirate: Playwright/requests scraping, JobPosting JSON-LD, expired detection
│
├── JobSource/
│   ├── simplify.py            # Scrapes Simplify's GitHub internship README
│   ├── jsearch.py             # JSearch API (OpenWebNinja)
│   └── remote.py              # RemoteOK API
│
├── Refine/
│   ├── refine.py               # enrich_unenriched_jobs() — DB-driven enrichment loop
│   ├── llm.py                  # LLMProvider ABC, OllamaProvider, LLMParseError, JSON repair
│   └── extractor.py            # JobEnricher: regex stage, scrape stage, LLM stage orchestration
│
├── Utils/
│   ├── models.py               # Job, Company, JobStats dataclasses
│   ├── constants.py            # Config, enums, LLMConstants (prompt template)
│   ├── sanitate.py              # JobDataSanitizer — cleans/coerces raw LLM JSON
│   └── notify.py               # Discord webhook helper
│
├── Tasks/
│   ├── scrape.py               # CLI entry point: runs Azalea.run()
│   └── enrich.py               # Standalone enrichment task + Discord job embeds
│
├── docs/diagrams/               # Mermaid class + sequence diagrams (currently stale — see below)
└── wiki/                        # Wiki source, auto-synced to the GitHub Wiki on push to master
```

---

## Tech stack

| Layer | Library | Purpose |
|---|---|---|
| Web framework | FastAPI 0.117 | REST API, routing, middleware |
| ASGI server | uvicorn 0.37 | Serve the FastAPI app |
| Database | asyncpg 0.31 | Async PostgreSQL driver with connection pooling |
| Scraping | BeautifulSoup4, requests | Parse Simplify GitHub README, static fallback scraping |
| Browser automation | Playwright 1.58 | Extract job descriptions from apply pages (Workday, Greenhouse, etc.) |
| LLM enrichment | Ollama (`deepseek-r1:8b`) | Structured JSON extraction from descriptions, runs locally |
| Data processing | pandas 3.0, RapidFuzz 3.14 | Data manipulation, fuzzy deduplication |
| Validation | Pydantic | Request/response models |

---

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL database
- [Ollama](https://ollama.com) installed locally with `deepseek-r1:8b` pulled (`ollama pull deepseek-r1:8b`)
- API keys (see below)

### Install

```bash
git clone https://github.com/AustinDwomoh/Libra.git
cd Libra
pip install -r requirements.txt
playwright install chromium
```

### Environment variables

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

# Notifications
DISCORD_WEBHOOK_URL=your_discord_webhook_url

# Legacy / optional — Groq support is present in code but currently unused
GROQ_API_KEY=
GEMINI_KEY=
```

### Database

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
    enrich_attempts INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (title, company, apply_url)
);
```

---

## Running locally

```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

```bash
python Tasks/scrape.py    # full scrape + enrich cycle
python Tasks/enrich.py    # enrichment only, processes rows where enriched=false
```

---

## API reference

Base URL: `http://libra.austindwomoh.xyz`. Full details in [`wiki/API-Reference.md`](./wiki/API-Reference.md).

| Route | Description |
|---|---|
| `GET /` | API metadata and endpoint list |
| `GET /jobs?limit=N` | All jobs, newest first |
| `GET /company/{company_name}?limit=N` | Jobs by company (lowercase name required) |
| `GET /search/{keyword}` | Case-insensitive title search |
| `GET /sponsor` | Jobs tagged with likely H-1B sponsorship |

---

## Deployment

Three GitHub Actions workflows (`.github/workflows/`): `deploy.yaml` (API deploy on push to `master`), `scrape.yaml` (scrape 5x/day, enrich 1x/day, both via SSH to the DigitalOcean droplet), and `notify.yaml` (Discord notifications on any push/issue activity). A fourth, `wiki-sync.yaml`, mirrors this repo's `wiki/` folder into the GitHub Wiki on push. See [`wiki/Deployment-CI-CD.md`](./wiki/Deployment-CI-CD.md) for the full breakdown.

---

## Known gaps (see [`wiki/Roadmap.md`](./wiki/Roadmap.md) for the full list)

- `enrich_attempts` column isn't in a tracked SQL migration — add manually if missing from your DB.
- No automated test suite yet.
- `master` requires PRs — see `.github/PULL_REQUEST_TEMPLATE.md` for the checklist enforced on every PR via the `PR Checklist` GitHub Action.

---

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE).

You are free to use, modify, and distribute this software. If you deploy a modified version as a network service, you must release your source code under the same license.