# Libra Wiki

Internal reference for the Libra job-scraping/enrichment pipeline. This is not user-facing docs — it's here so future-me (or anyone else touching this) doesn't have to re-derive the architecture from scratch.

**What Libra does:** pulls job postings from the Simplify and Speedy GitHub READMEs plus the JSearch API, dedupes them, stores them in Postgres, runs an LLM enrichment pass (**Ollama**, running `qwen2.5:3b-instruct` locally) to fill in missing fields (pay range, remote status, role type, description, summary, tags), periodically re-validates active listings for expiry, and serves everything read-only through a FastAPI. A standalone embedding pass also builds a pgvector-backed RAG example bank for future use.

**Live API:** `http://libra.austindwomoh.xyz` · Swagger: `/docs`

## Pages

- [[Architecture]] — end-to-end data flow, source → dedupe → DB → enrich → embed/expire → API
- [[Enrichment-Pipeline]] — how `extractor.py` / `llm.py` / `refine.py` / `Scrapper.py` fit together, the stage-by-stage fill logic
- [[Database-Layer]] — schema, `JobDatabase`, the COALESCE upsert pattern, pgvector
- [[API-Reference]] — every FastAPI route, params, response shape
- [[Workflows]] — every GitHub Actions workflow: triggers, jobs, the 3×/week scrape + weekly expiry cron, secrets
- [[Deployment-CI-CD]] — the droplet layout, venv/systemd, and the self-sufficient deploy script
- [[Diagrams]] — index of all Mermaid class/sequence diagrams in `docs/diagrams`
- [[Roadmap]] — planned/unfinished work, known bugs
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — new-contributor setup, workflow, and PR checklist walkthrough

## Repo map

```
Libra/
├── main.py              # FastAPI app + routes
├── Service/
│   ├── azalea.py         # orchestrator: fetch → dedup → self.jobs → fin_jobs → upsert
│   ├── db.py              # asyncpg pool + CRUD (select/upsert/update/delete), pgvector-aware
│   └── Scrapper.py        # Pirate: Playwright/requests scraping, ScrapeResult, JobPosting JSON-LD, blocked/expired detection
├── JobSource/
│   ├── simplify.py        # scrapes Simplify's GitHub README tables
│   ├── speedy.py           # scrapes Speedy (speedyapply) GitHub README tables
│   ├── jsearch.py         # JSearch (OpenWebNinja) API
│   └── base.py            # shared helper base
├── Refine/
│   ├── extractor.py       # JobEnricher: regex stage + Pirate scrape stage + LLM stage
│   ├── llm.py              # LLMProvider ABC, OllamaProvider, LLMParseError, JSON repair, check_expired()
│   └── refine.py           # enrich_unenriched_jobs() — DB-driven enrichment loop, retry-cap logic
├── Utils/
│   ├── models.py           # Job (now with summary), Company, JobStats dataclasses
│   ├── constants.py        # Config, enums, LLMConstants (prompt template)
│   ├── sanitate.py         # JobDataSanitizer — cleans/coerces raw LLM JSON
│   └── notify.py           # Discord webhook helper
├── Tasks/
│   ├── scrape.py           # CLI entrypoint: runs Azalea.run()
│   ├── enrich.py           # standalone enrich + Discord embed poster
│   ├── expired.py          # ExpiryChecker: weekly tiered re-validation of active jobs
│   └── embeddings.py       # standalone embedding + RAG example-bank promotion pass (new, not yet scheduled)
└── docs/diagrams/          # Mermaid class + sequence diagrams, one pair per module
```