```mermaid
%% flowchart — enrich_unenriched_jobs() batch loop
flowchart TD
    A["Tasks/enrich.py calls enrich_unenriched_jobs(batch_size=20)"] --> B["select(job_list, filters={enriched: False, status: active}, limit=20, order_by=created_at DESC)"]
    B --> C["open tqdm(total=len(rows)); start 1s background refresh thread"]
    C --> D[loop each row]
    D --> E["_needs_enrichment(row)"]
    E --> F{nothing actually missing?}
    F -->|yes| G["update(enriched=True) — stats.skipped += 1"]
    F -->|no, needs enrichment| H["_row_to_job(row) — normalizes tags if stored as a JSON string"]
    H --> I["new JobEnricher(provider, use_llm)"]
    I --> J["enrich_job(job)"]
    J --> K{outcome?}
    K -->|success| L["upsert(job_list, payload with enriched=True) — stats.enriched += 1"]
    K -->|LLMParseError raised| M["attempts = row.enrich_attempts + 1"]
    M --> N{attempts >= MAX_ENRICH_ATTEMPTS (3)?}
    N -->|yes| O["update(enriched=True, enrich_attempts=attempts) — stats.gave_up += 1"]
    N -->|no, under cap| P["update(enrich_attempts=attempts) — row stays enriched=False, retried next run"]
    K -->|other Exception, network/DB| Q["stats.errors += 1 — row left enriched=False"]
    G --> R["update progress bar (enriched/skipped/errors/gave_up)"]
    L --> R
    O --> R
    P --> R
    Q --> R
    R --> S["sleep(llm_delay) if use_llm and not last row"]
    S --> T{more rows?}
    T -->|yes| D
    T -->|no| U["Note: unlike the previous version, this loop no longer calls<br/>maybe_promote_to_example_bank() — that pass now runs<br/>independently via Tasks/embeddings.py"]
    U --> V["return {attempted, enriched, skipped, errors, gave_up} to Task"]
```
