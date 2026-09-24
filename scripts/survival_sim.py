"""Simulated survival curves and league category totals for the mock-draft study.

    python scripts/survival_sim.py --sims 2000 --out data/studies/2026-09-23 --workers 9

Runs full twelve-team drafts in which every team is one of the study's simulated drafters (z,
adp or lp with a punt of its own) through ``pickandroll.draft.league_sim.simulate_league``, the
same routine the API runs when a session asks for a simulated survival table, and writes

``survival.csv``
    ``S[p, k]``, the share of drafts in which player ``p`` was still on the board when pick ``k``
    came up (see ``pickandroll.availability.survival``), the planner's replacement for the ADP
    availability model.
``curve.json``
    Mean and standard deviation of each category's team total (z summed over the roster) across
    every simulated team, the ``mu`` and ``sigma`` of the category-win objective.
``team_totals.csv``
    One row per simulated team with its drafter, punt and category totals.
``survival_summary.csv``
    Per player: ADP used by the drafters, simulated median pick and survival at a few picks.

Seeds start at ``--first-seed`` (100000 by default) so they never collide with the study's.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from pickandroll.draft import DraftState, LeagueSettings
from pickandroll.draft.autopick import STRATEGIES
from pickandroll.draft.league_sim import FIRST_SEED, simulate_league
from pickandroll.sources.bbm import load_bbm

DEFAULT_PROJECTIONS = ROOT / "data" / "bbm_ros_pergame_2026-09-21.xls"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sims", type=int, default=2000)
    parser.add_argument("--first-seed", type=int, default=FIRST_SEED)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--projections", type=Path, default=DEFAULT_PROJECTIONS)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument(
        "--drafters", default=",".join(STRATEGIES), help="comma list drawn from z, adp, lp"
    )
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    projections = load_bbm(args.projections, horizon="season")
    settings = LeagueSettings(num_teams=args.teams)
    drafters = tuple(d.strip() for d in args.drafters.split(",") if d.strip())
    started = time.perf_counter()
    last = {"done": 0}

    def progress(update: dict) -> None:
        done = update["done"]
        if done % 50 == 0 or done == args.sims:
            elapsed = time.perf_counter() - started
            eta = elapsed / done * (args.sims - done)
            print(
                f"[{done}/{args.sims}] elapsed {elapsed / 60:.1f} min, eta {eta / 60:.1f} min",
                flush=True,
            )
        last["done"] = done

    sim = simulate_league(
        settings,
        projections,
        args.sims,
        strategies=drafters,  # type: ignore[arg-type]
        first_seed=args.first_seed,
        workers=args.workers,
        progress=progress,
    )
    sim.survival.save(args.out / "survival.csv")
    sim.team_totals.to_csv(args.out / "team_totals.csv", index=False)
    curve = {
        **sim.curve.to_dict(),
        "teams": len(sim.team_totals),
        "sims": args.sims,
        "source": sim.curve.source,
    }
    (args.out / "curve.json").write_text(json.dumps(curve, indent=2))

    state = DraftState(settings=settings, projections=projections, my_team="me", my_position=1)
    adp = state.effective_adp()
    summary = pd.DataFrame(
        {
            "name": state.projections.df["player"],
            "adp": adp,
            "median_pick": sim.survival.median_pick().reindex(state.z.index),
            "z_total": state.z["total"],
        }
    )
    for k in (13, 25, 49, 73, 97, 121, 145):
        if k in sim.survival.table.columns:
            summary[f"S{k}"] = sim.survival.table[k].reindex(state.z.index)
    summary.sort_values("adp").to_csv(args.out / "survival_summary.csv")
    cats = [c.value for c in settings.cats]
    print(
        f"{args.sims} drafts in {sim.seconds / 60:.1f} min; "
        f"curve mu {[round(curve['mu'][c], 2) for c in cats]} "
        f"sigma {[round(curve['sigma'][c], 2) for c in cats]}",
        flush=True,
    )


if __name__ == "__main__":
    main()
