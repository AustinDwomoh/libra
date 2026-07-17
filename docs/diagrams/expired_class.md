```mermaid
%% classDiagram — Tasks/expired.py (new diagram — module previously had none)
classDiagram
    class ExpiryChecker {
        +TIMEOUT: ClientTimeout = 8s
        +DEAD_STATUS_CODES: set = {404, 410}
        +GET_BYTE_LIMIT: int = 20000
        +USER_AGENT: str
        +DEFAULT_HTTP_CONCURRENCY: int = 10
        +DEFAULT_HEAVY_CONCURRENCY: int = 2
        +SPA_ONLY_DOMAINS: tuple
        -http_semaphore: Semaphore
        -heavy_semaphore: Semaphore
        -pirate: Pirate
        +use_llm: bool
        +provider: LLMProvider
        +llm_delay: float
        +metrics: dict
        +run(db) dict
        -_is_spa_only_domain(url) bool
        -_redirect_looks_expired(original_url, final_url) bool
        -_visible_text(html) str$
        -_cheap_check(session, url) Optional[bool]
        -_deep_check(apply_url) Optional[bool]
        -_check_one(session, job) tuple
    }

    class Pirate {
        <<Service/Scrapper.py>>
        +scrape_apply_url(url) ScrapeResult|dict|None
        +classify_scraped_text(text) str
    }

    class LLMProvider {
        <<abstract, Refine/llm.py>>
        +extract(job, text) dict
    }

    class JobDatabase {
        <<Service/db.py>>
        +select(...) list~dict~
        +raw(sql, params) list~dict~
    }

    class tqdm {
        <<external: tqdm>>
    }

    ExpiryChecker --> Pirate : tiers 2/3 escalation
    ExpiryChecker --> LLMProvider : tier 3 — expired-signal-only extraction
    ExpiryChecker --> JobDatabase : run() pulls active jobs, flips status='expired' in bulk
    ExpiryChecker --> tqdm : run() progress bar + background 1s refresh thread

    note for ExpiryChecker "Three-tier escalation, cheapest first:\nTier 1 (_cheap_check): plain aiohttp GET, checks\n  DEAD_STATUS_CODES, redirect-looks-expired heuristics,\n  and (for non-SPA domains) visible-text signals.\n  SPA_ONLY_DOMAINS skip straight to tier 2 since a\n  plain GET only returns an empty JS shell for them.\nTier 2/3 (_deep_check): Pirate.scrape_apply_url() —\n  a dict result (structured OR the newer {blocked,\n  status_code} shape) is read via scraped.get('description')\n  either way; a ScrapeResult is classified via\n  classify_scraped_text(scraped.raw_text) then, if still\n  inconclusive, sent to the LLM for an expired-only signal.\n\nrun() now wraps asyncio.gather with asyncio.as_completed\ninside a tqdm progress bar (with a background thread\nticking pbar.refresh() every second) instead of a bare\nawait asyncio.gather(*tasks) — behavior is unchanged,\nonly progress visibility during long runs improved.\nDebug print() calls in _deep_check and _check_one have\nbeen removed in favor of the progress bar's postfix stats."
```
