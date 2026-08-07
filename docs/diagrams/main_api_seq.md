```mermaid
%% flowchart — FastAPI lifespan: startup and shutdown
%% NOTE: file named main_flask_seq.md for historical reasons — this is FastAPI, not Flask
flowchart TD
    A["uvicorn: startup (lifespan context enters)"] --> B["await JobDatabase.create()<br/>(creates singleton asyncpg pool, min=2, max=10)"]
    B --> C["app.state.db = db"]
    C --> D["yield — ready to serve requests"]
    D --> E["uvicorn: shutdown signal (lifespan context exits)"]
    E --> F["await app.state.db.pool.close()<br/>(singleton _instance still set — pool is closed)"]
```

```mermaid
%% flowchart — GET /jobs (all jobs, optional limit)
flowchart TD
    A["Client: GET /jobs?limit=N"] --> B["db.select('job_list', filters={enriched: True, status: 'active'}, order_by='created_at ASC', limit=N)"]
    B --> C["PostgreSQL: SELECT * FROM job_list WHERE enriched=true AND status='active' ORDER BY created_at ASC LIMIT N"]
    C --> D[rows returned]
    D --> E["response: {success: true, params: {limit}, jobs: [...]}<br/>Note: order_by is ASC (oldest first), not DESC —<br/>worth confirming this is intentional for a 'recent jobs' feed."]
```

```mermaid
%% flowchart — GET /company/{company_name} (jobs by company)
flowchart TD
    A["Client: GET /company/google?limit=N"] --> B["db.select('job_list', raw_where='company = (SELECT id FROM company WHERE name = $1) AND enriched=true AND status=\'active\'', raw_params=['google'], order_by='created_at ASC')"]
    B --> C["PostgreSQL: subquery + filters, LIMIT N"]
    C --> D[rows returned]
    D --> E["response: {success: true, params: {company_name, limit}, jobs: [...]}"]
```

```mermaid
%% flowchart — GET /search/{keyword} (title keyword search)
flowchart TD
    A["Client: GET /search/python"] --> B["keyword.lower() → 'python'"]
    B --> C["db.select('job_list', raw_where=\"lower(title) LIKE $1 AND enriched=true AND status='active'\", raw_params=['%python%'], order_by='created_at ASC')"]
    C --> D["PostgreSQL: LIKE query, NO LIMIT applied"]
    D --> E[rows returned]
    E --> F["response: {success: true, params: {keyword}, jobs: [...]}<br/>Note: no limit param on this route — a common keyword<br/>could return the entire active, enriched table."]
```

```mermaid
%% flowchart — GET /sponsor (sponsorship tag filter)
%% BUG: tags->>'sponsorship' is never set by the enrichment pipeline.
%% The LLM prompt populates skill_0..N and experience_years, not a sponsorship key.
%% This endpoint will always return an empty list until the enrichment tags schema is updated.
flowchart TD
    A["Client: GET /sponsor"] --> B["db.select('job_list', raw_where=\"tags->>'sponsorship' = 'true' AND enriched=true AND status='active'\", order_by='created_at DESC')"]
    B --> C["PostgreSQL executes query"]
    C --> D["rows — currently ALWAYS empty (no enricher sets this key)"]
    D --> E["response: {success: true, params: {sponsorship: 'likely sponsorship'}, jobs: []}"]
```

```mermaid
%% flowchart — error handlers (404 / 500)
flowchart TD
    A[Client request] --> B{route matches?}
    B -->|unknown route| C["GET /nonexistent → 404 {success: false, detail: 'Endpoint not found'}"]
    B -->|known route, handler throws| D["unhandled exception → 500 {success: false, detail: 'Internal server error'}"]
```
