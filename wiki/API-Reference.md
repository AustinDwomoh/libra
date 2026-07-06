# API Reference

FastAPI app defined in `main.py`. Base URL: `http://libra.austindwomoh.xyz`. Interactive docs at `/docs` (Swagger) and `/redoc`. All routes are read-only.

Standard response shape:

```json
{ "success": true, "params": { ... }, "jobs": [ ... ] }
```

## `GET /`

Metadata + endpoint list. No params.

## `GET /jobs?limit=N`

All jobs, newest first (`created_at DESC`). `limit` optional.

## `GET /company/{company_name}?limit=N`

Jobs for one company. `company_name` must be **lowercase** — matched against `company.name` via a subquery (`company = (SELECT id FROM company WHERE name = $1)`), not a join.

## `GET /search/{keyword}`

Case-insensitive `LIKE` match on `title` only (not description). No `limit` param currently exposed on this route.

## `GET /sponsor`

Jobs where `tags->>'sponsorship' = 'true'`. This is an LLM-assigned tag (see `_LLM_PROMPT` in [[Enrichment-Pipeline]]) — not independently verified, hence the disclaimer text in `Config.DISCLAIMER_TEXT`.

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
