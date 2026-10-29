"""What the browser steps need of a browser (PR 2 implements it with Playwright and the
extension loaded; this build has none). A routine with no browser skips those steps and says
so, as the Desktop routines did when Chrome was away."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Browser(Protocol):
    def available(self) -> bool: ...

    def signed_in(self, site: str) -> bool:
        """``site`` is ``"bbm"`` or ``"yahoo"``; read-only."""
        ...

    def export(self, kind: str) -> Path | None:
        """Make one Basketball Monster export (``report.EXPORT_KINDS``) and give its file."""
        ...

    def open(self, url: str, wait_s: float) -> str:
        """Open ``url`` in the routine's own tab, wait, and give the URL the tab is on."""
        ...

    def close(self) -> None: ...


NO_BROWSER = "no browser in this build: the browser steps land in PR 2 of #225"
