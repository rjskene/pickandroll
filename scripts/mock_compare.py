"""Compare mock-draft studies run under different planner settings.

    python scripts/mock_compare.py --out data/studies/2026-09-23 --baseline sum-adp

Every subdirectory of ``--out`` holding ``mock_*.json`` files from ``scripts/mock_study.py`` is a
condition. Mocks with the same seed share the opponents, their drafters, punts and every random
draw, so conditions are compared pairwise by seed: the difference in each score is averaged over
the seeds both conditions ran, with a 95% confidence interval.

Scores per mock (my team against the eleven others in the same draft):

value
    Total z above replacement in the active categories under my best punt: the planner's own
    scale from the earlier study (``value_best``).
cats won
    Categories in which my summed z beats an opponent's, averaged over the eleven opponents.
matchups won
    Opponents I beat in five or more of the nine categories, out of eleven; the head-to-head
    scoreboard.
roto points
    Sum over categories of the number of teams I beat plus one (12 for the best team), out of 108.
rank
    My rank among the twelve teams by ``value``.

Writes ``compare/report.html``, ``compare/summary.md`` and ``compare/tables/*.csv`` under
``--out``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mock_study_report import (
    CAT_NAMES,
    CATS,
    _ok,
    bar_chart,
    calibration_chart,
    line_chart,
    mean_ci,
    punt_name,
    table,
    table_md,
)

CAT_LABELS = [CAT_NAMES[c] for c in CATS]
CONCEDED = -4.0  # a category total this far below the field is a punt in all but name
CAL_BINS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]


# --------------------------------------------------------------------------- loading
def load_condition(path: Path) -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted(path.glob("mock_*.json"))]


def describe(cfg: dict) -> str:
    parts = ["win curve" if cfg.get("objective") == "win" else "sum of z"]
    if cfg.get("objective") == "win":
        if cfg.get("sigma_scale", 1.0) != 1.0:
            parts.append(f"sigma x{cfg['sigma_scale']:g}")
    else:
        parts.append(f"up to {cfg.get('max_punts', 2)} punts")
    parts.append("survival table" if cfg.get("availability") == "survival" else "ADP model")
    return ", ".join(parts)


def score_final(final: dict) -> dict:
    """The scoreboard for one finished draft: value, categories, matchups, roto, rank."""
    teams = final["teams"]
    me = teams["me"]
    others = {t: info for t, info in teams.items() if t != "me"}
    values = sorted((t["value_best"] for t in teams.values()), reverse=True)
    rank = values.index(me["value_best"]) + 1
    won_per_cat = dict.fromkeys(CATS, 0)
    cats_won = []
    matchups = 0
    for info in others.values():
        w = 0
        for c in CATS:
            if me["z"][c] > info["z"][c]:
                won_per_cat[c] += 1
                w += 1
        cats_won.append(w)
        matchups += w >= 5
    roto = sum(1 + won_per_cat[c] for c in CATS)
    conceded = [c for c in CATS if me["z"][c] <= CONCEDED]
    return {
        "value": final["value_best"],
        "punt_best": final["punt_best"],
        "value_nopunt": final["value_nopunt"],
        "rank": rank,
        "top": int(rank == 1),
        "cats_won": float(np.mean(cats_won)),
        "matchups_won": matchups,
        "roto": roto,
        "conceded": len(conceded),
        "conceded_cats": "/".join(conceded) or "-",
        "won_per_cat": {c: won_per_cat[c] / len(others) for c in CATS},
        "my_z": dict(me["z"]),
        "field_mean": {c: float(np.mean([info["z"][c] for info in others.values()])) for c in CATS},
    }


SCORE_KEYS = ("won_per_cat", "my_z", "field_mean")


def mock_rows(name: str, mock: dict) -> tuple[dict, list[dict], list[dict]]:
    """Scores for one mock plus its per-category rows and plan-calibration rows."""
    run = mock["runs"]["auto"]
    final = run["final"]
    scored = score_final(final)
    recs = run["my_picks"]
    first = recs[0]
    expected_first = (
        sum(first["expected_wins"].values()) if first.get("expected_wins") else math.nan
    )
    # PuLP reports a HiGHS solve stopped at the time limit with an incumbent as "Optimal", so
    # count time-limited solves by their duration instead.
    limit = float(mock.get("config", {}).get("time_limit", 10.0))
    limited = sum(1 for r in recs if float(r.get("plan_seconds", 0.0)) >= 0.97 * limit)
    row = {
        "condition": name,
        "seed": mock["seed"],
        "slot": mock["slot"],
        **{k: v for k, v in scored.items() if k not in SCORE_KEYS},
        "punt_last": recs[-1]["punt"],
        "expected_wins_first": expected_first,
        "objective_first": first["objective"],
        "first_pick": first["player"],
        "first_z_rank": first["z_rank"],
        "reach": float(np.mean([r["adp_rank"] - r["z_rank"] for r in recs])),
        "seconds": run["seconds"],
        "solve_ms": float(np.mean([r["solve_ms"] for r in recs])),
        "plan_seconds": float(np.mean([r.get("plan_seconds", math.nan) for r in recs])),
        "time_limited": limited,
        "n_lp": sum(1 for s in mock["design"]["strategies"].values() if s == "lp"),
        "n_adp": sum(1 for s in mock["design"]["strategies"].values() if s == "adp"),
        "n_z": sum(1 for s in mock["design"]["strategies"].values() if s == "z"),
    }
    cat_rows = [
        {
            "condition": name,
            "seed": mock["seed"],
            "cat": c,
            "my_z": scored["my_z"][c],
            "win_rate": scored["won_per_cat"][c],
            "field_mean": scored["field_mean"][c],
        }
        for c in CATS
    ]
    taken_at = {p["player"]: p for p in run["picks"]}
    cal_rows = []
    for rec in recs:
        for planned in rec["plan"]:
            j = planned["pick"]
            if j == rec["overall"]:
                continue
            hit = taken_at.get(planned["player"])
            taker = hit["team"] if hit and hit["overall"] < j else None
            realized = taker is None or taker == "me"
            cal_rows.append(
                {
                    "condition": name,
                    "seed": mock["seed"],
                    "k": rec["k"],
                    "pick": j,
                    "next": int(j == rec["plan"][1]["pick"]) if len(rec["plan"]) > 1 else 0,
                    "p": planned["availability"],
                    "realized": int(realized),
                }
            )
    return row, cat_rows, cal_rows


def frames(out: Path) -> dict[str, pd.DataFrame | dict]:
    conditions = {}
    scores, cats, cal = [], [], []
    for path in sorted(p for p in out.iterdir() if p.is_dir()):
        mocks = load_condition(path)
        if not mocks:
            continue
        conditions[path.name] = {
            "config": mocks[0].get("config", {}),
            "n": len(mocks),
            "label": describe(mocks[0].get("config", {})),
        }
        for mock in mocks:
            row, cat_rows, cal_rows = mock_rows(path.name, mock)
            scores.append(row)
            cats.extend(cat_rows)
            cal.extend(cal_rows)
    return {
        "conditions": conditions,
        "scores": pd.DataFrame(scores),
        "cats": pd.DataFrame(cats),
        "cal": pd.DataFrame(cal),
    }


# --------------------------------------------------------------------------- analysis
METRICS = ["value", "cats_won", "matchups_won", "roto", "rank", "top", "conceded"]
METRIC_NAMES = {
    "value": "value (z above repl.)",
    "cats_won": "cats won of 9",
    "matchups_won": "matchups won of 11",
    "roto": "roto points of 108",
    "rank": "rank by value",
    "top": "share ranked first",
    "conceded": "cats conceded (z <= -4)",
}


def summary_table(scores: pd.DataFrame, conditions: dict) -> pd.DataFrame:
    rows = []
    for name, info in conditions.items():
        sub = scores[scores["condition"] == name]
        row = {"condition": name, "setting": info["label"], "n": len(sub)}
        for m in METRICS:
            mean, half, _ = mean_ci(sub[m].tolist())
            row[m] = mean
            row[f"{m}_ci"] = half
        row["seconds"] = float(sub["seconds"].mean())
        row["time_limited"] = float(sub["time_limited"].mean())
        rows.append(row)
    return pd.DataFrame(rows).set_index("condition")


def paired(scores: pd.DataFrame, baseline: str, conditions: dict) -> pd.DataFrame:
    base = scores[scores["condition"] == baseline].set_index("seed")
    rows = []
    for name in conditions:
        if name == baseline:
            continue
        other = scores[scores["condition"] == name].set_index("seed")
        seeds = base.index.intersection(other.index)
        row = {"condition": name, "vs": baseline, "n": len(seeds)}
        for m in METRICS:
            diff = (other.loc[seeds, m] - base.loc[seeds, m]).astype(float)
            mean, half, _ = mean_ci(diff.tolist())
            row[m] = mean
            row[f"{m}_ci"] = half
            row[f"{m}_better"] = (
                float((diff > 0).mean())
                if m not in ("rank", "conceded")
                else float((diff < 0).mean())
            )
        rows.append(row)
    return pd.DataFrame(rows).set_index("condition")


def factorial(scores: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    """Main effects and interaction of objective and availability on the four main
    conditions, on the seeds all four ran."""
    have = [n for n in names.values() if n in set(scores["condition"])]
    if len(have) < 4:
        return pd.DataFrame()
    wide = {
        key: scores[scores["condition"] == name].set_index("seed") for key, name in names.items()
    }
    seeds = wide["sum_adp"].index
    for w in wide.values():
        seeds = seeds.intersection(w.index)
    rows = []
    for m in METRICS:
        a = wide["sum_adp"].loc[seeds, m].astype(float)
        b = wide["win_adp"].loc[seeds, m].astype(float)
        c = wide["sum_surv"].loc[seeds, m].astype(float)
        d = wide["win_surv"].loc[seeds, m].astype(float)
        objective = ((b - a) + (d - c)) / 2
        availability = ((c - a) + (d - b)) / 2
        interaction = (d - c) - (b - a)
        row = {"metric": m, "n": len(seeds)}
        for label, diff in (
            ("objective", objective),
            ("availability", availability),
            ("interaction", interaction),
        ):
            mean, half, _ = mean_ci(diff.tolist())
            row[label] = mean
            row[f"{label}_ci"] = half
        rows.append(row)
    return pd.DataFrame(rows).set_index("metric")


def by_slot(scores: pd.DataFrame, conditions: dict, metric: str) -> pd.DataFrame:
    groups = pd.cut(scores["slot"], [0, 4, 8, 12], labels=["slots 1-4", "slots 5-8", "slots 9-12"])
    out = scores.assign(group=groups).pivot_table(
        index="condition", columns="group", values=metric, aggfunc="mean", observed=True
    )
    return out.reindex(list(conditions))


def by_opponents(scores: pd.DataFrame, conditions: dict, metric: str) -> pd.DataFrame:
    groups = pd.cut(scores["n_lp"], [-1, 2, 4, 11], labels=["0-2 LP", "3-4 LP", "5+ LP"])
    out = scores.assign(group=groups).pivot_table(
        index="condition", columns="group", values=metric, aggfunc="mean", observed=True
    )
    return out.reindex(list(conditions))


def cat_profile(cats: pd.DataFrame, conditions: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    win = cats.pivot_table(index="condition", columns="cat", values="win_rate", aggfunc="mean")
    z = cats.pivot_table(index="condition", columns="cat", values="my_z", aggfunc="mean")
    win = win.reindex(index=list(conditions), columns=CATS)
    z = z.reindex(index=list(conditions), columns=CATS)
    win.columns = CAT_LABELS
    z.columns = CAT_LABELS
    return win, z


def conceded_profile(scores: pd.DataFrame, conditions: dict) -> pd.DataFrame:
    counts = scores.pivot_table(
        index="condition", columns="conceded", values="seed", aggfunc="count", fill_value=0
    )
    counts = counts.reindex(list(conditions)).fillna(0)
    share = counts.div(counts.sum(axis=1), axis=0)
    share.columns = [f"{int(c)} conceded" for c in share.columns]
    return share


def top_conceded(scores: pd.DataFrame, conditions: dict, k: int = 5) -> pd.DataFrame:
    rows = []
    for name in conditions:
        sub = scores[scores["condition"] == name]
        top = sub["conceded_cats"].value_counts(normalize=True).head(k)
        rows.append(
            {
                "condition": name,
                **{
                    f"#{i + 1}": f"{punt_name(label)} ({share:.0%})"
                    for i, (label, share) in enumerate(top.items())
                },
            }
        )
    return pd.DataFrame(rows).set_index("condition")


def calibration(cal: pd.DataFrame, conditions: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Predicted vs realized availability of planned players, by availability model (pooled
    over the objectives that used it), plus a Brier score and loss rates per condition."""
    model = {name: info["config"].get("availability", "adp") for name, info in conditions.items()}
    cal = cal.assign(model=cal["condition"].map(model))
    cal = cal.assign(bin=pd.cut(cal["p"], CAL_BINS, right=False, include_lowest=True))
    curves = (
        cal.groupby(["model", "bin"], observed=True)
        .agg(predicted=("p", "mean"), realized=("realized", "mean"), planned=("p", "size"))
        .reset_index()
    )
    per = (
        cal.groupby("condition")
        .apply(
            lambda g: pd.Series(
                {
                    "planned": len(g),
                    "expected_available": g["p"].mean(),
                    "realized_available": g["realized"].mean(),
                    "brier": float(((g["p"] - g["realized"]) ** 2).mean()),
                    "next_pick_expected": g.loc[g["next"] == 1, "p"].mean(),
                    "next_pick_realized": g.loc[g["next"] == 1, "realized"].mean(),
                }
            ),
            include_groups=False,
        )
        .reindex(list(conditions))
    )
    return curves, per


def convergence(scores: pd.DataFrame, baseline: str, name: str, metric: str) -> pd.DataFrame:
    base = scores[scores["condition"] == baseline].set_index("seed")[metric]
    other = scores[scores["condition"] == name].set_index("seed")[metric]
    seeds = sorted(base.index.intersection(other.index))
    diff = (other.loc[seeds] - base.loc[seeds]).astype(float).to_numpy()
    rows = []
    for n in range(10, len(diff) + 1, max(1, len(diff) // 60)):
        part = diff[:n]
        half = 1.96 * part.std(ddof=1) / math.sqrt(n)
        rows.append(
            {"n": n, "mean": part.mean(), "lo": part.mean() - half, "hi": part.mean() + half}
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- report
def fmt_ci(mean: float, half: float, digits: int = 2) -> str:
    if not _ok(mean):
        return ""
    if not _ok(half):
        return f"{mean:.{digits}f}"
    return f"{mean:.{digits}f} ± {half:.{digits}f}"


def ci_table(df: pd.DataFrame, metrics: list[str], extra: list[str] = ()) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col in extra:
        out[col] = df[col]
    for m in metrics:
        digits = 3 if m in ("top",) else 2
        out[METRIC_NAMES.get(m, m)] = [
            fmt_ci(v, h, digits) for v, h in zip(df[m], df[f"{m}_ci"], strict=True)
        ]
    return out


def build(f: dict, a: dict, out: Path, baseline: str) -> tuple[str, str]:
    conditions = f["conditions"]
    summary = a["summary"]
    pairs = a["paired"]
    sections: list[str] = []
    md: list[str] = []
    n_base = int(summary.loc[baseline, "n"]) if baseline in summary.index else 0

    md.append(f"# Objective and availability study ({out.name})\n")
    md.append(
        f"Conditions: {', '.join(f'{k} ({v["label"]}, {v["n"]} mocks)' for k, v in conditions.items())}. Baseline {baseline}. Same seeds face the same opponents; differences are paired by seed with 95% confidence intervals.\n"
    )

    # --- scoreboard
    cols = ["setting", "n"]
    sb = ci_table(summary, METRICS, cols)
    sb["s/mock"] = summary["seconds"].round(0)
    md.append("## Scoreboard (mean ± 95% CI)\n")
    md.append(table_md(sb))
    pt = ci_table(pairs, METRICS, ["n"])
    for m in ("matchups_won", "cats_won", "value"):
        pt[f"{METRIC_NAMES[m]}: share better"] = pairs[f"{m}_better"].map(lambda v: f"{v:.0%}")
    md.append(f"## Paired differences vs {baseline}\n")
    md.append(table_md(pt))
    fact = a["factorial"]
    if not fact.empty:
        ft = pd.DataFrame(index=[METRIC_NAMES[m] for m in fact.index])
        ft["n"] = fact["n"].tolist()
        for col in ("objective", "availability", "interaction"):
            ft[col] = [fmt_ci(v, h) for v, h in zip(fact[col], fact[f"{col}_ci"], strict=True)]
        md.append("## Main effects (win curve vs sum; survival vs ADP; interaction)\n")
        md.append(table_md(ft))

    labels = list(conditions)
    charts = []
    for m in ("matchups_won", "cats_won", "value", "roto"):
        halves = [h if _ok(h) else 0.0 for h in summary.loc[labels, f"{m}_ci"].tolist()]
        charts.append(
            bar_chart(
                labels,
                {METRIC_NAMES[m]: summary.loc[labels, m].tolist()},
                f"{METRIC_NAMES[m]} by condition",
                errors={METRIC_NAMES[m]: halves},
                zero=False,
            )
        )
    sections.append(f"""
<h2>1. Scoreboard</h2>
<p class="lede">Each condition drafts my team through the same {n_base} simulated leagues (seeds) with a different planner setting; the opponents and every random draw are identical, so the conditions differ only through my picks and what they do to the board.</p>
{table(sb, index=True)}
<p class="note">value: total z above replacement under my best punt (the earlier study's scale). cats won: categories where my summed z beats an opponent, averaged over eleven opponents. matchups won: opponents beaten in five or more categories. roto: one point per team beaten per category plus one, out of 108. conceded: categories where my total is at least 4 z below the field's mean, punted in all but name.</p>
<div class="row">{"".join(charts)}</div>
<h3>Paired differences vs {baseline}</h3>
{table(pt, index=True)}
""")
    if not fact.empty:
        sections.append(f"""
<h3>Main effects on the four main conditions</h3>
<p>Two-by-two design: objective (sum of z vs win curve) crossed with availability (ADP model vs survival table), each effect averaged over the other factor, paired by seed.</p>
{table(ft, index=True)}
""")

    # --- categories
    win, z = a["cat_win"], a["cat_z"]
    main = [n for n in labels if n in ("sum-adp", "win-adp", "sum-surv", "win-surv")] or labels[:4]
    cat_chart = bar_chart(
        CAT_LABELS,
        {n: win.loc[n].tolist() for n in main},
        "share of opponents beaten, by category",
        ylabel="share",
    )
    z_chart = bar_chart(
        CAT_LABELS,
        {n: z.loc[n].tolist() for n in main},
        "my category total (z summed over the roster)",
        ylabel="z",
    )
    md.append("## Category win rates\n")
    md.append(table_md(win))
    md.append("## Category totals (mean z)\n")
    md.append(table_md(z))
    conc = a["conceded"]
    topc = a["top_conceded"]
    md.append("## Categories conceded (total at least 4 z below the field)\n")
    md.append(table_md(conc))
    md.append(table_md(topc))
    sections.append(f"""
<h2>2. Where the categories go</h2>
<p>The sum objective with a two-category punt gives up two categories and piles surplus into the ones it already wins. The win curve gets no explicit punt: a category is worth its chance of beating the field, so it concedes on its own whatever it cannot win and stops paying for surplus.</p>
<div class="row">{cat_chart}{z_chart}</div>
<h3>Share of opponents beaten, by category</h3>
{table(win, index=True, pct_cols=list(win.columns))}
<h3>My category totals</h3>
{table(z, index=True)}
<h3>Categories conceded</h3>
<p>A category is counted as conceded when my total ends at least {abs(CONCEDED):.0f} z below the field. The distribution of how many, and the most common sets.</p>
{table(conc, index=True, pct_cols=list(conc.columns))}
{table(topc, index=True)}
""")

    # --- availability
    curves, per = a["cal_curves"], a["cal_per"]
    cal_charts = "".join(
        calibration_chart(curves[curves["model"] == m], f"{m}: planned players still there")
        for m in curves["model"].unique()
    )
    md.append("## Availability calibration (planned players)\n")
    md.append(table_md(per))
    sections.append(f"""
<h2>3. Availability: ADP model vs survival table</h2>
<p>Every plan names a player for each later pick with the odds he is still there. The ADP model is 1 − Φ((k − adp) / (3 + 0.15·adp)); the survival table is the share of {a["sim_n"]} simulated all-auto drafts in which the player was still on the board at pick k, conditioned on being there now. Points sit on the diagonal when the odds are calibrated; the Brier score (mean squared error of the odds) is lower when they are also sharper.</p>
<div class="row">{cal_charts}</div>
{table(per, index=True, pct_cols=["expected_available", "realized_available", "next_pick_expected", "next_pick_realized"], floatfmt="{:.3f}")}
""")

    # --- slots and opponents
    slot_m = a["by_slot_matchups"]
    slot_v = a["by_slot_value"]
    opp_m = a["by_opp_matchups"]
    md.append("## Matchups won by draft slot\n")
    md.append(table_md(slot_m))
    md.append("## Matchups won by number of LP opponents\n")
    md.append(table_md(opp_m))
    sections.append(f"""
<h2>4. Draft slot and opponents</h2>
<div class="cols"><div><h3>Matchups won, by slot group</h3>{table(slot_m, index=True)}</div><div><h3>Value, by slot group</h3>{table(slot_v, index=True)}</div></div>
<h3>Matchups won, by how many opponents run the roster model</h3>
{table(opp_m, index=True)}
""")

    # --- convergence and timing
    conv_charts = ""
    series = {}
    bands = {}
    for name, cv in a["convergence"].items():
        if cv.empty:
            continue
        series[name] = (cv["n"].tolist(), cv["mean"].tolist())
        bands[name] = (cv["n"].tolist(), cv["lo"].tolist(), cv["hi"].tolist())
    if series:
        conv_charts = line_chart(
            series,
            f"matchups won vs {baseline}: running mean and 95% CI by number of seeds",
            ylabel="matchups won, difference",
            xlabel="seeds",
            bands=bands,
        )
    timing = summary[["n", "seconds", "time_limited"]].copy()
    timing["plan_seconds"] = f["scores"].groupby("condition")["plan_seconds"].mean().reindex(labels)
    timing["reach (adp rank − z rank)"] = (
        f["scores"].groupby("condition")["reach"].mean().reindex(labels)
    )
    md.append("## Timing\n")
    md.append(table_md(timing))
    sections.append(f"""
<h2>5. Convergence and cost</h2>
{conv_charts}
<h3>Cost per mock</h3>
<p>seconds: one full draft on one core, my thirteen picks plus the opponents' roster-model picks. time_limited: my picks whose plan solve hit the time limit and kept the incumbent. plan_seconds: mean plan solve. The win curve runs with a per-pick candidate cap of 80 and a 1% MIP gap.</p>
{table(timing, index=True)}
""")

    body = "\n".join(sections)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Objective and availability study</title>
<style>
:root {{ --bg: #ffffff; --fg: #111827; --muted: #6b7280; --line: #e5e7eb; --accent: #2563eb; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --line: #262a33; }} }}
:root[data-theme="dark"] {{ --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --line: #262a33; }}
body {{ margin: 0; padding: 24px 16px 64px; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; }}
h1 {{ font-size: 26px; margin: 0 0 4px; }} h2 {{ font-size: 20px; margin: 40px 0 8px; border-top: 1px solid var(--line); padding-top: 20px; }} h3 {{ font-size: 15px; margin: 20px 0 6px; }}
.sub {{ color: var(--muted); margin: 0 0 16px; }} .lede {{ font-size: 16px; }}
.chart {{ width: 100%; height: auto; max-width: 760px; display: block; margin: 12px 0; background: #fff; border-radius: 8px; }}
.row {{ display: flex; flex-wrap: wrap; gap: 12px; }} .row .chart {{ flex: 1 1 320px; max-width: 460px; }}
.cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
table.tbl {{ border-collapse: collapse; font-size: 13px; margin: 8px 0 12px; width: 100%; overflow-x: auto; display: block; }}
.tbl th, .tbl td {{ padding: 4px 8px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }} .tbl th {{ color: var(--muted); font-weight: 500; }} .tbl td:first-child, .tbl th:first-child {{ text-align: left; }}
.note {{ color: var(--muted); font-size: 13px; }}
</style></head>
<body><main>
<h1>Objective and availability study</h1>
<p class="sub">{out.name} · {len(conditions)} conditions · generated by scripts/mock_compare.py</p>
{body}
</main></body></html>"""
    return page, "\n".join(md)


def analyse(f: dict, baseline: str, sim_n: int) -> dict:
    scores, cats, cal, conditions = f["scores"], f["cats"], f["cal"], f["conditions"]
    a: dict = {"sim_n": sim_n}
    a["summary"] = summary_table(scores, conditions)
    a["paired"] = paired(scores, baseline, conditions)
    a["factorial"] = factorial(
        scores,
        {
            "sum_adp": "sum-adp",
            "win_adp": "win-adp",
            "sum_surv": "sum-surv",
            "win_surv": "win-surv",
        },
    )
    a["cat_win"], a["cat_z"] = cat_profile(cats, conditions)
    a["conceded"] = conceded_profile(scores, conditions)
    a["top_conceded"] = top_conceded(scores, conditions)
    a["cal_curves"], a["cal_per"] = calibration(cal, conditions)
    a["by_slot_matchups"] = by_slot(scores, conditions, "matchups_won")
    a["by_slot_value"] = by_slot(scores, conditions, "value")
    a["by_opp_matchups"] = by_opponents(scores, conditions, "matchups_won")
    a["convergence"] = {
        name: convergence(scores, baseline, name, "matchups_won")
        for name in conditions
        if name != baseline
    }
    return a


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", default="sum-adp")
    args = parser.parse_args()
    f = frames(args.out)
    if args.baseline not in f["conditions"]:
        raise SystemExit(f"baseline {args.baseline!r} not among {list(f['conditions'])}")
    sim_n = 0
    sims_file = args.out / "sim" / "survival.csv.sims"
    if sims_file.exists():
        sim_n = int(sims_file.read_text().strip())
    a = analyse(f, args.baseline, sim_n)
    target = args.out / "compare"
    (target / "tables").mkdir(parents=True, exist_ok=True)
    f["scores"].to_csv(target / "tables" / "scores.csv", index=False)
    f["cats"].to_csv(target / "tables" / "cats.csv", index=False)
    for key in (
        "summary",
        "paired",
        "factorial",
        "cat_win",
        "cat_z",
        "conceded",
        "top_conceded",
        "cal_curves",
        "cal_per",
        "by_slot_matchups",
        "by_slot_value",
        "by_opp_matchups",
    ):
        a[key].to_csv(target / "tables" / f"{key}.csv")
    page, md = build(f, a, args.out, args.baseline)
    (target / "report.html").write_text(page)
    (target / "summary.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
