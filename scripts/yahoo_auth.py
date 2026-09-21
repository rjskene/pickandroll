"""One-time Yahoo OAuth handshake and league discovery.

Run from the repo root with the venv active::

    python scripts/yahoo_auth.py

Reads YAHOO_CONSUMER_KEY / YAHOO_CONSUMER_SECRET from .env, opens a browser for the Yahoo
consent screen, asks for the verification code on the command line, then saves the access
token back into .env (gitignored) and prints your NBA leagues so you can pick a YAHOO_LEAGUE_ID.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pickandroll.sources.yahoo import make_query

NOT_AUTHORIZED_HELP = """
Yahoo accepted the login but rejected the Fantasy Sports call. That means the developer app
has no Fantasy Sports API permission. Fix:
  1. Open https://developer.yahoo.com/apps/ and edit the app.
  2. Under API Permissions tick "Fantasy Sports" (Read) and save.
  3. Delete the YAHOO_ACCESS_TOKEN / YAHOO_REFRESH_TOKEN / YAHOO_GUID / YAHOO_TOKEN_* lines
     from .env so the next run asks for consent with the new permission.
  4. Run this script again.
"""


def main() -> None:
    from yfpy.exceptions import YahooFantasySportsDataNotFound

    query = make_query(league_id="0")
    try:
        user = query.get_current_user()
    except YahooFantasySportsDataNotFound as exc:
        if "not authorized" in str(exc):
            sys.exit(NOT_AUTHORIZED_HELP)
        raise
    print(f"Authenticated as Yahoo user {user.guid}")
    print("NBA leagues on this account:")
    leagues = query.get_user_leagues_by_game_key("nba")
    for league in leagues:
        name = league.name.decode() if isinstance(league.name, bytes) else league.name
        print(
            f"  league_id={league.league_id:<8} key={league.league_key:<16} "
            f"teams={league.num_teams:<3} draft={league.draft_status:<10} {name}"
        )
    print("\nAdd the one you want to .env as YAHOO_LEAGUE_ID=<league_id>")


if __name__ == "__main__":
    main()
