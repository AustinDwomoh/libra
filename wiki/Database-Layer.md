# Database Layer

`Service/db.py` — `JobDatabase`, a singleton wrapping an `asyncpg` connection pool (min 2 / max 10, SSL with hostname checking disabled).

## Schema

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

> **`enrich_attempts` is referenced in code (`Refine/refine.py`) but was never added as a tracked SQL migration.** If your live DB predates the retry-cap logic, run `ALTER TABLE job_list ADD COLUMN enrich_attempts INT DEFAULT 0;` manually. There's no migrations folder in this repo — schema changes so far have all been manual `ALTER`/`CREATE` statements run directly against the DB, so it's worth keeping a running note (here, or a `migrations/` folder) of anything applied outside this file.

## `JobDatabase` methods

| Method | Notes |
|---|---|
| `create()` | classmethod, singleton — returns existing instance if pool already built |
| `select(table, columns, filters, raw_where, raw_params, order_by, limit)` | supports both simple `filters` dict (`col = $n`) and a `raw_where` string for anything more complex (e.g. subqueries, `LIKE`) |
| `selectOne(...)` | thin wrapper, `limit=1` |
| `upsert(table, data, conflict_column)` | single-row insert with `ON CONFLICT ... DO UPDATE` |
| `bulk_upsert(table, rows, conflict_column)` | same but multi-row `VALUES (...), (...), ...` in one query |
| `update(table, data, filters)` | plain `UPDATE ... WHERE ...` |
| `delete(table, filters)` | plain `DELETE ... WHERE ...` |
| `call_function(fn, params, fetch_type)` | calls a Postgres function, `fetch`/`fetchval`/`fetchrow` |
| `raw(sql, params)` | escape hatch for anything the helpers don't cover |

Dicts/lists in `data` values are automatically `json.dumps`'d before going to Postgres (for the `tags`/`pay_range` JSONB columns).

## The COALESCE upsert pattern

`_build_conflict_clause()` is the important bit. Given `conflict_column=["title", "company", "apply_url"]`, it builds:

```sql
ON CONFLICT (title, company, apply_url)
DO UPDATE SET
    location = COALESCE(EXCLUDED.location, job_list.location),
    is_remote = COALESCE(EXCLUDED.is_remote, job_list.is_remote),
    ...
```

This means re-scraping a job that already exists **never nulls out** a field that was previously enriched — a fresh scrape only has `title`/`location`/`apply_url`/`source`, so `description`, `pay_range`, etc. would otherwise get wiped to `NULL` on every re-scrape. COALESCE prevents that: only a non-null incoming value overwrites the existing one.

This is also why enrichment can safely run independently of scraping — a scrape never regresses an already-enriched row. The one place this pattern is deliberately *not* used is `_apply_structured_data()` in the enrichment pipeline (see [[Enrichment-Pipeline]]), which overwrites fields in-memory on the `Job` object when a schema.org `JobPosting` block is found — that overwritten value then flows through the normal `upsert()` afterward.
