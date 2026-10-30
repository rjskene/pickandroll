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
