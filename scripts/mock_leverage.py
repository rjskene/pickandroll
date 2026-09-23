"""Leverage of each of my picks: what the planner's choice at round k was worth.

    python scripts/mock_leverage.py --out data/studies/2026-09-23 --runs win-surv-naive sum-adp-naive

Reads leverage studies written by ``scripts/mock_study.py --naive-branches``: for every seed the
finished draft (``auto``) and, per round k, the same draft with the consensus pick (best
available by ADP order) made at my k-th pick and the planner drafting the rest. The paired
difference ``auto - naive_k`` in matchups won, categories won, value and roto points is the
incremental alpha of the planner at round k. Rounds where the consensus and the planner agreed
count as zero alpha; the share of such rounds is reported alongside, with the alpha among the
rounds where they disagreed.

Writes ``leverage/report.html``, ``leverage/summary.md`` and ``leverage/tables/*.csv`` under
``--out``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mock_compare import METRIC_NAMES, score_final
from mock_study_report import line_chart, mean_ci, table, table_md

METRICS = ["matchups_won", "cats_won", "value", "roto"]


def rows_for(name: str, path: Path) -> list[dict]:
    rows = []
    for f in sorted(path.glob("mock_*.json")):
        mock = json.loads(f.read_text())
        auto = mock["runs"]["auto"]
        base = score_final(auto["final"])
        for run_name, run in mock["runs"].items():
            if run_name == "auto":
                continue
            k = run["naive_at"]
            scored = score_final(run["final"])
            naive = next(r for r in run["my_picks"] if r.get("naive"))
            planner = auto["my_picks"][k - 1]
            rows.append(
                {
                    "study": name,
                    "seed": mock["seed"],
                    "slot": mock["slot"],
                    "k": k,
                    "round": k,
                    "overall": planner["overall"],
                    "planner_pick": planner["player"],
                    "naive_pick": naive["player"],
                    "same": int(planner["player"] == naive["player"]),
                    "planner_z_rank": planner["z_rank"],
                    "naive_z_rank": naive["z_rank"],
                    "planner_adp_rank": planner["adp_rank"],
                    **{m: base[m] - scored[m] for m in METRICS},
                }
            )
    return rows


def by_round(df: pd.DataFrame, only_different: bool = False) -> pd.DataFrame:
    out = []
    for (study, k), g in df.groupby(["study", "k"]):
        sub = g[g["same"] == 0] if only_different else g
        row = {"study": study, "round": k, "n": len(sub), "same_share": float(g["same"].mean())}
        for m in METRICS:
            mean, half, _ = mean_ci(sub[m].tolist())
            row[m] = mean
            row[f"{m}_ci"] = half
        out.append(row)
    return pd.DataFrame(out)


def cumulative(df: pd.DataFrame) -> pd.DataFrame:
    """Alpha summed over rounds 1..k: the profile's shape says where the planner earns its keep."""
    per = by_round(df)
    out = []
    for study, g in per.groupby("study"):
        g = g.sort_values("round")
        for m in METRICS:
            g[f"{m}_cum"] = g[m].cumsum()
        out.append(g)
    return pd.concat(out)


def fmt(mean: float, half: float) -> str:
    if pd.isna(mean):
        return ""
    return f"{mean:.2f} ± {half:.2f}" if not pd.isna(half) else f"{mean:.2f}"


def report(df: pd.DataFrame, out: Path) -> tuple[str, str]:
    per = by_round(df)
    diff = by_round(df, only_different=True)
    cum = cumulative(df)
    md: list[str] = [f"# Round leverage ({out.name})\n"]
    md.append(
        "Incremental alpha of the planner's pick at each round: the finished draft minus the same draft with the consensus pick (best available by ADP order) made at that round and the planner drafting the rest. Paired by seed, mean ± 95% CI. `same` is the share of rounds where the consensus pick and the planner's agreed (zero alpha by construction); the second table conditions on the rounds where they differed.\n"
    )
    sections: list[str] = []
    for study, g in per.groupby("study"):
        g = g.sort_values("round").set_index("round")
        t = pd.DataFrame(index=g.index)
        t["n"] = g["n"]
        t["same"] = g["same_share"].map(lambda v: f"{v:.0%}")
        for m in METRICS:
            t[METRIC_NAMES.get(m, m)] = [fmt(a, b) for a, b in zip(g[m], g[f"{m}_ci"], strict=True)]
        md.append(f"## {study}: alpha by round, all seeds\n")
        md.append(table_md(t))
        d = diff[diff["study"] == study].sort_values("round").set_index("round")
        td = pd.DataFrame(index=d.index)
        td["n different"] = d["n"]
        for m in METRICS:
            td[METRIC_NAMES.get(m, m)] = [
                fmt(a, b) for a, b in zip(d[m], d[f"{m}_ci"], strict=True)
            ]
        md.append(f"## {study}: alpha by round, rounds where the picks differed\n")
        md.append(table_md(td))
        c = cum[cum["study"] == study].sort_values("round")
        chart = line_chart(
            {
                "matchups won": (c["round"].tolist(), c["matchups_won"].tolist()),
                "cats won": (c["round"].tolist(), c["cats_won"].tolist()),
            },
            f"{study}: alpha of the planner's pick by round",
            ylabel="auto − consensus pick at round k",
            xlabel="round",
            bands={
                "matchups won": (
                    c["round"].tolist(),
                    (c["matchups_won"] - c["matchups_won_ci"]).tolist(),
                    (c["matchups_won"] + c["matchups_won_ci"]).tolist(),
                )
            },
            xticks=list(range(1, 14)),
        )
        value_chart = line_chart(
            {"value": (c["round"].tolist(), c["value"].tolist())},
            f"{study}: value alpha by round",
            ylabel="z above replacement, auto − consensus",
            xlabel="round",
            bands={
                "value": (
                    c["round"].tolist(),
                    (c["value"] - c["value_ci"]).tolist(),
                    (c["value"] + c["value_ci"]).tolist(),
                )
            },
            xticks=list(range(1, 14)),
        )
        cum_chart = line_chart(
            {
                "matchups won, cumulative": (c["round"].tolist(), c["matchups_won_cum"].tolist()),
                "cats won, cumulative": (c["round"].tolist(), c["cats_won_cum"].tolist()),
            },
            f"{study}: alpha summed over rounds 1..k",
            ylabel="cumulative alpha",
            xlabel="round",
            xticks=list(range(1, 14)),
        )
        sections.append(f"""
<h2>{study}</h2>
<div class="row">{chart}{value_chart}</div>
{cum_chart}
<h3>Alpha by round, all seeds</h3>
{table(t, index=True)}
<h3>Alpha by round, rounds where the consensus pick and the planner differed</h3>
{table(td, index=True)}
""")
    body = "\n".join(sections)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Round leverage</title>
<style>
:root {{ --bg: #ffffff; --fg: #111827; --muted: #6b7280; --line: #e5e7eb; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --line: #262a33; }} }}
:root[data-theme="dark"] {{ --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --line: #262a33; }}
body {{ margin: 0; padding: 24px 16px 64px; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; }}
h1 {{ font-size: 26px; margin: 0 0 4px; }} h2 {{ font-size: 20px; margin: 40px 0 8px; border-top: 1px solid var(--line); padding-top: 20px; }} h3 {{ font-size: 15px; margin: 20px 0 6px; }}
.chart {{ width: 100%; height: auto; max-width: 760px; display: block; margin: 12px 0; background: #fff; border-radius: 8px; }}
.row {{ display: flex; flex-wrap: wrap; gap: 12px; }} .row .chart {{ flex: 1 1 320px; max-width: 460px; }}
table.tbl {{ border-collapse: collapse; font-size: 13px; margin: 8px 0 12px; width: 100%; overflow-x: auto; display: block; }}
.tbl th, .tbl td {{ padding: 4px 8px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }} .tbl th {{ color: var(--muted); font-weight: 500; }} .tbl td:first-child, .tbl th:first-child {{ text-align: left; }}
</style></head>
<body><main>
<h1>Round leverage</h1>
<p>Incremental alpha of the planner's pick at each round: the finished draft minus the same draft with the consensus pick (best available by ADP order) made at that round and the planner drafting the rest. Paired by seed, 95% confidence bands.</p>
{body}
</main></body></html>"""
    return page, "\n".join(md)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", nargs="+", required=True, help="leverage study dirs under --out")
    args = parser.parse_args()
    rows = []
    for name in args.runs:
        rows.extend(rows_for(name, args.out / name))
    if not rows:
        raise SystemExit("no leverage runs found")
    df = pd.DataFrame(rows)
    target = args.out / "leverage"
    (target / "tables").mkdir(parents=True, exist_ok=True)
    df.to_csv(target / "tables" / "branches.csv", index=False)
    by_round(df).to_csv(target / "tables" / "by_round.csv", index=False)
    by_round(df, only_different=True).to_csv(
        target / "tables" / "by_round_different.csv", index=False
    )
    page, md = report(df, args.out)
    (target / "report.html").write_text(page)
    (target / "summary.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
