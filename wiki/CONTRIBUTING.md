# Contributing to Libra

This doc is meant to provide everything a new
contributor needs to go from "cloned the repo" to "opened a PR" without pinging
anyone on Discord first.

If something here is wrong or missing, that's a bug in this doc — open a PR against
it, same as code.

---

## Before you start

Read these two first, in order:

1. [`wiki/Home.md`](./wiki/Home.md) — what Libra does and the repo map
2. [`wiki/Architecture.md`](./wiki/Architecture.md) — end-to-end data flow

Then skim [`wiki/Roadmap.md`](./wiki/Roadmap.md). It lists active bugs and known gaps —
worth five minutes so you don't spend an hour rediscovering one of them.

---

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL database (local or remote)
- [Ollama](https://ollama.com) installed locally, with the model pulled:
  ```bash
  ollama pull qwen2.5:3b-instruct
  ```
- API keys — you'll need a `JSearch_API_Key` at minimum (ask in Discord if you don't
  have one yet; there's no self-serve signup documented here)

### Install

```bash
git clone https://github.com/Tempest150/libra.git
cd libra
python -m venv venv
installer.ps1 (Run this on your device)
```

### Environment variables

Create a `.env` file in the project root:

```env
# PostgreSQL
DB_HOST=your_db_host
DB_PORT=5432
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password

# Job source APIs
JSearch_API_Key=your_jsearch_api_key

# Notifications
DISCORD_WEBHOOK_URL= Can be any as its used for notifications


```

### Database

Run the `CREATE TABLE` statements in the README's [Database section](./README.md#database)
against your Postgres instance.


### Verify it runs

```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

Then hit `http://localhost:5000/docs` — you should see the Swagger UI. If it loads,
your DB connection and env vars are working.

```bash
python Tasks/scrape.py    # full scrape + enrich cycle
python Tasks/enrich.py    # enrichment only, processes rows where enriched=false
```

The enrich task needs Ollama running locally (`ollama serve`, or it may already be
running as a service depending on your install).

---

## Where to start

If you don't already have something specific to fix, [`wiki/Roadmap.md`](./wiki/Roadmap.md)
is the best source of real, scoped work — it's a live list of active bugs and known
gaps rather than a wishlist. A few standing entry points as of this writing:

- No automated test suite exists yet


The [`potential/`](./potential/) folder also holds half-built ideas Austin has been
workshopping — worth a look, but check with him before picking one up since they're
not necessarily scoped yet.

---

## Making a change

1. Branch off `master`.
2. Make your change.
3. Open a PR into `master` — **PRs are required**, `master` is protected.
4. Fill out the PR template checklist (`.github/PULL_REQUEST_TEMPLATE.md`). It's
   enforced by the `PR Checklist` GitHub Action, and it's scoped to what you actually
   touched — you won't need to check boxes for parts of the codebase you didn't change.

A few things the checklist will ask about, worth knowing going in:

- **If you touch `JobSource/`, `Service/azalea.py`, `Refine/`, or `Utils/sanitate.py`:**
  the matching Mermaid diagrams in `docs/diagrams/` need regenerating, and any wiki
  page describing that flow (`Architecture.md`, `Roadmap.md`, etc.) needs a pass too.
  This has already caused stale diagrams/wiki content multiple times (once when
  `extractor.py` became `JobEnricher`, once when `azalea.py`'s method names changed,
  once when a new `JobSource/speedy.py` shipped with no matching wiki update). Adding
  a new `JobSource` subclass needs a new diagram pair, not just a code review pass.
- **If you touch anything covered by the wiki:** update the actual `wiki/*.md` page,
  not just the diagrams. `wiki/Home.md` especially is easy to forget since it doesn't
  get touched by most module-level changes.
- **If you change the DB schema:** update both `wiki/Database-Layer.md` and the
  README's schema block — see the note above about why.
- **Before merging:** actually run the code path you touched. An import succeeding
  isn't the same as the logic being correct.

### Wiki editing

Don't edit pages directly in the GitHub Wiki UI — edit the markdown files under
[`wiki/`](./wiki/) in this repo. A GitHub Actions workflow (`wiki-sync.yaml`) mirrors
that folder into the GitHub Wiki automatically on push to `master`, so the repo copy
is the source of truth and stays version-controlled and reviewable like any other change.

### Diagrams

If you add or edit a Mermaid diagram, validate that it actually parses before opening
the PR — GitHub's renderer fails silently and just shows a parse error box instead of
the diagram. Process diagrams (anything that used to be a sequence diagram) should be
`flowchart TD`, not `sequenceDiagram` — that's the repo-wide convention now.

---

## Getting help

Join the [Discord](https://discord.gg/Uuy5BwxGzU) — that's where day-to-day
discussion happens. If you get stuck on setup and this doc doesn't cover it, ask
there, and consider opening a PR to add what you learned here for the next person.
