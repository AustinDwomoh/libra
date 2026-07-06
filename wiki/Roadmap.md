# Roadmap / Open Threads

Things planned or half-wired, worth checking before assuming they're done.

## Enrichment

- Enrichment is currently invoked separately from scraping (`Tasks/enrich.py`, once/day via CI) rather than inline in `Azalea.run()` — the inline call is commented out in `azalea.py` pending more confidence in the enrichment path
- `Phi3Provider` stub exists in `llm.py` (commented out) as a fully-offline fallback if Groq's free tier ever becomes a bottleneck
- pgvector + `nomic-embed-text` (via Ollama) planned for RAG-style search over job descriptions — not yet in the schema or code

## Sources

- `RemoteOKHelper.fetch_jobs()` doesn't actually filter by `position_type` — RemoteOK's API has no such filter, so everything gets pulled and would need post-filtering by tags. Flagged as a `TODO` in `remote.py`

## API

- No pagination (`limit` only, no offset/cursor) — will matter once `job_list` grows past a few thousand rows
- No auth on any route — fine for a read-only public API, worth revisiting if write endpoints are ever added
- `/search` doesn't support a `limit` param

## Known naming quirk

`.github/workflows/scarpe.yaml` is a typo for "scrape" — left as-is since renaming doesn't functionally matter, but noted here so it's not mistaken for a missing file when searching.
