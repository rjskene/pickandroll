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
or read beyond a count of elements. While a page opened with one of the extension's fragments
waits, the tab's address is read every half second: a claim Yahoo kept on its form's own path
is screened once (``screens/claim-form-*.png``, #341), the evidence the page's words alone did
not give on 2026-11-07.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .browser import (
    BBM_HOST,
    NOT_LOADED,
    SIGNED_IN,
    SIGNED_OUT,
    YAHOO_HOST,
    SignCheck,
    refused,
)
from .clock import now
from .lock import BrowserBusy, BrowserLock
from .report import EXPORT_KINDS
from .steps import PRIVATE_LEAGUE, YAHOO

BBM = f"https://{BBM_HOST}"
#: The sign-in check pages: Basketball Monster's front page (its Logout link), the private
#: league's page (its My Team link; Yahoo sends it to the sign-in when signed out).
BBM_CHECK = f"{BBM}/"
YAHOO_CHECK = f"{YAHOO}/nba/{PRIVATE_LEAGUE}"
#: The extension's background worker must be up before anything opens.
WORKER_WAIT_S = 20.0
GOTO_TIMEOUT_MS = 60_000
#: A sign-in check page that did not load is tried again after each of these waits (#364): three
#: tries, about a minute. Yahoo's 502s at the 2026-11-12 05:00 daily were brief.
SIGNIN_RETRY_S = (15.0, 45.0)
DOWNLOAD_TIMEOUT_MS = 60_000
#: A stuck export page may not eat the routine's window.
EXPORT_CEILING_S = 120.0
#: After a select changes (the page re-renders) and after the Refresh button.
SELECT_WAIT_S = 4.0
REFRESH_WAIT_S = 5.0
SCREENS_KEPT = 20
#: A page opened with one of these fragments is watched while it waits (#341).
WATCHED = "#pickandroll-"
WATCH_STEP_S = 0.5
#: The claim form's own action path: a submit Yahoo did not take stays there (#341).
CLAIM_FORM = re.compile(r"^/nba/\d+/\d+/addplayer/?$")
WINDOW = "1440,900"
#: The profile keeps the extension's background worker compiled in this folder and runs that
#: copy on every launch: ``--load-extension`` reads the manifest and the content scripts from
#: the checkout again, never the worker. Dropped when the extension's files changed (the stamp).
WORKER_CACHE = Path("Default") / "Service Worker"
EXTENSION_STAMP = ".pickandroll-extension"

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
#: Signed in: the league navigation's My Team link, to the user's team page. Signed out: a
#: sign-in form, or no such link (the redirect to login.yahoo.com is caught by the host). The
#: header's own Sign in link is never consulted: Yahoo shows one to signed-in users too.
YAHOO_SIGNED_IN_JS = (
    "() => !document.querySelector('input#login-username')"
    " && !document.querySelector('form[action*=\"login.yahoo.com\"]')"
    " && Array.from(document.querySelectorAll('a')).some(a =>"
    " /^my team$/i.test((a.textContent || '').trim())"
    " && /\\/nba\\/\\d+\\/\\d+(?:[/?#]|$)/.test(a.getAttribute('href') || ''))"
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
        lock: Path | None = None,
        holder: str = "a routine",
        lock_wait_s: float = 0.0,
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
        #: The profile's lock (#355), taken at launch and given back at close; ``busy`` is the
        #: holder's line when the run's wait ran out.
        self._lock = (
            BrowserLock(lock, holder, lock_wait_s, sleep=sleep, clock=clock) if lock else None
        )
        self.busy: str | None = None
        #: The extension's worker scripts, once up.
        self.workers: list[str] = []
        #: Every URL this run loaded, in order (the run log's evidence).
        self.opened: list[str] = []
        self._pw: Any = None
        self._context: Any = None
        self._page: Any = None
        self._available: bool | None = None
        #: The sign-in checks kept for the run: signed in or out, never a page that did not load.
        self._signed: dict[str, SignCheck] = {}
        #: The HTTP status of the last page loaded (None when the load gave no response).
        self.status: int | None = None

    # ------------------------------------------------------------------ lifecycle
    def available(self) -> bool:
        if self._available is None:
            try:
                if self._lock is not None:
                    self._lock.acquire()
                self._launch()
                self._available = True
            except BrowserBusy as exc:
                self.reason = self.busy = str(exc)
                self._available = False
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
        fresh_worker(self.profile, self.extension)
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
        if self._lock is not None:
            self._lock.release()

    # ------------------------------------------------------------------ the sites
    def signed_in(self, site: str) -> bool:
        return self.sign_check(site).state == SIGNED_IN

    def sign_check(self, site: str) -> SignCheck:
        """The site's sign-in check (#364): its check page loaded and read, up to three tries
        while it does not load (:data:`SIGNIN_RETRY_S`). Signed in or out is kept for the run; a
        page that did not load is not, so the next step checks again. ``reason`` says why."""
        if site not in ("bbm", "yahoo"):
            raise ValueError(f"unknown site {site!r}")
        if site in self._signed:
            return self._signed[site]
        if not self.available():
            return SignCheck(NOT_LOADED, self.reason, 0)
        check = self._check(site, 1)
        for tries, wait in enumerate(SIGNIN_RETRY_S, 2):
            if check.state != NOT_LOADED:
                break
            self.sleep(wait)
            check = self._check(site, tries)
        if check.state != NOT_LOADED:
            self._signed[site] = check
        if check.state != SIGNED_IN:
            self.reason = check.reason
        return check

    def _check(self, site: str, tries: int) -> SignCheck:
        url = BBM_CHECK if site == "bbm" else YAHOO_CHECK
        try:
            landed = self._goto(url)
            if not loaded(self.status):
                return SignCheck(NOT_LOADED, f"HTTP {self.status} at {url}", tries)
            if site == "bbm":
                if self.count(BBM_LOGOUT) > 0:
                    return SignCheck(SIGNED_IN, "", tries)
                return SignCheck(SIGNED_OUT, f"no Logout link on {landed}", tries)
            host = (urlsplit(landed).hostname or "").lower()
            if host != YAHOO_HOST:
                return SignCheck(SIGNED_OUT, f"sent to {host or landed}", tries)
            if not self._page.evaluate(YAHOO_SIGNED_IN_JS):
                return SignCheck(
                    SIGNED_OUT, "a sign-in form, or no My Team link, on the league page", tries
                )
            return SignCheck(SIGNED_IN, "", tries)
        except Exception as exc:  # noqa: BLE001 - a check page that did not load
            return SignCheck(NOT_LOADED, one_line(exc), tries)

    def export(self, kind: str) -> Path:
        recipe = RECIPES[kind]
        if not self.available():
            raise RuntimeError(self.reason)
        deadline = self.clock() + EXPORT_CEILING_S
        try:
            self._goto(recipe.page)
            if not loaded(self.status):
                raise RuntimeError(f"the export page did not load: HTTP {self.status}")
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
        if WATCHED in url:
            self._watch(wait_s)
        else:
            self.sleep(wait_s)
        return str(self._page.url)

    def _watch(self, wait_s: float) -> None:
        """The wait in steps of :data:`WATCH_STEP_S`, the tab's address read after each: each
        arrival on the claim form's own action path is screened once (#341). The steps add up to
        ``wait_s``; the clock is not read."""
        waited = 0.0
        on_form = False
        while waited < wait_s:
            step = min(WATCH_STEP_S, wait_s - waited)
            self.sleep(step)
            waited += step
            here = bool(CLAIM_FORM.match(urlsplit(str(self._page.url)).path))
            if here and not on_form:
                self._screenshot("claim-form")
            on_form = here

    def count(self, selector: str) -> int:
        return int(self._page.evaluate(COUNT_JS, selector))

    # ------------------------------------------------------------------ helpers
    def _goto(self, url: str) -> str:
        self.opened.append(url)
        self.status = None
        response = self._page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        self.status = getattr(response, "status", None)
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


def loaded(status: int | None) -> bool:
    """A page loaded: not a server error or a rate limit (429, Yahoo's 999). A signed-out
    profile lands on a page that loaded (the sign-in redirect), so it is never this. No status
    (a load with no response) counts as loaded: the page's own markers decide."""
    return status is None or (status < 500 and status != 429)


def one_line(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return (f"{type(exc).__name__}: {text}" if text else type(exc).__name__)[:300]


def empty(folder: Path) -> None:
    """The downloads folder with nothing in it: a stale file is never imported as today's."""
    folder.mkdir(parents=True, exist_ok=True)
    for p in folder.iterdir():
        if p.is_file():
            p.unlink()


def extension_stamp(extension: Path) -> str:
    """A hash of every file of the extension folder, its tests left out: what it changes with."""
    h = hashlib.sha256()
    for p in sorted(extension.rglob("*")):
        rel = p.relative_to(extension)
        if p.is_file() and rel.parts[0] != "test":
            h.update(rel.as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def fresh_worker(profile: Path, extension: Path) -> bool:
    """The profile's compiled copy of the extension's worker dropped when the extension changed
    since the stamp (or there is no stamp): the launch then registers the worker from the
    checkout. The sign-ins and the extension's own records live elsewhere in the profile and are
    kept. On 2026-11-02 the droplet ran the worker of 2026-10-29 under extension 0.11.2, without
    the live lineup run's messages, and every live lineup run was skipped (#301). Answers whether it
    dropped the copy."""
    stamp = profile / EXTENSION_STAMP
    now_ = extension_stamp(extension)
    try:
        was = stamp.read_text().strip()
    except OSError:
        was = ""
    if was == now_:
        return False
    shutil.rmtree(profile / WORKER_CACHE, ignore_errors=True)
    stamp.write_text(now_ + "\n")
    return True


def prune(folder: Path, keep: int) -> None:
    """The newest ``keep`` files of ``folder``, the rest removed."""
    folder.mkdir(parents=True, exist_ok=True)
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
    for p in files[: max(0, len(files) - keep)]:
        p.unlink()
