"""The sign-in browser (``ops/vm/signin.sh``): the routine's Chromium on its own profile with
the extension loaded, the same launch the routines make plus the DevTools port on localhost
for the fallback path, a tab on each site. The user signs in from the Mac over VNC or DevTools
and presses Enter in the terminal; nothing here reads, types or logs a credential."""

from __future__ import annotations

import sys
from pathlib import Path

BBM = "https://basketballmonster.com/"
YAHOO = "https://basketball.fantasysports.yahoo.com/nba/31822"
WINDOW = "1440,900"
DEVTOOLS_PORT = 9222


def main(profile: Path, extension: Path) -> int:
    from playwright.sync_api import sync_playwright

    if not (extension / "manifest.json").is_file():
        print(f"no extension at {extension}")
        return 1
    profile.mkdir(parents=True, exist_ok=True)
    profile.chmod(0o700)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            accept_downloads=True,
            args=[
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                "--no-first-run",
                f"--window-size={WINDOW}",
                f"--remote-debugging-port={DEVTOOLS_PORT}",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(BBM, wait_until="domcontentloaded")
        second = context.new_page()
        second.goto(YAHOO, wait_until="domcontentloaded")
        print(
            "browser up with a tab on Basketball Monster and one on the league page: sign in to both there,"
            " then press Enter here to close it.",
            flush=True,
        )
        try:
            sys.stdin.readline()
        except KeyboardInterrupt:
            pass
        context.close()
    print(f"browser closed; the profile is {profile}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: signin_browser.py <profile dir> <extension dir>")
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
