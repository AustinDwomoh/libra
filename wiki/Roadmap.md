# Roadmap / Open Threads

Things planned, half-wired, broken, or recently fixed — worth checking before assuming otherwise.

## 🔴 Active bugs (found during this pass)

- **Production scrape runs only ever save the first 10 jobs.** `Azalea.run()`'s DB-insert step calls `db.bulk_upsert("job_list", fin_jobs[:10], ...)` in both production and test mode, marked `#TODO: Remove the 10 limit` in the source. Every valid job past the first 10 in a given cycle is silently dropped, not deferred — there's no carry-over to the next run. This looks like a debugging leftover rather than an intended throttle; worth removing (or turning into a real config value) before it's mistaken for a scrape yield being genuinely that low.
- **`JobSource/speedy.py` imports the `markdown` package, which isn't in `requirements.txt`.** `speedy.py` does `import markdown` and calls `markdown.markdown(...)` to turn the GFM-Markdown README into HTML before parsing. `requirements.txt` has `markdown-it-py` (a different, unrelated package with no `markdown.markdown()` API) but no `Markdown`/`markdown` entry — a fresh `pip install -r requirements.txt` will leave `JobSource/speedy.py` unable to import, breaking `Service/azalea.py` (which imports `Speedy` unconditionally) and therefore the whole scrape entrypoint.
- **`Speedy`'s scraped salary is silently discarded.** `Speedy._extract_salary()` returns the Salary column as a plain string (e.g. `"$120K - $150K"`), passed through as `refined_job["salary_range"]`. `Job.from_dict()` only converts `salary_range` into `job.pay_range` when it's already a 2-element tuple/list (`isinstance(salary_range, (tuple, list)) and len(salary_range) == 2`); a string fails that check, so `pay_range` ends up `None` regardless of what Speedy scraped. Simplify never had this problem because it never populates `salary_range` at all (`pay_range` is left for the regex/LLM enrichment stages to fill in later) — Speedy is the first source to actually hand over a salary string, and it's currently a no-op. Needs either a parser (`"$120K - $150K"` → `[120000, 150000]`) in `speedy.py` or a string-handling branch in `Job.from_dict()`.
- **`JobEnricher._run_scrape()` doesn't distinguish a blocked scrape from structured data.** `Pirate.scrape_apply_url()` can now return `{"blocked": True, "status_code": 403|429}` as well as the schema.org JobPosting dict — but `_run_scrape()` branches on `isinstance(scraped, dict)` for both and treats a blocked response as an (empty) structured payload. It's a harmless no-op today since the blocked dict has none of the expected keys, but it means a 403/429 currently looks identical to "nothing found" in `meta["stages_run"]`, with no distinct signal. `Tasks/expired.py`'s `_deep_check()` already handles this correctly (checks `scraped.get("blocked")` explicitly, counts it in `metrics["blocked"]`, and returns `None` without treating it as expired) — `extractor.py` could mirror that.
- **Possible upsert conflict-target mismatch.** `azalea.py`/`refine.py` upsert with `conflict_column=["company", "location", "title", "apply_url"]` but the documented schema's `UNIQUE` constraint on `job_list` is only `(title, company, apply_url)`. If the live DB really only has the 3-column constraint, these upserts should be failing outright — worth confirming what's actually deployed. See [[Database-Layer]].

## Recently fixed

- **Logging is now per-run and per-module** (`Utils/run_logging.py`). The old
  `logging.basicConfig` + single append-only `logs/run.log` is gone; each process
  gets its own `logs/run_<ts>_pid<pid>/` folder with per-module files, a
  `combined.log`, and a `section()` `flow.log` trace. `Config.logger` is kept as a
  `get_logger("app")` shim. Terminal output trimmed to warnings/errors + section
  banners (routed through `tqdm.write()`); `LIBRA_CONSOLE_LEVEL` overrides it.
  See [[Logging]].
- **`Tasks/embeddings.py`'s completion notification now sends.** It attached a
  never-written `embedded_jobs.txt`, so `notify_discord()` hit `FileNotFoundError`
  and silently swallowed the whole message. It now attaches the run's
  `combined.log` (`combined_log()`), same as `scrape` / `enrich`.
- **No more progress-bar spam in captured logs.** tqdm writes to stderr and never
  enters the logger, so the per-run files were always clean; `Automations.yaml`
  now also exports `TQDM_DISABLE=1` so the raw `> logs/*.log 2>&1` redirects and
  the file `expired` posts to Discord are clean too.
- **`ExpiryChecker`'s weekly cron now actually fires.** `Automations.yaml` was reworked: `scrape` dropped from 5×/day to 3×/week (Mon/Wed/Fri), the `0 6 * * 6` cron the `expired` job was gated on is now a real entry in `on.schedule` (Sat 06:00 UTC), and its `if` matches it exactly. `enrich` lost its `if: github.event.schedule == '0 5 * * *'` filter and now runs on every scrape via `needs: scrape`. `scrape` gained an `if` so it doesn't also fire on the Sat expiry cron. See [[Workflows]].
- **`deploy.yaml` is now self-sufficient.** `installer.ps1`'s setup logic (manual-install pip packages, `playwright install[-deps]`, Ollama binary + model pulls) was merged into the deploy SSH script, before `systemctl restart libra`. No separate installer run on the server any more; `installer.ps1` is local-dev-only.
- **Enrichment LLM switched** from `deepseek-r1:8b` to `qwen2.5:3b-instruct` (`OllamaProvider` default; `nomic-embed-text` unchanged).

## Recently implemented (previously "planned")

- **pgvector + `nomic-embed-text` RAG pipeline is live**, not just planned. `job_list.embedding` and the new `enrichment_examples` table are written by the new standalone `Tasks/embeddings.py` (`run_embedding_pass()`), decoupled from `enrich_unenriched_jobs()` so a slow first Ollama embedding load never blocks scrape/enrich throughput. It reuses the enrichment's own embedding when deciding whether to promote a job into the example bank, rather than re-embedding. **Not yet wired into any CI schedule** — still needs a cron job in `Automations.yaml` (or its own workflow) to run unattended.
- **Weekly expiry re-validation is implemented** (`Tasks/expired.py::ExpiryChecker`) — a three-tier escalation (cheap HTTP HEAD/GET → Playwright scrape → LLM `check_expired()`) over all `status='active'` jobs, flipping newly-dead ones to `status='expired'` in one bulk `UPDATE`. Its weekly cron (Sat 06:00 UTC) now actually fires — see "Recently fixed" above.

## Database

- `enrich_attempts`, `status`, `summary`, `embedding`, and the `enrichment_examples` table are all referenced in code but not in any tracked SQL migration — same undocumented-drift pattern as before, now larger. Worth actually starting a `migrations/` folder rather than continuing to patch live.

## Enrichment

- Enrichment is invoked separately from scraping (`Tasks/enrich.py`, as its own job after every scrape — 3×/week — via CI) — intentional decoupling to bound Ollama enrichment time and avoid coupling scrape failures to enrichment failures.
- `job.description` is now filled directly from the scraped, trimmed page text rather than LLM-generated — the LLM's job shifted to producing a separate `summary` field plus a `description_looks_valid` sanity signal. Worth watching whether `description` quality/consistency regresses now that it's raw-trimmed text rather than model-normalized prose.

## Sources

- **`Speedy` is a new, real, always-on source** (`JobSource/speedy.py`, `JobSource.SPEEDY`) — scrapes speedyapply's `2027-SWE-College-Jobs` GitHub README (Markdown, not HTML like Simplify) and is registered unconditionally in `Azalea._init_helpers()`, same as Simplify. See the active-bugs entries above for its two rough edges (missing `markdown` dependency, discarded salary column).

## API

- No pagination (`limit` only, no offset/cursor) — will matter once `job_list` grows past a few thousand rows.
- No auth on any route — fine for a read-only public API, worth revisiting if write endpoints are ever added.
- `/search` doesn't support a `limit` param.
- `/jobs` and `/company` order `created_at ASC`; `/sponsor` orders `DESC` — inconsistent, worth checking which is intended.
- **`/sponsor` is no longer necessarily dead**, following issue #18: the LLM `tags` schema now includes a `sponsorship: true | false | null` key, and `main.py`'s filter was updated from `tags->>'sponsorship' = 'true'` to `= 'True'` to match the capitalization `JobDataSanitizer._normalise_tags()` produces when it stringifies a Python bool (`str(True)` → `"True"`). Functionally wired up now, assuming the LLM actually emits the tag — but it's a string comparison riding on `str(bool)`'s exact casing rather than an explicit type cast or `LOWER()` in the query, so it'll silently break dead again if that stringification ever changes.

## Repo hygiene

- **Nothing prunes old `logs/run_*` folders.** Every process start (each Task run,
  each `uvicorn --reload` child) leaves a folder behind. Fine on a dev box, but the
  droplet will accumulate them — needs a `find logs -maxdepth 1 -type d -mtime +N
  -exec rm -rf` step somewhere, or a retention cap in `run_logging.py`.
- **New dependency gap:** `JobSource/speedy.py` imports the `markdown` package but it's absent from `requirements.txt` — see the active-bugs entry above.
- Diagram/wiki regeneration (this pass) covered every module touched since the last full sync (`Refine/`, `Service/Scrapper.py`, `Service/db.py`, `Tasks/expired.py`, `Tasks/embeddings.py`) plus a follow-up pass covering `JobSource/simplify.py` + the new `JobSource/speedy.py`, `Service/azalea.py`, `Utils/constants.py`, `Refine/llm.py`, and `main.py` (the new `Speedy` source, the `fin_jobs[:10]` cap, the `sponsorship` tag). Worth treating diagram/wiki regeneration as part of the PR checklist for any change touching `JobSource/`, `Refine/`, `Service/`, or `Tasks/` going forward, rather than a periodic catch-up pass like this one.