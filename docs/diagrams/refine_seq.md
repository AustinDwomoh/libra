```mermaid
%% sequenceDiagram — enrich_unenriched_jobs() batch loop
sequenceDiagram
    participant Task as Tasks/enrich.py
    participant Ref as enrich_unenriched_jobs
    participant DB as JobDatabase
    participant JE as JobEnricher (fresh per job)
    participant Bar as tqdm progress bar

    Task->>Ref: enrich_unenriched_jobs(batch_size=20)
    Ref->>DB: select(job_list, filters={enriched: False, status: active}, limit=20, order_by=created_at DESC)
    DB-->>Ref: rows
    Ref->>Bar: open tqdm(total=len(rows)); start 1s background refresh thread

    loop each row
        Ref->>Ref: _needs_enrichment(row)
        alt nothing actually missing
            Ref->>DB: update(enriched=True)
            Note over Ref: stats.skipped += 1
        else needs enrichment
            Ref->>Ref: _row_to_job(row)  — normalizes tags if stored as a JSON string
            Ref->>JE: new JobEnricher(provider, use_llm)
            Ref->>JE: enrich_job(job)

            alt success
                JE-->>Ref: meta
                Ref->>DB: upsert(job_list, payload with enriched=True)
                Note over Ref: stats.enriched += 1, row appended to ENRICHED
            else LLMParseError raised
                JE-->>Ref: raises LLMParseError
                Ref->>Ref: attempts = row.enrich_attempts + 1
                alt attempts >= MAX_ENRICH_ATTEMPTS (3)
                    Ref->>DB: update(enriched=True, enrich_attempts=attempts)
                    Note over Ref: stats.gave_up += 1
                else under cap
                    Ref->>DB: update(enrich_attempts=attempts)
                    Note over Ref: row stays enriched=False, retried next run
                end
            else other Exception (network, DB)
                JE-->>Ref: raises
                Note over Ref: stats.errors += 1, row left enriched=False
            end
        end
        Ref->>Bar: update(1), set_postfix(enriched/skipped/errors/gave_up)
        Ref->>Ref: sleep(llm_delay) if use_llm and not last row
    end

    Note over Ref: Unlike the previous version, this loop no longer\ncalls maybe_promote_to_example_bank() at the end —\nthat pass now runs independently via Tasks/embeddings.py.

    Ref-->>Task: {attempted, enriched, skipped, errors, gave_up}
```