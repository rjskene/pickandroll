"""The routine's browser (#225 PR 2): Playwright's bundled Chromium, headed (under Xvfb on the
droplet), one persistent profile with the pickandroll extension loaded unpacked from the
checkout, one tab of its own. The branded Chrome refuses an unpacked extension (Chrome 148),
so it is never that.

The profile (``data/routine/profile``) holds the user's Yahoo and Basketball Monster sessions,
signed in once by the user over VNC through SSH (``docs/OPS.md``); no session ever types a
credential. The profile, the downloads (``data/routine/downloads``) and the failure
screenshots (``data/routine/screens``) live under ``data/`` and are never committed; PR 3's
rsync excludes the profile and the downloads.

What it does on each site is what the Desktop routines' SKILL texts did. On Basketball
Monster: the export pages' selects, set from JavaScript with a change event (the pages
re-render on it), the Refresh button, and one real click on the export button (Chrome silently
blocks a script-triggered download after the first of a session). On Yahoo: opens only. The
page is loaded, the wait passes, the extension acts. Nothing on Yahoo is ever clicked, typed
or read beyond a count of elements.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .browser import BBM_HOST, YAHOO_HOST, refused
from .clock import now
from .report import EXPORT_KINDS
from .steps import PRIVATE_LEAGUE, YAHOO

BBM = f"https://{BBM_HOST}"
#: The sign-in check pages: Basketball Monster's front page (its Logout link), the private
#: league's page (Yahoo sends it to the sign-in when signed out).
BBM_CHECK = f"{BBM}/"
YAHOO_CHECK = f"{YAHOO}/nba/{PRIVATE_LEAGUE}"
#: The extension's background worker must be up before anything opens.
WORKER_WAIT_S = 20.0
GOTO_TIMEOUT_MS = 60_000
DOWNLOAD_TIMEOUT_MS = 60_000
#: A stuck export page may not eat the routine's window.
EXPORT_CEILING_S = 120.0
#: After a select changes (the page re-renders) and after the Refresh button.
SELECT_WAIT_S = 4.0
REFRESH_WAIT_S = 5.0
SCREENS_KEPT = 20
WINDOW = "1440,900"

#: One select per call, no sleep inside: the option by its trimmed text, a bubbling change.
SET_SELECT_JS = (
    "([id, label]) => { const s = document.querySelector('select#' + id);"
    " if (!s) return 'no select#' + id;"
    " const o = Array.prototype.find.call(s.options, o => o.text.trim() === label);"
    " if (!o) return 'no option ' + label + ' in select#' + id;"
    " if (s.value === o.value) return 'same';"
    " s.value = o.value; s.dispatchEvent(new Event('change', {bubbles: true})); return 'set'; }"
)
READ_SELECT_JS = (
    "(id) => { const s = document.querySelector('select#' + id);"
    " return s && s.options[s.selectedIndex] ? s.options[s.selectedIndex].text.trim() : null; }"
)
CLICK_JS = (
    "(sel) => { const el = document.querySelector(sel); if (!el) return false;"
    " el.click(); return true; }"
)
COUNT_JS = "(sel) => document.querySelectorAll(sel).length"
#: A sign-in form, or a Sign in link, where the league should be.
YAHOO_SIGNED_OUT_JS = (
    "() => Boolean(document.querySelector('input#login-username')"
    " || document.querySelector('form[action*=\"login.yahoo.com\"]')"
    " || Array.from(document.querySelectorAll('a'))"
    ".some(a => /^sign in$/i.test((a.textContent || '').trim())))"
)
BBM_LOGOUT = 'a[href*="logout" i]'


@dataclass(frozen=True)
class Recipe:
    """One export: its page, its export button's label and the actions before the refresh,
    ``("select", id, label)`` or ``("click", selector)``, in order."""

    page: str
    button: str
    actions: tuple[tuple[str, ...], ...]


#: The five exports, the SKILL's steps 3a-3d: a select already on its value is confirmed and
#: left alone (the week_next and actual_14d confirmations).
RECIPES: dict[str, Recipe] = {
    "ros": Recipe(
        f"{BBM}/projections.aspx",
        "Export to CSV",
        (
            ("select", "PlayerFilterControl", "All Players"),
            ("select", "StatDisplayType", "Total Stats"),
        ),
    ),
    "week_this": Recipe(
        f"{BBM}/weeklyprojections.aspx",
        "Export to Excel",
        (("click", "[name=RESTWEEK]"), ("select", "PlayerFilterControl", "All Players")),
    ),
    "week_next": Recipe(
        f"{BBM}/weeklyprojections.aspx",
        "Export to Excel",
        (("click", "[name=NEXTWEEK]"), ("select", "PlayerFilterControl", "All Players")),
    ),
    "actual_7d": Recipe(
        f"{BBM}/playerrankings.aspx",
        "Export to Excel",
        (
            ("select", "PlayerFilterControl", "All Players"),
            ("select", "DateFilterControl", "Past 1 Week"),
            ("select", "StatDisplayType", "Total Stats"),
        ),
    ),
    "actual_14d": Recipe(
        f"{BBM}/playerrankings.aspx",
        "Export to Excel",
        (
            ("select", "PlayerFilterControl", "All Players"),
            ("select", "DateFilterControl", "Past 2 Weeks"),
            ("select", "StatDisplayType", "Total Stats"),
        ),
    ),
}
assert set(RECIPES) == set(EXPORT_KINDS)

#: ``launch(profile, extension, headless)`` gives the Playwright driver (``stop()``) and the
#: persistent context; the tests inject a fake.
Launch = Callable[[Path, Path, bool], tuple[Any, Any]]


def playwright_launch(profile: Path, extension: Path, headless: bool) -> tuple[Any, Any]:
    """The real launch: Playwright's Chromium with the extension, the persistent profile, a
    window the extension can act in."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        context = pw.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            accept_downloads=True,
            args=[
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                "--no-first-run",
                f"--window-size={WINDOW}",
            ],
        )
    except Exception:
        pw.stop()
        raise
    return pw, context


class ChromiumBrowser:
    """The ``Browser`` of the routines, launched on the first step that asks."""

    def __init__(
        self,
        profile: Path,
        extension: Path,
        downloads: Path,
        screens: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        launch: Launch = playwright_launch,
        headless: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.profile = Path(profile)
        self.extension = Path(extension)
        self.downloads = Path(downloads)
        self.screens = Path(screens) if screens else self.downloads.parent / "screens"
        self.sleep = sleep
        self.launch = launch
        self.headless = headless
        self.clock = clock
        self.reason = ""
        #: The extension's worker scripts, once up.
        self.workers: list[str] = []
        #: Every URL this run loaded, in order (the run log's evidence).
        self.opened: list[str] = []
        self._pw: Any = None
        self._context: Any = None
        self._page: Any = None
        self._available: bool | None = None
        self._signed: dict[str, bool] = {}

    # ------------------------------------------------------------------ lifecycle
    def available(self) -> bool:
        if self._available is None:
            try:
                self._launch()
                self._available = True
            except Exception as exc:  # noqa: BLE001 - the reason is reported, never raised
                self.reason = one_line(exc)
                self._available = False
                self.close()
        return self._available

    def _launch(self) -> None:
        if not (self.extension / "manifest.json").is_file():
            raise RuntimeError(f"no extension at {self.extension}")
        self.profile.mkdir(parents=True, exist_ok=True)
        self.profile.chmod(0o700)
        empty(self.downloads)
        prune(self.screens, SCREENS_KEPT)
        self._pw, self._context = self.launch(self.profile, self.extension, self.headless)
        pages = list(self._context.pages)
        self._page = pages[0] if pages else self._context.new_page()
        if not list(self._context.service_workers):
            self._context.wait_for_event("serviceworker", timeout=WORKER_WAIT_S * 1000)
        self.workers = [str(w.url).rsplit("/", 1)[-1] for w in self._context.service_workers]
        if not self.workers:
            raise RuntimeError("the extension's service worker did not start")

    def close(self) -> None:
        context, pw = self._context, self._pw
        self._context = self._page = self._pw = None
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        if pw is not None:
            with contextlib.suppress(Exception):
                pw.stop()

    # ------------------------------------------------------------------ the sites
    def signed_in(self, site: str) -> bool:
        if site not in self._signed:
            if site not in ("bbm", "yahoo"):
                raise ValueError(f"unknown site {site!r}")
            if not self.available():
                return False
            try:
                if site == "bbm":
                    self._goto(BBM_CHECK)
                    self._signed[site] = self.count(BBM_LOGOUT) > 0
                else:
                    landed = self._goto(YAHOO_CHECK)
                    host = (urlsplit(landed).hostname or "").lower()
                    signed_out = bool(self._page.evaluate(YAHOO_SIGNED_OUT_JS))
                    self._signed[site] = host == YAHOO_HOST and not signed_out
            except Exception as exc:  # noqa: BLE001 - a check page that did not load
                self.reason = one_line(exc)
                self._signed[site] = False
        return self._signed[site]

    def export(self, kind: str) -> Path:
        recipe = RECIPES[kind]
        if not self.available():
            raise RuntimeError(self.reason)
        deadline = self.clock() + EXPORT_CEILING_S
        try:
            self._goto(recipe.page)
            if self.count(BBM_LOGOUT) == 0:
                raise RuntimeError("signed out of Basketball Monster")
            for action in recipe.actions:
                self._inside(deadline, "before " + " ".join(action))
                if action[0] == "click":
                    if not self._page.evaluate(CLICK_JS, action[1]):
                        raise RuntimeError(f"no {action[1]} on the page")
                    self.sleep(SELECT_WAIT_S)
                else:
                    answer = self._page.evaluate(SET_SELECT_JS, [action[1], action[2]])
                    if answer == "set":
                        self.sleep(SELECT_WAIT_S)
                    elif answer != "same":
                        raise RuntimeError(str(answer))
            for action in recipe.actions:
                if action[0] == "select":
                    got = self._page.evaluate(READ_SELECT_JS, action[1])
                    if got != action[2]:
                        raise RuntimeError(f"select#{action[1]} reads {got!r}, not {action[2]!r}")
            self._inside(deadline, "before the refresh")
            if not self._page.evaluate(CLICK_JS, "#RefreshButton"):
                raise RuntimeError("no #RefreshButton on the page")
            self.sleep(REFRESH_WAIT_S)
            self._inside(deadline, "before the export click")
            with self._page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
                self._page.get_by_role("button", name=recipe.button, exact=True).first.click()
            download = info.value
            suggested = Path(download.suggested_filename or f"{kind}.xls")
            target = self.downloads / f"{suggested.stem}-{now():%H%M%S}{suggested.suffix}"
            download.save_as(str(target))
            if not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError(f"nothing landed at {target.name}")
            return target
        except Exception as exc:
            shot = self._screenshot(kind)
            where = f"; screenshot {shot.name}" if shot else ""
            raise RuntimeError(f"{kind}: {one_line(exc)}{where}") from exc

    def open(self, url: str, wait_s: float) -> str:
        why = refused(url)
        if why:
            raise ValueError(why)
        if not self.available():
            raise RuntimeError(self.reason)
        self._goto(url)
        self.sleep(wait_s)
        return str(self._page.url)

    def count(self, selector: str) -> int:
        return int(self._page.evaluate(COUNT_JS, selector))

    # ------------------------------------------------------------------ helpers
    def _goto(self, url: str) -> str:
        self.opened.append(url)
        self._page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        return str(self._page.url)

    def _inside(self, deadline: float, where: str) -> None:
        if self.clock() > deadline:
            raise RuntimeError(f"past the {EXPORT_CEILING_S:.0f} s ceiling {where}")

    def _screenshot(self, kind: str) -> Path | None:
        try:
            self.screens.mkdir(parents=True, exist_ok=True)
            shot = self.screens / f"{kind}-{now():%Y%m%d-%H%M%S}.png"
            self._page.screenshot(path=str(shot), full_page=True)
            return shot
        except Exception:  # noqa: BLE001 - the screenshot is best effort
            return None


def one_line(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return (f"{type(exc).__name__}: {text}" if text else type(exc).__name__)[:300]


def empty(folder: Path) -> None:
    """The downloads folder with nothing in it: a stale file is never imported as today's."""
    folder.mkdir(parents=True, exist_ok=True)
    for p in folder.iterdir():
        if p.is_file():
            p.unlink()


def prune(folder: Path, keep: int) -> None:
    """The newest ``keep`` files of ``folder``, the rest removed."""
    folder.mkdir(parents=True, exist_ok=True)
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
    for p in files[: max(0, len(files) - keep)]:
        p.unlink()
