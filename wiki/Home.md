# Libra Wiki

Internal reference for the Libra job-scraping/enrichment pipeline. This is not user-facing docs — it's here so future-me (or anyone else touching this) doesn't have to re-derive the architecture from scratch.

**What Libra does:** pulls job postings from Simplify's GitHub README, the JSearch API, and RemoteOK, dedupes them, stores them in Postgres, runs an LLM enrichment pass (**Ollama**, running `deepseek-r1:8b` locally) to fill in missing fields (pay range, remote status, role type, sponsorship signals, tags), and serves everything read-only through a FastAPI.

**Live API:** `http://libra.austindwomoh.xyz` · Swagger: `/docs`

## Pages

- [[Architecture]] — end-to-end data flow, source → dedupe → DB → enrich → API
- [[Enrichment-Pipeline]] — how `extractor.py` / `llm.py` / `refine.py` fit together, the 3-stage fill logic
- [[Database-Layer]] — schema, `JobDatabase`, the COALESCE upsert pattern
- [[API-Reference]] — every FastAPI route, params, response shape
- [[Deployment-CI-CD]] — GitHub Actions workflows, cron schedule, SSH deploy
- [[Diagrams]] — index of all Mermaid class/sequence diagrams in `docs/diagrams`
- [[Roadmap]] — planned/unfinished work

## Repo map

```
Libra/
├── main.py              # FastAPI app + routes
├── Service/
│   ├── azalea.py        # orchestrator: fetch → dedup → self.jobs → fin_jobs → upsert
│   ├── db.py            # asyncpg pool + CRUD (select/upsert/update/delete)
│   └── Scrapper.py      # Pirate: Playwright/requests scraping, JobPosting JSON-LD, expired detection
├── JobSource/
│   ├── simplify.py       # scrapes Simplify's GitHub README tables
│   ├── jsearch.py        # JSearch (OpenWebNinja) API
│   └── remote.py         # RemoteOK API
├── Refine/
│   ├── extractor.py      # JobEnricher: regex stage + Pirate scrape stage + LLM stage
│   ├── llm.py            # LLMProvider ABC, OllamaProvider, LLMParseError, JSON repair
│   └── refine.py         # enrich_unenriched_jobs() — DB-driven enrichment loop, retry-cap logic
├── Utils/
│   ├── models.py         # Job, Company, JobStats dataclasses
│   ├── constants.py      # Config, enums, LLMConstants (prompt template)
│   ├── sanitate.py       # JobDataSanitizer — cleans/coerces raw LLM JSON
│   └── notify.py         # Discord webhook helper
├── Tasks/
│   ├── scrape.py         # CLI entrypoint: runs Azalea.run()
│   └── enrich.py         # standalone enrich + Discord embed poster
└── docs/diagrams/         # Mermaid class + sequence diagrams, one pair per module
```
