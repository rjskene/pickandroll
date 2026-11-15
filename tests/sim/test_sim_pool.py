"""The simulator's pool starts its workers by ``spawn`` on every machine (#172).

Python's default start method is ``spawn`` on macOS and ``fork`` on Linux. On Linux a HiGHS solve
in a forked worker spins for ever when the thread that started the pool has already solved: the
fork copies the solver's record of its threads but not the threads. The simulator's commands run
their first task in the parent and then start the pool, so the pattern is in its code; a fresh
process (``spawn``) cannot inherit it, and the two machines then start their workers alike.
"""

from __future__ import annotations

import multiprocessing
import sys

import pickandroll.sim.run as rn

#: Set in the parent by the test below. A forked worker inherits it; a spawned one imports this
#: module afresh and sees None.
PLANTED: str | None = None


def worker_report(i: int) -> tuple[int, str, str | None]:
    """In a worker: the task's index, the class of the process it runs in (``SpawnProcess``,
    ``ForkProcess`` or ``ForkServerProcess``) and whether the parent's runtime state reached it."""
    return i, type(multiprocessing.current_process()).__name__, PLANTED


def test_the_pool_is_given_a_spawn_context(monkeypatch):
    seen: dict = {}

    class Recorder:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def map(self, fn, *iterables):
            return map(fn, *iterables)

    monkeypatch.setattr(rn, "ProcessPoolExecutor", Recorder)
    assert rn.run_tasks(worker_report, [(0,), (1,)], workers=2) == [
        (0, "_MainProcess", None),
        (1, "_MainProcess", None),
    ]
    ctx = seen.get("mp_context")
    assert ctx is not None, "the pool takes the machine's default start method"
    assert ctx.get_start_method() == "spawn"
    # Nothing else moves: the worker count and the priority as before.
    assert seen["max_workers"] == 2 and seen["initializer"] is rn._lower_priority


def test_a_real_pool_spawns_its_workers_and_keeps_the_tasks_order(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "PLANTED", "parent")
    assert PLANTED == "parent"
    got = rn.run_tasks(worker_report, [(i,) for i in range(6)], workers=2)
    assert [i for i, _, _ in got] == list(range(6))
    assert {kind for _, kind, _ in got} == {"SpawnProcess"}
    assert {seen for _, _, seen in got} == {None}, "a worker inherited the parent's state"


def test_one_worker_runs_the_tasks_in_this_process():
    got = rn.run_tasks(worker_report, [(0,), (1,)], workers=1)
    assert got == [(0, "_MainProcess", None), (1, "_MainProcess", None)]
