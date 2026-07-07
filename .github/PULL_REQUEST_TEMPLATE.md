## What does this PR change?

<!-- One or two sentences. What's the actual behavior change? -->

## Checklist

### If you touched `Refine/`, `Service/Scrapper.py`, or `Utils/sanitate.py`
- [ ] Regenerated the matching `docs/diagrams/*_class.md` and `*_seq.md` for any changed class/function — don't leave them describing the old shape (this has happened twice: once when `extractor.py` became `JobEnricher`, once when `azalea.py`'s `list_jobs`/`fin_jobs` changed)
- [ ] If a class holds mutable state built in `__init__` (like `JobEnricher.meta`), confirm callers create a fresh instance per unit of work, not one shared instance reused across a loop
- [ ] If you added/changed a field the LLM can return, updated `LLMConstants._LLM_PROMPT` **and** the matching sanitizer method in `Utils/sanitate.py`

### If you touched `Service/azalea.py` or anything in the scrape → DB path
- [ ] Confirmed `Job.to_dict()` (JSON backup shape) and `Job.to_dict_for_db()` (Postgres shape) aren't mixed up — anything reaching `bulk_upsert`/`upsert` should go through `to_dict_for_db()`
- [ ] If you added a new mode/branch (like `test=True`), confirmed it converges on the same DB-insert step as the normal path, rather than duplicating (and potentially diverging from) it

### If you changed the DB schema (new column, changed type, etc.)
- [ ] Added the `ALTER TABLE`/`CREATE TABLE` change to `wiki/Database-Layer.md` and the README's schema block — this repo has no `migrations/` folder, so these two places are the only record of what a fresh DB needs (this bit us with `enrich_attempts`)

### If you changed anything covered by the wiki
- [ ] Updated the actual page under `wiki/` (not just the diagrams) — `Home.md` specifically is easy to forget since it doesn't get touched by most module-level changes, but it's the landing page
- [ ] Searched the changed wiki pages for now-wrong terminology (e.g. a provider/library swap leaving stale references to the old one)

### Before merging
- [ ] Ran the actual code path this PR touches, not just read it — an import succeeding isn't the same as the logic being correct (e.g. the `azalea.py` test-mode bug didn't crash, it just silently inserted the wrong data shape)
- [ ] If you added a Mermaid diagram or edited one, validated the syntax actually parses (GitHub's renderer will silently show a parse error otherwise) — Mermaid sequence diagrams don't support `try`/`catch`; use `alt`/`else` instead