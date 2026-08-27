# API Reference

FastAPI app defined in `main.py`. Base URL: `http://libra.austindwomoh.xyz`. Interactive docs at `/docs` (Swagger) and `/redoc`. All routes are read-only.

Standard response shape:

```json
{ "success": true, "params": { ... }, "jobs": [ ... ] }
```

All job-listing routes below implicitly filter to `enriched = true AND status = 'active'` — unenriched and expired rows never surface through the API.

## `GET /`

Metadata + endpoint list. No params.

## `GET /jobs?limit=N`

All active, enriched jobs, ordered `created_at ASC` (oldest first). `limit` optional.

> Worth double-checking this is intentional — `ASC` on a "browse jobs" endpoint means the oldest matching rows page in first, which is an easy off-by-one direction to get wrong versus a "recent jobs" feed. `/sponsor` below uses `DESC` for the same kind of query, so the two routes are inconsistent with each other if that wasn't deliberate.

## `GET /company/{company_name}?limit=N`

Jobs for one company. `company_name` must be **lowercase** — matched against `company.name` via a subquery (`company = (SELECT id FROM company WHERE name = $1)`), not a join. Also ordered `created_at ASC`.

## `GET /search/{keyword}`

Case-insensitive `LIKE` match on `title` only (not `description` or `summary`). Ordered `created_at ASC`. No `limit` param currently exposed on this route — a common keyword could return the entire active, enriched table.

## `GET /sponsor`

Jobs where `tags->>'sponsorship' = 'True'`, ordered `created_at DESC`. This is an LLM-assigned tag (see `_LLM_PROMPT` in [[Enrichment-Pipeline]]) — the prompt now asks for a `sponsorship: true | false | null` key alongside `experience_years`, `requirements`, `preferred`, `skills`, `technologies`, `certifications`. `JobDataSanitizer._normalise_tags()` stringifies non-string tag values via Python's `str(v)`, so a `sponsorship: true` from the LLM ends up stored in `tags` as the literal string `"True"` (capital T) — which is exactly what this route's filter now matches, deliberately. So the route is wired up end-to-end, assuming the LLM reliably emits the key; it's just a string-equality check riding on `str(bool)`'s exact capitalization rather than an explicit cast or `LOWER()`, which is fragile if that stringification behavior ever changes. Not independently verified against live data, hence the disclaimer text in `Config.DISCLAIMER_TEXT`.

## Error responses

| Status | Body |
|---|---|
| 404 | `{"success": false, "detail": "Endpoint not found"}` |
| 500 | `{"success": false, "detail": "Internal server error"}` |

## Gaps / things to remember when extending this

- `/search` has no `limit` — could return everything matching a common keyword
- No pagination anywhere (`limit` only, no offset/cursor)
- No auth — fully open CORS (`allow_origins=["*"]`)
- `company_name` lowercase requirement isn't documented anywhere except this wiki page and the (old) README
- `/jobs` and `/company` order `ASC`, `/sponsor` orders `DESC` — check this is intentional before relying on either
- `/sponsor` now has a real signal to filter on (`tags->>'sponsorship'`, set since issue #18) but the query matches the literal string `'True'`, not a boolean — see [[Roadmap]] for why that's fragile