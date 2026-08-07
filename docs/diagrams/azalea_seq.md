```mermaid
%% flowchart — _init_helpers (conditional source registration)
flowchart TD
    A[Azalea.__init__ calls _init_helpers] --> B["helpers[SIMPLIFY] = Simplify()<br/>(always registered)"]
    B --> C{J_SEARCH_API_KEY present?}
    C -->|yes| D["helpers[JSEARCH] = JSearch()"]
    C -->|no| E[log warning — JSearch disabled]
    D --> F["Note: _init_helpers() has NO branch for REMOTEOK —<br/>Config.REMOTEOK is never read, no RemoteOKHelper class exists.<br/>helpers[REMOTEOK] is never populated, so every<br/>'REMOTEOK in self.helpers' check elsewhere is always False<br/>and that source is dead code."]
    E --> F
```

```mermaid
%% flowchart — fetch_from_source (route to correct helper)
%% NOTE: position_type is forwarded to JSearch only. For SIMPLIFY (the only other
%% helper actually registered) the case _ branch calls helper.fetch_jobs() with no
%% args, dropping position_type. REMOTEOK is included for completeness but never
%% reaches this point in practice — see _init_helpers diagram above.
flowchart TD
    A[fetch_all_sources calls fetch_from_source] --> B["helper = helpers.get(source)"]
    B --> C{helper registered?}
    C -->|no| D[log warning — return empty list]
    C -->|yes| E{"source == JSEARCH?"}
    E -->|yes| F["await helper.fetch_jobs(queries, position_type, date_posted)"]
    E -->|no — SIMPLIFY or REMOTEOK| G["await helper.fetch_jobs()<br/>(position_type NOT forwarded)"]
    F --> H{Exception raised?}
    G --> H
    H -->|no| I["stats.increment_source(source, len(jobs)) — return List[Job]"]
    H -->|yes| J["log error, stats.errors++ — return []"]
```

```mermaid
%% flowchart — fetch_all_sources (per-source gating by position type)
flowchart TD
    A[Azalea.run calls fetch_all_sources] --> B{position_type in INTERN/HYBRID?}
    B -->|yes| C["fetch_from_source(SIMPLIFY) → extend all_jobs"]
    B -->|no| D{JSEARCH in helpers?}
    C --> D
    D -->|yes| E["fetch_from_source(JSEARCH, position_type, queries) → extend all_jobs"]
    D -->|no| F{"REMOTEOK in helpers?<br/>(never true in practice — see _init_helpers)"}
    E --> F
    F -->|yes, theoretically| G["fetch_from_source(REMOTEOK, position_type) → extend all_jobs"]
    F -->|no, always in practice| H["stats.total_fetched = len(all_jobs)"]
    G --> H
    H --> I[return all_jobs to Azalea.run]
```

```mermaid
%% flowchart — run() PRODUCTION mode (test=False): fetch → dedup → JSON → DB
%% Enrichment does NOT happen here by design — see Tasks/enrich.py /
%% the separate GitHub Actions "enrich" job instead.
flowchart TD
    A["Tasks/scrape.py calls run(position_type, save_json, jsearch_queries, test=False)"] --> B[await fetch_all_sources]
    B --> C{any jobs returned?}
    C -->|no| Z1[early return — stats.to_dict]
    C -->|yes| D["filter None → set() dedup → is_valid() filter<br/>self.jobs = unique_jobs (single source of truth from here on)"]
    D --> E{save_json=True?}
    E -->|yes| F["Config.save_to_json — Job.to_dict() shape (company as str),<br/>skipping ziprecruiter/bebee/lensa domains. JSON-only, never DB-bound."]
    E -->|no| G["fin_jobs = Job.to_dict_for_db() for jobs with valid title/apply_url,<br/>skipping ziprecruiter/bebee/lensa domains.<br/>(company as UUID, tags normalized — THIS reaches Postgres)"]
    F --> G
    G --> H{fin_jobs empty?}
    H -->|yes| Z2[early return — nothing to insert]
    H -->|no| I["bulk_upsert fin_jobs into job_list<br/>conflict=[company,location,title,apply_url]"]
    I --> J["stats.inserted = len(inserted)"]
    J --> K["Note: enrichment intentionally skipped here —<br/>handled separately by Tasks/enrich.py"]
    K --> L[return stats.to_dict to Entry]
```

```mermaid
%% flowchart — run() TEST mode (test=True): JSON load → self.jobs → DB → enrich
%% Used for iterating on enrichment logic without re-hitting scrape sources.
%% Both modes share the same fin_jobs conversion step (to_dict_for_db).
flowchart TD
    A["Developer calls run(test=True)"] --> B["JobDatabase.create() — moved to top of run(),<br/>before the test/production branch"]
    B --> C["open FilePaths.SCRAPED_JOBS_JSON, json.load()[:10]<br/>(raw dicts, Job.to_dict() shape; cap tightened 20→10)"]
    C --> D{FileNotFoundError or JSONDecodeError?}
    D -->|yes| Z1[early return — stats.to_dict]
    D -->|no| E[loop for each job_dict]
    E --> F{"company_id = UUID(job_dict['company'])<br/>missing/invalid?"}
    F -->|yes| G["get_or_create_company(job_dict.get('company_name', 'Unknown')) → company_id"]
    F -->|no| H["job = Job.from_dict(job_dict, company=company_id)<br/>self.jobs.append(job)"]
    G --> H
    H --> I{more job_dicts?}
    I -->|yes| E
    I -->|no| J["fin_jobs = Job.to_dict_for_db() — SAME conversion +<br/>domain-skip logic as production mode"]
    J --> K{fin_jobs empty?}
    K -->|yes| Z2[early return — stats.to_dict]
    K -->|no| L["bulk_upsert fin_jobs into job_list<br/>conflict=[company,location,title,apply_url]"]
    L --> M["await enrich_unenriched_jobs(batch_size=5)<br/>(tightened from 20 to 5)"]
    M --> N[print_summary]
    N --> O[return stats.to_dict to Dev]
```
