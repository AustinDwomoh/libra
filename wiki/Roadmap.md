# Roadmap / Open Threads

Things planned, half-wired, broken, or recently fixed — worth checking before assuming otherwise.

## 🔴 Active bugs (found during this pass)

- **`ExpiryChecker`'s weekly schedule can never actually fire from its own cron.** `Automations.yaml`'s `expired` job is gated on `github.event.schedule == '0 6 * * 6'`, but that cron string isn't in the workflow's `on.schedule` list (which only has the five scrape times). GitHub Actions only emits a `schedule` event for crons actually listed, so this condition is only ever satisfied by a manual `workflow_dispatch` — the "weekly" expiry check isn't actually running weekly. Needs either the cron added to `on.schedule` or the `if` condition changed to whichever slot it's meant to piggyback on.
- **`Tasks/embeddings.py`'s completion notification silently fails.** `run_embedding_pass()` calls `notify_discord(message=..., file_path="embedded_jobs.txt")`, but nothing in the module ever writes `embedded_jobs.txt`. `notify_discord()` tries to `open()` that path, gets a `FileNotFoundError`, and swallows it into a logged error — so the Discord summary for this pass never actually sends, silently.
- **`JobEnricher._run_scrape()` doesn't distinguish a blocked scrape from structured data.** `Pirate.scrape_apply_url()` can now return `{"blocked": True, "status_code": 403|429}` as well as the schema.org JobPosting dict — but `_run_scrape()` branches on `isinstance(scraped, dict)` for both and treats a blocked response as an (empty) structured payload. It's a harmless no-op today since the blocked dict has none of the expected keys, but it means a 403/429 currently looks identical to "nothing found" in `meta["stages_run"]`, with no distinct signal. `Tasks/expired.py`'s `_deep_check()` already handles this correctly (checks `scraped.get("blocked")` explicitly, counts it in `metrics["blocked"]`, and returns `None` without treating it as expired) — `extractor.py` could mirror that.
- **Possible upsert conflict-target mismatch.** `azalea.py`/`refine.py` upsert with `conflict_column=["company", "location", "title", "apply_url"]` but the documented schema's `UNIQUE` constraint on `job_list` is only `(title, company, apply_url)`. If the live DB really only has the 3-column constraint, these upserts should be failing outright — worth confirming what's actually deployed. See [[Database-Layer]].

## Recently implemented (previously "planned")

- **pgvector + `nomic-embed-text` RAG pipeline is live**, not just planned. `job_list.embedding` and the new `enrichment_examples` table are written by the new standalone `Tasks/embeddings.py` (`run_embedding_pass()`), decoupled from `enrich_unenriched_jobs()` so a slow first Ollama embedding load never blocks scrape/enrich throughput. It reuses the enrichment's own embedding when deciding whether to promote a job into the example bank, rather than re-embedding. **Not yet wired into any CI schedule** — still needs a cron job in `Automations.yaml` (or its own workflow) to run unattended.
- **Weekly expiry re-validation is implemented** (`Tasks/expired.py::ExpiryChecker`) — a three-tier escalation (cheap HTTP HEAD/GET → Playwright scrape → LLM `check_expired()`) over all `status='active'` jobs, flipping newly-dead ones to `status='expired'` in one bulk `UPDATE`. See the bug above about its schedule not actually firing weekly yet.

## Database

- `enrich_attempts`, `status`, `summary`, `embedding`, and the `enrichment_examples` table are all referenced in code but not in any tracked SQL migration — same undocumented-drift pattern as before, now larger. Worth actually starting a `migrations/` folder rather than continuing to patch live.

## Enrichment

- Enrichment is invoked separately from scraping (`Tasks/enrich.py`, once/day via CI) — intentional decoupling to bound Ollama enrichment time and avoid coupling scrape failures to enrichment failures.
- Groq (`GroqProvider` in `llm.py`) is fully commented out in favor of local Ollama (`deepseek-r1:8b`) — kept in the file as a documented, easy swap-back rather than deleted.
- `job.description` is now filled directly from the scraped, trimmed page text rather than LLM-generated — the LLM's job shifted to producing a separate `summary` field plus a `description_looks_valid` sanity signal. Worth watching whether `description` quality/consistency regresses now that it's raw-trimmed text rather than model-normalized prose.

## Sources

- **`RemoteOK` is not implemented at all**, not just gated behind a toggle bug. There is no `JobSource/remote.py` file, no `RemoteOKHelper` class anywhere in the codebase, and `Azalea._init_helpers()` has no branch that would ever register one — `JobSource.REMOTEOK` is a live enum value that every `"REMOTEOK in self.helpers"` check in `Azalea` evaluates as `False`. If RemoteOK is still wanted as a source, it needs to be built from scratch, not just re-enabled.

## API

- No pagination (`limit` only, no offset/cursor) — will matter once `job_list` grows past a few thousand rows.
- No auth on any route — fine for a read-only public API, worth revisiting if write endpoints are ever added.
- `/search` doesn't support a `limit` param.
- `/jobs` and `/company` order `created_at ASC`; `/sponsor` orders `DESC` — inconsistent, worth checking which is intended.
- `/sponsor` is currently dead — no part of the enrichment tags schema sets a `sponsorship` key.

## Repo hygiene

- Diagram/wiki regeneration (this pass) covered every module touched since the last sync (`Refine/`, `Service/Scrapper.py`, `Service/db.py`, `Tasks/expired.py`, the new `Tasks/embeddings.py`) plus a few pre-existing inaccuracies found along the way (RemoteOK, `/jobs` sort order, upsert conflict columns). Worth treating diagram/wiki regeneration as part of the PR checklist for any change touching `Refine/`, `Service/`, or `Tasks/` going forward, rather than a periodic catch-up pass like this one.