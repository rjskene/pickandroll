"""Compare the simulated category curve with the league's own (``curve: league``, #65).

    python scripts/league_curve.py                          # the 2026-10-14 draft, markdown out
    python scripts/league_curve.py --time-limit 60 --out /tmp/league_curve.md

Builds the draft night's session twice through the API, once per curve, with everything else
the same: the room log's last attach (projections, positions, ADP, and the keepers by the picks
they took), the product's default availability for the league, and the night's pick owners
from the archive's ``picks.csv`` (each team's slot is the one whose picks it made most). Then:

1. Both curves side by side, and the standings' sigma in z units (the fit's check).
2. My drafted roster's expected categories won on each curve, with each category's call
   (conceded, contested, secured).
3. The plan at my first pick (overall 4, after picks 1 to 3) under each curve: the priced
   candidates, the planned picks, and each plan's roster scored on both curves.

The output carries curve parameters, expected categories won and player names: no projection
numbers and no team names, so it can go into ``docs/analysis/``. A value run: keep timing
measurements off the machine while it solves.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.draft import pick_owner
from pickandroll.optim.objective import CategoryCurve, win_label
from pickandroll.projections.schema import Cat
from pickandroll.sources.matching import load_aliases, match_players

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def last_attach(ledger: Path) -> dict[str, Any]:
    attach = None
    for line in ledger.read_text().splitlines():
        event = json.loads(line)
        if event.get("type") == "attach":
            attach = event
    if attach is None:
        raise SystemExit(f"no attach record in {ledger}")
    return attach


def night_picks(archive: Path, year: int) -> pd.DataFrame:
    """The year's picks with each pick's draft position: the snake slot whose picks the team
    that made it made most often (a traded pick is the exception on a team's line)."""
    picks = pd.read_csv(archive / "picks.csv")
    picks = picks[picks["draft_year"] == year].sort_values("overall").reset_index(drop=True)
    teams = int(picks["n_teams"].iloc[0])
    picks["snake"] = [pick_owner(teams, int(k))[1] for k in picks["overall"]]
    counts = picks.groupby(["team", "snake"]).size()
    slot = {team: int(counts[team].idxmax()) for team in picks["team"].unique()}
    if sorted(slot.values()) != list(range(1, teams + 1)):
        raise SystemExit("two teams share a slot: the draft positions are not readable")
    picks["slot"] = picks["team"].map(slot)
    return picks


def name_of(state: Any, player_id: str) -> str:
    return str(state.projections.df["player"].get(player_id, player_id))


def table(rows: list[list[Any]], header: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument(
        "--ledger", type=Path, default=None, help="default data/fidelity/31822.jsonl"
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--time-limit", type=float, default=20.0, help="plan budget per solve")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    data = args.data
    ledger = args.ledger or data / "fidelity" / "31822.jsonl"
    attach = last_attach(ledger)
    picks = night_picks(data / "yahoo_history", args.year)
    me = int(attach["slot"])
    owners = picks["slot"].astype(int).tolist()
    body = {
        **{
            k: v
            for k, v in attach["session"].items()
            if k not in ("survival", "survival_file", "fit_curve", "keepers_file")
        },
        "solve_ahead": False,
        "time_limit": args.time_limit,
        "pick_owners": owners,
        # Each keeper by his pick outright: the log's session names a snake slot, the owner
        # map the team that holds the pick.
        "keepers": [
            {
                "overall": int(k["overall"]),
                "position": None if owners[k["overall"] - 1] == me else owners[k["overall"] - 1],
                "player_id": k["player_id"],
            }
            for k in attach["keepers"]
        ],
    }
    out: list[str] = []
    store = SessionStore()
    sessions: dict[str, dict[str, Any]] = {}
    with TestClient(create_app(store, data_dir=data)) as client:
        for curve in ("simulated", "league"):
            r = client.post("/sessions", json={**body, "curve": curve})
            if r.status_code != 201:
                raise SystemExit(f"curve={curve}: {r.status_code} {r.text}")
            sessions[curve] = r.json()
        state = store.sessions[sessions["league"]["id"]].state
        names = pd.DataFrame(
            {"name": picks["player"].astype(str).to_numpy()},
            index=picks["overall"].astype(int).to_numpy(),
        )
        match = match_players(names, state.projections.df, load_aliases(data / "aliases.json"))
        if match.unmatched_yahoo:
            raise SystemExit(f"picks with no projection: {match.unmatched_yahoo}")
        ids = {int(k): v for k, v in match.mapping.items()}
        curves = {
            k: CategoryCurve.from_dict(s["curve"], state.settings.cats) for k, s in sessions.items()
        }
        cats = list(state.settings.cats)
        fit = sessions["league"]["curve_fit"]

        out.append("## 1. The two curves\n")
        out.append(
            f"League fit: {curves['league'].source}. Simulated: {curves['simulated'].source}."
        )
        check = fit["check"]
        seasons = fit["check_seasons"]
        span = f"{seasons[0]} to {seasons[-1]}" if seasons else "none"
        rows = []
        for c in cats:
            v = check.get(c.value)
            rows.append(
                [
                    c.value,
                    f"{curves['simulated'].mu[c]:.2f}",
                    f"{curves['league'].mu[c]:.2f}",
                    f"{curves['simulated'].sigma[c]:.2f}",
                    f"{curves['league'].sigma[c]:.2f}",
                    "n/a" if v is None else f"{v:.2f}",
                ]
            )
        out.append(
            table(
                rows,
                [
                    "cat",
                    "mu simulated",
                    "mu league",
                    "sigma simulated",
                    "sigma league",
                    f"sigma standings ({span})",
                ],
            )
        )

        out.append("\n## 2. My 2026-10-14 roster on each curve\n")
        mine = [ids[k] for k, s in zip(picks["overall"], picks["slot"], strict=True) if s == me]
        totals = {c: float(state.z.loc[mine, c.value].sum()) for c in cats}
        rows = []
        for c in cats:
            row = [c.value]
            for k in ("simulated", "league"):
                p = curves[k].probability(c, totals[c])
                row.append(f"{p:.2f} ({win_label(p)})")
            rows.append(row)
        rows.append(
            ["**expected categories won**"]
            + [f"**{curves[k].wins(totals):.2f}**" for k in ("simulated", "league")]
        )
        out.append(f"{len(mine)} players, keepers included.\n")
        out.append(table(rows, ["cat", "simulated curve", "league curve"]))

        out.append("\n## 3. The plan at my first pick (overall 4)\n")
        league = sessions["league"]
        bias = (league.get("availability_bias") or {}).get("source")
        taken = name_of(state, ids[4])
        out.append(
            f"Availability: {league['availability_source']} "
            f"({league['survival'].get('source')}), ADP bias {bias}. My pick on the night: {taken}."
        )
        first = [
            [int(k), f"Team {s}" if s != me else "me", ids[int(k)]]
            for k, s in zip(picks["overall"], picks["slot"], strict=True)
            if int(k) < 4
        ]
        plans: dict[str, dict[str, Any]] = {}
        for k, s in sessions.items():
            r = client.post(f"/sessions/{s['id']}/sync", json={"picks": first})
            if r.status_code != 200:
                raise SystemExit(f"sync ({k}): {r.text}")
            r = client.post(f"/sessions/{s['id']}/recommend", json={"horizon": True})
            if r.status_code != 200:
                raise SystemExit(f"recommend ({k}): {r.text}")
            plans[k] = r.json()
        name = state.projections.df["player"]
        for k, rec in plans.items():
            out.append(f"\n### {k} curve\n")
            capped = rec["best_roster"]["time_limited"]
            out.append(
                f"Plan budget {args.time_limit:g} s; the plan {'hit' if capped else 'beat'} it; "
                f"{'exactly priced' if rec['priced'] else 'first-order prices'}.\n"
            )
            rows = [
                [
                    i + 1,
                    name.get(c["player"], c["player"]),
                    "" if c.get("cost_vs_best") is None else f"{c['cost_vs_best']:.3f}",
                ]
                for i, c in enumerate(rec["candidates"][:6])
            ]
            out.append(table(rows, ["rank", "candidate", "cost vs best (categories won)"]))
            plan = ", ".join(f"{p['pick']} {p['name']}" for p in rec["plan"])
            out.append(f"\nPlanned picks: {plan}.")
        rows = []
        for k, rec in plans.items():
            finals = {Cat(c): float(v) for c, v in rec["best_roster"]["cat_totals"].items()}
            rows.append(
                [f"{k} plan"] + [f"{curves[j].wins(finals):.2f}" for j in ("simulated", "league")]
            )
        out.append(
            "\nEach plan's final roster (drafted, kept and planned), scored on both curves:\n"
        )
        out.append(table(rows, ["plan", "on the simulated curve", "on the league curve"]))
    text = "\n".join(out) + "\n"
    if args.out:
        args.out.write_text(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
