```mermaid
%% sequenceDiagram — _init_helpers (conditional source registration)
sequenceDiagram
    participant Az as Azalea.__init__
    participant H as helpers dict
    participant Cfg as Config

    Az->>H: helpers[SIMPLIFY] = Simplify()
    Note over H: always registered

    Az->>Cfg: J_SEARCH_API_KEY?
    alt key present
        Az->>H: helpers[JSEARCH] = JSearch()
    else missing
        Az->>Az: log warning — JSearch disabled
    end

    Az->>Cfg: REMOTEOK configured?
    alt configured
        Az->>H: helpers[REMOTEOK] = RemoteOKHelper()
    end


```

```mermaid
%% sequenceDiagram — fetch_from_source (route to correct helper)
%% NOTE: position_type is forwarded to JSearch only. For SIMPLIFY and REMOTEOK
%% the case _ branch calls helper.fetch_jobs() with no args, dropping position_type.
sequenceDiagram
    participant FA as fetch_all_sources
    participant Az as fetch_from_source
    participant JS as JSearch.fetch_jobs
    participant Other as Simplify / RemoteOK .fetch_jobs

    FA->>Az: await fetch_from_source(source, position_type, date_posted, **kwargs)
    Az->>Az: helper = helpers.get(source)

    alt helper not registered
        Az->>Az: log warning
        Az-->>FA: [] (early return)
    end

    try
        alt source == JSEARCH
            Az->>JS: await helper.fetch_jobs(queries, position_type, date_posted)
            JS-->>Az: List[Job]
        else SIMPLIFY or REMOTEOK
            Az->>Other: await helper.fetch_jobs()
            Note over Other: position_type NOT forwarded here
            Other-->>Az: List[Job]
        end
        Az->>Az: stats.increment_source(source, len(jobs))
        Az-->>FA: List[Job]
    catch Exception
        Az->>Az: log error, stats.errors++
        Az-->>FA: []
    end

```

```mermaid
%% sequenceDiagram — fetch_all_sources (per-source gating by position type)
sequenceDiagram
    participant Run as Azalea.run
    participant FA as fetch_all_sources
    participant FFS as fetch_from_source

    Run->>FA: await fetch_all_sources(position_type, jsearch_queries)

    alt position_type in [INTERN, HYBRID]
        FA->>FFS: fetch_from_source(SIMPLIFY)
        FFS-->>FA: simplify_jobs
        FA->>FA: all_jobs.extend(simplify_jobs)
    end

    alt JSEARCH in helpers
        FA->>FFS: fetch_from_source(JSEARCH, position_type, queries)
        FFS-->>FA: jsearch_jobs
        FA->>FA: all_jobs.extend(jsearch_jobs)
    end

    alt REMOTEOK in helpers
        FA->>FFS: fetch_from_source(REMOTEOK, position_type)
        FFS-->>FA: remoteok_jobs
        FA->>FA: all_jobs.extend(remoteok_jobs)
    end

    FA->>FA: stats.total_fetched = len(all_jobs)
    FA-->>Run: all_jobs List[Job]

```

```mermaid
%% sequenceDiagram — run() normal mode (fetch → dedup → JSON → DB)
sequenceDiagram
    participant Entry as Tasks/main
    participant Az as Azalea.run
    participant FA as fetch_all_sources
    participant DB as JobDatabase
    participant Enrich as enrich_unenriched_jobs

    Entry->>Az: await run(position_type, save_json, jsearch_queries, test=False)

    Az->>FA: await fetch_all_sources(position_type, jsearch_queries)
    FA-->>Az: all_jobs

    alt no jobs
        Az-->>Entry: stats.to_dict()
    end

    Az->>Az: filter None → set() dedup → is_valid() filter
    Az->>Az: stats.unique_jobs = len(unique_jobs)

    alt save_json=True
        Az->>Az: Config.save_to_json(unique_jobs)
    end

    Az->>Az: to_dict_for_db() — exclude title="unknown"

    Az->>DB: JobDatabase.create()
    Az->>DB: bulk_upsert(job_list, list_jobs, conflict=[title,company,apply_url])
    DB-->>Az: inserted list
    Az->>Az: stats.inserted = len(inserted)

    Note over Az: Enrich skipped in normal mode (commented out)

    Az-->>Entry: stats.to_dict()

```

```mermaid
%% sequenceDiagram — run() test mode (JSON load → DB → enrich)
sequenceDiagram
    participant Dev as Developer
    participant Az as Azalea.run
    participant FS as FilePaths.SCRAPED_JOBS_JSON
    participant DB as JobDatabase
    participant Enrich as enrich_unenriched_jobs

    Dev->>Az: await run(test=True)

    Az->>FS: open + json.load()[:20]
    alt FileNotFoundError or JSONDecodeError
        Az-->>Dev: stats.to_dict() (early return)
    end

    loop for each job_dict
        Az->>Az: UUID(job_dict["company"])
        Az->>Az: Job.from_dict(job_dict, company=UUID)
        Az->>Az: self.jobs.append(job)
    end

    Az->>DB: JobDatabase.create()
    Az->>DB: bulk_upsert(job_list, list_jobs, conflict=[title,company,apply_url])
    DB-->>Az: inserted

    Az->>Enrich: await enrich_unenriched_jobs(batch_size=20)
    Enrich-->>Az: enrich_stats

    Az->>Az: print_summary()
    Az-->>Dev: stats.to_dict()

```
