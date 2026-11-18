"""One process pool for every parallel solve in the process, and a lower-priority one for
speculative solves.

Candidate pricing, scenario solves and league simulations each fan out independent solver
calls. Spawning a fresh pool per call costs about a second on macOS (every worker re-imports
the package), which is most of a small pricing round, so the pool is created once and reused.
Callers that need to run in-process pass ``workers=1`` and never touch it.

Every worker watches its parent and exits once the parent is gone (#241): a killed API or an
interrupted test run would otherwise leave its workers behind with PPID 1, waiting forever on
a queue nobody writes to.

Every pool starts its workers by ``spawn``, on every platform (#385). Linux's default, ``fork``,
copies a process whose HiGHS has already solved in another thread, and a solve in such a worker
never finishes: it spins at full CPU and the pool waits forever. macOS spawns by default, so the
Mac and the droplet now start workers the same way.

Every wait on a pool goes through :func:`completed` (#401): it waits in short slices and stops
once :func:`shutdown_pool` has run. A terminated worker's running future is not always resolved
(the pool's management thread can exit first), and a bare ``as_completed`` then waited forever:
the solver thread never returned and held the stopped API up.
"""

from __future__ import annotations

import atexit
import multiprocessing
import os
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait

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
#: How every pool starts its workers (#385): a fresh interpreter, never a fork of this one.
START_METHOD = "spawn"
#: Seconds a wait on a pool waits before it looks at the stop again (#401).
WAIT_SLICE_SECONDS = 0.5
#: How many times :func:`shutdown_pool` has run: a wait begun before a shutdown stops (#401).
_SHUTDOWNS = 0
_SHUTDOWNS_LOCK = threading.Lock()


class PoolStopped(RuntimeError):
    """The pools were shut down while a caller waited on them (#401)."""


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


def process_pool(
    max_workers: int | None, initializer: Callable[[], None] | None = None
) -> ProcessPoolExecutor:
    """A process pool whose workers start by :data:`START_METHOD` and watch their parent
    (``initializer`` defaults to :func:`orphan_guard`; one passed in should call it too)."""
    return ProcessPoolExecutor(
        max_workers=max_workers,
        mp_context=multiprocessing.get_context(START_METHOD),
        initializer=initializer or orphan_guard,
    )


def shared_pool(workers: int | None = None) -> ProcessPoolExecutor:
    """The shared pool, sized on first use (``workers`` or all but one core)."""
    global _POOL, _SIZE
    size = workers or max(1, (os.cpu_count() or 2) - 1)
    if _POOL is None or (_SIZE is not None and size > _SIZE):
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = process_pool(size)
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
        _BACKGROUND = process_pool(background_size(), initializer=_lower_priority)
    return _BACKGROUND


def completed(futures: Iterable[Future]) -> Iterator[Future]:
    """``as_completed`` that a shutdown ends (#401): each future as it finishes, the wait taken in
    slices of :data:`WAIT_SLICE_SECONDS`. Once :func:`shutdown_pool` has run since the call, the
    futures still waiting are cancelled and :class:`PoolStopped` is raised, so the caller reports
    a failure as for any other; a slice the shutdown landed in yields nothing (#425). Nothing
    else changes: every future comes, as it finishes."""
    return _completed(set(futures), _SHUTDOWNS)


def result(future: Future):
    """One future's result, waited on as :func:`completed` waits: a shutdown ends it (#401)."""
    for done in completed([future]):
        return done.result()
    raise PoolStopped("no future to wait on")  # unreachable: one future always comes


def _completed(pending: set[Future], began: int) -> Iterator[Future]:
    """The shutdowns are checked before each slice and again after it (#425): a terminating
    shutdown inside a slice hands its stopped workers back from it as done futures raising
    ``BrokenProcessPool``. Those are never yielded; the wait raises :class:`PoolStopped`, as
    one begun before the shutdown always does."""
    while pending:
        _stop_if_shut(pending, began)
        done, pending = wait(pending, timeout=WAIT_SLICE_SECONDS, return_when=FIRST_COMPLETED)
        _stop_if_shut(pending, began)
        yield from done


def _stop_if_shut(pending: set[Future], began: int) -> None:
    """Cancel ``pending`` and raise :class:`PoolStopped` once :func:`shutdown_pool` has run
    since ``began``."""
    if _SHUTDOWNS != began:
        for future in pending:
            future.cancel()
        raise PoolStopped(f"the process pools were shut down with {len(pending)} jobs waiting")


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
    API's shutdown, the test session's end); the default lets a running solve finish. Every
    wait on them (:func:`completed`) stops first, so no thread waits on a pool that is gone."""
    global _POOL, _SIZE, _BACKGROUND, _SHUTDOWNS
    with _SHUTDOWNS_LOCK:
        _SHUTDOWNS += 1
    if _POOL is not None:
        _close(_POOL, terminate)
        _POOL = None
        _SIZE = None
    if _BACKGROUND is not None:
        _close(_BACKGROUND, terminate)
        _BACKGROUND = None


atexit.register(shutdown_pool)
