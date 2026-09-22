"""Tables, charts and a report from a mock-draft study run by ``scripts/mock_study.py``.

    python scripts/mock_study_report.py data/studies/2026-09-22

Writes ``tables/*.csv``, ``report.html`` (self-contained, inline SVG charts) and ``summary.md``
into the study directory and prints the summary.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pickandroll.draft import DraftState, LeagueSettings
from pickandroll.projections.schema import NINE_CAT
from pickandroll.sources.bbm import load_bbm

CATS = [c.value for c in NINE_CAT]
CAT_NAMES = {
    "pts": "PTS",
    "threes": "3PM",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "tov": "TO",
    "fg_pct": "FG%",
    "ft_pct": "FT%",
}
STRATEGY_NAMES = {"z": "z-score", "adp": "ADP", "lp": "LP", "me": "me"}


def _ok(v: object) -> bool:
    """True unless ``v`` is NaN."""
    return not (isinstance(v, float) and math.isnan(v))


PALETTE = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#be185d", "#4b5563"]


def punt_name(label: str) -> str:
    return (
        "none" if label in ("-", "", None) else " + ".join(CAT_NAMES[c] for c in label.split("/"))
    )


# --------------------------------------------------------------------------- loading
def load(study: Path) -> list[dict]:
    files = sorted(study.glob("mock_*.json"))
    if not files:
        raise SystemExit(f"no mock_*.json in {study}")
    return [json.loads(f.read_text()) for f in files]


_PROJECTIONS: dict[str, object] = {}


def base_state(study: Path, slot: int) -> DraftState:
    """A fresh draft state on the projections the study used."""
    manifest = json.loads((study / "manifest.json").read_text())
    path = ROOT / "data" / manifest["projections"]
    key = str(path)
    if key not in _PROJECTIONS:
        _PROJECTIONS[key] = load_bbm(path, horizon="season")
    return DraftState(
        settings=LeagueSettings(), projections=_PROJECTIONS[key], my_team="me", my_position=slot
    )


def dream_benchmark(mock: dict, study: Path) -> dict:
    """Value of the first plan if every planned player had fallen to me, on the board as it
    stood at my first pick, and how much of that roster I ended up with."""
    auto = mock["runs"]["auto"]
    first = auto["my_picks"][0]
    state = base_state(study, mock["slot"])
    for row in auto["picks"]:
        if row["overall"] >= first["overall"]:
            break
        state.apply_pick(row["team"], row["player"])
    level = state.replacement_level()
    punt = set(first["punt"].split("/")) if first["punt"] != "-" else set()
    active = [c for c in CATS if c not in punt]
    planned = [p["player"] for p in first["plan"]]
    above = state.z.loc[planned, active] - level[active]
    final_roster = set(auto["final"]["teams"]["me"]["roster"])
    return {
        "dream": round(float(above.to_numpy().sum()), 3),
        "dream_share": round(len(final_roster & set(planned)) / max(1, len(planned)), 3),
    }


def cats_won(mine: dict, other: dict) -> int:
    return sum(1 for c in CATS if mine[c] > other[c])


def run_row(mock: dict, name: str, run: dict) -> dict:
    final = run["final"]
    teams = final["teams"]
    me = teams["me"]
    values = sorted((t["value_best"] for t in teams.values()), reverse=True)
    rank = values.index(me["value_best"]) + 1
    won = {}
    beaten = 0
    for team, info in teams.items():
        if team == "me":
            continue
        w = cats_won(me["z"], info["z"])
        won.setdefault(info["strategy"], []).append(w)
        beaten += w >= 5
    all_won = [w for ws in won.values() for w in ws]
    punts = [r["punt"] for r in run["my_picks"]]
    switches = sum(1 for a, b in pairwise(punts) if a != b)
    return {
        "seed": mock["seed"],
        "slot": mock["slot"],
        "run": name,
        "fixed_from": run["fixed_from"] if run["fixed_from"] is not None else 13,
        "punt_fixed": run["punt_fixed"],
        "benchmark": mock["benchmark"],
        "benchmark_punt": mock["benchmark_punt"],
        "value_best": final["value_best"],
        "punt_best": final["punt_best"],
        "value_last_punt": final["value_last_punt"],
        "punt_last": final["punt_last"],
        "value_nopunt": final["value_nopunt"],
        "vs_bench": round(final["value_best"] - mock["benchmark"], 3),
        "rank": rank,
        "cats_won": float(np.mean(all_won)),
        "cats_won_z": float(np.mean(won["z"])) if "z" in won else np.nan,
        "cats_won_adp": float(np.mean(won["adp"])) if "adp" in won else np.nan,
        "cats_won_lp": float(np.mean(won["lp"])) if "lp" in won else np.nan,
        "opponents_beaten": beaten,
        "switches": switches,
        "distinct_punts": len(set(punts)),
        "seconds": run["seconds"],
    }


def frames(mocks: list[dict], study: Path) -> dict[str, pd.DataFrame]:
    state = base_state(study, 1)
    z = state.z
    # How much more the model likes a player than the market: z rank minus ADP rank (negative
    # means the model ranks him higher than his ADP does).
    market_gap = (
        z["total"].rank(ascending=False) - state.effective_adp().rank(ascending=True)
    ).rename("market_gap")
    runs, mypicks, picks, plans, teams = [], [], [], [], []
    for mock in mocks:
        design = mock["design"]
        dream = dream_benchmark(mock, study)
        counts = pd.Series(list(design["strategies"].values())).value_counts()
        for name, run in mock["runs"].items():
            row = run_row(mock, name, run)
            row.update(dream)
            row["vs_dream"] = round(row["value_best"] - dream["dream"], 3)
            row.update(
                {
                    "n_z": int(counts.get("z", 0)),
                    "n_adp": int(counts.get("adp", 0)),
                    "n_lp": int(counts.get("lp", 0)),
                }
            )
            runs.append(row)
            prev = None
            for rec in run["my_picks"]:
                scan = rec.get("scan") or {}
                ordered = sorted(scan.values(), reverse=True)
                margin = ordered[0] - ordered[1] if len(ordered) > 1 else np.nan
                prev_loss = (ordered[0] - scan[prev]) if scan and prev in scan else np.nan
                mypicks.append(
                    {
                        "seed": mock["seed"],
                        "slot": mock["slot"],
                        "run": name,
                        "fixed_from": row["fixed_from"],
                        "k": rec["k"],
                        "overall": rec["overall"],
                        "punt": rec["punt"],
                        "objective": rec["objective"],
                        "vs_bench": round(rec["objective"] - mock["benchmark"], 3),
                        "locked_value": rec["locked_value"],
                        "player": rec["player"],
                        "z_rank": rec["z_rank"],
                        "adp_rank": rec["adp_rank"],
                        "replayed": rec["replayed"],
                        "switched": prev is not None and rec["punt"] != prev,
                        "prev_punt": prev,
                        "margin": margin,
                        "prev_loss": prev_loss,
                        "solve_ms": rec["solve_ms"],
                    }
                )
                prev = rec["punt"]
            if name != "auto":
                continue
            taken_at = {p["player"]: p for p in run["picks"]}
            for p in run["picks"]:
                picks.append(
                    {
                        "seed": mock["seed"],
                        "slot": mock["slot"],
                        **{
                            k: p[k]
                            for k in (
                                "overall",
                                "round",
                                "position",
                                "team",
                                "strategy",
                                "player",
                                "z_total",
                                "z_rank",
                                "z_gap",
                                "adp",
                                "adp_rank",
                                "positions",
                            )
                        },
                        "team_punt": design["team_punts"].get(p["team"])
                        if p["strategy"] == "lp"
                        else None,
                    }
                )
            for rec in run["my_picks"]:
                for planned in rec["plan"]:
                    j = planned["pick"]
                    if j == rec["overall"]:
                        continue
                    hit = taken_at.get(planned["player"])
                    taker = hit["team"] if hit and hit["overall"] < j else None
                    realized = taker is None or taker == "me"
                    plans.append(
                        {
                            "seed": mock["seed"],
                            "slot": mock["slot"],
                            "k": rec["k"],
                            "from_overall": rec["overall"],
                            "pick": j,
                            "player": planned["player"],
                            "p": planned["availability"],
                            "punt": rec["punt"],
                            "realized": realized,
                            "taker": taker,
                            "taker_strategy": hit["strategy"] if taker and taker != "me" else None,
                            "taker_punt": design["team_punts"].get(taker)
                            if taker and hit["strategy"] == "lp"
                            else None,
                            "taken_at": hit["overall"] if hit else None,
                        }
                    )
            for team, info in run["final"]["teams"].items():
                teams.append(
                    {
                        "seed": mock["seed"],
                        "slot": mock["slot"],
                        "team": team,
                        "position": info["position"],
                        "strategy": info["strategy"],
                        "team_punt": info["punt"],
                        "value_best": info["value_best"],
                        "punt_best": info["punt_best"],
                        **{f"z_{c}": info["z"][c] for c in CATS},
                    }
                )
    return {
        "runs": pd.DataFrame(runs),
        "mypicks": pd.DataFrame(mypicks),
        "picks": pd.DataFrame(picks).join(z[CATS].add_prefix("z_"), on="player"),
        "plans": pd.DataFrame(plans).join(market_gap, on="player"),
        "teams": pd.DataFrame(teams),
    }


# --------------------------------------------------------------------------- statistics
def mean_ci(values: Sequence[float]) -> tuple[float, float, int]:
    arr = np.asarray([v for v in values if _ok(v)], dtype=float)
    n = len(arr)
    if n == 0:
        return math.nan, math.nan, 0
    half = 1.96 * arr.std(ddof=1) / math.sqrt(n) if n > 1 else math.nan
    return float(arr.mean()), float(half), n


def ols(y: np.ndarray, X: pd.DataFrame) -> pd.DataFrame:
    """Plain least squares with conventional standard errors."""
    A = np.column_stack([np.ones(len(X)), X.to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    dof = max(1, len(y) - A.shape[1])
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.pinv(A.T @ A)
    se = np.sqrt(np.diag(cov))
    names = ["intercept", *X.columns]
    out = pd.DataFrame({"coef": beta, "se": se}, index=names)
    out["t"] = out["coef"] / out["se"]
    return out


def softmax_rows(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit_logistic(
    X: np.ndarray,
    y: np.ndarray,
    classes: list[str],
    l2: float = 1e-2,
    steps: int = 3000,
    lr: float = 0.1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Multinomial logistic regression by gradient descent on standardized features."""
    mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
    Xs = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    Y = np.zeros((len(y), len(classes)))
    for i, label in enumerate(y):
        Y[i, classes.index(label)] = 1.0
    W = np.zeros((Xs.shape[1], len(classes)))
    for _ in range(steps):
        P = softmax_rows(Xs @ W)
        grad = Xs.T @ (P - Y) / len(y) + l2 * np.vstack([np.zeros((1, len(classes))), W[1:]])
        W -= lr * grad
    return W, mu, sd


def predict_logistic(
    W: np.ndarray, mu: np.ndarray, sd: np.ndarray, X: np.ndarray, classes: list[str]
) -> list[str]:
    Xs = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    return [classes[i] for i in softmax_rows(Xs @ W).argmax(axis=1)]


# --------------------------------------------------------------------------- analyses
def team_features(picks: pd.DataFrame, rounds: int) -> pd.DataFrame:
    """Per-team summary of the picks made in the first ``rounds`` rounds."""
    sub = picks[(picks["strategy"] != "me") & (picks["round"] <= rounds)]
    g = sub.groupby(["seed", "team"])
    profile = g[[f"z_{c}" for c in CATS]].sum()
    feats = pd.DataFrame(
        {
            "strategy": g["strategy"].first(),
            "team_punt": g["team_punt"].first(),
            "mean_log_zrank": g["z_rank"].apply(lambda s: float(np.log(s).mean())),
            "share_z_top1": g["z_rank"].apply(lambda s: float((s == 1).mean())),
            "share_z_top3": g["z_rank"].apply(lambda s: float((s <= 3).mean())),
            "mean_zgap": g["z_gap"].mean(),
            "max_zgap": g["z_gap"].max(),
            "mean_log_adprank": g["adp_rank"].apply(lambda s: float(np.log(s).mean())),
            "share_adp_top3": g["adp_rank"].apply(lambda s: float((s <= 3).mean())),
            "mean_rank_diff": g.apply(
                lambda d: float((np.log(d["z_rank"]) - np.log(d["adp_rank"])).mean())
            ),
            "sd_log_zrank": g["z_rank"].apply(lambda s: float(np.log(s).std(ddof=0))),
            "profile_min": profile.min(axis=1),
            "profile_spread": profile.max(axis=1) - profile.min(axis=1),
        }
    )
    return feats.reset_index()


FEATURES = [
    "mean_log_zrank",
    "share_z_top1",
    "share_z_top3",
    "mean_zgap",
    "max_zgap",
    "mean_log_adprank",
    "share_adp_top3",
    "mean_rank_diff",
    "sd_log_zrank",
    "profile_min",
    "profile_spread",
]


def detection(picks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    """Can a team's drafter be told from its picks? Train on the first half of the mocks,
    test on the second, at several points of the draft."""
    classes = ["z", "adp", "lp"]
    seeds = sorted(picks["seed"].unique())
    cut = seeds[len(seeds) // 2] if len(seeds) > 1 else seeds[0] + 1
    rows, confusion, centroids = [], None, None
    for rounds in (2, 3, 4, 5, 7, 9, 13):
        feats = team_features(picks, rounds)
        train = feats[feats["seed"] < cut]
        test = feats[feats["seed"] >= cut]
        if len(train) < 10 or len(test) < 5:
            continue
        W, mu, sd = fit_logistic(
            train[FEATURES].to_numpy(float), train["strategy"].tolist(), classes
        )
        pred = predict_logistic(W, mu, sd, test[FEATURES].to_numpy(float), classes)
        truth = test["strategy"].tolist()
        punts = test["team_punt"].tolist()
        hits = [p == t for p, t in zip(pred, truth, strict=True)]
        row = {"rounds_seen": rounds, "teams_tested": len(test), "accuracy": float(np.mean(hits))}
        for c in classes:
            sel = [h for h, t in zip(hits, truth, strict=True) if t == c]
            row[f"recall_{c}"] = float(np.mean(sel)) if sel else np.nan
        with_punt = [
            h for h, t, q in zip(hits, truth, punts, strict=True) if t == "lp" and q != "-"
        ]
        no_punt = [h for h, t, q in zip(hits, truth, punts, strict=True) if t == "lp" and q == "-"]
        row["recall_lp_with_punt"] = float(np.mean(with_punt)) if with_punt else np.nan
        row["recall_lp_no_punt"] = float(np.mean(no_punt)) if no_punt else np.nan
        rows.append(row)
        if rounds in (5, 13):
            conf = pd.crosstab(
                pd.Series(truth, name="actual"), pd.Series(pred, name="predicted")
            ).reindex(index=classes, columns=classes, fill_value=0)
            conf.insert(0, "rounds_seen", rounds)
            confusion = conf if confusion is None else pd.concat([confusion, conf])
        if rounds == 13:
            centroids = feats.groupby("strategy")[FEATURES].mean().T
    return pd.DataFrame(rows), confusion, centroids


def implied_punts(picks: pd.DataFrame) -> pd.DataFrame:
    """Is the weakest category of a team's roster so far its punt? LP teams with a punt
    should show it; z-score, ADP and no-punt LP teams give the false-positive baseline."""
    rows = []
    for rounds in (3, 5, 8, 13):
        sub = picks[(picks["strategy"] != "me") & (picks["round"] <= rounds)]
        if sub.empty:
            continue
        g = sub.groupby(["seed", "team"])
        profile = g[[f"z_{c}" for c in CATS]].sum()
        meta = g[["strategy", "team_punt"]].first()
        meta["weakest"] = profile.idxmin(axis=1).str.replace("z_", "", regex=False)
        meta["weakest_z"] = profile.min(axis=1)
        lp_punt = meta[(meta["strategy"] == "lp") & (meta["team_punt"] != "-")]
        hit = [
            w in q.split("/") for w, q in zip(lp_punt["weakest"], lp_punt["team_punt"], strict=True)
        ]
        rows.append(
            {
                "rounds_seen": rounds,
                "lp_teams_with_punt": len(lp_punt),
                "weakest_cat_is_punt": float(np.mean(hit)) if hit else np.nan,
                "weakest_z_lp_with_punt": float(lp_punt["weakest_z"].mean()),
                "weakest_z_lp_no_punt": float(
                    meta[(meta["strategy"] == "lp") & (meta["team_punt"] == "-")][
                        "weakest_z"
                    ].mean()
                ),
                "weakest_z_zscore_teams": float(meta[meta["strategy"] == "z"]["weakest_z"].mean()),
                "weakest_z_adp_teams": float(meta[meta["strategy"] == "adp"]["weakest_z"].mean()),
            }
        )
    return pd.DataFrame(rows)


def analyse(f: dict[str, pd.DataFrame]) -> dict:
    runs, mypicks, picks, plans, teams = f["runs"], f["mypicks"], f["picks"], f["plans"], f["teams"]
    auto = runs[runs["run"] == "auto"].set_index("seed")
    fix1 = runs[runs["run"] == "fix1"].set_index("seed")
    out: dict = {"n_mocks": len(auto)}

    # 1. final vs benchmark
    out["auto_vs_bench"] = mean_ci(auto["vs_bench"])
    out["fix1_vs_bench"] = mean_ci(fix1["vs_bench"]) if len(fix1) else (math.nan, math.nan, 0)
    out["auto_share_above"] = float((auto["vs_bench"] >= 0).mean())
    out["fix1_share_above"] = float((fix1["vs_bench"] >= 0).mean()) if len(fix1) else math.nan
    out["benchmark_mean"] = mean_ci(auto["benchmark"])
    out["auto_final_mean"] = mean_ci(auto["value_best"])
    out["fix1_final_mean"] = mean_ci(fix1["value_best"]) if len(fix1) else (math.nan, math.nan, 0)
    out["auto_rank"] = auto["rank"].value_counts().sort_index()
    out["auto_cats_won"] = {s: mean_ci(auto[f"cats_won_{s}"]) for s in ("z", "adp", "lp")}
    out["auto_cats_won_all"] = mean_ci(auto["cats_won"])
    out["auto_beaten"] = mean_ci(auto["opponents_beaten"])
    traj = (
        mypicks[mypicks["run"].isin(["auto", "fix1"])]
        .groupby(["run", "k"])["vs_bench"]
        .agg(["mean", "std", "count"])
        .reset_index()
    )
    out["trajectory"] = traj
    by_slot = auto.groupby("slot").agg(
        mocks=("vs_bench", "size"),
        benchmark=("benchmark", "mean"),
        final=("value_best", "mean"),
        vs_bench=("vs_bench", "mean"),
        vs_bench_sd=("vs_bench", "std"),
        rank=("rank", "mean"),
        switches=("switches", "mean"),
    )
    if len(fix1):
        by_slot["fix1_final"] = fix1.groupby("slot")["value_best"].mean()
        by_slot["fix1_vs_bench"] = fix1.groupby("slot")["vs_bench"].mean()
    out["by_slot"] = by_slot

    # 2. punt changes
    ap = mypicks[mypicks["run"] == "auto"]
    out["switches_dist"] = auto["switches"].value_counts().sort_index()
    out["distinct_dist"] = auto["distinct_punts"].value_counts().sort_index()
    out["switch_rate_by_k"] = ap[ap["k"] > 1].groupby("k")["switched"].mean()
    out["margin_by_k"] = ap.groupby("k")["margin"].mean()
    punt_share = ap.groupby(["k", "punt"]).size().unstack(fill_value=0)
    punt_share = punt_share.div(punt_share.sum(axis=1), axis=0)
    out["punt_share"] = punt_share
    out["punt_first"] = ap[ap["k"] == 1]["punt"].value_counts()
    out["punt_last"] = ap[ap["k"] == 13]["punt"].value_counts()
    out["switch_margins"] = ap[ap["switched"]]["prev_loss"].describe()
    trans = (
        ap[ap["switched"]]
        .groupby(["prev_punt", "punt"])
        .size()
        .sort_values(ascending=False)
        .head(12)
    )
    out["transitions"] = trans
    sw = auto.reset_index()
    sw["switch_group"] = pd.cut(
        sw["switches"], bins=[-1, 0, 1, 2, 99], labels=["0", "1", "2", "3+"]
    )
    out["by_switches"] = sw.groupby("switch_group", observed=True).agg(
        mocks=("vs_bench", "size"),
        vs_bench=("vs_bench", "mean"),
        final=("value_best", "mean"),
        fix1_gain=(
            "seed",
            lambda s: (
                float((fix1.loc[s, "value_best"] - auto.loc[s, "value_best"]).mean())
                if len(fix1)
                else np.nan
            ),
        ),
    )
    # when does the first switch happen, and what did the first-pick punt lose by then
    first_switch = ap[ap["switched"]].groupby("seed")["k"].min()
    out["first_switch_k"] = first_switch.value_counts().sort_index()
    out["never_switch"] = int((auto["switches"] == 0).sum())

    # 3. fixed from pick k
    fixed_rows = []
    for name, group in runs.groupby("run"):
        g = group.set_index("seed")
        common = g.index.intersection(auto.index)
        diff = g.loc[common, "value_best"] - auto.loc[common, "value_best"]
        m, h, n = mean_ci(diff)
        fixed_rows.append(
            {
                "run": name,
                "fixed_from": int(g["fixed_from"].iloc[0]),
                "mocks": n,
                "final": float(g.loc[common, "value_best"].mean()),
                "vs_bench": float(g.loc[common, "vs_bench"].mean()),
                "gain_vs_auto": m,
                "ci": h,
                "share_better": float((diff > 0).mean()),
                "share_worse": float((diff < 0).mean()),
                "held_punt_value": float(g.loc[common, "value_last_punt"].mean()),
                "rank": float(g.loc[common, "rank"].mean()),
                "cats_won": float(g.loc[common, "cats_won"].mean()),
            }
        )
    fixed = pd.DataFrame(fixed_rows).sort_values("fixed_from").set_index("run")
    out["fixed"] = fixed
    pivot = runs.pivot(index="seed", columns="run", values="value_best")
    out["oracle"] = mean_ci(pivot.max(axis=1) - pivot["auto"])
    out["oracle_best_run"] = pivot.idxmax(axis=1).value_counts()
    slot_group = pd.cut(
        runs["slot"], bins=[0, 4, 8, 12], labels=["slots 1-4", "slots 5-8", "slots 9-12"]
    )
    fx = runs.assign(slot_group=slot_group)
    out["fixed_by_slot_group"] = fx.pivot_table(
        index="fixed_from", columns="slot_group", values="value_best", aggfunc="mean", observed=True
    )

    # 4. slot and opponents
    reg = auto.reset_index()
    X = pd.DataFrame({"n_lp": reg["n_lp"], "n_z": reg["n_z"]})
    X["late_slot"] = (reg["slot"] >= 9).astype(float)
    X["mid_slot"] = ((reg["slot"] >= 5) & (reg["slot"] <= 8)).astype(float)
    out["ols_vs_bench"] = ols(reg["vs_bench"].to_numpy(float), X)
    out["ols_final"] = ols(reg["value_best"].to_numpy(float), X)
    out["ols_bench"] = ols(reg["benchmark"].to_numpy(float), X)
    by_lp = auto.groupby("n_lp").agg(
        mocks=("vs_bench", "size"),
        vs_bench=("vs_bench", "mean"),
        final=("value_best", "mean"),
        rank=("rank", "mean"),
    )
    out["by_n_lp"] = by_lp
    strength = (
        teams[teams["strategy"] != "me"]
        .groupby("strategy")["value_best"]
        .agg(["mean", "std", "count"])
    )
    strength.loc["me"] = [auto["value_best"].mean(), auto["value_best"].std(), len(auto)]
    out["team_strength"] = strength
    lp_punt_strength = (
        teams[teams["strategy"] == "lp"]
        .groupby("team_punt")["value_best"]
        .agg(["mean", "count"])
        .sort_values("mean", ascending=False)
    )
    out["lp_punt_strength"] = lp_punt_strength
    # do LP opponents sharing my benchmark punt hurt?
    share_rows = []
    for seed, row in auto.iterrows():
        mine = set(row["benchmark_punt"].split("/")) if row["benchmark_punt"] != "-" else set()
        opp = teams[(teams["seed"] == seed) & (teams["strategy"] == "lp")]
        overlap = sum(1 for p in opp["team_punt"] if p != "-" and set(p.split("/")) & mine)
        share_rows.append(
            {
                "seed": seed,
                "overlap_lp": overlap,
                "vs_bench": row["vs_bench"],
                "final": row["value_best"],
            }
        )
    share = pd.DataFrame(share_rows)
    out["by_overlap"] = share.groupby("overlap_lp").agg(
        mocks=("seed", "size"), vs_bench=("vs_bench", "mean"), final=("final", "mean")
    )

    # 5. detection and competition
    out["detection"], out["confusion"], out["centroids"] = detection(picks)
    out["implied_punts"] = implied_punts(picks)
    lost = plans[~plans["realized"]]
    n_picks_by_strategy = picks[picks["strategy"] != "me"].groupby("strategy").size()
    snipes = lost.groupby("taker_strategy").size()
    out["snipes"] = pd.DataFrame(
        {"planned_players_taken": snipes, "picks_made": n_picks_by_strategy}
    ).fillna(0)
    out["snipes"]["per_100_picks"] = (
        100 * out["snipes"]["planned_players_taken"] / out["snipes"]["picks_made"]
    )
    # same-punt LP teams
    lp_lost = lost[lost["taker_strategy"] == "lp"].copy()
    lp_lost["same_punt"] = [
        bool(set(str(a).split("/")) & set(str(b).split("/")))
        if a not in (None, "-") and b not in (None, "-")
        else False
        for a, b in zip(lp_lost["taker_punt"], lp_lost["punt"], strict=True)
    ]
    lp_picks = picks[picks["strategy"] == "lp"]
    out["lp_same_punt"] = {
        "lost_to_same_punt": int(lp_lost["same_punt"].sum()),
        "lost_to_other_lp": int((~lp_lost["same_punt"]).sum()),
        "lp_picks": len(lp_picks),
    }
    top_lost = (
        lost.groupby("player")
        .agg(times_lost=("seed", "size"), mocks=("seed", "nunique"), mean_p=("p", "mean"))
        .sort_values("times_lost", ascending=False)
        .head(15)
    )
    takers = lost.groupby(["player", "taker_strategy"]).size().unstack(fill_value=0)
    out["top_lost"] = top_lost.join(takers, how="left").fillna(0)
    out["plan_loss_rate"] = float((~plans["realized"]).mean())
    out["plan_expected_loss"] = float((1 - plans["p"]).mean())
    # calibration
    bins = np.linspace(0, 1, 11)
    cal = (
        plans.assign(bin=pd.cut(plans["p"], bins=bins, include_lowest=True))
        .groupby("bin", observed=True)
        .agg(planned=("realized", "size"), predicted=("p", "mean"), realized=("realized", "mean"))
    )
    out["calibration"] = cal
    cal_next = plans[plans["pick"] == plans.groupby(["seed", "k"])["pick"].transform("min")]
    out["calibration_next"] = (
        cal_next.assign(bin=pd.cut(cal_next["p"], bins=bins, include_lowest=True))
        .groupby("bin", observed=True)
        .agg(planned=("realized", "size"), predicted=("p", "mean"), realized=("realized", "mean"))
    )
    # who takes the players my plan wanted, relative to the model's expectation, by strategy mix
    out["timing"] = {
        "auto_seconds": float(auto["seconds"].mean()),
        "solve_ms_auto": float(ap["solve_ms"].mean()),
        "solve_ms_fixed": float(
            mypicks[(mypicks["run"] != "auto") & (~mypicks["replayed"])]["solve_ms"].mean()
        ),
    }
    # my picks: how far off the top of the board do I draft
    out["my_pick_ranks"] = ap.groupby("k")[["z_rank", "adp_rank"]].mean()
    out["dream_mean"] = mean_ci(auto["dream"])
    out["auto_vs_dream"] = mean_ci(auto["vs_dream"])
    out["dream_share"] = mean_ci(auto["dream_share"])
    wins = []
    for seed, grp in teams.groupby("seed"):
        me = grp[grp["team"] == "me"].iloc[0]
        for _, opp in grp[grp["team"] != "me"].iterrows():
            wins.append(
                {
                    "seed": seed,
                    "strategy": opp["strategy"],
                    **{c: float(me[f"z_{c}"] > opp[f"z_{c}"]) for c in CATS},
                }
            )
    wins = pd.DataFrame(wins)
    cat_wins = pd.DataFrame(
        {
            "all opponents": wins[CATS].mean(),
            **{
                STRATEGY_NAMES[st]: wins[wins["strategy"] == st][CATS].mean()
                for st in ("z", "adp", "lp")
            },
        }
    )
    cat_wins["my mean z"] = [teams[teams["team"] == "me"][f"z_{c}"].mean() for c in CATS]
    cat_wins["LP mean z"] = [teams[teams["strategy"] == "lp"][f"z_{c}"].mean() for c in CATS]
    cat_wins["z-score mean z"] = [teams[teams["strategy"] == "z"][f"z_{c}"].mean() for c in CATS]
    cat_wins.index = [CAT_NAMES[c] for c in CATS]
    out["cat_wins"] = cat_wins
    sel = runs[runs["run"].isin(["auto", "fix1", "fix2"])]
    by_punt = sel.groupby(["run", "punt_best"]).agg(
        runs=("seed", "size"), value=("value_best", "mean"), cats_won=("cats_won", "mean")
    )
    by_punt = by_punt[by_punt["runs"] >= 3].reset_index()
    by_punt["punt_best"] = by_punt["punt_best"].map(punt_name)
    out["by_punt"] = by_punt.rename(columns={"punt_best": "final punt"})
    gap_bins = pd.cut(
        plans["market_gap"],
        bins=[-1000, -10.5, 10.5, 1000],
        labels=[
            "model likes him more (z rank 11+ ahead of ADP)",
            "model and market agree",
            "market likes him more",
        ],
    )
    out["cal_gap"] = (
        plans.assign(group=gap_bins)
        .groupby("group", observed=True)
        .agg(planned=("realized", "size"), predicted=("p", "mean"), realized=("realized", "mean"))
    )
    return out


# --------------------------------------------------------------------------- charts
def _fmt(v: float) -> str:
    if abs(v) >= 100:
        return f"{v:.0f}"
    if abs(v) >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v)}"


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=10) * mag
    start = math.floor(lo / step) * step
    ticks = []
    t = start
    while t <= hi + 1e-9:
        ticks.append(round(t, 10))
        t += step
    return ticks


class Chart:
    def __init__(
        self,
        width: int = 720,
        height: int = 320,
        left: int = 56,
        right: int = 16,
        top: int = 46,
        bottom: int = 44,
    ) -> None:
        self.w, self.h = width, height
        self.l, self.r, self.t, self.b = left, right, top, bottom
        self.parts: list[str] = []

    @property
    def plot_w(self) -> int:
        return self.w - self.l - self.r

    @property
    def plot_h(self) -> int:
        return self.h - self.t - self.b

    def x(self, v: float, lo: float, hi: float) -> float:
        return self.l + (v - lo) / (hi - lo) * self.plot_w

    def y(self, v: float, lo: float, hi: float) -> float:
        return self.t + self.plot_h - (v - lo) / (hi - lo) * self.plot_h

    def axes(self, ylo: float, yhi: float, ylabel: str = "", title: str = "") -> None:
        for tick in _ticks(ylo, yhi):
            if ylo <= tick <= yhi:
                yy = self.y(tick, ylo, yhi)
                self.parts.append(
                    f'<line x1="{self.l}" x2="{self.w - self.r}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#e5e7eb"/>'
                )
                self.parts.append(
                    f'<text x="{self.l - 6}" y="{yy + 4:.1f}" text-anchor="end" class="tick">{_fmt(tick)}</text>'
                )
        if title:
            self.parts.append(
                f'<text x="{self.l}" y="14" class="title">{html.escape(title)}</text>'
            )
        if ylabel:
            self.parts.append(
                f'<text transform="translate(12 {self.t + self.plot_h / 2:.0f}) rotate(-90)" text-anchor="middle" class="label">{html.escape(ylabel)}</text>'
            )

    def legend(self, items: list[tuple[str, str]]) -> None:
        """Colour swatches with labels along the top, wrapping when they run out of room."""
        x, y = self.l + 8, 20
        for name, color in items:
            width = 26 + 6.2 * len(name)
            if x + width > self.w - self.r and x > self.l + 8:
                x, y = self.l + 8, y + 13
            self.parts.append(
                f'<rect x="{x:.0f}" y="{y:.0f}" width="10" height="10" fill="{color}"/>'
                f'<text x="{x + 14:.0f}" y="{y + 9:.0f}" class="legend">{html.escape(name)}</text>'
            )
            x += width

    def render(self) -> str:
        style = "<style>.tick{font:11px system-ui,sans-serif;fill:#6b7280}.label{font:12px system-ui,sans-serif;fill:#374151}.title{font:600 13px system-ui,sans-serif;fill:#111827}.legend{font:11px system-ui,sans-serif;fill:#374151}</style>"
        return f'<svg viewBox="0 0 {self.w} {self.h}" xmlns="http://www.w3.org/2000/svg" class="chart">{style}{"".join(self.parts)}</svg>'


def line_chart(
    series: dict[str, tuple[Sequence[float], Sequence[float]]],
    title: str,
    ylabel: str = "",
    xlabel: str = "",
    bands: dict[str, tuple[Sequence[float], Sequence[float], Sequence[float]]] | None = None,
    zero: bool = True,
    xticks: Sequence[float] | None = None,
) -> str:
    c = Chart()
    legend_items: list[tuple[str, str]] = []
    xs_all = [x for xs, _ in series.values() for x in xs]
    ys_all = [y for _, ys in series.values() for y in ys if _ok(y)]
    if bands:
        ys_all += [v for _, lo, hi in bands.values() for v in list(lo) + list(hi) if _ok(v)]
    if not xs_all or not ys_all:
        return ""
    xlo, xhi = min(xs_all), max(xs_all)
    if xhi == xlo:
        xhi = xlo + 1
    ylo, yhi = min(ys_all), max(ys_all)
    if zero:
        ylo, yhi = min(ylo, 0.0), max(yhi, 0.0)
    pad = (yhi - ylo) * 0.08 or 1.0
    ylo, yhi = ylo - pad, yhi + pad
    c.axes(ylo, yhi, ylabel, title)
    if zero and ylo < 0 < yhi:
        yy = c.y(0, ylo, yhi)
        c.parts.append(
            f'<line x1="{c.l}" x2="{c.w - c.r}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#9ca3af" stroke-dasharray="4 3"/>'
        )
    for tick in xticks if xticks is not None else _ticks(xlo, xhi, 8):
        if xlo <= tick <= xhi:
            xx = c.x(tick, xlo, xhi)
            c.parts.append(
                f'<text x="{xx:.1f}" y="{c.h - c.b + 16}" text-anchor="middle" class="tick">{_fmt(tick)}</text>'
            )
    if xlabel:
        c.parts.append(
            f'<text x="{c.l + c.plot_w / 2:.0f}" y="{c.h - 8}" text-anchor="middle" class="label">{html.escape(xlabel)}</text>'
        )
    for i, (name, (xs, ys)) in enumerate(series.items()):
        color = PALETTE[i % len(PALETTE)]
        if bands and name in bands:
            bx, lo, hi = bands[name]
            top = " ".join(
                f"{c.x(x, xlo, xhi):.1f},{c.y(v, ylo, yhi):.1f}"
                for x, v in zip(bx, hi, strict=True)
                if _ok(v)
            )
            bot = " ".join(
                f"{c.x(x, xlo, xhi):.1f},{c.y(v, ylo, yhi):.1f}"
                for x, v in reversed(list(zip(bx, lo, strict=True)))
                if _ok(v)
            )
            c.parts.append(f'<polygon points="{top} {bot}" fill="{color}" fill-opacity="0.12"/>')
        pts = " ".join(
            f"{c.x(x, xlo, xhi):.1f},{c.y(y, ylo, yhi):.1f}"
            for x, y in zip(xs, ys, strict=True)
            if _ok(y)
        )
        c.parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
        for x, y in zip(xs, ys, strict=True):
            if _ok(y):
                c.parts.append(
                    f'<circle cx="{c.x(x, xlo, xhi):.1f}" cy="{c.y(y, ylo, yhi):.1f}" r="2.5" fill="{color}"/>'
                )
        legend_items.append((name, color))
    c.legend(legend_items)
    return c.render()


def bar_chart(
    labels: Sequence[str],
    groups: dict[str, Sequence[float]],
    title: str,
    ylabel: str = "",
    errors: dict[str, Sequence[float]] | None = None,
    zero: bool = True,
    width: int = 720,
) -> str:
    c = Chart(width=width)
    legend_items: list[tuple[str, str]] = []
    vals = [v for vs in groups.values() for v in vs if _ok(v)]
    if not vals:
        return ""
    ylo, yhi = min(vals), max(vals)
    if errors:
        ylo = min(
            ylo,
            min(
                v - e
                for vs, es in zip(groups.values(), errors.values(), strict=True)
                for v, e in zip(vs, es, strict=True)
                if _ok(v) and _ok(e)
            ),
        )
        yhi = max(
            yhi,
            max(
                v + e
                for vs, es in zip(groups.values(), errors.values(), strict=True)
                for v, e in zip(vs, es, strict=True)
                if _ok(v) and _ok(e)
            ),
        )
    if zero:
        ylo, yhi = min(ylo, 0.0), max(yhi, 0.0)
    pad = (yhi - ylo) * 0.08 or 1.0
    ylo, yhi = ylo - pad, yhi + pad
    c.axes(ylo, yhi, ylabel, title)
    n_groups = max(1, len(groups))
    slot_w = c.plot_w / max(1, len(labels))
    bar_w = slot_w * 0.8 / n_groups
    zero_y = c.y(0.0, ylo, yhi) if zero else c.y(ylo, ylo, yhi)
    for gi, (name, vs) in enumerate(groups.items()):
        color = PALETTE[gi % len(PALETTE)]
        for i, v in enumerate(vs):
            if not _ok(v):
                continue
            xx = c.l + i * slot_w + slot_w * 0.1 + gi * bar_w
            yy = c.y(v, ylo, yhi)
            top, hgt = (yy, zero_y - yy) if v >= 0 else (zero_y, yy - zero_y)
            c.parts.append(
                f'<rect x="{xx:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{max(0.5, hgt):.1f}" fill="{color}"/>'
            )
            if errors and name in errors and errors[name][i] == errors[name][i]:
                e = errors[name][i]
                cx = xx + bar_w / 2
                c.parts.append(
                    f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{c.y(v - e, ylo, yhi):.1f}" y2="{c.y(v + e, ylo, yhi):.1f}" stroke="#111827" stroke-width="1"/>'
                )
        if n_groups > 1:
            legend_items.append((name, color))
    for i, label in enumerate(labels):
        xx = c.l + i * slot_w + slot_w / 2
        c.parts.append(
            f'<text x="{xx:.1f}" y="{c.h - c.b + 16}" text-anchor="middle" class="tick">{html.escape(str(label))}</text>'
        )
    c.legend(legend_items)
    return c.render()


def stacked_chart(
    labels: Sequence[str],
    groups: dict[str, Sequence[float]],
    title: str,
    ylabel: str = "share of mocks",
) -> str:
    c = Chart(height=340, bottom=44)
    legend_items: list[tuple[str, str]] = []
    c.axes(0.0, 1.0, ylabel, title)
    slot_w = c.plot_w / max(1, len(labels))
    bar_w = slot_w * 0.8
    base = np.zeros(len(labels))
    for gi, (name, vs) in enumerate(groups.items()):
        color = PALETTE[gi % len(PALETTE)]
        for i, v in enumerate(vs):
            if v <= 0:
                continue
            xx = c.l + i * slot_w + slot_w * 0.1
            y_top = c.y(base[i] + v, 0.0, 1.0)
            y_bot = c.y(base[i], 0.0, 1.0)
            c.parts.append(
                f'<rect x="{xx:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{y_bot - y_top:.1f}" fill="{color}"><title>{html.escape(name)}: {v:.0%}</title></rect>'
            )
            base[i] += v
        legend_items.append((name, color))
    for i, label in enumerate(labels):
        xx = c.l + i * slot_w + slot_w / 2
        c.parts.append(
            f'<text x="{xx:.1f}" y="{c.h - c.b + 16}" text-anchor="middle" class="tick">{html.escape(str(label))}</text>'
        )
    c.legend(legend_items)
    return c.render()


def hist_chart(values: Sequence[float], title: str, bins: int = 20, xlabel: str = "") -> str:
    arr = np.asarray([v for v in values if _ok(v)], dtype=float)
    if len(arr) == 0:
        return ""
    counts, edges = np.histogram(arr, bins=bins)
    labels = [f"{edges[i]:.1f}" if i % max(1, bins // 8) == 0 else "" for i in range(bins)]
    svg = bar_chart(labels, {"mocks": counts.tolist()}, title, ylabel="mocks")
    if xlabel:
        svg = svg.replace(
            "</svg>",
            f'<text x="388" y="312" text-anchor="middle" class="label">{html.escape(xlabel)}</text></svg>',
        )
    return svg


def calibration_chart(cal: pd.DataFrame, title: str) -> str:
    c = Chart(width=420, height=360, left=56)
    c.axes(0.0, 1.0, "realized share still available", title)
    c.parts.append(
        f'<line x1="{c.x(0, 0, 1):.1f}" y1="{c.y(0, 0, 1):.1f}" x2="{c.x(1, 0, 1):.1f}" y2="{c.y(1, 0, 1):.1f}" stroke="#9ca3af" stroke-dasharray="4 3"/>'
    )
    for tick in _ticks(0, 1, 5):
        c.parts.append(
            f'<text x="{c.x(tick, 0, 1):.1f}" y="{c.h - c.b + 16}" text-anchor="middle" class="tick">{_fmt(tick)}</text>'
        )
    c.parts.append(
        f'<text x="{c.l + c.plot_w / 2:.0f}" y="{c.h - 8}" text-anchor="middle" class="label">predicted availability</text>'
    )
    pts = [
        (row.predicted, row.realized, row.planned) for row in cal.itertuples() if row.planned > 0
    ]
    line = " ".join(f"{c.x(p, 0, 1):.1f},{c.y(r, 0, 1):.1f}" for p, r, _ in pts)
    c.parts.append(
        f'<polyline points="{line}" fill="none" stroke="{PALETTE[0]}" stroke-width="2"/>'
    )
    for p, r, n in pts:
        c.parts.append(
            f'<circle cx="{c.x(p, 0, 1):.1f}" cy="{c.y(r, 0, 1):.1f}" r="{min(9, 2 + math.sqrt(n) / 3):.1f}" fill="{PALETTE[0]}" fill-opacity="0.7"><title>{n} planned</title></circle>'
        )
    return c.render()


# --------------------------------------------------------------------------- report
def table(
    df: pd.DataFrame, floatfmt: str = "{:.2f}", index: bool = True, pct_cols: Sequence[str] = ()
) -> str:
    df = df.copy()
    for col in df.columns:
        if col in pct_cols:
            df[col] = df[col].map(lambda v: f"{v:.0%}" if _ok(v) else "")
        elif pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].map(lambda v: floatfmt.format(v) if _ok(v) else "")
    return df.to_html(index=index, border=0, classes="tbl", escape=True)


def signed(v: float) -> str:
    return f"{v:+.2f}"


def build_report(a: dict, f: dict[str, pd.DataFrame], study: Path) -> tuple[str, str]:
    runs = f["runs"]
    auto = runs[runs["run"] == "auto"]
    n = a["n_mocks"]
    m_auto, h_auto, _ = a["auto_vs_bench"]
    m_fix, h_fix, _ = a["fix1_vs_bench"]
    bench_m = a["benchmark_mean"][0]
    final_m = a["auto_final_mean"][0]
    fix1_m = a["fix1_final_mean"][0]
    fixed = a["fixed"]
    traj = a["trajectory"]
    sections: list[str] = []
    md: list[str] = []

    # --- headline
    best_fix = (
        fixed.drop(index="auto", errors="ignore")
        .sort_values("gain_vs_auto", ascending=False)
        .iloc[0]
        if len(fixed) > 1
        else None
    )
    md.append(f"# Mock-draft study ({study.name})\n")
    md.append(
        f"{n} mocks, 12 teams, 13 rounds, me in slots 1 to 12 drafting with the rolling-horizon planner; the other eleven teams drew z-score, ADP or LP drafters at random (noise 1.0).\n"
    )
    md.append("## Headline\n")
    md.append(
        f"- Final roster value vs the plan value frozen at my first pick: auto punt {signed(m_auto)} (95% CI ±{h_auto:.2f}, {a['auto_share_above']:.0%} of mocks at or above the benchmark); punt fixed from the first pick {signed(m_fix)} (±{h_fix:.2f}, {a['fix1_share_above']:.0%})."
    )
    md.append(
        f"- Benchmark averages {bench_m:.1f}; auto finishes at {final_m:.1f}, fixed-from-first-pick at {fix1_m:.1f}."
    )
    if best_fix is not None:
        md.append(
            f"- Best point to freeze the punt: my pick {int(best_fix['fixed_from'])} ({signed(best_fix['gain_vs_auto'])} vs auto, ±{best_fix['ci']:.2f}); an oracle choosing the best freeze point per mock would gain {signed(a['oracle'][0])}."
        )
    md.append(
        f"- Auto switched punts in {n - a['never_switch']} of {n} mocks (mean {auto['switches'].mean():.1f} switches, {auto['distinct_punts'].mean():.1f} distinct punts per draft)."
    )
    md.append(
        f"- I finish first in {int(a['auto_rank'].get(1, 0))} of {n} mocks (mean rank {auto['rank'].mean():.1f}) and win {a['auto_cats_won_all'][0]:.1f} of 9 categories per matchup on average (vs LP teams {a['auto_cats_won']['lp'][0]:.1f}, z-score {a['auto_cats_won']['z'][0]:.1f}, ADP {a['auto_cats_won']['adp'][0]:.1f})."
    )

    head = f"""
    <p class="lede">{n} mocks. 12 teams, 13 rounds, Yahoo default lineup, nine categories. My team drafts from every slot (1 to 12, cycling) with the rolling-horizon planner and its automatic punt choice. The other eleven teams draw a drafter each, uniformly at random from z-score, ADP and LP, and LP teams draw a punt of their own. Each mock is then branched at every one of my picks with the punt held from that pick on, replaying the same board and the same random draws, so every comparison below is paired.</p>
    <div class="kpis">
      <div class="kpi"><div class="v">{signed(m_auto)}</div><div class="k">final vs benchmark, auto punt<br>±{h_auto:.2f}, {a["auto_share_above"]:.0%} at or above</div></div>
      <div class="kpi"><div class="v">{signed(m_fix)}</div><div class="k">final vs benchmark, punt fixed at pick 1<br>±{h_fix:.2f}, {a["fix1_share_above"]:.0%} at or above</div></div>
      <div class="kpi"><div class="v">{auto["switches"].mean():.1f}</div><div class="k">punt switches per draft (auto)<br>{n - a["never_switch"]} of {n} drafts switched</div></div>
      <div class="kpi"><div class="v">{int(a["auto_rank"].get(1, 0))}/{n}</div><div class="k">mocks finished first of 12<br>mean rank {auto["rank"].mean():.1f}, {a["auto_cats_won_all"][0]:.1f} of 9 cats per matchup</div></div>
    </div>"""
    sections.append(head)

    # --- 1. final vs benchmark
    tr_auto = traj[traj["run"] == "auto"]
    tr_fix = traj[traj["run"] == "fix1"]
    series = {
        "auto punt: plan value − benchmark": (tr_auto["k"].tolist(), tr_auto["mean"].tolist())
    }
    bands = {
        "auto punt: plan value − benchmark": (
            tr_auto["k"].tolist(),
            (tr_auto["mean"] - 1.96 * tr_auto["std"] / np.sqrt(tr_auto["count"])).tolist(),
            (tr_auto["mean"] + 1.96 * tr_auto["std"] / np.sqrt(tr_auto["count"])).tolist(),
        )
    }
    if len(tr_fix):
        series["punt fixed at pick 1"] = (tr_fix["k"].tolist(), tr_fix["mean"].tolist())
    series["final (auto)"] = ([13.6], [m_auto])
    series["final (fixed at 1)"] = ([13.9], [m_fix])
    chart1 = line_chart(
        series,
        "Plan value relative to the benchmark, by my pick number",
        "z above replacement",
        "my pick (1 = first pick, 13 = last); finals at right",
        bands=bands,
        xticks=list(range(1, 14)),
    )
    hist1 = hist_chart(
        auto["vs_bench"].tolist(),
        "Final − benchmark, auto punt (one bar per 0.5 z)",
        bins=20,
        xlabel="z",
    )
    by_slot = a["by_slot"]
    chart_slot = bar_chart(
        [str(s) for s in by_slot.index],
        {
            "benchmark": by_slot["benchmark"].tolist(),
            "final, auto": by_slot["final"].tolist(),
            **(
                {"final, fixed at 1": by_slot["fix1_final"].tolist()}
                if "fix1_final" in by_slot
                else {}
            ),
        },
        "Benchmark and final value by draft slot",
        "z above replacement",
        zero=False,
    )
    chart_slot2 = bar_chart(
        [str(s) for s in by_slot.index],
        {
            "auto": by_slot["vs_bench"].tolist(),
            **(
                {"fixed at 1": by_slot["fix1_vs_bench"].tolist()}
                if "fix1_vs_bench" in by_slot
                else {}
            ),
        },
        "Final − benchmark by draft slot",
        "z",
    )
    sections.append(f"""
    <h2>1. Final team vs the score frozen at my first pick</h2>
    <p>The benchmark is the plan objective the moment I am on the clock for my first pick: the players already mine (none yet) plus the availability-weighted value of the plan for every later pick, all measured above replacement level. The final is the same measure for the finished roster, under whichever punt suits it best. The plan value drifts up through the draft in both conditions because the plan is re-optimized against the real board, which is usually kinder than the ADP odds assumed, and because later picks find bench value the first plan did not count on. A final below the benchmark means the board went worse than the first plan expected, above means better.</p>
    {chart1}
    <div class="row">{hist1}</div>
    {chart_slot}{chart_slot2}
    {table(by_slot.rename(columns={"vs_bench": "final − bench", "vs_bench_sd": "sd", "fix1_final": "final (fixed at 1)", "fix1_vs_bench": "fixed − bench"}))}
    <p>Where I finish among the 12 teams (auto punt): {", ".join(f"rank {int(r)}: {int(c)} mocks" for r, c in a["auto_rank"].items())}. Mean categories won per matchup: {a["auto_cats_won_all"][0]:.2f} of 9 overall; vs LP teams {a["auto_cats_won"]["lp"][0]:.2f}, vs z-score teams {a["auto_cats_won"]["z"][0]:.2f}, vs ADP teams {a["auto_cats_won"]["adp"][0]:.2f}; opponents beaten (5 or more categories) {a["auto_beaten"][0]:.1f} of 11.</p>
    """)
    cw = a["cat_wins"]
    chart_cw = bar_chart(
        list(cw.index),
        {
            "vs all opponents": cw["all opponents"].tolist(),
            "vs LP": cw["LP"].tolist(),
            "vs z-score": cw["z-score"].tolist(),
            "vs ADP": cw["ADP"].tolist(),
        },
        "Share of matchups I win in each category (auto punt, final rosters)",
        "share won",
    )
    sections.append(f"""
    <h3>If every planned player had fallen to me</h3>
    <p>The first plan, valued without the availability discount, is worth {a["dream_mean"][0]:.1f} on average (the benchmark discounts it to {bench_m:.1f}). I end the draft with {a["dream_share"][0]:.0%} of the players that first plan named and a roster worth {signed(a["auto_vs_dream"][0])} (±{a["auto_vs_dream"][1]:.2f}) relative to that undiscounted first plan. Beating the benchmark by {signed(m_auto)} while landing below the undiscounted plan says the benchmark is a cautious number: it prices in the chance of losing each planned player but not the chance to re-plan around whoever falls instead.</p>
    <h3>Categories won per matchup</h3>
    <p>Total value above replacement is the planner's objective, but a head-to-head week is won by categories. Comparing each of my finished rosters with each opponent's category totals (z summed over the roster), I win {a["auto_cats_won_all"][0]:.2f} of 9 categories on average, the two punted ones lost by design.</p>
    {chart_cw}
    {table(cw, pct_cols=["all opponents", "LP", "z-score", "ADP"])}
    """)
    md.append("\n## 1. Final vs benchmark\n")
    md.append(table_md(a["cat_wins"]))
    md.append(
        table_md(
            by_slot.rename(
                columns={
                    "vs_bench": "final − bench",
                    "vs_bench_sd": "sd",
                    "fix1_final": "final (fixed at 1)",
                    "fix1_vs_bench": "fixed − bench",
                }
            )
        )
    )

    # --- 2. punt changes
    ps = a["punt_share"]
    top_punts = ps.sum(axis=0).sort_values(ascending=False).index.tolist()
    keep = top_punts[:7]
    groups = {punt_name(p): ps[p].reindex(range(1, 14), fill_value=0).tolist() for p in keep}
    other = ps.drop(columns=keep).sum(axis=1).reindex(range(1, 14), fill_value=0)
    if other.sum() > 0:
        groups["other"] = other.tolist()
    chart_punts = stacked_chart(
        [str(k) for k in range(1, 14)], groups, "Punt in force at each of my picks (auto)"
    )
    sr = a["switch_rate_by_k"]
    mg = a["margin_by_k"]
    chart_switch = line_chart(
        {
            "share of drafts switching punt at this pick": (sr.index.tolist(), sr.tolist()),
            "mean margin of the best punt over the runner-up (z)": (mg.index.tolist(), mg.tolist()),
        },
        "When the punt changes, and how close the runner-up punt is",
        "",
        "my pick",
        xticks=list(range(1, 14)),
    )
    trans = a["transitions"].reset_index()
    trans.columns = ["from", "to", "count"]
    trans["from"] = trans["from"].map(punt_name)
    trans["to"] = trans["to"].map(punt_name)
    first_last = (
        pd.DataFrame({"at first pick": a["punt_first"], "at last pick": a["punt_last"]})
        .fillna(0)
        .astype(int)
    )
    first_last.index = [punt_name(p) for p in first_last.index]
    first_last = first_last.sort_values("at first pick", ascending=False)
    sm = a["switch_margins"]
    sections.append(f"""
    <h2>2. How the punt strategy changed over the draft</h2>
    {chart_punts}
    {chart_switch}
    <div class="cols">
      <div><h3>Punt at the first and the last pick</h3>{table(first_last)}</div>
      <div><h3>Most common switches</h3>{table(trans, index=False)}</div>
    </div>
    <p>Switches per draft: {", ".join(f"{int(k)}: {int(v)}" for k, v in a["switches_dist"].items())}. First switch at pick: {", ".join(f"{int(k)}: {int(v)}" for k, v in a["first_switch_k"].items())}. When the punt switched, the punt it abandoned trailed the new best by a median {sm["50%"]:.2f} z (mean {sm["mean"]:.2f}, 75th percentile {sm["75%"]:.2f}) on the punt scan, so most switches are near-ties resolved by the latest pick, not a change of heart.</p>
    <h3>Outcome by number of switches (auto)</h3>
    {table(a["by_switches"].rename(columns={"vs_bench": "final − bench", "fix1_gain": "gain from fixing at pick 1"}))}
    """)
    md.append("\n## 2. Punt changes\n")
    md.append(table_md(first_last))
    md.append("\nOutcome by switches:\n")
    md.append(
        table_md(
            a["by_switches"].rename(
                columns={"vs_bench": "final − bench", "fix1_gain": "gain from fixing at pick 1"}
            )
        )
    )

    # --- 3. fixed from pick k
    fx = fixed.drop(index="auto", errors="ignore")
    chart_fixed = line_chart(
        {"gain vs auto (mean, 95% CI)": (fx["fixed_from"].tolist(), fx["gain_vs_auto"].tolist())},
        "Final value when the punt is held from my k-th pick, relative to auto",
        "z",
        "punt held from my pick k",
        bands={
            "gain vs auto (mean, 95% CI)": (
                fx["fixed_from"].tolist(),
                (fx["gain_vs_auto"] - fx["ci"]).tolist(),
                (fx["gain_vs_auto"] + fx["ci"]).tolist(),
            )
        },
        xticks=list(range(1, 13)),
    )
    fbs = a["fixed_by_slot_group"]
    chart_fixed_slot = line_chart(
        {str(col): (fbs.index.tolist(), fbs[col].tolist()) for col in fbs.columns},
        "Final value by freeze point and slot group (13 = auto, never frozen)",
        "z above replacement",
        "punt held from my pick k",
        zero=False,
        xticks=list(range(1, 14)),
    )
    fixed_table = fixed.rename(
        columns={
            "gain_vs_auto": "gain vs auto",
            "ci": "±95%",
            "share_better": "better than auto",
            "share_worse": "worse than auto",
            "held_punt_value": "value under held punt",
            "vs_bench": "final − bench",
        }
    )
    sections.append(f"""
    <h2>3. What if the punt had been fixed from pick k?</h2>
    <p>Each branch replays the auto draft up to my k-th pick, then holds the punt the auto run chose at that pick for the rest of the draft; the other teams keep the same random draws, so the branches differ from the auto run only through my choices. "Final" is under the best punt for the finished roster, "value under held punt" scores the roster under the punt that was held.</p>
    {chart_fixed}
    {chart_fixed_slot}
    {table(fixed_table, pct_cols=["better than auto", "worse than auto"])}
    <p>An oracle that picked the best freeze point for each mock after the fact would gain {signed(a["oracle"][0])} (±{a["oracle"][1]:.2f}) over auto; the best run per mock was {", ".join(f"{k}: {int(v)}" for k, v in a["oracle_best_run"].items())}.</p>
    """)
    bp = a["by_punt"]
    sections.append(f"""
    <h3>Outcome by the punt the finished roster suits best</h3>
    <p>Auto runs and the two best freeze points, grouped by the punt under which the finished roster scores highest (groups of fewer than three runs dropped).</p>
    {table(bp, index=False)}
    """)
    md.append("\n## 3. Punt fixed from pick k\n")
    md.append(table_md(a["by_punt"]))
    md.append(
        table_md(
            fixed_table[
                [
                    "fixed_from",
                    "mocks",
                    "final",
                    "final − bench",
                    "gain vs auto",
                    "±95%",
                    "better than auto",
                    "worse than auto",
                    "rank",
                    "cats_won",
                ]
            ]
        )
    )

    # --- 4. slot and opponents
    ols1 = a["ols_vs_bench"]
    ols2 = a["ols_final"]
    ols3 = a["ols_bench"]
    strength = a["team_strength"]
    strength.index = [STRATEGY_NAMES.get(i, i) for i in strength.index]
    lps = a["lp_punt_strength"].copy()
    lps.index = [punt_name(p) for p in lps.index]
    sections.append(f"""
    <h2>4. Draft position and the other drafters</h2>
    <div class="cols">
      <div><h3>Final − benchmark on slot and opponents (OLS)</h3>{table(ols1)}</div>
      <div><h3>Final value on slot and opponents</h3>{table(ols2)}</div>
    </div>
    <div class="cols">
      <div><h3>Benchmark itself on slot and opponents</h3>{table(ols3)}<p class="note">n_lp and n_z count LP and z-score opponents (ADP is the baseline); mid_slot is slots 5 to 8, late_slot 9 to 12 (slots 1 to 4 are the baseline). A |t| above 2 is conventionally significant.</p></div>
      <div><h3>By number of LP opponents</h3>{table(a["by_n_lp"].rename(columns={"vs_bench": "final − bench"}))}</div>
    </div>
    <div class="cols">
      <div><h3>How strong each drafter's finished roster is</h3>{table(strength)}<p class="note">Value under each team's own best punt; "me" is the auto run.</p></div>
      <div><h3>LP opponents by the punt they drew</h3>{table(lps)}</div>
    </div>
    <h3>LP opponents whose punt overlaps mine at my first pick</h3>
    {table(a["by_overlap"].rename(columns={"vs_bench": "final − bench"}))}
    """)
    md.append("\n## 4. Slot and opponents\n")
    md.append(table_md(ols1.rename(columns={"coef": "coef (final − bench)"})))
    md.append("\nOpponent strength:\n")
    md.append(table_md(strength))

    # --- 5. detection & competition
    det = a["detection"]
    conf = a["confusion"]
    cent = a["centroids"]
    chart_det = (
        line_chart(
            {
                "accuracy on held-out mocks": (
                    det["rounds_seen"].tolist(),
                    det["accuracy"].tolist(),
                ),
                "recall z-score": (det["rounds_seen"].tolist(), det["recall_z"].tolist()),
                "recall ADP": (det["rounds_seen"].tolist(), det["recall_adp"].tolist()),
                "recall LP": (det["rounds_seen"].tolist(), det["recall_lp"].tolist()),
            },
            "Telling z-score, ADP and LP drafters apart from their picks",
            "share correct",
            "rounds observed",
            xticks=[2, 3, 4, 5, 7, 9, 13],
        )
        if len(det)
        else ""
    )
    snipes = a["snipes"].copy()
    snipes.index = [STRATEGY_NAMES.get(i, i) for i in snipes.index]
    top_lost = a["top_lost"].copy()
    cal = a["calibration"]
    cal_next = a["calibration_next"]
    chart_cal = calibration_chart(cal, "All planned picks") + calibration_chart(
        cal_next, "Next pick only"
    )
    same = a["lp_same_punt"]
    sections.append(f"""
    <h2>5. Can I tell what the other teams are doing, and who competes with me?</h2>
    <p>A multinomial logistic regression on per-team features of the picks made so far (how far down the z board and the ADP board each pick was, the gap to the best available player, how consistent the team is) is trained on the first half of the mocks and tested on the second half. Chance is one in three.</p>
    {chart_det}
    <div class="cols">
      <div><h3>Confusion (rows actual, columns predicted)</h3>{table(conf) if conf is not None else ""}</div>
      <div><h3>Feature averages after the full draft</h3>{table(cent, floatfmt="{:.3f}") if cent is not None else ""}</div>
    </div>
    <h3>Reading an LP team's punt from its roster</h3>
    {table(a["implied_punts"], pct_cols=["weakest_cat_is_punt"]) if len(a["implied_punts"]) else "<p>n/a</p>"}
    <h3>Who takes the players my plan wanted</h3>
    <p>Every plan names a player for each of my later picks with the odds he is still there. Over all plans in the auto runs, {a["plan_loss_rate"]:.0%} of planned players were gone by the pick they were planned for, against {a["plan_expected_loss"]:.0%} the availability model expected.</p>
    {table(snipes.rename(columns={"planned_players_taken": "planned players taken", "picks_made": "picks made", "per_100_picks": "per 100 picks"}))}
    <p>Of the planned players LP teams took, {same["lost_to_same_punt"]} went to an LP team whose punt overlaps the punt my plan was built on and {same["lost_to_other_lp"]} to LP teams with a different punt.</p>
    <h3>Players most often planned and lost</h3>
    {table(top_lost.rename(columns={"times_lost": "times lost", "mean_p": "mean predicted availability"}))}
    <h3>Availability odds vs what happened</h3>
    <div class="row">{chart_cal}</div>
    {table(cal.rename(columns={"planned": "planned players", "predicted": "mean predicted", "realized": "share available"}), pct_cols=["share available"])}
    """)
    sections.append(f"""
    <h3>Whose availability the model gets wrong</h3>
    <p>Planned players split by how the model's own ranking compares with the ADP the odds are built on. Opponents who draft by value take the players the model likes more than the market earlier than their ADP suggests.</p>
    {table(a["cal_gap"].rename(columns={"planned": "planned players", "predicted": "mean predicted", "realized": "share available"}), pct_cols=["share available"])}
    """)
    md.append("\n## 5. Detection and competition\n")
    md.append(table_md(a["cal_gap"]))
    if len(det):
        md.append(table_md(det))
    md.append("\nPlanned players taken, by taker:\n")
    md.append(table_md(snipes))
    md.append(
        f"\nPlanned players lost overall: {a['plan_loss_rate']:.0%} realized vs {a['plan_expected_loss']:.0%} expected.\n"
    )
    md.append(table_md(cal))

    md.append("\n## More tables\n")
    md.append("\nPunt in force by my pick (share of mocks):\n")
    ps_md = a["punt_share"].copy()
    ps_md.columns = [punt_name(c) for c in ps_md.columns]
    md.append(table_md(ps_md[ps_md.sum().sort_values(ascending=False).index[:6]]))
    md.append("\nSwitch rate and punt-scan margin by pick:\n")
    md.append(
        table_md(pd.DataFrame({"switch_rate": a["switch_rate_by_k"], "margin": a["margin_by_k"]}))
    )
    md.append("\nMost common switches:\n")
    md.append(table_md(trans))
    md.append(
        f"\nFirst switch at pick: {dict(a['first_switch_k'])}; never switched: {a['never_switch']}\n"
    )
    md.append("\nMargin the abandoned punt trailed by at a switch:\n")
    md.append(table_md(a["switch_margins"].to_frame().T))
    md.append(
        "\nOracle best run per mock: "
        + ", ".join(f"{k}: {int(v)}" for k, v in a["oracle_best_run"].items())
        + f"; oracle gain {a['oracle'][0]:+.2f} ± {a['oracle'][1]:.2f}\n"
    )
    md.append("\nBy number of LP opponents:\n")
    md.append(table_md(a["by_n_lp"]))
    md.append("\nBy LP opponents whose punt overlaps mine:\n")
    md.append(table_md(a["by_overlap"]))
    md.append("\nLP opponents by punt:\n")
    md.append(table_md(lps))
    md.append("\nConfusion:\n")
    if conf is not None:
        md.append(table_md(conf))
    md.append("\nImplied punts:\n")
    md.append(table_md(a["implied_punts"]))
    md.append(f"\nSame-punt LP snipes: {same}\n")
    md.append("\nTop lost planned players:\n")
    md.append(table_md(top_lost))
    md.append("\nMy picks: mean z-rank and ADP-rank by pick:\n")
    md.append(table_md(a["my_pick_ranks"]))
    md.append("\nCentroids:\n")
    if cent is not None:
        md.append(table_md(cent))

    # --- takeaways
    first_punt_top = a["punt_first"].index[0]
    last_punt_top = a["punt_last"].index[0]
    fs = a["first_switch_k"]
    cg = a["cal_gap"]
    sections.append(f"""
    <h2>6. Takeaways</h2>
    <ol>
      <li><b>The frozen benchmark is conservative.</b> Every plan value discounts later picks by the odds of losing the player, so the finished roster beats the pick-one benchmark by {signed(m_auto)} on average and lands {signed(a["auto_vs_dream"][0])} against the undiscounted first plan, of which {a["dream_share"][0]:.0%} of the names were actually drafted. Read "vs benchmark" as a running gauge against the first plan, not as an efficiency score; the branches and slots are the fair comparisons.</li>
      <li><b>The punt at pick one is the availability-blind one.</b> The punt scan uses the roster model, which assumes every undrafted player can be had, so at pick one it picks {punt_name(first_punt_top)} in {int(a["punt_first"].iloc[0])} of {n} mocks; once the board thins the horizon plan prefers {punt_name(last_punt_top)} ({int(a["punt_last"].iloc[0])} of {n} at the last pick). {int(fs.get(2, 0))} drafts switched at pick two and {int(fs.get(3, 0))} at pick three; after pick {int(fs.index.max()) if len(fs) else 0} nothing switched for the first time, and the runner-up margin on the scan grows from {a["margin_by_k"].iloc[0]:.1f} z at pick one to {a["margin_by_k"].get(5, float("nan")):.1f} z by pick five. Choosing the punt with the availability-weighted horizon model (a short list from the roster scan, re-priced by the plan) would remove the systematic pick-one-to-pick-two flip.</li>
      <li><b>Hold the punt after pick two.</b> Holding the pick-two punt gains {signed(fixed.loc["fix2", "gain_vs_auto"])} (±{fixed.loc["fix2", "ci"]:.2f}) over letting it float, pick three {signed(fixed.loc["fix3", "gain_vs_auto"])}, pick one only {signed(fixed.loc["fix1", "gain_vs_auto"])} (±{fixed.loc["fix1", "ci"]:.2f}); from pick four on the branches equal auto. Drafts with two or more switches finish about a z-point lower against the benchmark than drafts with none or one. A pin-after-pick-two default, or a switch threshold of a couple of z on the scan margin, captures most of the oracle's {signed(a["oracle"][0])}.</li>
      <li><b>Slot matters, opponents barely.</b> Benchmarks fall from {by_slot["benchmark"].iloc[0]:.1f} (slot 1) to {by_slot["benchmark"].iloc[-1]:.1f} (slot 12) and finals from {by_slot["final"].iloc[0]:.1f} to {by_slot["final"].iloc[-1]:.1f}; the final-minus-benchmark gap has no significant slot or opponent-mix effect (|t| below 2 on every term). Two or more LP opponents whose punt overlaps mine cost roughly a z-point and a half, on small samples.</li>
      <li><b>ADP drafters are visible by round three, value drafters later.</b> The classifier recalls {det.loc[det["rounds_seen"] == 3, "recall_adp"].iloc[0]:.0%} of ADP teams after three rounds; LP teams with a punt are recalled {det.loc[det["rounds_seen"] == 5, "recall_lp_with_punt"].iloc[0]:.0%} after five rounds and {det.loc[det["rounds_seen"] == 13, "recall_lp_with_punt"].iloc[0]:.0%} after the draft, and a no-punt LP team is indistinguishable from a z-score team. The weakest category of an LP team's roster is its punt {a["implied_punts"].iloc[-1]["weakest_cat_is_punt"]:.0%} of the time by the end but only {a["implied_punts"].iloc[1]["weakest_cat_is_punt"]:.0%} after five rounds.</li>
      <li><b>LP teams are the competition.</b> They take a player my plan had pencilled in {snipes.loc["LP", "per_100_picks"]:.1f} times per 100 picks, against {snipes.loc["z-score", "per_100_picks"]:.1f} for z-score teams and {snipes.loc["ADP", "per_100_picks"]:.1f} for ADP teams, and {same["lost_to_same_punt"]} of the {same["lost_to_same_punt"] + same["lost_to_other_lp"]} LP snipes came from a team whose punt overlaps mine. The odds are calibrated overall ({a["plan_loss_rate"]:.0%} of planned players lost against {a["plan_expected_loss"]:.0%} expected) but not per player: players the model ranks well ahead of their ADP were available {cg.iloc[0]["realized"]:.0%} of the time against {cg.iloc[0]["predicted"]:.0%} predicted. Blending the ADP with the model's own rank for the availability odds, more so once value drafters are detected, would fix the names that keep getting taken.</li>
      <li><b>Value is not category wins.</b> My rosters lead the league in value in {int(a["auto_rank"].get(1, 0))} of {n} mocks yet win only {a["auto_cats_won_all"][0]:.2f} of nine categories per matchup: the two punted categories are gone, three are near-certain ({", ".join(cw.index[cw["all opponents"] >= 0.75])}), and the rest are coin flips because the sum-of-z objective piles surplus into categories that are already won (my FG% total averages {cw.loc["FG%", "my mean z"]:+.1f} z). The rosters that held a punt from pick one or two win {fixed.loc["fix1", "cats_won"]:.2f} and {fixed.loc["fix2", "cats_won"]:.2f}. An objective that saturates per category, or the existing balance floor, is the next thing to test with this harness.</li>
    </ol>
    """)
    # --- timings
    t = a["timing"]
    sections.append(f"""
    <h2>Run details</h2>
    <p>Auto draft {t["auto_seconds"]:.0f} s per mock on one core; a punt scan plus plan {t["solve_ms_auto"]:.0f} ms per pick, a plan alone {t["solve_ms_fixed"]:.0f} ms. Projections: BBM rest-of-season per game (2026-09-21) converted to totals; ADP is BBM's rank because the export carries no ADP. Availability model: 1 − Φ((k − adp) / (3 + 0.15·adp)).</p>
    """)

    body = "\n".join(sections)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mock draft study</title>
<style>
:root {{ --bg: #ffffff; --fg: #111827; --muted: #6b7280; --line: #e5e7eb; --accent: #2563eb; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --line: #262a33; }} }}
:root[data-theme="dark"] {{ --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --line: #262a33; }}
body {{ margin: 0; padding: 24px 16px 64px; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; }}
h1 {{ font-size: 26px; margin: 0 0 4px; }} h2 {{ font-size: 20px; margin: 40px 0 8px; border-top: 1px solid var(--line); padding-top: 20px; }} h3 {{ font-size: 15px; margin: 20px 0 6px; }}
.sub {{ color: var(--muted); margin: 0 0 16px; }} .lede {{ font-size: 16px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 16px 0 8px; }}
.kpi {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }} .kpi .v {{ font-size: 28px; font-weight: 600; }} .kpi .k {{ color: var(--muted); font-size: 12px; line-height: 1.35; }}
.chart {{ width: 100%; height: auto; max-width: 760px; display: block; margin: 12px 0; background: #fff; border-radius: 8px; }}
.row {{ display: flex; flex-wrap: wrap; gap: 12px; }} .row .chart {{ flex: 1 1 320px; max-width: 460px; }}
.cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
table.tbl {{ border-collapse: collapse; font-size: 13px; margin: 8px 0 12px; width: 100%; overflow-x: auto; display: block; }}
.tbl th, .tbl td {{ padding: 4px 8px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }} .tbl th {{ color: var(--muted); font-weight: 500; }} .tbl td:first-child, .tbl th:first-child {{ text-align: left; }}
.note {{ color: var(--muted); font-size: 13px; }}
</style></head>
<body><main>
<h1>Mock draft study</h1>
<p class="sub">{study.name} · {n} mocks · generated by scripts/mock_study_report.py</p>
{body}
</main></body></html>"""
    return page, "\n".join(md)


def table_md(df: pd.DataFrame) -> str:
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].map(lambda v: f"{v:.2f}" if _ok(v) else "")
    cols = [str(c) for c in df.columns]
    lines = [
        "| " + " | ".join([str(df.index.name or "")] + cols) + " |",
        "|" + "---|" * (len(cols) + 1),
    ]
    for idx, row in df.iterrows():
        lines.append("| " + " | ".join([str(idx)] + [str(v) for v in row.tolist()]) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("study", type=Path)
    args = parser.parse_args()
    mocks = load(args.study)
    f = frames(mocks, args.study)
    tables = args.study / "tables"
    tables.mkdir(exist_ok=True)
    for name, df in f.items():
        df.to_csv(tables / f"{name}.csv", index=False)
    a = analyse(f)
    for name in (
        "by_slot",
        "fixed",
        "detection",
        "calibration",
        "snipes",
        "top_lost",
        "team_strength",
        "punt_share",
        "by_switches",
        "fixed_by_slot_group",
    ):
        obj = a.get(name)
        if isinstance(obj, pd.DataFrame):
            obj.to_csv(tables / f"{name}.csv")
    page, summary = build_report(a, f, args.study)
    (args.study / "report.html").write_text(page)
    (args.study / "summary.md").write_text(summary)
    print(summary)
    print(f"\nreport: {args.study / 'report.html'}")


if __name__ == "__main__":
    main()
