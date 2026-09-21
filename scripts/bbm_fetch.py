"""Download Basketball Monster exports into data/.

    python scripts/bbm_fetch.py --ros                # rest-of-season totals + per game
    python scripts/bbm_fetch.py --week               # this week's remainder and next week
    python scripts/bbm_fetch.py --actual 7           # past 7 days actuals
    python scripts/bbm_fetch.py --ros --headless     # once the profile is logged in

First run without --headless and log in when the browser opens.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pickandroll.sources.bbm.fetch import BBMFetcher


def week_bounds(today):
    """Yahoo weeks run Monday to Sunday."""
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ros", action="store_true", help="rest-of-season projections")
    parser.add_argument(
        "--week", action="store_true", help="this-week remainder and next-week projections"
    )
    parser.add_argument(
        "--actual", type=int, metavar="DAYS", help="actual stats over the past DAYS days"
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if not (args.ros or args.week or args.actual):
        parser.error("choose at least one of --ros, --week, --actual")

    today = datetime.now(tz=UTC).date()
    with BBMFetcher(headless=args.headless) as bbm:
        bbm.ensure_login()
        if args.ros:
            for stat_type in ("totals", "pergame"):
                print("saved", bbm.rest_of_season(stat_type))
        if args.week:
            start, end = week_bounds(today)
            print("saved", bbm.weekly(max(start, today), end, this_week=True))
            print("saved", bbm.weekly(start + timedelta(days=7), end + timedelta(days=7)))
        if args.actual:
            print("saved", bbm.rankings_past_days(args.actual))


if __name__ == "__main__":
    main()
