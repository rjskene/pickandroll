"""Build the winning-bids table for the season simulator (#416), by hand, on the live checkout.

    python scripts/sim_bids.py                    # data/sim_share/winning_bids.csv + meta
    python scripts/sim_bids.py --data-dir /path   # another data folder
    python scripts/sim_bids.py --out /tmp/bids    # another output folder

It reads only the stored reads under ``data/leagues/<id>/season/snapshots`` and the autopilot
queue files; it never calls Yahoo or the API. The nine public leagues only, never 31822, and no
team name or id (``pickandroll.api.sim_bids``). It prints the meta: the table's sha256, the rows
and each league's reads.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pickandroll.api import sim_bids

ROOT = Path(__file__).resolve().parents[1]


def main_sha(root: Path) -> str:
    """The checkout's HEAD, with ``+dirty`` when its tracked files have changes."""
    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return sha + ("+dirty" if dirty else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--out", type=Path, help="the output folder (default: <data-dir>/sim_share)"
    )
    args = parser.parse_args(argv)
    meta = sim_bids.build(args.data_dir, main_sha(ROOT), datetime.now(UTC), args.out)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
