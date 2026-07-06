# Diagrams

Full Mermaid class + sequence diagrams for every module live in the main repo under [`docs/diagrams`](https://github.com/AustinDwomoh/Libra/tree/master/docs/diagrams) rather than duplicated here, so they stay in sync with the code instead of drifting in two places.

| Module | Class diagram | Sequence diagram |
|---|---|---|
| `Service/azalea.py` | [azalea_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/azalea_class.md) | [azalea_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/azalea_seq.md) |
| `Service/db.py` | [db_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/db_class.md) | [db_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/db_seq.md) |
| `JobSource/base.py` | [base_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/base_class.md) | [base_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/base_seq.md) |
| `JobSource/simplify.py` | [simplify_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/simplify_class.md) | [simplify_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/simplify_seq.md) |
| `JobSource/jsearch.py` | [jsearch_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/jsearch_class.md) | [jsearch_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/jsearch_seq.md) |
| `JobSource/remote.py` | [remote_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/remote_class.md) | [remote_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/remote_seq.md) |
| `Refine/extractor.py` | [extractor_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/extractor_class.md) | [extractor_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/extractor_seq.md) |
| `Refine/llm.py` | [llm_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/llm_class.md) | [llm_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/llm_seq.md) |
| `Refine/refine.py` | [refine_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/refine_class.md) | [refine_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/refine_seq.md) |
| `Utils/models.py` | [models_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/models_class.md) | — |
| `Utils/constants.py` | [constants_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/constants_class.md) | — |
| `Tasks/scrape.py` | — | [scrape_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/scrape_seq.md) |
| `Tasks/enrich.py` | — | [enrich_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/enrich_seq.md) |
| `main.py` (API routes) | — | [main_api_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/main_api_seq.md) |

## Higher-level diagrams (kept in the wiki, not per-module)

The [[Architecture]] page has the full pipeline flowchart (source → dedupe → DB → enrich → API), and [[Enrichment-Pipeline]] has the 3-stage `enrich_job()` decision flow. These are cross-module views that don't map to a single file, so they live here instead of in `docs/diagrams`.

## Keeping these in sync

If a module's class shape changes meaningfully, regenerate its diagram pair rather than hand-editing — the existing files were likely generated from the source, and hand-edits will drift silently.
