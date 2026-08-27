# Diagrams

Mermaid class + sequence diagrams for most modules live in the main repo under [`docs/diagrams`](https://github.com/AustinDwomoh/Libra/tree/master/docs/diagrams).

| Module | Class diagram | Sequence diagram |
|---|---|---|
| `Service/azalea.py` | [azalea_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/azalea_class.md) | [azalea_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/azalea_seq.md) |
| `Service/db.py` | [db_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/db_class.md) | [db_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/db_seq.md) |
| `Service/Scrapper.py` (`Pirate`) | [scrapper_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/scrapper_class.md) | [scrapper_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/scrapper_seq.md) |
| `JobSource/base.py` | [base_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/base_class.md) | [base_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/base_seq.md) |
| `JobSource/simplify.py` | [simplify_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/simplify_class.md) | [simplify_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/simplify_seq.md) |
| `JobSource/speedy.py` | [speedy_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/speedy_class.md) **(new)** | [speedy_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/speedy_seq.md) **(new)** |
| `JobSource/jsearch.py` | [jsearch_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/jsearch_class.md) | [jsearch_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/jsearch_seq.md) |
| `Refine/extractor.py` (`JobEnricher`) | [extractor_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/extractor_class.md) | [extractor_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/extractor_seq.md) |
| `Refine/llm.py` (`OllamaProvider`) | [llm_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/llm_class.md) | [llm_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/llm_seq.md) |
| `Refine/refine.py` | [refine_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/refine_class.md) | [refine_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/refine_seq.md) |
| `Utils/models.py` | [models_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/models_class.md) | — |
| `Utils/constants.py` | [constants_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/constants_class.md) | — |
| `Utils/sanitate.py` (`JobDataSanitizer`) | [sanitate_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/sanitate_class.md) | — |
| `Tasks/scrape.py` | — | [scrape_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/scrape_seq.md) |
| `Tasks/enrich.py` | — | [enrich_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/enrich_seq.md) |
| `Tasks/expired.py` (`ExpiryChecker`) | [expired_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/expired_class.md) **(new)** | [expired_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/expired_seq.md) **(new)** |
| `Tasks/embeddings.py` | [embeddings_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/embeddings_class.md) **(new)** | [embeddings_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/embeddings_seq.md) **(new)** |
| `main.py` (API routes) | — | [main_api_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/main_api_seq.md) |

## What changed in this pass

Follow-up pass, catching up on everything merged/edited since the previous regeneration below (`aa49fdc` → current), which touched `JobSource/simplify.py`, `JobSource/jsearch.py`, `Refine/extractor.py`, `Refine/llm.py`, `Refine/refine.py`, `Service/azalea.py`, `Utils/constants.py`, `main.py`, and added the new `JobSource/speedy.py`:

- **`speedy_class.md` / `speedy_seq.md`** — new. `JobSource/speedy.py` adds a `Speedy` source (speedyapply/2027-SWE-College-Jobs), always registered alongside Simplify. Parses a Markdown README (via the `markdown` package, not in `requirements.txt` — see [[Roadmap]]) into HTML, then reuses Simplify's BeautifulSoup table-parsing approach with a different column layout. Also flagged: the scraped salary column is a plain string, but `Job.from_dict()` only converts `salary_range` into `pay_range` when it's already a 2-element tuple/list — so Speedy's salary text is silently dropped today.
- **`base_class.md`** — added `JobSourceBase <|-- Speedy`.
- **`azalea_class.md` / `azalea_seq.md`** — added `Speedy`/`SPEEDY` throughout; `fetch_all_sources()` rewritten to build an explicit `sources_to_run` list under a `tqdm` bar instead of three separate if-blocks; dedup (Step 2) no longer goes through `list(set(...))` — it filters `is_valid()` first, then walks results in scrape order building a seen-set by hand; `bulk_upsert` is now hard-capped to `fin_jobs[:10]` in both modes (`#TODO: Remove the 10 limit` in source) — flagged as an active bug, see [[Roadmap]].
- **`constants_class.md`** — `Config.DEFAULT_URL` moved to `SimplifyConfig.DEFAULT_URL` (and the target repo bumped `Summer2026`→`Summer2027`); new `SpeedyConfig` class; new `FilePaths.LAST_RUN`; the LLM prompt's `tags` schema gained a `sponsorship: true|false|null` key (issue #18).
- **`models_class.md`** — `JobSource` enum gained `SPEEDY`.
- **`main_api_seq.md`** — `/sponsor` updated: it's no longer guaranteed-empty. The tags schema now includes `sponsorship`, and `main.py`'s filter was changed to match `str(True)`'s capitalization (`tags->>'sponsorship' = 'True'`, not `'true'`) — still a fragile string match, but no longer dead. See [[Roadmap]].
- **`scrape_seq.md`** — entry-point note updated to reflect Simplify+Speedy always registering.

### Previous pass

Regenerated to catch up with everything merged since the last sync (`d6fa990` → current `master`), which touched `Refine/extractor.py`, `Refine/refine.py`, `Service/Scrapper.py`, `Service/azalea.py`, `Service/db.py`, `Tasks/expired.py`, `Utils/constants.py`, `Utils/models.py`, `Utils/notify.py`, `Utils/sanitate.py`, and added the new `Tasks/embeddings.py`:

- **`extractor_class.md` / `extractor_seq.md`** — `Pirate.scrape_apply_url()` now returns a `ScrapeResult` dataclass instead of a bare `str`; `description` is filled directly from scraped text rather than by the LLM; the LLM now returns a separate `summary` + `description_looks_valid`; noted that `_run_scrape()` doesn't distinguish a blocked-scrape dict from a structured-data dict.
- **`scrapper_class.md` / `scrapper_seq.md`** — new `ScrapeResult` dataclass, `BLOCKED_STATUS_CODES` (403/429) handling, `_trim_to_description()` window-narrowing, `_trim_trailing_cookie_banner()` fallback.
- **`refine_class.md` / `refine_seq.md`** — `tqdm` progress bar + background refresh thread around the batch loop; RAG example-bank promotion moved out to `Tasks/embeddings.py`; flagged the new `from the import get_job_by_id` broken import.
- **`db_class.md` / `db_seq.md`** — new `get_or_create_company()` method, `_serialize()`/`_json_default()` replacing the inline `json.dumps` check, pgvector `Vector` type registration on pool connections.
- **`sanitate_class.md`** — new `_normalise_description_valid()` step; removed the now-defunct `_MAX_TAGS` cap.
- **`models_class.md`** — added the new `summary` field, updated the hash/eq note.
- **`constants_class.md`** — logging now also writes to `logs/run.log`; `is_missing()` covers more stringified-empty cases; prompt schema notes (`summary`/`description_looks_valid` replacing `description`, `_MAX_TAGS` removed).
- **`azalea_class.md` / `azalea_seq.md`** — test-mode JSON cap tightened to 10 jobs; new `get_or_create_company()` fallback; `domains_to_ignore` grew to include `bebee`/`lensa`; test-mode enrichment batch size tightened to 5.
- **`main_api_seq.md`** — corrected `/jobs`, `/company`, and `/search` to their actual `ORDER BY created_at ASC` (the diagram previously said `DESC` for all four routes; only `/sponsor` is actually `DESC`), and added the `enriched=true AND status='active'` filters that were missing from all four.
- **`expired_class.md` / `expired_seq.md`** — new. `Tasks/expired.py::ExpiryChecker` had no diagram at all before this pass, despite predating most of the other recent changes.
- **`embeddings_class.md` / `embeddings_seq.md`** — new, for the brand-new `Tasks/embeddings.py`.

## Higher-level diagrams (kept in the wiki, not per-module)

[[Architecture]] has the full pipeline flowchart and the enrichment-stack tree; [[Enrichment-Pipeline]] has the `JobEnricher.enrich_job()` decision flow reflecting the current `ScrapeResult`/structured/blocked branching.

## Keeping these in sync

If a module's class shape changes meaningfully, regenerate its diagram pair rather than hand-editing — hand-edits drift silently.