# Database Layer

`Service/db.py` — `JobDatabase`, a singleton wrapping an `asyncpg` connection pool (min 2 / max 10, SSL with hostname checking disabled). Each new pool connection now also runs `register_vector()` (`pgvector.asyncpg`) so `vector` columns round-trip as `pgvector.Vector` objects instead of raw strings.

## Schema

```sql
CREATE TABLE company(
     id uuid NOT NULL DEFAULT gen_random_uuid(),
    name varchar(255),
    company_url varchar(255),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP ,
    PRIMARY KEY(id) 
); 
CREATE UNIQUE INDEX company_name_unique ON public.company USING btree (name);
CREATE UNIQUE INDEX company_name_unique_ci ON public.company USING btree (lower((name)::text));

CREATE TABLE job_list(
     id uuid NOT NULL DEFAULT gen_random_uuid(),
    title varchar(1000),
    company uuid,
    location varchar(500),
    is_remote boolean,
    description text,
    apply_url varchar(1000),
    role_type varchar(255),
    pay_range varchar(255),
    "source" varchar(20),
    tags json,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    enriched boolean NOT NULL DEFAULT false,
    enrich_attempts integer DEFAULT 0,
    status text NOT NULL DEFAULT 'active'::text,
    embedding vector,
    summary text ,
    PRIMARY KEY(id) ,
    CONSTRAINT job_list_company_fkey FOREIGN key(company) REFERENCES company(id),
    CONSTRAINT job_company_fkey FOREIGN key(company) REFERENCES company(id) 
); 
CREATE UNIQUE INDEX company_location_title_apply_url_1784051293594_index ON public.job_list USING btree (company, location, title, apply_url);

CREATE TABLE enrichment_examples(
     id uuid NOT NULL DEFAULT gen_random_uuid(),
    raw_description text NOT NULL,
    extracted_json jsonb NOT NULL,
    embedding vector,
    source_job_id uuid,
    verified_by text,
    added_at timestamp with time zone DEFAULT now(),
    demoted boolean DEFAULT false ,
    PRIMARY KEY(id) 
); 
CREATE UNIQUE INDEX uq_source_job ON public.enrichment_examples USING btree (source_job_id);
```

> **None of `enrich_attempts`, `status`, `summary`, `embedding`, or `enrichment_examples` are tracked in a SQL migration anywhere in this repo.** There's still no `migrations/` folder — schema changes have all been manual `ALTER`/`CREATE` statements run directly against the live DB. If you're setting up a fresh DB from just the `CREATE TABLE` block above (or an older README copy of it), you'll need all of the above added by hand. This is now the third+ round of undocumented schema drift found — worth actually starting a `migrations/` folder rather than a running note.
>
> **Possible conflict-target mismatch:** `bulk_upsert`/`upsert` calls in `Service/azalea.py` and `Refine/refine.py` pass `conflict_column=["company", "location", "title", "apply_url"]` (4 columns, including `location`), but the `UNIQUE` constraint above is only `(title, company, apply_url)` (3 columns, no `location`). Postgres requires `ON CONFLICT (...)` to name an existing unique constraint or index exactly — if the live schema really only has the 3-column constraint, these upserts would fail at the DB level rather than silently doing the wrong thing. Worth checking what the live schema actually has (possibly a 4-column unique index was added out-of-band, same as the other undocumented drift above) and reconciling this doc, the code, and the DB.

## `JobDatabase` methods

| Method | Notes |
|---|---|
| `create()` | classmethod, singleton — returns existing instance if pool already built; now also registers the pgvector type on each new connection |
| `select(table, columns, filters, raw_where, raw_params, order_by, limit)` | supports both simple `filters` dict (`col = $n`) and a `raw_where` string for anything more complex (e.g. subqueries, `LIKE`) |
| `selectOne(...)` | thin wrapper, `limit=1` |
| `get_or_create_company(name)` | **new.** Looks up `company` by `lower(name)`; if not found, `upsert`s a new row (`conflict_column="name"`) and returns its id. Added for `Azalea` test mode, where a JSON-backed job may carry a company name instead of a UUID |
| `upsert(table, data, conflict_column)` | single-row insert with `ON CONFLICT ... DO UPDATE` |
| `bulk_upsert(table, rows, conflict_column)` | same but multi-row `VALUES (...), (...), ...` in one query |
| `update(table, data, filters)` | plain `UPDATE ... WHERE ...` |
| `delete(table, filters)` | plain `DELETE ... WHERE ...` |
| `call_function(fn, params, fetch_type)` | calls a Postgres function, `fetch`/`fetchval`/`fetchrow` |
| `raw(sql, params)` | escape hatch for anything the helpers don't cover — used by the expiry checker's bulk status flip and the embedding pass's similarity query |

## Value serialization: `_serialize()` (new)

Previously `upsert`/`bulk_upsert` inlined `json.dumps(v) if isinstance(v, (dict, list)) else v` for every column value. That's now a dedicated `_serialize(v)` method:

- `pgvector.Vector` values pass through untouched — the asyncpg + pgvector driver handles the wire format directly
- `dict`/`list` values go through `json.dumps(v, default=self._json_default)` — the new `_json_default` stringifies `uuid.UUID` and `datetime.date`/`datetime.datetime` objects, so a `tags` or `pay_range` payload that happens to contain one of those no longer raises `TypeError: Object of type UUID is not JSON serializable`
- everything else passes through unchanged

## The COALESCE upsert pattern

`_build_conflict_clause()` is the important bit. Given `conflict_column=["title", "company", "apply_url"]`, it builds:

```sql
ON CONFLICT (title, company, apply_url)
DO UPDATE SET
    location = COALESCE(EXCLUDED.location, job_list.location),
    is_remote = COALESCE(EXCLUDED.is_remote, job_list.is_remote),
    ...
```

This means re-scraping a job that already exists **never nulls out** a field that was previously enriched — a fresh scrape only has `title`/`location`/`apply_url`/`source`, so `description`, `summary`, `pay_range`, etc. would otherwise get wiped to `NULL` on every re-scrape. COALESCE prevents that: only a non-null incoming value overwrites the existing one.

This is also why enrichment can safely run independently of scraping — a scrape never regresses an already-enriched row. The one place this pattern is deliberately *not* used is `_apply_structured_data()` in the enrichment pipeline (see [[Enrichment-Pipeline]]), which overwrites fields in-memory on the `Job` object when a schema.org `JobPosting` block is found — that overwritten value then flows through the normal `upsert()` afterward.