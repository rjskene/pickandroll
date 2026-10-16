"""The ADP model's bias table from the league's history archive (#64).

    python scripts/fit_adp_bias.py                     # data/yahoo_history -> its adp_bias.json
    python scripts/fit_adp_bias.py --history data/yahoo_history --target 2026 --dry-run

Reads the archive's ``picks_with_adp.csv`` and ``adp.csv`` (see the archive's README), chooses the
season half-life and the first effective ADP with a shift by each season held out in turn
(``pickandroll.availability.bias.choose``), fits the table on every season with that choice,
weighted toward ``--target``, and writes it beside the league's survival table, where the API
loads it with that table (``adp_bias.json``). It prints the held-out Brier by bucket, the share
of each bucket that went undrafted against the share the formula leaves on the board at the
last pick, and the target season's pick error with the fit on the other seasons: the mean
absolute error, in overall picks, of keeper-adjusted ADP with and without the shift.

Seasons start at ``--first-season`` (2017, the league's first with keepers).

The choice: of the half-lives 1, 2 and 3 seasons and unweighted, and the first ADPs 0, 48, 60, 72,
84 and 96, the fit with the lowest held-out Brier over all buckets among those no worse than the
plain formula in any bucket. On 2017-2026 (2026-10-16) that is a one-season half-life and a shift
from ADP 72: a shift from 0, 48 or 60 is worse in an early bucket at every half-life. The JSON
records the choice, the rule and every fit compared (``choice``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from pickandroll.availability import bias as adp_bias

OUT_NAME = "adp_bias.json"


def target_error(
    obs: pd.DataFrame, picks: pd.DataFrame, target: int, half_life: float | None, from_adp: float
) -> dict[str, float]:
    """The target season's drafted non-keepers: the mean absolute error in overall picks of
    keeper-adjusted ADP, plain and shifted by the fit on the other seasons."""
    season = picks[picks["draft_year"] == target]
    slots = sorted(season.loc[season["keeper_any"].astype(bool), "overall"].astype(int))
    total = len(season)
    drafted = obs[(obs["season"] == target) & obs["market_pick"].notna()]
    fitted = adp_bias.fit(obs[obs["season"] != target], target, half_life, from_adp)

    def overall(market: pd.Series) -> pd.Series:
        return market.map(lambda m: adp_bias.market_to_overall(float(m), slots, total))

    real = overall(drafted["market_pick"])
    return {
        "season": target,
        "n": len(drafted),
        "plain": float((overall(drafted["adp_eff"]) - real).abs().mean()),
        "biased": float((overall(fitted.apply(drafted["adp_eff"])) - real).abs().mean()),
    }


def availability(mu: pd.Series, pick: pd.Series) -> np.ndarray:
    """The plain formula's ``S`` for each player at his own pick."""
    curve = [
        adp_bias.survival_curve(np.array([m]), np.array([k]))[0, 0]
        for m, k in zip(mu.to_numpy(float), pick.to_numpy(float), strict=True)
    ]
    return np.asarray(curve)


def undrafted_shares(obs: pd.DataFrame, table: adp_bias.AdpBias) -> pd.DataFrame:
    """By bucket, the share never drafted against the mean ``S`` at the season's last market
    pick, plain and shifted (the table fit on every season, so in sample)."""
    edges = adp_bias.EDGES
    rows = []
    inside = obs[obs["adp_eff"].between(edges[0], edges[-1])]
    bucket = np.digitize(inside["adp_eff"].to_numpy(float), edges[1:-1], right=True)
    for b in range(len(edges) - 1):
        part = inside[bucket == b]
        if part.empty:
            continue
        last = part["market_picks"]
        rows.append(
            {
                "bucket": f"{edges[b]:g}-{edges[b + 1]:g}",
                "players": len(part),
                "undrafted": float(part["market_pick"].isna().mean()),
                "plain": float(availability(part["adp_eff"], last).mean()),
                "biased": float(availability(table.apply(part["adp_eff"]), last).mean()),
            }
        )
    return pd.DataFrame(rows).set_index("bucket")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--history", type=Path, default=ROOT / "data" / "yahoo_history")
    parser.add_argument("--first-season", type=int, default=2017)
    parser.add_argument("--target", type=int, default=None, help="default: the archive's last")
    parser.add_argument("--out", type=Path, default=None, help=f"default: <history>/{OUT_NAME}")
    parser.add_argument("--dry-run", action="store_true", help="print the fit, write nothing")
    args = parser.parse_args(argv)

    picks = pd.read_csv(args.history / "picks_with_adp.csv")
    adp = pd.read_csv(args.history / "adp.csv")
    seasons = [int(s) for s in sorted(picks["draft_year"].unique()) if s >= args.first_season]
    obs = adp_bias.observations(picks, adp, seasons)
    target = args.target if args.target is not None else max(seasons)

    choice = adp_bias.choose(obs)
    pd.set_option("display.width", 160)
    if choice is None:
        print("every fit is worse than the plain formula in some bucket: no table written")
        return 1
    grid = choice.grid.assign(half_life=choice.grid["half_life"].astype(object))
    print("Held out, each season in turn (Brier over all buckets, worst bucket change):")
    print(grid.round(5).to_string(index=False))
    print(
        f"\nChosen: half-life {choice.half_life} seasons, shift from effective ADP {choice.from_adp:g}"
    )
    print(choice.scores.round(5).to_string())

    table = adp_bias.fit(obs, target, choice.half_life, choice.from_adp)
    error = target_error(obs, picks, target, choice.half_life, choice.from_adp)
    print(
        f"\n{target}, fit on the other seasons: pick MAE {error['biased']:.2f} against "
        f"{error['plain']:.2f} for keeper-adjusted ADP (n {error['n']})"
    )
    print("\nNever drafted, against S at the last market pick (the table fit on every season):")
    print(undrafted_shares(obs, table).round(3).to_string())
    print(f"\nThe same, {target} only:")
    print(undrafted_shares(obs[obs["season"] == target], table).round(3).to_string())
    late = obs[(obs["season"] == target) & obs["adp_eff"].between(60, 90)]
    print(
        f"{target}, effective ADP 60-90: {late['market_pick'].isna().mean():.0%} never drafted "
        f"(n {len(late)}); S at the last pick {availability(late['adp_eff'], late['market_picks']).mean():.1%} "
        f"plain, {availability(table.apply(late['adp_eff']), late['market_picks']).mean():.1%} shifted"
    )
    print("\nTable:", json.dumps(table.to_dict()))
    if args.dry_run:
        return 0
    out = args.out or args.history / OUT_NAME
    record = {
        **table.to_dict(),
        "choice": {
            "rule": "lowest held-out Brier over all buckets among the fits no worse than the plain "
            "formula in any bucket, each season held out in turn",
            "half_life": choice.half_life,
            "from_adp": choice.from_adp,
            "grid": choice.grid.round(6).to_dict(orient="records"),
        },
        "held_out": {
            "buckets": choice.scores.round(6).reset_index().to_dict(orient="records"),
            "target_mae": error,
        },
    }
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
