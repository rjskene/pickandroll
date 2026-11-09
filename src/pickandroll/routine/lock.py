"""The browser profile's lock (#355): one routine at a time on ``data/routine/profile``. Every
routine takes it when its browser launches and gives it back when the browser closes; the
process ending gives it back too (``flock``), so a crash never leaves it held. A run that cannot
have it within its wait is told who holds it."""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .clock import CENTRAL

#: How often a waiting run tries the lock again.
POLL_S = 5.0


class BrowserBusy(RuntimeError):
    """The lock stayed held past the run's wait; the message names the holder."""


class BrowserLock:
    def __init__(
        self,
        path: Path,
        holder: str,
        wait_s: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = Path(path)
        self.holder = holder
        self.wait_s = max(0.0, wait_s)
        self.sleep = sleep
        self.clock = clock
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        """Take the lock, trying every :data:`POLL_S` until the wait is over; then
        :class:`BrowserBusy` with the holder's line."""
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = self.clock() + self.wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if self.clock() >= deadline:
                    who = self._read(fd)
                    os.close(fd)
                    raise BrowserBusy(
                        f"the browser profile is in use by {who or 'another run'}"
                        f" (waited {round(self.wait_s)} s)"
                    ) from None
                self.sleep(min(POLL_S, max(0.01, deadline - self.clock())))
        os.ftruncate(fd, 0)
        line = f"{self.holder}, pid {os.getpid()}, since {datetime.now(CENTRAL):%H:%M:%S}"
        os.pwrite(fd, line.encode(), 0)
        self._fd = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    @staticmethod
    def _read(fd: int) -> str:
        try:
            return os.pread(fd, 200, 0).decode(errors="replace").strip()
        except OSError:
            return ""
