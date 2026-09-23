"""Simulated survival curves and league category totals for the mock-draft study.

    python scripts/survival_sim.py --sims 2000 --out data/studies/2026-09-23 --workers 9

Runs full twelve-team drafts in which every team is one of the study's simulated drafters (z,
adp or lp with a punt of its own, drawn as ``scripts/mock_study.py`` draws them) and records the
overall pick at which every player went. From that record it writes

``survival.csv``
    ``S[p, k]``, the share of drafts in which player ``p`` was still on the board when pick ``k``
    came up (see ``pickandroll.availability.survival``), the planner's replacement for the ADP
    availability model.
``curve.json``
    Mean and standard deviation of each category's team total (z summed over the roster) across
    every simulated team, the ``mu`` and ``sigma`` of the category-win objective.
``pick_numbers.csv.gz``
    The raw record, one row per simulated pick.
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
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
import pandas as pd
from mock_study import (
    DEFAULT_PROJECTIONS,
    Config,
    latent_boards,
    new_state,
    other_pick,
    punt_label,
    rng,
)

from pickandroll.availability.survival import SurvivalTable
from pickandroll.draft.autopick import STRATEGIES, TEAM_PUNTS, team_label
from pickandroll.projections.schema import NINE_CAT


def all_auto_design(seed: int, slot: int, state) -> dict:
    """A study design with a drafter and a punt for all twelve teams (my slot included)."""
    draw = rng(seed, 7)
    strategies = {
        position: STRATEGIES[int(draw.integers(len(STRATEGIES)))]
        for position in range(1, state.settings.num_teams + 1)
    }
    options = [p for p, _ in TEAM_PUNTS if p <= set(state.settings.cats)]
    weights = np.array([w for p, w in TEAM_PUNTS if p <= set(state.settings.cats)], dtype=float)
    weights /= weights.sum()
    draw = rng(seed, 999)
    punts = {
        team_label(state, position): options[int(draw.choice(len(options), p=weights))]
        for position in range(1, state.settings.num_teams + 1)
    }
    return {
        "seed": seed,
        "slot": slot,
        "strategies": strategies,
        "team_punts": {team: punt_label(p) for team, p in punts.items()},
    }


def simulate(cfg: Config, seed: int) -> tuple[int, list[tuple[str, int]], list[dict], float]:
    """One all-auto draft: the pick numbers and every team's category totals."""
    started = time.perf_counter()
    slot = (seed % 12) + 1
    state = new_state(cfg, slot)
    design = all_auto_design(seed, slot, state)
    boards = latent_boards(design, state)
    adp = state.effective_adp()
    picks = []
    while not state.complete:
        row = other_pick(state, design, boards, adp)
        picks.append((row["player"], row["overall"]))
    cats = [c.value for c in state.settings.cats]
    totals = []
    for position in range(1, state.settings.num_teams + 1):
        team = team_label(state, position)
        roster = [p.player_id for p in state.picks if p.team == team]
        totals.append(
            {
                "seed": seed,
                "position": position,
                "strategy": design["strategies"][position],
                "punt": design["team_punts"][team],
                **{c: float(state.z.loc[roster, c].sum()) for c in cats},
            }
        )
    return seed, picks, totals, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sims", type=int, default=2000)
    parser.add_argument("--first-seed", type=int, default=100000)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--projections", type=Path, default=DEFAULT_PROJECTIONS)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = Config(projections=str(args.projections))
    seeds = [args.first_seed + i for i in range(args.sims)]

    started = time.perf_counter()
    rows: list[dict] = []
    totals: list[dict] = []
    done = 0

    def collect(seed: int, picks: list[tuple[str, int]], team_totals: list[dict]) -> None:
        rows.extend({"sim": seed, "player": p, "overall": k} for p, k in picks)
        totals.extend(team_totals)

    if args.workers == 1:
        for seed in seeds:
            seed, picks, team_totals, seconds = simulate(cfg, seed)
            collect(seed, picks, team_totals)
            done += 1
            print(f"[{done}/{len(seeds)}] seed {seed} {seconds:.1f}s", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(simulate, cfg, seed) for seed in seeds]
            for future in as_completed(futures):
                seed, picks, team_totals, seconds = future.result()
                collect(seed, picks, team_totals)
                done += 1
                if done % 50 == 0 or done == len(seeds):
                    elapsed = time.perf_counter() - started
                    eta = elapsed / done * (len(seeds) - done)
                    print(
                        f"[{done}/{len(seeds)}] elapsed {elapsed / 60:.1f} min, "
                        f"eta {eta / 60:.1f} min",
                        flush=True,
                    )

    state = new_state(cfg, 1)
    picks = pd.DataFrame(rows)
    picks.to_csv(args.out / "pick_numbers.csv.gz", index=False)
    table = SurvivalTable.from_pick_numbers(
        picks, total_picks=state.settings.total_picks, sims=len(seeds), players=state.z.index
    )
    table.save(args.out / "survival.csv")

    team_totals = pd.DataFrame(totals)
    team_totals.to_csv(args.out / "team_totals.csv", index=False)
    cats = [c.value for c in NINE_CAT]
    curve = {
        "mu": {c: float(team_totals[c].mean()) for c in cats},
        "sigma": {c: float(team_totals[c].std(ddof=1)) for c in cats},
        "teams": len(team_totals),
        "sims": len(seeds),
        "source": "survival_sim.py all-auto drafts",
    }
    (args.out / "curve.json").write_text(json.dumps(curve, indent=2))

    adp = state.effective_adp()
    summary = pd.DataFrame(
        {
            "name": state.projections.df["player"],
            "adp": adp,
            "median_pick": table.median_pick().reindex(state.z.index),
            "z_total": state.z["total"],
        }
    )
    for k in (13, 25, 49, 73, 97, 121, 145):
        summary[f"S{k}"] = table.table[k].reindex(state.z.index)
    summary.sort_values("adp").to_csv(args.out / "survival_summary.csv")
    print(
        f"{len(seeds)} drafts in {(time.perf_counter() - started) / 60:.1f} min; "
        f"curve mu {[round(curve['mu'][c], 2) for c in cats]} "
        f"sigma {[round(curve['sigma'][c], 2) for c in cats]}",
        flush=True,
    )


if __name__ == "__main__":
    main()
