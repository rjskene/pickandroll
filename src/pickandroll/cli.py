"""Command line: ``python -m pickandroll ...`` (or ``pickandroll ...`` once installed).

* ``fidelity report <draft_id>`` prints the YAHOO SYNC scorecard of a room's log as markdown.
* ``room replay <fixture.csv>`` replays a recorded room into a running API (Tier 1).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .fidelity import FIDELITY_DIR, analyze, markdown, read_events


def fidelity_report(args: argparse.Namespace) -> int:
    path = Path(args.dir) / f"{args.draft_id}.jsonl"
    events = read_events(path)
    if not events:
        print(f"no events in {path}", file=sys.stderr)
        return 1
    card = analyze(events)
    if args.json:
        print(json.dumps(card, indent=1, default=str))
    else:
        print(markdown(card), end="")
    return 0


def room_replay(args: argparse.Namespace) -> int:
    import httpx

    from .fidelity.replay import load_fixture, replay

    picks = load_fixture(Path(args.fixture))
    draft_id = args.draft_id or f"{Path(args.fixture).stem}-replay-{time.strftime('%H%M%S')}"
    session = {
        "projection_file": args.projection_file,
        "positions_file": args.positions_file,
        "adp_file": args.adp_file,
        "num_teams": args.num_teams,
        "my_position": args.slot,
        "objective": args.objective,
        "time_limit": args.time_limit,
    }
    solve = {"n": args.n, "scenarios": 0, "time_limit": args.time_limit}
    with httpx.Client(base_url=args.api, timeout=60.0) as client:
        result = replay(
            client,
            picks,
            draft_id=draft_id,
            slot=args.slot,
            num_teams=args.num_teams,
            session=session,
            players_file=args.players_file,
            solve=solve,
            speed=args.speed or None,
            plan_wait=args.plan_wait,
        )
    print(result["scorecard"]["markdown"], end="")
    print(f"\nlog: {result['attach']['fidelity_log']}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pickandroll")
    sub = parser.add_subparsers(dest="command", required=True)

    fidelity = sub.add_parser("fidelity", help="YAHOO SYNC fidelity logs")
    fsub = fidelity.add_subparsers(dest="action", required=True)
    report = fsub.add_parser("report", help="print a room's scorecard")
    report.add_argument("draft_id")
    report.add_argument("--dir", default=str(FIDELITY_DIR), help="log directory")
    report.add_argument("--json", action="store_true", help="the scorecard as data")
    report.set_defaults(fn=fidelity_report)

    room = sub.add_parser("room", help="Yahoo draft rooms")
    rsub = room.add_subparsers(dest="action", required=True)
    rep = rsub.add_parser("replay", help="replay a recorded room into a running API")
    rep.add_argument("fixture", help="CSV: overall, yahoo_player_id, label, team, t_ms")
    rep.add_argument("--api", default="http://localhost:8000")
    rep.add_argument("--draft-id", default=None, help="default: <fixture>-replay-<time>")
    rep.add_argument("--slot", type=int, required=True)
    rep.add_argument("--num-teams", type=int, default=12)
    rep.add_argument("--projection-file", required=True)
    rep.add_argument("--positions-file", default=None)
    rep.add_argument("--adp-file", default=None)
    rep.add_argument("--players-file", default=None)
    rep.add_argument("--objective", choices=["win", "sum"], default="win")
    rep.add_argument("--time-limit", type=float, default=5.0)
    rep.add_argument("--n", type=int, default=3)
    rep.add_argument("--speed", type=float, default=1.0, help="0 = back to back")
    rep.add_argument("--plan-wait", type=float, default=10.0)
    rep.set_defaults(fn=room_replay)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
