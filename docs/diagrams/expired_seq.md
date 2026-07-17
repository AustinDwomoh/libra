```mermaid
%% sequenceDiagram — ExpiryChecker.run() orchestration
sequenceDiagram
    participant Task as Tasks/expired.py (__main__) / weekly cron
    participant Run as ExpiryChecker.run
    participant DB as JobDatabase
    participant Check as _check_one (per job)
    participant Bar as tqdm progress bar

    Task->>Run: run(db)
    Run->>DB: select(job_list, filters={status: active})
    DB-->>Run: jobs
    Run->>Bar: open tqdm(total=len(jobs)); start 1s background refresh thread

    par for each job (as_completed)
        Run->>Check: _check_one(session, job)
        Check-->>Run: (job_id, is_expired | None)
        Run->>Bar: update(1), set_postfix(t1/t2/t3/blocked)
    end

    Run->>Run: collect newly_expired_ids where is_expired is True
    alt any newly expired
        Run->>DB: raw("UPDATE job_list SET status='expired' WHERE id = ANY($1)", [newly_expired_ids])
    end

    Run-->>Task: metrics {checked, newly_expired, failed, blocked, resolved_tier1/2/3}
```

```mermaid
%% sequenceDiagram — _check_one() tiered escalation for a single job
sequenceDiagram
    participant Run as ExpiryChecker.run
    participant C1 as _cheap_check (tier 1, http_semaphore)
    participant C2 as _deep_check (tiers 2/3, heavy_semaphore)
    participant P as Pirate
    participant LLM as OllamaProvider.check_expired

    Run->>C1: _cheap_check(session, apply_url)
    C1->>C1: HEAD request → DEAD_STATUS_CODES / redirect-looks-expired?
    alt confident from HEAD
        C1-->>Run: True/False
    else inconclusive, fall through to GET
        C1->>C1: GET request, read first GET_BYTE_LIMIT bytes
        alt SPA_ONLY_DOMAINS
            C1-->>Run: None (escalate — raw HTML is an empty JS shell)
        else classify_scraped_text(visible_text)
            C1-->>Run: True (expired) / False (ok) / None (garbage → escalate)
        end
    end

    alt tier 1 resolved (not None)
        Note over Run: resolved_tier1 += 1
    else tier 1 inconclusive
        Run->>C2: _deep_check(apply_url)
        C2->>P: scrape_apply_url(apply_url)
        P-->>C2: ScrapeResult | dict (structured or blocked) | None

        alt result is None
            C2-->>Run: None (failed)
        else dict with blocked=True
            C2-->>Run: None
            Note over C2: metrics.blocked += 1 — NOT treated as expired
        else dict with job_expired True/False
            C2-->>Run: True/False
            Note over C2: metrics.resolved_tier2 += 1
        else ScrapeResult
            C2->>P: classify_scraped_text(scraped.raw_text)
            alt "expired"
                C2-->>Run: True (resolved_tier2 += 1)
            else "garbage"
                C2-->>Run: None
            else "ok"
                C2->>LLM: check_expired(scraped.raw_text)
                alt model gives clear verdict
                    LLM-->>C2: True/False
                    C2-->>Run: True/False (resolved_tier3 += 1)
                else no clear verdict
                    LLM-->>C2: None
                    C2-->>Run: None
                end
            end
        end
    end
```
