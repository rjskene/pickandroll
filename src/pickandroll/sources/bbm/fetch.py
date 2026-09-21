"""Download Basketball Monster projection exports with the member's own browser session.

Basketball Monster has no API. Its projection pages have an Excel export button for members,
so this module drives a real Chromium through Playwright using a persistent profile stored under
``data/bbm-profile`` (gitignored). The first run is headed: log in yourself in the window that
opens, and the profile keeps the session for later headless runs. No credentials are handled by
this code.

Selectors come from the site's ASP.NET pages (``projections.aspx``, ``weeklyprojections.aspx``,
``playerrankings.aspx``). If the site changes, a failing step saves a screenshot next to the
downloads so the selector can be fixed.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Self

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"
PROFILE_DIR = DATA_DIR / "bbm-profile"
BASE_URL = "https://basketballmonster.com"

PAGES = {
    "ros": f"{BASE_URL}/projections.aspx",
    "week": f"{BASE_URL}/weeklyprojections.aspx",
    "rankings": f"{BASE_URL}/playerrankings.aspx",
}
STAT_TYPES = {"totals": "Total Stats", "pergame": "Per Game Stats"}


class BBMFetcher:
    def __init__(
        self,
        headless: bool = False,
        profile_dir: Path = PROFILE_DIR,
        data_dir: Path = DATA_DIR,
        login_timeout: float = 300.0,
    ) -> None:
        self.headless = headless
        self.profile_dir = Path(profile_dir)
        self.data_dir = Path(data_dir)
        self.login_timeout = login_timeout
        self._pw = None
        self.context = None
        self.page = None

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self) -> Self:
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), headless=self.headless, accept_downloads=True
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    # ------------------------------------------------------------------ login
    def logged_in(self) -> bool:
        return self.page.locator("a", has_text="Logout").count() > 0

    def ensure_login(self) -> None:
        self.page.goto(BASE_URL, wait_until="domcontentloaded")
        if self.logged_in():
            return
        if self.headless:
            raise RuntimeError(
                "not logged in to Basketball Monster; run once with headless=False and log in"
            )
        print("Log in to Basketball Monster in the browser window. Waiting...")
        deadline = time.time() + self.login_timeout
        while time.time() < deadline:
            if self.logged_in():
                print("Logged in.")
                return
            time.sleep(2)
        raise TimeoutError("timed out waiting for Basketball Monster login")

    # ------------------------------------------------------------------ exports
    def rest_of_season(self, stat_type: str = "totals") -> Path:
        """Rest-of-season projections for all players."""
        self._open(PAGES["ros"])
        self._select_all_players()
        self._select_stat_type(stat_type)
        return self._download("[name=EXCELBUTTON]", f"bbm_ros_{stat_type}", horizon="season")

    def weekly(self, start: date, end: date, this_week: bool = False) -> Path:
        """Projections for a date range (this week's remainder or next week)."""
        self._open(PAGES["week"])
        if this_week:
            self._click("[name=THISWEEK]")
        self._select_all_players()
        self._pick_calendar_day("#ContentPlaceHolder1_StartCalendar", start)
        self._pick_calendar_day("#ContentPlaceHolder1_EndCalendar", end)
        label = "week_this" if this_week else "week_next"
        return self._download(
            "#ContentPlaceHolder1_ExcelButton", f"bbm_{label}", horizon="week", start=start, end=end
        )

    def rankings_past_days(self, days: int, stat_type: str = "totals") -> Path:
        """Actual production over the past N days (for in-season tracking)."""
        self._open(PAGES["rankings"])
        self._select_all_players()
        self.page.select_option("#DateFilterControl", label="Past Days")
        days_input = self.page.locator("#DateFilterControlDAYS")
        days_input.fill(str(days))
        self._select_stat_type(stat_type)
        self._click("[name=RANKINGSBUTTON]")
        end = datetime.now(tz=UTC).date()
        return self._download(
            "[name=EXCELBUTTON]",
            f"bbm_actual_{days}d_{stat_type}",
            horizon="custom",
            start=end - timedelta(days=days),
            end=end,
        )

    # ------------------------------------------------------------------ helpers
    def _open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        if not self.logged_in():
            self.ensure_login()
            self.page.goto(url, wait_until="domcontentloaded")

    def _select_all_players(self) -> None:
        self._guard(
            lambda: self.page.select_option("#PlayerFilterControl", label="All Players"),
            "player filter",
        )

    def _select_stat_type(self, stat_type: str) -> None:
        if stat_type not in STAT_TYPES:
            raise ValueError(f"stat_type must be one of {list(STAT_TYPES)}")
        self._guard(
            lambda: self.page.select_option("#StatDisplayType", label=STAT_TYPES[stat_type]),
            "stat type",
        )

    def _pick_calendar_day(self, calendar: str, day: date) -> None:
        title = f"{day:%B} {day.day}"
        self._guard(
            lambda: self.page.locator(f"{calendar} [title='{title}']").first.click(),
            f"calendar day {title}",
        )

    def _click(self, selector: str) -> None:
        self._guard(lambda: self.page.locator(selector).first.click(), selector)

    def _download(
        self,
        selector: str,
        stem: str,
        horizon: str,
        start: date | None = None,
        end: date | None = None,
    ) -> Path:
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M")
        target = self.data_dir / f"{stem}_{stamp}.xls"

        def go():
            with self.page.expect_download(timeout=60_000) as info:
                self.page.locator(selector).first.click()
            info.value.save_as(str(target))

        self._guard(go, f"download via {selector}")
        meta = {
            "source": "bbm",
            "horizon": horizon,
            "as_of": datetime.now(tz=UTC).isoformat(),
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "file": target.name,
        }
        target.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return target

    def _guard(self, action, what: str) -> None:
        try:
            action()
        except Exception as exc:
            shot = self.data_dir / f"bbm_error_{datetime.now(tz=UTC):%Y%m%d-%H%M%S}.png"
            try:
                self.page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001 - screenshot is best effort
                shot = None
            raise RuntimeError(
                f"Basketball Monster step failed ({what}): {exc}; screenshot {shot}"
            ) from exc
