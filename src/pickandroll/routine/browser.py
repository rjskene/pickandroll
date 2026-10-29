"""What the browser steps need of a browser. ``ChromiumBrowser`` (``routine/chromium.py``) is
the real one, Playwright's Chromium with the pickandroll extension loaded; the tests inject
fakes. A run with ``--no-browser`` has none and skips the browser steps, saying so, as the
Desktop routines did when Chrome was away."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

YAHOO_HOST = "basketball.fantasysports.yahoo.com"
BBM_HOST = "basketballmonster.com"
#: Never opened by a routine: a draft room runs in the user's own Chrome.
DRAFT_CLIENT = "draftclient"


class Browser(Protocol):
    #: Why the last answer was negative: ``available()`` False, or a check page that did not
    #: load. Read after that answer.
    reason: str

    def available(self) -> bool:
        """Launched and ready, the extension's worker up; False with ``reason`` otherwise."""
        ...

    def signed_in(self, site: str) -> bool:
        """``site`` is ``"bbm"`` or ``"yahoo"``; opens that site's check page and nothing else."""
        ...

    def export(self, kind: str) -> Path:
        """Make one Basketball Monster export (``report.EXPORT_KINDS``) and give its file; a
        failed step raises with the reason."""
        ...

    def open(self, url: str, wait_s: float) -> str:
        """Open ``url`` in the routine's own tab, wait, and give the URL the tab is on."""
        ...

    def count(self, selector: str) -> int:
        """How many elements match ``selector`` on the page open now; reads only."""
        ...

    def close(self) -> None: ...


NO_BROWSER = "no browser in this run (--no-browser): the browser steps are skipped"


def refused(url: str) -> str | None:
    """Why ``url`` may not be opened: not a page of Yahoo's fantasy host or Basketball Monster,
    or the draft client. None when it may."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in (YAHOO_HOST, BBM_HOST, f"www.{BBM_HOST}"):
        return f"not a page of {YAHOO_HOST} or {BBM_HOST}: {url}"
    if DRAFT_CLIENT in url.lower():
        return f"a draft client page is never opened by a routine: {url}"
    return None
