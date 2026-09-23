"""Mock-draft study: how the planner does against simulated leagues.

    python scripts/mock_study.py --mocks 100 --out data/studies/2026-09-22 --workers 9 \
        --branches 1,2,3,4,5,6,7,8,9,10,11,12
    python scripts/mock_study.py --mocks 1 --out /tmp/smoke --workers 1 --branches 1,6
    python scripts/mock_study.py --mocks 500 --out data/studies/x/win-surv --objective win \
        --curve data/studies/x/curve.json --availability survival \
        --survival data/studies/x/survival.csv
    python scripts/mock_study.py --mocks 100 --out data/studies/x/win-surv-naive \
        --base data/studies/x/win-surv --naive-branches 1,2,3,4,5,6,7,8,9,10,11,12,13

Every mock puts my team in a draft slot (slots cycle 1..12 over the mocks) and has it draft with
the rolling-horizon planner, re-choosing its punt at every pick ("auto"). The eleven other teams
each draw a drafter at random from z, adp and lp (see ``pickandroll.draft.autopick``) and, for
lp, a punt of their own. With ``--branches`` the draft is also branched at each listed pick k of
mine: the picks before k are replayed from the auto run and the punt the auto run chose at pick k
is held for the rest of the draft. Branch 1 is "punt fixed from the first pick"; branch 13 would
be the auto run itself.

The planner's objective is the sum of category totals (``--objective sum``, with the punt scan
choosing up to ``--max-punts`` categories to drop) or the expected number of categories won
(``--objective win``, a category curve with no explicit punt; see ``pickandroll.optim.objective``).
Availability comes from the ADP model or from a simulated survival table
(``--availability survival --survival table.csv``, see ``scripts/survival_sim.py``).

With ``--naive-branches`` the harness measures the leverage of each of my picks instead: for
every listed pick k it replays the finished draft in ``--base`` up to that pick, takes the
consensus player (best available by the ADP order, here Basketball Monster's rank) in place of
the planner's choice, and lets the planner finish the draft. The base run's settings are reused.
``scripts/mock_leverage.py`` reads the result.

All randomness is keyed by (seed, overall pick) so that runs with the same seed under different
settings face the same opponents making the same draws; they differ only through the players
still on the board. One JSON file per mock lands in the output directory;
``scripts/mock_study_report.py`` turns one study into tables and a report and
``scripts/mock_compare.py`` compares several.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from pickandroll.availability.survival import SurvivalTable
from pickandroll.draft import DraftState, LeagueSettings
from pickandroll.draft.autopick import (
    STRATEGIES,
    draw_team_punts,
    latent_slots,
    lp_choices,
    softmax_choice,
    team_label,
)
from pickandroll.optim.horizon import solve_horizon
from pickandroll.optim.objective import DEFAULT_SIGMA, CategoryCurve
from pickandroll.optim.roster import punt_sets
from pickandroll.projections.schema import NINE_CAT, Cat
from pickandroll.sources.bbm import load_bbm

DEFAULT_PROJECTIONS = ROOT / "data" / "bbm_ros_pergame_2026-09-21.xls"
NOISE = 1.0
MAX_PUNTS = 2


@dataclass(frozen=True)
class Config:
    """Everything a worker needs to reproduce a run: the planner's settings and data paths."""

    projections: str
    objective: str = "sum"  # "sum" of category totals or "win" (category curve)
    max_punts: int = MAX_PUNTS  # punt scan width for the sum objective (0 = never punt)
    curve: str | None = None  # JSON with per-category mu/sigma, else the default curve
    sigma: float = DEFAULT_SIGMA  # sigma of the default curve when no curve file is given
    sigma_scale: float = 1.0  # multiplies every sigma (sensitivity runs)
    availability: str = "adp"  # "adp" model or "survival" table
    survival: str | None = None  # path of the survival table for --availability survival
    plan_candidates: int | None = None  # candidates per pick in the plan (None = all)
    time_limit: float = 10.0  # seconds per plan solve
    gap: float = 0.0  # relative MIP gap per plan solve

    def __post_init__(self) -> None:
        if self.objective not in ("sum", "win"):
            raise ValueError("objective must be sum or win")
        if self.availability not in ("adp", "survival"):
            raise ValueError("availability must be adp or survival")
        if self.availability == "survival" and not self.survival:
            raise ValueError("--availability survival needs --survival PATH")
        if self.max_punts < 0:
            raise ValueError("max_punts must be non-negative")


_PROJECTIONS: dict[str, object] = {}
_SURVIVAL: dict[str, SurvivalTable] = {}
_CURVES: dict[str, CategoryCurve] = {}


def load_curve(cfg: Config) -> CategoryCurve | None:
    """The category curve a config asks for, cached per worker; ``None`` for the sum objective."""
    if cfg.objective != "win":
        return None
    key = f"{cfg.curve}|{cfg.sigma}|{cfg.sigma_scale}"
    if key not in _CURVES:
        if cfg.curve:
            spec = json.loads(Path(cfg.curve).read_text())
            curve = CategoryCurve(
                mu={Cat(c): float(v) for c, v in spec["mu"].items()},
                sigma={Cat(c): float(v) for c, v in spec["sigma"].items()},
            )
        else:
            curve = CategoryCurve.default(NINE_CAT, sigma=cfg.sigma)
        if cfg.sigma_scale != 1.0:
            curve = CategoryCurve(
                mu=dict(curve.mu),
                sigma={c: v * cfg.sigma_scale for c, v in curve.sigma.items()},
                breaks=curve.breaks,
            )
        _CURVES[key] = curve
    return _CURVES[key]


def load_survival(cfg: Config) -> SurvivalTable | None:
    if cfg.availability != "survival":
        return None
    if cfg.survival not in _SURVIVAL:
        _SURVIVAL[cfg.survival] = SurvivalTable.load(Path(cfg.survival))
    return _SURVIVAL[cfg.survival]


def punt_label(punt) -> str:
    return "/".join(c.value for c in sorted(punt, key=NINE_CAT.index)) or "-"


def parse_punt(label: str) -> frozenset[Cat]:
    return frozenset() if label in ("-", "") else frozenset(Cat(v) for v in label.split("/"))


def projections(path: Path):
    key = str(path)
    if key not in _PROJECTIONS:
        _PROJECTIONS[key] = load_bbm(path, horizon="season")
    return _PROJECTIONS[key]


def new_state(cfg: Config, slot: int) -> DraftState:
    state = DraftState(
        settings=LeagueSettings(),
        projections=projections(Path(cfg.projections)),
        my_team="me",
        my_position=slot,
    )
    state.curve = load_curve(cfg)
    state.survival = load_survival(cfg)
    state.plan_candidates = cfg.plan_candidates
    return state


def rng(seed: int, *keys: int) -> np.random.Generator:
    return np.random.default_rng([seed, *keys])


# --------------------------------------------------------------------------- design
def make_design(seed: int, slot: int, state: DraftState) -> dict:
    """Which drafter every other team uses, drawn independently and uniformly."""
    draw = rng(seed, 7)
    strategies = {}
    for position in range(1, state.settings.num_teams + 1):
        if position == slot:
            continue
        strategies[position] = STRATEGIES[int(draw.integers(len(STRATEGIES)))]
    punts = draw_team_punts(state, rng(seed, 999))
    return {
        "seed": seed,
        "slot": slot,
        "strategies": strategies,
        "team_punts": {team: punt_label(p) for team, p in punts.items()},
    }


def latent_boards(design: dict, state: DraftState) -> dict[int, pd.Series]:
    """One private noisy ADP board per adp team, drawn on the full player pool."""
    boards = {}
    for position, strategy in design["strategies"].items():
        if strategy == "adp":
            boards[position] = latent_slots(state, rng(design["seed"], 100 + position), NOISE)
    return boards


# --------------------------------------------------------------------------- picks
def pick_features(state: DraftState, player: str, adp: pd.Series) -> dict:
    """Where the chosen player sat on the board at the time of the pick."""
    available = state.available
    totals = state.z.loc[available, "total"]
    chosen_total = float(totals[player])
    board_adp = adp.reindex(available)
    return {
        "z_total": round(chosen_total, 3),
        "z_rank": int((totals > chosen_total).sum()) + 1,
        "z_gap": round(float(totals.max() - chosen_total), 3),
        "adp": float(board_adp[player]),
        "adp_rank": int((board_adp < board_adp[player]).sum()) + 1,
        "positions": state.projections.df.at[player, "positions"],
    }


def other_pick(state: DraftState, design: dict, boards: dict, adp: pd.Series) -> dict:
    overall = state.next_overall
    rnd, position = state.owner_of(overall)
    team = team_label(state, position)
    strategy = design["strategies"][position]
    draw = rng(design["seed"], overall)
    if strategy == "adp":
        slots = boards[position].reindex(state.available).dropna()
        chosen = str(slots.idxmin())
    elif strategy == "lp":
        punt = parse_punt(design["team_punts"][team])
        chosen = softmax_choice(lp_choices(state, team, punt), draw, NOISE)
    else:
        chosen = softmax_choice(state.z.loc[state.available, "total"], draw, NOISE)
    features = pick_features(state, chosen, adp)
    state.apply_pick(team, chosen)
    return {
        "overall": overall,
        "round": rnd,
        "position": position,
        "team": team,
        "strategy": strategy,
        "player": chosen,
        **features,
    }


def my_pick(
    state: DraftState, k: int, punt: frozenset[Cat] | None, adp: pd.Series, cfg: Config
) -> dict:
    """Solve for my pick and make it. ``punt=None`` lets the punt scan choose (sum objective);
    the win objective never punts explicitly, its curve soft-punts on its own."""
    started = time.perf_counter()
    scan = None
    if punt is not None:
        chosen = punt
    elif cfg.objective == "win" or cfg.max_punts == 0:
        chosen = frozenset()
    else:
        chosen = state.choose_punt(max_punts=cfg.max_punts, workers=1)
        table = state.last_punt_scan
        scan = {row.punt: round(float(row.objective), 3) for row in table.itertuples()}
    solution = solve_horizon(state.horizon_problem(chosen), time_limit=cfg.time_limit, gap=cfg.gap)
    player = solution.first_pick
    if player is None:
        raise RuntimeError("empty plan")
    wins = solution.expected_wins
    record = {
        "k": k,
        "overall": state.next_overall,
        "punt": punt_label(chosen),
        "objective": round(float(solution.objective), 3),
        "locked_value": round(state.roster_value(chosen), 3),
        "locked_wins": (None if wins is None else round(float(state.roster_wins(chosen)), 3)),
        "expected_wins": (
            None if wins is None else {c.value: round(float(v), 3) for c, v in wins.items()}
        ),
        "player": player,
        "plan": [
            {
                "pick": int(r.pick),
                "player": r.player,
                "availability": round(float(r.availability), 4),
            }
            for r in solution.plan.itertuples()
        ],
        "expected": {c.value: round(float(v), 3) for c, v in solution.expected_totals.items()},
        "scan": scan,
        "status": solution.status,
        "plan_seconds": round(float(solution.solve_seconds), 2),
        "solve_ms": round((time.perf_counter() - started) * 1000),
        "replayed": False,
        **pick_features(state, player, adp),
    }
    state.apply_pick(state.my_team, player)
    return record


def naive_pick(state: DraftState, k: int, adp: pd.Series) -> dict:
    """The consensus pick: the best available player by the ADP order, no model."""
    board = adp.reindex(state.available).dropna()
    player = str(board.idxmin())
    record = {
        "k": k,
        "overall": state.next_overall,
        "punt": "-",
        "objective": None,
        "locked_value": None,
        "locked_wins": None,
        "expected_wins": None,
        "player": player,
        "plan": [],
        "expected": {},
        "scan": None,
        "status": "naive",
        "plan_seconds": 0.0,
        "solve_ms": 0,
        "replayed": False,
        "naive": True,
        **pick_features(state, player, adp),
    }
    state.apply_pick(state.my_team, player)
    return record


# --------------------------------------------------------------------------- scoring
def team_value(
    state: DraftState, roster: list[str], punt: frozenset[Cat], level: pd.Series
) -> float:
    active = [c.value for c in state.settings.cats if c not in punt]
    if not roster or not active:
        return 0.0
    above = state.z.loc[roster, active] - level[active]
    return float(above.sum().sum())


def finish(state: DraftState, design: dict, records: list[dict]) -> dict:
    """Final scores for me and every other team, each under its own best punt (the sum-of-z
    scoreboard, whichever objective drafted the roster)."""
    level = state.replacement_level()
    sets = punt_sets(state.settings.cats, MAX_PUNTS)
    cats = [c.value for c in state.settings.cats]
    rosters: dict[str, list[str]] = {}
    for p in state.picks:
        rosters.setdefault(p.team, []).append(p.player_id)
    teams = {}
    for position in range(1, state.settings.num_teams + 1):
        team = team_label(state, position)
        roster = rosters.get(team, [])
        values = {punt_label(p): team_value(state, roster, p, level) for p in sets}
        best = max(values, key=values.get)
        teams[team] = {
            "position": position,
            "strategy": "me" if team == state.my_team else design["strategies"][position],
            "punt": None if team == state.my_team else design["team_punts"][team],
            "value_best": round(values[best], 3),
            "punt_best": best,
            "value_nopunt": round(values["-"], 3),
            "z": {c: round(float(state.z.loc[roster, c].sum()), 3) for c in cats},
            "roster": roster,
        }
    mine = teams[state.my_team]
    my_values = {punt_label(p): team_value(state, rosters[state.my_team], p, level) for p in sets}
    last_punt = records[-1]["punt"]
    first_punt = records[0]["punt"]
    return {
        "value_best": mine["value_best"],
        "punt_best": mine["punt_best"],
        "value_last_punt": round(my_values[last_punt], 3),
        "punt_last": last_punt,
        "value_first_punt": round(my_values[first_punt], 3),
        "punt_first": first_punt,
        "value_nopunt": mine["value_nopunt"],
        "values": {k: round(v, 3) for k, v in my_values.items()},
        "teams": teams,
    }


# --------------------------------------------------------------------------- runs
def run_draft(
    cfg: Config,
    design: dict,
    fixed_from: int | None = None,
    punt: frozenset[Cat] | None = None,
    prefix: list[dict] | None = None,
    prefix_records: list[dict] | None = None,
    naive_at: int | None = None,
) -> dict:
    """One full draft. With ``fixed_from`` the picks in ``prefix`` are replayed first and the
    punt is held from my ``fixed_from``-th pick onward. With ``naive_at`` my ``naive_at``-th
    pick is the consensus player instead of the planner's choice."""
    started = time.perf_counter()
    state = new_state(cfg, design["slot"])
    boards = latent_boards(design, state)
    adp = state.effective_adp()
    log: list[dict] = []
    records: list[dict] = []
    replay = {row["overall"]: row for row in (prefix or [])}
    replayed_records = {row["overall"]: row for row in (prefix_records or [])}
    k = 0
    while not state.complete:
        overall = state.next_overall
        if overall in replay:
            row = replay[overall]
            state.apply_pick(row["team"], row["player"])
            log.append(row)
            if overall in replayed_records:
                k += 1
                records.append({**replayed_records[overall], "replayed": True})
            continue
        if state.on_the_clock:
            k += 1
            hold = punt if fixed_from is not None and k >= fixed_from else None
            if naive_at is not None and k == naive_at:
                record = naive_pick(state, k, adp)
            else:
                record = my_pick(state, k, hold, adp, cfg)
            records.append(record)
            log.append(
                {
                    "overall": overall,
                    "round": state.owner_of(overall)[0],
                    "position": design["slot"],
                    "team": state.my_team,
                    "strategy": "me",
                    "player": record["player"],
                    "z_total": record["z_total"],
                    "z_rank": record["z_rank"],
                    "z_gap": record["z_gap"],
                    "adp": record["adp"],
                    "adp_rank": record["adp_rank"],
                    "positions": record["positions"],
                }
            )
        else:
            log.append(other_pick(state, design, boards, adp))
    return {
        "fixed_from": fixed_from,
        "punt_fixed": punt_label(punt) if punt is not None else None,
        "naive_at": naive_at,
        "my_picks": records,
        "picks": log,
        "final": finish(state, design, records),
        "seconds": round(time.perf_counter() - started, 1),
    }


def run_mock(cfg: Config, seed: int, slot: int, branches: list[int]) -> dict:
    state = new_state(cfg, slot)
    design = make_design(seed, slot, state)
    auto = run_draft(cfg, design)
    my_overall = state.my_picks
    runs = {"auto": auto}
    for k in branches:
        if k < 1 or k > len(my_overall):
            continue
        cut = my_overall[k - 1]
        prefix = [row for row in auto["picks"] if row["overall"] < cut]
        prefix_records = [rec for rec in auto["my_picks"] if rec["overall"] < cut]
        punt = parse_punt(auto["my_picks"][k - 1]["punt"])
        runs[f"fix{k}"] = run_draft(cfg, design, k, punt, prefix, prefix_records)
    return {
        "seed": seed,
        "slot": slot,
        "design": design,
        "config": asdict(cfg),
        "my_overall": my_overall,
        "benchmark": auto["my_picks"][0]["objective"],
        "benchmark_punt": auto["my_picks"][0]["punt"],
        "runs": runs,
    }


def run_leverage(base: dict, ks: list[int]) -> dict:
    """Branch a finished draft at each of my picks in ``ks`` with the consensus pick made
    there, the planner drafting the rest; the base run's settings and design are reused."""
    cfg = Config(**base["config"])
    design = dict(base["design"])
    design["strategies"] = {int(k): v for k, v in design["strategies"].items()}  # JSON keys
    auto = base["runs"]["auto"]
    my_overall = base["my_overall"]
    runs = {"auto": auto}
    for k in ks:
        if k < 1 or k > len(my_overall):
            continue
        cut = my_overall[k - 1]
        prefix = [row for row in auto["picks"] if row["overall"] < cut]
        prefix_records = [rec for rec in auto["my_picks"] if rec["overall"] < cut]
        runs[f"naive{k}"] = run_draft(
            cfg, design, prefix=prefix, prefix_records=prefix_records, naive_at=k
        )
    return {
        "seed": base["seed"],
        "slot": base["slot"],
        "design": design,
        "config": base["config"],
        "my_overall": my_overall,
        "benchmark": base["benchmark"],
        "benchmark_punt": base["benchmark_punt"],
        "runs": runs,
    }


def _job(args: tuple[Config, str, int, int, list[int]]) -> tuple[int, str, float]:
    cfg, out, seed, slot, branches = args
    started = time.perf_counter()
    result = run_mock(cfg, seed, slot, branches)
    target = Path(out) / f"mock_{seed:03d}.json"
    target.write_text(json.dumps(result))
    return seed, slot, time.perf_counter() - started


def _leverage_job(args: tuple[str, str, int, list[int]]) -> tuple[int, str, float]:
    base_dir, out, seed, ks = args
    started = time.perf_counter()
    base = json.loads((Path(base_dir) / f"mock_{seed:03d}.json").read_text())
    result = run_leverage(base, ks)
    target = Path(out) / f"mock_{seed:03d}.json"
    target.write_text(json.dumps(result))
    return seed, base["slot"], time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mocks", type=int, default=100)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--projections", type=Path, default=DEFAULT_PROJECTIONS)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument(
        "--branches",
        default="",
        help="my picks at which to branch with the punt held (comma list, empty for none)",
    )
    parser.add_argument("--objective", choices=("sum", "win"), default="sum")
    parser.add_argument("--max-punts", type=int, default=MAX_PUNTS)
    parser.add_argument("--curve", type=Path, default=None, help="JSON with mu/sigma per cat")
    parser.add_argument("--sigma", type=float, default=DEFAULT_SIGMA)
    parser.add_argument("--sigma-scale", type=float, default=1.0)
    parser.add_argument("--availability", choices=("adp", "survival"), default="adp")
    parser.add_argument("--survival", type=Path, default=None)
    parser.add_argument("--plan-candidates", type=int, default=None)
    parser.add_argument("--time-limit", type=float, default=10.0)
    parser.add_argument("--gap", type=float, default=0.0)
    parser.add_argument(
        "--naive-branches",
        default="",
        help="leverage mode: my picks at which to substitute the consensus pick (comma list)",
    )
    parser.add_argument("--base", type=Path, default=None, help="finished study for leverage mode")
    args = parser.parse_args()
    naive = [int(b) for b in args.naive_branches.split(",") if b.strip()]
    if naive:
        if args.base is None:
            raise SystemExit("--naive-branches needs --base DIR")
        run_leverage_main(args, naive)
        return
    cfg = Config(
        projections=str(args.projections),
        objective=args.objective,
        max_punts=args.max_punts,
        curve=str(args.curve) if args.curve else None,
        sigma=args.sigma,
        sigma_scale=args.sigma_scale,
        availability=args.availability,
        survival=str(args.survival) if args.survival else None,
        plan_candidates=args.plan_candidates,
        time_limit=args.time_limit,
        gap=args.gap,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    branches = [int(b) for b in args.branches.split(",") if b.strip()]
    jobs = []
    for i in range(args.mocks):
        seed = args.first_seed + i
        slot = (seed % 12) + 1
        if (args.out / f"mock_{seed:03d}.json").exists():
            continue
        jobs.append((cfg, str(args.out), seed, slot, branches))
    (args.out / "manifest.json").write_text(
        json.dumps(
            {
                "projections": args.projections.name,
                "mocks": args.mocks,
                "first_seed": args.first_seed,
                "branches": branches,
                "noise": NOISE,
                "max_punts": cfg.max_punts,
                "config": asdict(cfg),
                "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            indent=2,
        )
    )
    print(f"{len(jobs)} mocks to run with {args.workers} workers -> {args.out}", flush=True)
    started = time.perf_counter()
    done = 0
    if args.workers == 1:
        for job in jobs:
            seed, slot, seconds = _job(job)
            done += 1
            print(f"[{done}/{len(jobs)}] seed {seed} slot {slot} {seconds:.0f}s", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_job, job) for job in jobs]
            for future in as_completed(futures):
                seed, slot, seconds = future.result()
                done += 1
                elapsed = time.perf_counter() - started
                eta = elapsed / done * (len(jobs) - done)
                print(
                    f"[{done}/{len(jobs)}] seed {seed} slot {slot} {seconds:.0f}s "
                    f"(elapsed {elapsed / 60:.1f} min, eta {eta / 60:.1f} min)",
                    flush=True,
                )
    print(f"done in {(time.perf_counter() - started) / 60:.1f} min", flush=True)


def run_leverage_main(args, ks: list[int]) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i in range(args.mocks):
        seed = args.first_seed + i
        if (args.out / f"mock_{seed:03d}.json").exists():
            continue
        if not (args.base / f"mock_{seed:03d}.json").exists():
            continue
        jobs.append((str(args.base), str(args.out), seed, ks))
    (args.out / "manifest.json").write_text(
        json.dumps(
            {
                "mode": "leverage",
                "base": str(args.base),
                "naive_branches": ks,
                "mocks": args.mocks,
                "first_seed": args.first_seed,
                "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            indent=2,
        )
    )
    print(f"{len(jobs)} leverage mocks with {args.workers} workers -> {args.out}", flush=True)
    started = time.perf_counter()
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_leverage_job, job) for job in jobs]
        for future in as_completed(futures):
            seed, slot, seconds = future.result()
            done += 1
            elapsed = time.perf_counter() - started
            eta = elapsed / done * (len(jobs) - done)
            print(
                f"[{done}/{len(jobs)}] seed {seed} slot {slot} {seconds:.0f}s "
                f"(elapsed {elapsed / 60:.1f} min, eta {eta / 60:.1f} min)",
                flush=True,
            )
    print(f"done in {(time.perf_counter() - started) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
