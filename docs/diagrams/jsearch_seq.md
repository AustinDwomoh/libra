```mermaid
%% flowchart — fetch_jobs (multi-query loop with rate limiting)
flowchart TD
    A["Caller: fetch_jobs(queries, position_type, date_posted, rate_limit_delay)"] --> B["queries = queries or JSearchConfig.DEFAULT_CATEGORIES"]
    B --> C[loop for each query]
    C --> D["await fetch_positions(query, position_type, date_posted)"]
    D --> E["all_jobs.extend(jobs)"]
    E --> F{not last query?}
    F -->|yes| G["await asyncio.sleep(rate_limit_delay)"]
    G --> C
    F -->|no| H["list(set(all_jobs)) — dedup via Job.__hash__/__eq__"]
    H --> I[return unique List[Job] to Caller]
```

```mermaid
%% flowchart — fetch_positions (single page with retry logic)
flowchart TD
    A["_build_search_query(query, position_type)"] --> B["_build_request_params(search_query, ...)"]
    B --> C[loop up to retry_count attempts]
    C --> D["_make_request(params) — GET JSEARCH_API_URL"]
    D --> E{response status?}
    E -->|401 or 403| F["log error, return []"]
    E -->|429 rate limited| G["sleep (attempt+1) × RATE_LIMIT_WAIT_MULTIPLIER, continue"]
    E -->|2xx success| H["_process_response → _save_raw_jobs → await _map_jobs → return List[Job]"]
    E -->|RequestException| I{attempts remain?}
    I -->|yes| J["sleep RETRY_DELAY, continue"]
    I -->|no, exhausted| K["return []"]
    G --> C
    J --> C
    C -->|all attempts exhausted| L["log 'all retries failed', return []"]
```

```mermaid
%% flowchart — _map_job (single raw dict → Job)
flowchart TD
    A["JobSourceBase._map_jobs calls await _map_job(raw_job dict)"] --> B["_upsert_company(employer_name, employer_website)"]
    B --> C["upsert/selectOne company → company dict"]
    C --> D["employment_types = job['job_employment_types']"]
    D --> E["_get_position_type(employment_types)<br/>(INTERN+FULLTIME→HYBRID, else singular or OTHER)"]
    E --> F["_extract_salary(job) — [min, max] if both present, else None"]
    F --> G[build refined_job dict]
    G --> H["_make_job(refined_job, company)"]
    H --> I[return Job to Base]
```
