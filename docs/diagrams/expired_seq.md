```mermaid
%% flowchart — ExpiryChecker.run() orchestration
flowchart TD
    A["Tasks/expired.py (__main__) / weekly cron calls run(db)"] --> B["select(job_list, filters={status: active})"]
    B --> C["open tqdm(total=len(jobs)); start 1s background refresh thread"]
    C --> D["for each job in parallel (as_completed): _check_one(session, job)"]
    D --> E["collect (job_id, is_expired | None) → update progress bar (t1/t2/t3/blocked)"]
    E --> F{more jobs?}
    F -->|yes| D
    F -->|no| G["collect newly_expired_ids where is_expired is True"]
    G --> H{any newly expired?}
    H -->|yes| I["raw UPDATE job_list SET status='expired' WHERE id = ANY(newly_expired_ids)"]
    H -->|no| J["return metrics {checked, newly_expired, failed, blocked, resolved_tier1/2/3}"]
    I --> J
```

```mermaid
%% flowchart — _check_one() tiered escalation for a single job
flowchart TD
    A["ExpiryChecker.run calls _cheap_check(session, apply_url) — tier 1<br/>(http_semaphore)"] --> B["HEAD request → DEAD_STATUS_CODES / redirect-looks-expired?"]
    B --> C{confident from HEAD?}
    C -->|yes| D[return True/False]
    C -->|no, inconclusive| E["GET request, read first GET_BYTE_LIMIT bytes"]
    E --> F{in SPA_ONLY_DOMAINS?}
    F -->|yes| G["return None — escalate (raw HTML is an empty JS shell)"]
    F -->|no| H["classify_scraped_text(visible_text)"]
    H --> I{classification?}
    I -->|expired/ok| D
    I -->|garbage| G
    D --> J{tier 1 resolved (not None)?}
    G --> J
    J -->|yes| K["resolved_tier1 += 1"]
    J -->|no, inconclusive| L["_deep_check(apply_url) — tiers 2/3 (heavy_semaphore)"]
    L --> M["Pirate.scrape_apply_url(apply_url)"]
    M --> N{result type?}
    N -->|None| O[return None — failed]
    N -->|"dict, blocked=True"| P["return None — metrics.blocked += 1<br/>(NOT treated as expired)"]
    N -->|"dict, job_expired True/False"| Q["return True/False — metrics.resolved_tier2 += 1"]
    N -->|ScrapeResult| R["classify_scraped_text(scraped.raw_text)"]
    R --> S{classification?}
    S -->|expired| T["return True (resolved_tier2 += 1)"]
    S -->|garbage| U[return None]
    S -->|ok| V["LLM: check_expired(scraped.raw_text)"]
    V --> W{model gives clear verdict?}
    W -->|yes| X["return True/False (resolved_tier3 += 1)"]
    W -->|no| Y[return None]
```
