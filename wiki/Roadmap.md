# Roadmap / Open Threads

Things planned, half-wired, or recently fixed — worth checking before assuming otherwise.

## Recently fixed

- **`Refine/refine.py` import bug**: it was importing a top-level `enrich_job` function from `Refine/extractor.py` that no longer existed after the `JobEnricher` class refactor (part of the `testing-ollama-deepseek` merge). This broke `enrich_unenriched_jobs()` entirely — an `ImportError` at module load, meaning both `Service/azalea.py`'s enrichment call and `Tasks/enrich.py` would have crashed. Fixed by importing `JobEnricher` and instantiating a fresh instance per job (needed because `JobEnricher.meta` is built once in `__init__` and isn't reset between calls, so reusing one instance across a batch would silently accumulate stats across jobs).

## Database

- `enrich_attempts` column is referenced in `refine.py`'s retry-cap logic but isn't in a tracked SQL migration anywhere in the repo — if a fresh DB is set up from the `CREATE TABLE` statement in the README, this column needs to be added manually. Worth starting a `migrations/` folder or at least a running changelog of manual `ALTER TABLE` statements applied to the live DB, since this is the second undocumented schema drift found.

## Enrichment

- Enrichment is invoked separately from scraping (`Tasks/enrich.py`, once/day via CI) rather than inline in `Azalea.run()` — intentional decoupling to bound Ollama enrichment time and avoid coupling scrape failures to enrichment failures.
- Groq (`GroqProvider` in `llm.py`) is fully commented out in favor of local Ollama (`deepseek-r1:8b`) — kept in the file as a documented, easy swap-back rather than deleted.
- pgvector + `nomic-embed-text` (via Ollama) still planned for RAG-style search over job descriptions — not yet in the schema or code.

## Sources

- `RemoteOKHelper.fetch_jobs()` doesn't filter by `position_type` — RemoteOK's API has no such filter, so everything gets pulled and would need post-filtering by tags. Flagged as a `TODO` in `remote.py`.

## API

- No pagination (`limit` only, no offset/cursor) — will matter once `job_list` grows past a few thousand rows.
- No auth on any route — fine for a read-only public API, worth revisiting if write endpoints are ever added.
- `/search` doesn't support a `limit` param.

## Repo hygiene

- `debug_page.html` (152K) and `logs/enrich.log` appear to be committed debug artifacts rather than intentional repo content. `Config.DEBUG_SCRAPE` in `Pirate.scrape_apply_url` writes to `debug_page.html` when enabled — worth adding both to `.gitignore` so future debug runs don't get committed by accident.
- `docs/diagrams/*.md` had drifted stale relative to the `JobEnricher`/`Pirate`/`JobDataSanitizer` refactor — now regenerated (see [[Diagrams]]), but worth treating diagram regeneration as part of the PR checklist for any change touching `Refine/` or `Service/Scrapper.py` going forward, rather than a follow-up cleanup task.

## Known naming quirk (resolved)

`.github/workflows/scarpe.yaml` (typo for "scrape") has since been renamed to `scrape.yaml`.
