# Logging

Per-run, per-module logging. Lives in `Utils/run_logging.py`. Replaces the old
setup (`logging.basicConfig` + a single `logs/run.log` file handler that every
process appended to and clobbered).

## What you get

Every **process start** creates its own folder — runs never overwrite each
other, and `uvicorn --reload` (two processes) or two Task scripts running back
to back each get their own:

```
logs/
├── LATEST_RUN.txt                      # run id + ISO start time of the newest run
└── run_<YYYYMMDD-HHMMSS>_pid<pid>/
    ├── app.log                         # anything logged without its own module logger
    ├── azalea.log, jsearch.log, …      # one file per module that logged this run
    ├── combined.log                    # every line from every module, interleaved
    └── flow.log                        # section enter/exit trace — the high-level run map
```

`logs/` is gitignored. Nothing prunes old run folders yet — see [[Roadmap]].

## Using it

```python
from Utils.run_logging import get_logger, logged_section

logger = get_logger(__name__)           # -> logs/<run>/<module>.log  (+ combined.log)

logger.info("fetched %d jobs", n)       # .debug / .info / .warning / .error / .exception
```

`get_logger(name)` keys off the **last** dotted segment, so
`get_logger("JobSource.jsearch")` and `get_logger(__name__)` in that module both
write `jsearch.log`. `__main__` and `None` map to `app`.

`Config.logger` still works — it's `get_logger("app")` now, a back-compat shim so
the ~120 legacy `Config.logger.*` call sites didn't all have to change at once.
New code should use its own module logger. `Config.get_logger` and
`Config.RUN_DIR` are also exposed.

## Sections (the enter/exit logic)

A **section** marks that work entered a named stage. It writes a full banner
into that module's file + `combined.log`, a compact `>>> stage` line on the
terminal, and `ENTER` / `EXIT` markers into `flow.log` with a `(from: …)` back-
pointer to the stage that called it.

```python
with logger.section("dedup", fetched=len(all_jobs)):   # context manager -> records EXIT
    ...

logger.section("serve", port=5010)                      # fire-and-forget -> ENTER only
```

`EXIT` records the outcome: `(ok)` or `(TimeoutError: …)` if the block raised.

`@logged_section("label")` is the decorator form — wraps a whole
function/coroutine, attributed to the module it's **defined** in:

```python
@logged_section("run")
async def run(self, ...):
    ...
```

### Where sections are applied today

| Module | Sections |
|---|---|
| `Service/azalea.py` | `run`, `fetch_all_sources`, `fetch` (per source), `dedup`, `save_to_db`, `enrich`, `summary` |
| `JobSource/{simplify,speedy,jsearch}.py` | `fetch_jobs` |
| `Refine/refine.py` | `enrich_unenriched_jobs` |
| `Tasks/scrape.py` / `Tasks/enrich.py` | `scrape` / `enrich` (task-level wrapper around the call) |
| `Tasks/expired.py` | `run_weekly_expiry_check` |
| `Tasks/embeddings.py` | `embedding_pass` |
| `main.py` | `serve` (spans startup → shutdown) |

A scrape run's `flow.log` ends up as a full trace:

```
>>> ENTER app.scrape  position_type=intern   (from: startup)
>>> ENTER azalea.run  position_type=intern   (from: app.scrape)
>>> ENTER azalea.fetch_all_sources   (from: azalea.run)
>>> ENTER simplify.fetch_jobs   (from: azalea.fetch)
<<< EXIT  simplify.fetch_jobs  (ok)
…
>>> ENTER azalea.dedup  fetched=1109   (from: azalea.run)
<<< EXIT  azalea.dedup  (ok)
>>> ENTER azalea.save_to_db   (from: azalea.run)
<<< EXIT  azalea.save_to_db  (ok)
<<< EXIT  azalea.run  (ok)
```

## Terminal vs. files

| | gets |
|---|---|
| **files** (`combined.log`, `<module>.log`) | everything, DEBUG and up |
| **terminal** (stdout) | `WARNING`/`ERROR` + the section `>>>`/`<<<` banners |

The console handler routes through `tqdm.write()`, so log lines never smash into
an active progress bar. tqdm bars themselves go to **stderr** and are never
captured by the logger — they stay in the terminal only.

Raise the console threshold for a run with an env var:

```bash
LIBRA_CONSOLE_LEVEL=INFO python Tasks/scrape.py    # DEBUG | INFO | WARNING | ERROR
```

## CI / Discord

- `Automations.yaml` exports `TQDM_DISABLE=1` before each task run, so the raw
  `> logs/<task>.log 2>&1` redirect on the droplet (and the file `expired`
  attaches to Discord) has no progress-bar repaint spam.
- `Tasks/scrape.py`, `Tasks/enrich.py`, and `Tasks/embeddings.py` attach **this
  run's `combined.log`** to their Discord notification (`combined_log()` from
  `run_logging`) instead of a fixed path. `expired`'s notification is still built
  by the CI shell wrapper and attaches the raw `logs/expired.log` redirect (so a
  Python crash before the notify step still ships a log).

## Helpers

`current_process()` — the stage currently in effect (`<module>.<label>`).
`run_dir()` — this process's log folder (`Path`).
`combined_log()` — `run_dir() / "combined.log"`.
