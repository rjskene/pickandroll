"""One process pool for every parallel solve in the process.

Candidate pricing, scenario solves and league simulations each fan out independent solver
calls. Spawning a fresh pool per call costs about a second on macOS (every worker re-imports
the package), which is most of a small pricing round, so the pool is created once and reused.
Callers that need to run in-process pass ``workers=1`` and never touch it.
"""

from __future__ import annotations

import atexit
import os
from concurrent.futures import ProcessPoolExecutor

_POOL: ProcessPoolExecutor | None = None
_SIZE: int | None = None


def shared_pool(workers: int | None = None) -> ProcessPoolExecutor:
    """The shared pool, sized on first use (``workers`` or all but one core)."""
    global _POOL, _SIZE
    size = workers or max(1, (os.cpu_count() or 2) - 1)
    if _POOL is None or (_SIZE is not None and size > _SIZE):
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = ProcessPoolExecutor(max_workers=size)
        _SIZE = size
    return _POOL


def shutdown_pool() -> None:
    global _POOL, _SIZE
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None
        _SIZE = None


atexit.register(shutdown_pool)
