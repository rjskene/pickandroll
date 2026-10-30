"""One process pool for every parallel solve in the process, and a lower-priority one for
speculative solves.

Candidate pricing, scenario solves and league simulations each fan out independent solver
calls. Spawning a fresh pool per call costs about a second on macOS (every worker re-imports
the package), which is most of a small pricing round, so the pool is created once and reused.
Callers that need to run in-process pass ``workers=1`` and never touch it.

Every worker watches its parent and exits once the parent is gone (#241): a killed API or an
interrupted test run would otherwise leave its workers behind with PPID 1, waiting forever on
a queue nobody writes to.
"""

from __future__ import annotations

import atexit
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor

_POOL: ProcessPoolExecutor | None = None
_SIZE: int | None = None
_BACKGROUND: ProcessPoolExecutor | None = None
#: How much lower the background pool's workers run than the process (``os.nice``).
BACKGROUND_NICE = 10
#: Cores the background pool leaves free for the live solve: its plan, the exact prices of
#: my turn (two candidates, the plan's first pick and an installed plan's) and the event loop.
#: A lower priority alone helps only once the cores are contended.
LIVE_CORES = 6
#: Seconds between a worker's looks at its parent.
PARENT_POLL_SECONDS = 1.0


def _exit_with(parent: int) -> None:
    while os.getppid() == parent:
        time.sleep(PARENT_POLL_SECONDS)
    os._exit(0)


def orphan_guard() -> None:
    """Pool initializer: a daemon thread ends the worker once its parent has gone (any signal,
    ``SIGKILL`` included, since the check is the worker's own)."""
    threading.Thread(
        target=_exit_with, args=(os.getppid(),), name="orphan-guard", daemon=True
    ).start()


def shared_pool(workers: int | None = None) -> ProcessPoolExecutor:
    """The shared pool, sized on first use (``workers`` or all but one core)."""
    global _POOL, _SIZE
    size = workers or max(1, (os.cpu_count() or 2) - 1)
    if _POOL is None or (_SIZE is not None and size > _SIZE):
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = ProcessPoolExecutor(max_workers=size, initializer=orphan_guard)
        _SIZE = size
    return _POOL


def _lower_priority() -> None:
    orphan_guard()
    os.nice(BACKGROUND_NICE)


def background_size() -> int:
    """Workers of the background pool: every core but the live solve's (at least one)."""
    return max(1, (os.cpu_count() or 2) - LIVE_CORES)


def background_pool() -> ProcessPoolExecutor:
    """A second pool for speculative solves (the plans of boards that may come), smaller than
    the machine and its workers at a lower CPU priority: work for the board on the table never
    queues behind them in the shared pool, finds ``LIVE_CORES`` cores they do not use, and the
    OS gives it the rest first."""
    global _BACKGROUND
    if _BACKGROUND is None:
        _BACKGROUND = ProcessPoolExecutor(
            max_workers=background_size(), initializer=_lower_priority
        )
    return _BACKGROUND


def _close(pool: ProcessPoolExecutor, terminate: bool) -> None:
    workers = list((getattr(pool, "_processes", None) or {}).values())
    pool.shutdown(wait=False, cancel_futures=True)
    if terminate:
        for proc in workers:
            proc.terminate()
        for proc in workers:
            proc.join(timeout=5)


def shutdown_pool(terminate: bool = False) -> None:
    """Close both pools. ``terminate`` also stops the workers mid-solve and waits for them (the
    API's shutdown, the test session's end); the default lets a running solve finish."""
    global _POOL, _SIZE, _BACKGROUND
    if _POOL is not None:
        _close(_POOL, terminate)
        _POOL = None
        _SIZE = None
    if _BACKGROUND is not None:
        _close(_BACKGROUND, terminate)
        _BACKGROUND = None


atexit.register(shutdown_pool)
