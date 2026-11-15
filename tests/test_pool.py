"""The process pools leave no workers behind (#241): a worker exits once its parent is gone, a
terminating shutdown stops a worker mid-solve, and the API's shutdown closes the pools."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pickandroll.api.app import SessionStore, create_app

SRC = Path(__file__).resolve().parents[1] / "src"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone_within(pid: int, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.2)
    return not alive(pid)


def run(script: str) -> list[int]:
    """Run ``script`` in a fresh interpreter; the worker pids it prints, one a line."""
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    done = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    pids = [int(line) for line in done.stdout.split()]
    assert pids, done.stderr
    return pids


@pytest.mark.parametrize("pool", ["shared_pool(1)", "background_pool()"])
def test_a_worker_exits_once_its_parent_is_killed(pool):
    (pid,) = run(
        f"""
        import os, signal, sys
        from pickandroll.optim.pool import background_pool, shared_pool
        print(({pool}).submit(os.getpid).result(timeout=60), flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
        """
    )
    try:
        assert gone_within(pid, 10)
    finally:
        if alive(pid):
            os.kill(pid, 9)


def test_a_terminating_shutdown_stops_a_worker_mid_solve():
    (pid, after) = run(
        """
        import os, time
        from pickandroll.optim.pool import shared_pool, shutdown_pool
        pool = shared_pool(1)
        pid = pool.submit(os.getpid).result(timeout=60)
        pool.submit(time.sleep, 60)
        time.sleep(0.5)
        shutdown_pool(terminate=True)
        try:
            os.kill(pid, 0)
            after = 1
        except ProcessLookupError:
            after = 0
        print(pid, after, flush=True)
        """
    )
    try:
        assert after == 0
    finally:
        if alive(pid):
            os.kill(pid, 9)


def test_the_api_shutdown_terminates_the_pools(monkeypatch, tmp_path):
    calls: list[bool] = []
    # ``pickandroll.api.app`` the attribute is the package's FastAPI instance, not the module.
    module = sys.modules[create_app.__module__]
    monkeypatch.setattr(module, "shutdown_pool", lambda terminate=False: calls.append(terminate))
    with TestClient(create_app(SessionStore(), data_dir=tmp_path)):
        assert calls == []
    assert calls == [True]


#: A small HiGHS model, solved through PuLP as every solve in the package is. It lives in a
#: module of its own so a spawned worker can import it.
HIGHS_JOB = """
import pulp


def solve():
    model = pulp.LpProblem("knapsack", pulp.LpMaximize)
    xs = [pulp.LpVariable(f"x{i}", cat="Binary") for i in range(40)]
    model += pulp.lpSum((i % 7 + 1) * x for i, x in enumerate(xs))
    model += pulp.lpSum((i % 5 + 2) * x for i, x in enumerate(xs)) <= 40
    model.solve(pulp.HiGHS(msg=False))
    return pulp.LpStatus[model.status]
"""

#: Seconds the whole check may take before it counts as hung (a solve takes milliseconds).
HANG_LIMIT = 90


def test_every_pool_solves_after_the_parent_has_solved_even_where_fork_is_the_default(tmp_path):
    """#385: on Linux a forked worker of a process whose HiGHS already solved in another thread
    spins forever. The check makes ``fork`` the default, as on Linux, solves in a thread of the
    parent, then solves through each pool under a hard time limit."""
    (tmp_path / "highs_job.py").write_text(HIGHS_JOB)
    script = textwrap.dedent(
        """
        import multiprocessing, threading
        multiprocessing.set_start_method("fork", force=True)
        import highs_job
        from pickandroll.optim.pool import background_pool, process_pool, shared_pool
        parent = threading.Thread(target=highs_job.solve)
        parent.start()
        parent.join()
        for name, pool in (
            ("shared", shared_pool(2)),
            ("background", background_pool()),
            ("process", process_pool(2)),
        ):
            method = pool._mp_context.get_start_method()
            print(name, method, pool.submit(highs_job.solve).result(), flush=True)
        """
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC), str(tmp_path)])}
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=HANG_LIMIT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        proc.communicate()
        pytest.fail(f"a pool's solve hung past {HANG_LIMIT} s")
    assert proc.returncode == 0, err
    assert out.split("\n")[:3] == [
        "shared spawn Optimal",
        "background spawn Optimal",
        "process spawn Optimal",
    ]


def test_the_punt_sweep_starts_its_pool_by_spawn(monkeypatch, pool):
    from pickandroll.optim import RosterProblem, roster
    from pickandroll.optim import pool as pools
    from pickandroll.projections import zscores
    from pickandroll.projections.schema import split_positions

    made: list[str] = []
    real = pools.process_pool

    class Spy:
        def __init__(self, workers):
            self.inner = real(workers)
            made.append(self.inner._mp_context.get_start_method())

        def __enter__(self):
            return self.inner.__enter__()

        def __exit__(self, *exc):
            return self.inner.__exit__(*exc)

    monkeypatch.setattr(pools, "process_pool", Spy)
    positions = {pid: split_positions(v) for pid, v in pool["positions"].items()}
    problem = RosterProblem(z=zscores(pool), positions=positions, raw=pool, punt=None, max_punts=1)
    scan = roster.punt_scan(problem, workers=2)
    assert made == ["spawn"]
    assert len(scan.solutions) == len(roster.punt_sets(problem.cats, problem.max_punts))
