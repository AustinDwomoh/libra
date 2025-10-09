<!--
Docify-style README for Libra
This file is structured for readability and easy consumption by static doc generators.
-->

# Libra

> Job scraping and sponsorship detection API

<p align="center">
  <img src="./logo.svg" alt="Libra logo" width="240" />
</p>

---

## Overview

Libra is a small FastAPI-based service that exposes scraped internship/job listings and tags them with likely H1-B sponsorship data. The project contains scrapers, a lightweight DB layer, and a read-only REST API for querying results.

This README is written in a Docify-friendly layout and includes a quickstart, API reference, and a detailed file-explanation section.

---

## Quickstart (development)

1. Create/activate a Python virtual environment (or use the included `libra/` venv):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create a `.env` file in the repository root with your DB settings (example below).

4. Run the API (development mode with auto-reload):

```powershell
python main.py
```

Open interactive docs:
- Swagger UI: `http://localhost:5000/docs`
- ReDoc: `http://localhost:5000/redoc`

---

## Environment example (.env)

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=libra
DB_USER=postgres
DB_PASSWORD=secret
```

---

## API Reference (examples)

Base URL: `http://localhost:5000`

### GET /
Returns API metadata and available endpoints.

Response (200):

```json
{
  "api": {"name": "Libra", "version": "1.0"},
  "endpoints": {"GET /jobs": "Retrieve jobs"}
}
```

### GET /jobs
Query parameters:
- `company` (optional): case-insensitive partial match on company name
- `sponsorship` (optional): exact match on sponsorship field
- `limit` (optional): integer limit on returned rows

Example:
`GET /jobs?company=google&limit=10`

Response (200):

```json
{
  "success": true,
  "count": 2,
  "jobs": [
    {"id": "...", "company": "Google", "title": "SWE Intern", "source": "jsearch", "sponsorship": "Likely sponsorship"}
  ]
}
```

### GET /jobs/company/{company_name}
Return jobs filtered by company name (exact match path param). Example:
`GET /jobs/company/Google`

### GET /jobs/search/{keyword}
Full-text-ish search across title and company.

### GET /jobs/sponsor
Return jobs that are likely to offer sponsorship.

---

## File-by-file explanation

This section explains the purpose of each top-level file and important modules. Use this as a quick code map.

- `main.py` — FastAPI application entrypoint.
  - Defines endpoints: `/`, `/jobs`, `/jobs/company/{company_name}`, `/jobs/search/{keyword}`, `/jobs/sponsor`.
  - Configures CORS and exception handlers.
  - Contains a small `run()` helper that uses `uvicorn.run("main:app", ...)` for dev reload.

- `requirements.txt` — pinned Python dependencies. Install with `pip install -r requirements.txt`.

- `logo.svg` — project logo referenced by this README.

- `libra/` — virtual environment directory (if present). It contains Python interpreter and installed packages. You can either use it or create your own venv.

- `services/` — core service modules:
  - `services/db_manager.py` — `JobDatabase` context manager. Handles connection, queries, and helper read methods used by API endpoints.
  - `services/azalea.py` — scraping logic (fetches README from external repo, parses tables via BeautifulSoup, extracts job rows).
  - `services/assist.py` or `services/sponsor.py` — sponsorship matching logic (loads Employer CSVs and uses fuzzy matching to tag jobs).
  - `services/jsearch.py`, `services/simplify.py` — auxiliary scrapers / parsers for different sources.

- `resources/` — static assets and DB schema:
  - `schema.sql` — SQL to create `jobs` table and triggers for timestamps.
  - `Employer_info.csv` — H1-B employer dataset (used for sponsorship matching).

- `cache/` — local cached scraper outputs (such as `scraped_jobs.json`) to speed up development.

---

## How the pieces work together (flow)

1. Scrapers in `services/` fetch remote README/table sources and extract job rows.
2. Extracted rows are cleaned and passed to `services/assist.py` (sponsorship matcher) which returns a `sponsorship` tag per job.
3. Jobs are stored (or read) by `services/db_manager.JobDatabase` into a PostgreSQL `jobs` table.
4. `main.py` exposes the read-only API endpoints that query `JobDatabase` and return JSON responses.

---

## Troubleshooting & notes

- If you see the uvicorn reload warning, ensure `uvicorn.run` is called with an import string: `uvicorn.run("main:app", reload=True)`.
- If `psycopg2` is missing, install via `pip install psycopg2-binary` (or `psycopg2` if you prefer compiled wheel).
- Use `.env` or environment variables to configure DB connection; do not commit secrets.

---

## Contributing

Small notes on developing locally:
- Use the `cache/` JSON files to avoid re-scraping during development.
- Run unit tests (if present) with `pytest`.

---

Generated: 2025-10-09
