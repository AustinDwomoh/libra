"""Per-run, per-module logging for the Libra backend.

Adapted from the Scales backend logger. Every process start creates its own
folder so runs never overwrite each other -- the API (uvicorn ``--reload``
spawns two processes) and each standalone task (``python Tasks/scrape.py``,
``python Tasks/enrich.py`` ...) all get their own folder:

    logs/run_<YYYYMMDD-HHMMSS>_pid<pid>/
        <module>.log      one file per module that logs (jsearch.log, db.log ...)
        combined.log      every line from every module, interleaved
        flow.log          just the section headers -- a high-level trace of
                          which stage ran, in order, with enter/exit markers

``logs/LATEST_RUN.txt`` always points at the newest run folder.

Terminal vs. files
------------------
The **files** get everything (DEBUG and up). The **terminal** gets only
WARNING/ERROR plus the section enter/exit banners -- so a run's console stays
readable next to the tqdm progress bars. Console lines are written through
``tqdm.write()`` so they never garble an active bar. Raise/lower the console
threshold with ``LIBRA_CONSOLE_LEVEL=INFO`` (DEBUG/INFO/WARNING/ERROR).

Usage
-----
    from Utils.run_logging import get_logger, logged_section

    logger = get_logger(__name__)          # -> logs/<run>/<module>.log
    logger.info("fetched %d jobs", n)

    with logger.section("dedup", n=len(jobs)):   # banner + flow.log enter/exit
        ...

    @logged_section("run")                  # wrap a whole function / coroutine
    async def run(self, ...):
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

# <project root>/logs  (this file lives in <project root>/Utils/)
LOG_ROOT = Path(__file__).resolve().parent.parent / "logs"

_RUN_STARTED = datetime.now()
_RUN_ID = f"run_{_RUN_STARTED:%Y%m%d-%H%M%S}_pid{os.getpid()}"
RUN_DIR = LOG_ROOT / _RUN_ID

_ROOT_NAME = "libra"
_FMT = "%(asctime)s  %(levelname)-7s %(smod)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _console_level() -> int:
    raw = os.getenv("LIBRA_CONSOLE_LEVEL", "WARNING").upper()
    return getattr(logging, raw, logging.WARNING)


# The stage currently in effect (``<module>.<method>``). Cosmetic -- shown in
# section banners and flow.log so you can see what ran before what.
_current_process: ContextVar[str] = ContextVar("libra_process", default="startup")

_loggers: dict[str, "RunLogger"] = {}
_root_ready = False


class _Formatter(logging.Formatter):
    """Formatter that exposes the short module name as ``%(smod)s``."""

    def format(self, record: logging.LogRecord) -> str:
        record.smod = record.name.split(".")[-1]
        return super().format(record)


# --- terminal writer: tqdm-aware so log lines never smash into a progress bar -
try:
    from tqdm import tqdm as _tqdm

    def _term_write(text: str) -> None:
        _tqdm.write(text.rstrip("\n"), file=sys.stdout)

    class _ConsoleHandler(logging.Handler):
        """Console handler that routes through ``tqdm.write``."""

        def emit(self, record: logging.LogRecord) -> None:
            try:
                _tqdm.write(self.format(record), file=sys.stdout)
            except Exception:  # pragma: no cover
                self.handleError(record)

except Exception:  # tqdm missing -- fall back to plain stdout
    def _term_write(text: str) -> None:
        print(text.rstrip("\n"), file=sys.stdout, flush=True)

    class _ConsoleHandler(logging.StreamHandler):  # type: ignore[no-redef]
        def __init__(self) -> None:
            super().__init__(stream=sys.stdout)


def _ensure_root() -> None:
    global _root_ready
    if _root_ready:
        return

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    fmt = _Formatter(_FMT, _DATEFMT)

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.propagate = False

    combined = logging.FileHandler(RUN_DIR / "combined.log", encoding="utf-8")
    combined.setFormatter(fmt)
    combined.setLevel(logging.DEBUG)
    root.addHandler(combined)

    console = _ConsoleHandler()
    console.setFormatter(fmt)
    console.setLevel(_console_level())  # terminal: WARNING+ by default
    root.addHandler(console)

    try:
        (LOG_ROOT / "LATEST_RUN.txt").write_text(
            f"{_RUN_ID}\nstarted {_RUN_STARTED.isoformat()}\n", encoding="utf-8"
        )
    except OSError:
        pass

    _root_ready = True


def _append(path: Path, text: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass


class _Section:
    """Returned by :meth:`RunLogger.section`. Optionally a context manager."""

    def __init__(self, owner: "RunLogger", stage: str, previous: str):
        self._owner = owner
        self._stage = stage
        self._previous = previous

    def __enter__(self) -> "_Section":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        stamp = datetime.now().strftime(_DATEFMT)
        outcome = "ok" if exc_type is None else f"{exc_type.__name__}: {exc}"
        _append(RUN_DIR / "flow.log", f"{stamp}  <<< EXIT  {self._stage}  ({outcome})\n")
        self._owner._file_banner(
            f"{'-' * 78}\n{stamp}  <<< EXIT {self._stage}  ({outcome})\n{'-' * 78}"
        )
        _term_write(f"<<< {self._stage}  ({outcome})")
        _current_process.set(self._previous)


class RunLogger:
    """Thin wrapper over a stdlib logger that owns one per-module file."""

    def __init__(self, name: str):
        _ensure_root()
        self.name = name
        self._log = logging.getLogger(f"{_ROOT_NAME}.{name}")
        self._log.setLevel(logging.DEBUG)
        self._log.propagate = True  # also lands in combined.log + console

        self._file = RUN_DIR / f"{name}.log"
        tag = f"libra:{self._file}"
        if not any(getattr(h, "_libra_tag", None) == tag for h in self._log.handlers):
            fh = logging.FileHandler(self._file, encoding="utf-8")
            fh.setFormatter(_Formatter(_FMT, _DATEFMT))
            fh.setLevel(logging.DEBUG)
            fh._libra_tag = tag  # type: ignore[attr-defined]
            self._log.addHandler(fh)

    # -- level-labelled lines ----------------------------------------------
    def debug(self, msg, *args, **kwargs):
        self._log.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log.error(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._log.exception(msg, *args, **kwargs)

    # aliases kept for stdlib-logger parity
    warn = warning
    fatal = critical = error

    def setLevel(self, *_a, **_k):  # no-op: levels are fixed at DEBUG here
        pass

    # -- banner writer: files only (terminal gets a compact line elsewhere) --
    def _file_banner(self, text: str) -> None:
        block = text if text.endswith("\n") else text + "\n"
        _append(self._file, block)
        _append(RUN_DIR / "combined.log", block)

    # -- section header --------------------------------------------------
    def section(self, label: str, **context) -> _Section:
        """Mark that work has entered ``<this module>.<label>``.

        Drops a full banner into this module's file + combined.log, a compact
        line on the terminal, and enter/exit markers into flow.log. Use
        ``with logger.section(...):`` to also record the exit.
        """
        previous = _current_process.get()
        stage = f"{self.name}.{label}"
        _current_process.set(stage)

        stamp = datetime.now().strftime(_DATEFMT)
        extra = ("  " + " ".join(f"{k}={v}" for k, v in context.items())) if context else ""
        bar = "=" * 78
        self._file_banner(f"{bar}\n{stamp}  >>> {stage}{extra}   (from: {previous})\n{bar}")
        _term_write(f">>> {stage}{extra}")
        _append(RUN_DIR / "flow.log", f"{stamp}  >>> ENTER {stage}{extra}   (from: {previous})\n")
        return _Section(self, stage, previous)


def get_logger(name: str | None = None) -> RunLogger:
    """Return the :class:`RunLogger` for ``name`` (one file per distinct name)."""
    short = (name or "app").split(".")[-1] or "app"
    if short == "__main__":
        short = "app"
    if short not in _loggers:
        _loggers[short] = RunLogger(short)
    return _loggers[short]


def logged_section(label: str | None = None, **static_context):
    """Decorator: wrap a whole function/coroutine in one :meth:`section`.

    The section is opened on the module's own logger, so the banner and
    flow.log markers are attributed to where the function is defined::

        @logged_section("run")
        async def run(self, ...):
            ...
    """

    def decorate(fn):
        name = label or fn.__name__
        log = get_logger(fn.__module__)

        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                with log.section(name, **static_context):
                    return await fn(*args, **kwargs)

            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with log.section(name, **static_context):
                return fn(*args, **kwargs)

        return wrapper

    return decorate


def current_process() -> str:
    return _current_process.get()


def run_dir() -> Path:
    """The folder holding this process's log files."""
    return RUN_DIR


def combined_log() -> Path:
    """Path to this run's ``combined.log`` (handy for notify_discord)."""
    return RUN_DIR / "combined.log"


# Configure immediately so every module shares this run's folder.
_ensure_root()
