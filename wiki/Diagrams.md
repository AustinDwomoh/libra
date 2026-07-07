# Diagrams

Mermaid class + sequence diagrams for most modules live in the main repo under [`docs/diagrams`](https://github.com/AustinDwomoh/Libra/tree/master/docs/diagrams).

| Module | Class diagram | Sequence diagram |
|---|---|---|
| `Service/azalea.py` | [azalea_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/azalea_class.md) | [azalea_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/azalea_seq.md) |
| `Service/db.py` | [db_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/db_class.md) | [db_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/db_seq.md) |
| `Service/Scrapper.py` (`Pirate`) | [scrapper_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/scrapper_class.md) | [scrapper_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/scrapper_seq.md) |
| `JobSource/base.py` | [base_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/base_class.md) | [base_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/base_seq.md) |
| `JobSource/simplify.py` | [simplify_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/simplify_class.md) | [simplify_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/simplify_seq.md) |
| `JobSource/jsearch.py` | [jsearch_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/jsearch_class.md) | [jsearch_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/jsearch_seq.md) |
| `JobSource/remote.py` | [remote_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/remote_class.md) | [remote_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/remote_seq.md) |
| `Refine/extractor.py` (`JobEnricher`) | [extractor_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/extractor_class.md) | [extractor_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/extractor_seq.md) |
| `Refine/llm.py` (`OllamaProvider`) | [llm_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/llm_class.md) | [llm_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/llm_seq.md) |
| `Refine/refine.py` | [refine_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/refine_class.md) | [refine_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/refine_seq.md) |
| `Utils/models.py` | [models_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/models_class.md) | — |
| `Utils/constants.py` | [constants_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/constants_class.md) | — |
| `Utils/sanitate.py` (`JobDataSanitizer`) | [sanitate_class.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/sanitate_class.md) | — |
| `Tasks/scrape.py` | — | [scrape_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/scrape_seq.md) |
| `Tasks/enrich.py` | — | [enrich_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/enrich_seq.md) |
| `main.py` (API routes) | — | [main_api_seq.md](https://github.com/AustinDwomoh/Libra/blob/master/docs/diagrams/main_api_seq.md) |

All diagrams above are current as of the `testing-ollama-deepseek` merge (`JobEnricher`, `Pirate`, `JobDataSanitizer`, `OllamaProvider`, `LLMParseError`). `extractor_class.md`, `extractor_seq.md`, `llm_class.md`, `llm_seq.md`, `refine_class.md`, and `refine_seq.md` were regenerated to replace stale versions describing the old function-based `extractor.py` and Groq-only `llm.py`. `scrapper_class.md`, `scrapper_seq.md`, and `sanitate_class.md` are new additions for modules that previously had no diagram at all.

## Higher-level diagrams (kept in the wiki, not per-module)

[[Architecture]] has the full pipeline flowchart and the enrichment-stack tree; [[Enrichment-Pipeline]] has the `JobEnricher.enrich_job()` decision flow reflecting the current structured-data/expired/garbage branching.

## Keeping these in sync

If a module's class shape changes meaningfully, regenerate its diagram pair rather than hand-editing — hand-edits drift silently, as happened here.
