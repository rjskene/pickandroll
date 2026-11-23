"""SEASON SIM (#172, PR lab): the lab's model on made-up records, its server on a loopback
port, its command and its static files. No network beyond loopback, no real record."""

from __future__ import annotations

import contextlib
import copy
import http.client
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path
from statistics import NormalDist

import pytest

from pickandroll.sim import cli
from pickandroll.sim.lab import model as md
from pickandroll.sim.lab import records as rd
from pickandroll.sim.lab import server as sv
from pickandroll.sim.lab import trace_view as tv

ONE_WIN = {
    "scoring": "categories",
    "points": None,
    "held": ["IL", "IL"],
    "h2h": "one_win",
    "waivers": "faab",
    "waiver_days": 2,
    "waiver_rule": "continuous",
    "budget": 100,
    "rival_scale": 1.0,
    "rival_bids": "book",
}
EACH = {
    "scoring": "categories",
    "points": None,
    "held": [],
    "h2h": "each_category",
    "waivers": "priority",
    "waiver_days": 2,
    "waiver_rule": "dropped",
}
#: A pair's shape as the records hold it: ``slots`` is the list of positions.
SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "UTIL", "UTIL", "BN", "BN", "BN"]
SHAPE = {"teams": 10, "slots": SLOTS, "weekly_adds": 4, "playoff_teams": 4, "playoff_weeks": 3}


# --------------------------------------------------------------------------- made-up records
def block(measure: str, mean: float, se: float) -> dict:
    """A difference block: ``mean`` and ``se`` on ``measure``, a small move on every other."""
    out = {o: {"mean": 0.01, "se": 0.02, "n": 8} for o in md.OUTCOMES}
    out[measure] = {"mean": mean, "se": se, "n": 8}
    return out


def row(
    key: str,
    lever: str,
    mean: float | None,
    se: float = 0.5,
    *,
    measure: str = "matchup_wins",
    both: dict | None = None,
    did_nothing: bool = False,
    values: tuple = (0, 1),
    tier: str = "surrogate",
    season: str = "2023",
    status: str = "played",
) -> dict:
    out = {
        "lever": lever,
        "key": key,
        "nudge": f"{lever}: {values[0]} to {values[1]}",
        "tier": tier,
        "both": {"tier": tier} | (both or {}),
        "values": {"a": values[0], "b": values[1]},
        "status": status,
        "why": None if status == "played" else "made-up reason",
        "note": None,
        "file": f"{key}.json",
    }
    if mean is None:
        out["result"] = None
        return out
    clears = abs(mean) > se
    out["result"] = {
        "cells": {
            season: {
                "prior": {
                    "paths": 8,
                    "difference": block(measure, mean, se),
                    "clears": clears,
                    "counts": {},
                }
            }
        },
        "counts_equal": did_nothing,
        "outcomes_equal": did_nothing,
        "did_nothing": did_nothing,
        "measure": measure,
        "paths": 8,
        "survives": clears and not did_nothing,
        "voided": 0,
    }
    return out


def pair(r: dict, *, breaches: int = 0, voided: int = 0, base: float = 5.0) -> dict:
    cells = r["result"]["cells"]
    results, counts = {}, {}
    for t, by in cells.items():
        for lab, c in by.items():
            a = {o: {"mean": base, "se": 0.3, "n": 8} for o in md.OUTCOMES}
            b = {
                o: {"mean": base + (c["difference"][o]["mean"] or 0.0), "se": 0.3, "n": 8}
                for o in md.OUTCOMES
            }
            results.setdefault(t, {})[lab] = {
                "a": a,
                "b": b,
                "difference": c["difference"],
                "paths": 8,
            }
            counts.setdefault(t, {})[lab] = {
                "a": {"adds_per_week": {"mean": 1.5}},
                "b": {"adds_per_week": {"mean": 2.5}},
                "rivals": {},
            }
    return {
        "kind": "replay",
        "results": results,
        "counts": {"by_season": counts},
        "audit": {"breaches": [{"what": "made up"}] * breaches, "paths_voided": voided},
        "league": {"rules": {}, "shapes": [SHAPE]},
    }


def screen(
    name: str,
    rules: dict,
    rows: list[dict],
    *,
    seasons: tuple = (2023,),
    seed: int = 1,
    started: str = "2026-01-02T10:00:00+00:00",
    finished: str = "2026-01-02T12:00:00+00:00",
    measure: str = "matchup_wins",
    left: list | None = None,
    breaches: dict | None = None,
    hold_out: int = 2025,
) -> dict:
    record = {
        "kind": "screen",
        "name": name,
        "screen_version": 1,
        "spec": {
            "world": {"seasons": list(seasons), "paths": 8, "seed": seed, "forecasters": "prior"},
            "replay_version": 1,
        },
        "code_sha": "abcdef0123456789",
        "hold_out": hold_out,
        "league": {"rules": rules, "label": "made-up league, the rivals' bids on the book x1"},
        "measure": measure,
        "rows": rows,
        "left": left or [],
        "timing": {
            "pieces": [
                {"started_at": started, "finished_at": finished, "played": [r["key"] for r in rows]}
            ]
        },
    }
    pairs = {
        r["file"]: pair(r, breaches=(breaches or {}).get(r["key"], 0))
        for r in rows
        if r.get("result")
    }
    return {"folder": name, "record": record, "pairs": pairs}


def tune(name: str, rules: dict, *, confirm: int = 2024, taken: float = 0.6, kept: float = 0.3):
    step_values = [
        {
            "key": "pool-up",
            "nudge": "pool: 10 to 20",
            "values": {"a": 10, "b": 20},
            "status": "played",
            "result": {"mean": taken, "se": 0.2, "signs": "above", "voided": 0},
        },
        {
            "key": "pool-down",
            "nudge": "pool: 10 to 5",
            "values": {"a": 10, "b": 5},
            "status": "played",
            "result": {"mean": -0.1, "se": 0.2, "signs": "flips", "voided": 0},
        },
    ]
    conf_cells = {
        "run": {
            "prior": {
                "difference": block("matchup_wins", kept, 0.1),
                "read": True,
                "finish": "ahead",
            }
        },
        "static": {
            "prior": {
                "difference": block("matchup_wins", kept / 2, 0.1),
                "read": True,
                "finish": "level",
            }
        },
    }
    record = {
        "kind": "tune",
        "name": name,
        "tune_version": 1,
        "spec": {"world": {"seasons": [2023], "paths": 8, "seed": 1}, "confirm": confirm},
        "code_sha": "abcdef0123456789",
        "hold_out": 2025,
        "league": {"rules": rules, "label": "made-up league"},
        "measure": "matchup_wins",
        "order": [{"lever": "pool", "from": 10, "strength": 2.0, "place": 1}],
        "steps": [
            {
                "pass": 1,
                "lever": "pool",
                "from": 10,
                "values": step_values,
                "choice": {
                    "key": "pool-up",
                    "passed": ["pool-up"],
                    "standings": {"pool-up": "taken", "pool-down": "below"},
                    "depends": [],
                },
            }
        ],
        "final": {"set": {"pool": 20}, "levers": ["pool"], "tier": "surrogate", "unread": {}},
        "confirmation": {
            "season": confirm,
            "status": "played",
            "cells": conf_cells,
            "verdict": {"state": "confirmed", "words": "made-up verdict", "flags": []},
        },
        "left": None,
        "timing": {
            "pieces": [
                {
                    "started_at": "2026-01-03T10:00:00+00:00",
                    "finished_at": "2026-01-03T11:00:00+00:00",
                    "played": ["p1-pool-up"],
                }
            ]
        },
    }
    return {"folder": name, "record": record, "pairs": {}}


def built(screens=(), tunes=(), replays=(), looks=(), notes=None, **kw):
    return md.build(
        list(screens),
        list(tunes),
        list(replays),
        list(looks),
        notes,
        traces=list(kw.get("traces", ())),
        hold_out=kw.get("hold_out", 2025),
        confirmation=kw.get("confirmation", 2026),
        generated={"at": "2026-01-04T00:00:00+00:00", "code_sha": None},
    )


def flag(rs: dict, title: str) -> dict:
    return next(f for f in rs["checks"]["flags"] if f["title"] == title)


def two_screens():
    a = screen(
        "s-one",
        ONE_WIN,
        [
            row("base-exact", "pool", 0.0, both={"season_weight": 0.5}, tier="exact"),
            row("base", "pool", 0.0, did_nothing=True),
            row("up", "pool", 1.2, 0.5, values=(10, 20)),
            row("down", "min_gain", -0.9, 0.4),
            row("small", "daily_cap", 0.1, 0.5),
            row("cap", "season_weight", 0.8, 0.5, values=(0, 0.5)),
            row("never", "guard", None, status="not played"),
        ],
    )
    b = screen(
        "s-each",
        EACH,
        [
            row("base", "pool", 0.0, did_nothing=True, measure="category_wins"),
            row("up", "pool", 2.0, 0.5, measure="category_wins", values=(10, 20)),
            row("down", "min_gain", 1.5, 0.5, measure="category_wins"),
            row("cap", "season_weight", -0.2, 0.5, measure="category_wins", values=(0, 0.5)),
        ],
        measure="category_wins",
        started="2026-01-01T10:00:00+00:00",
        finished="2026-01-01T11:00:00+00:00",
    )
    return a, b


# --------------------------------------------------------------------------- the model
def test_ruleset_key_leaves_out_the_rivals_and_keeps_the_rest():
    k = md.ruleset_key(ONE_WIN)
    assert k == md.ruleset_key(ONE_WIN | {"rival_scale": 2.0, "rival_bids": "assumed"})
    assert k == md.ruleset_key(
        {key: v for key, v in ONE_WIN.items() if not key.startswith("rival")}
    )
    assert k != md.ruleset_key(ONE_WIN | {"budget": 200})
    assert k != md.ruleset_key(ONE_WIN | {"h2h": "each_category"})
    assert md.rules_label("teams 10, FAAB, the rivals' bids on the book x1") == "teams 10, FAAB"


def test_two_rulesets_by_their_rules_ordered_by_first_run_or_the_notes():
    a, b = two_screens()
    m = built([a, b])
    keys = [x["key"] for x in m["rulesets"]]
    assert keys == [md.ruleset_key(EACH), md.ruleset_key(ONE_WIN)]
    assert [x["measure"] for x in m["rulesets"]] == ["category_wins", "matchup_wins"]
    assert [x["tone"] for x in m["rulesets"]] == [0, 1]
    assert m["rulesets"][1]["name"] == "One win a matchup, FAAB"
    assert m["rulesets"][1]["named"] == "rules"
    assert m["rulesets"][1]["teams"] == 10
    notes = md.notes_of({"rulesets": {md.ruleset_key(ONE_WIN): {"name": "Ours", "order": 0}}})
    m = built([a, b], notes=notes)
    assert m["rulesets"][0]["name"] == "Ours"
    assert m["rulesets"][0]["named"] == "notes"


def test_the_baseline_is_a_row_with_nothing_in_both_never_the_first_row():
    a, _ = two_screens()
    m = built([a])
    rs = m["rulesets"][0]
    assert rs["baseline"]["row"] == "base"
    assert rs["baseline"]["cells"][0]["outcomes"]["matchup_wins"]["mean"] == 5.0
    assert rs["stages"][0]["tag"] == "played"
    only_both = screen("s-x", ONE_WIN, [row("b", "pool", 0.3, both={"season_weight": 0.5})])
    m = built([only_both])
    assert m["rulesets"][0]["baseline"] is None
    assert m["rulesets"][0]["stages"][0]["tag"] == "not recorded"
    assert any("no baseline" in x for x in m["generated"]["lacks"])


def test_survivors_both_ways_did_nothing_and_not_played():
    a, _ = two_screens()
    rs = built([a])["rulesets"][0]
    t = rs["tried"]
    # up and down clear their SE (1.2 > 0.5, 0.9 > 0.4), cap clears (0.8 > 0.5), small does not
    assert (t["done"], t["cleared"], t["better"], t["worse"]) == (5, 3, 2, 1)
    assert t["did_nothing"] == 1 and t["not_played"] == 1
    assert t["luck"] == pytest.approx(5 * md.ONE_SE)
    assert rs["strongest"]["key"] == "up"
    assert rs["strongest"]["values"] == {"a": "10", "b": "20"}
    assert rs["spark"][0]["key"] == "up"
    assert rs["stages"][1]["label"] == "Candidate pool size"
    assert rs["stages"][1]["diff"]["mean"] == 1.2


def test_survives_is_the_records_own_and_another_outcome_is_worked_out():
    a, _ = two_screens()
    m = built([a])
    rows = {r["key"]: r for r in m["knobs"]["rows"] if r["run"] == "s-one"}
    up = rows["up"]
    assert up["survives"] is True
    assert up["diff"]["matchup_wins"]["ratio"] == pytest.approx(1.2 / 0.5)
    assert up["diff"]["matchup_wins"]["side"] == "better"
    # rank is better down: a rise in rank is worse, and its z is signed so
    assert up["diff"]["rank"]["side"] == "worse"
    assert up["diff"]["rank"]["z"] == pytest.approx(-0.5)
    assert up["diff"]["rank"]["clears"] is False
    # a record that says it does not survive is believed, whatever its mean
    rec = a["record"]["rows"][2]["result"]
    rec["survives"] = False
    assert {r["key"]: r for r in built([a])["knobs"]["rows"]}["up"]["survives"] is False
    assert rows["never"]["played"] is False and rows["never"]["status"] == "not played"
    assert rows["up"]["counts"]["b"]["adds_per_week"] == 2.5


def test_every_row_shows_its_values_and_the_records_nudge():
    a, _ = two_screens()
    rows = {r["key"]: r for r in built([a])["knobs"]["rows"]}
    assert rows["cap"]["values"] == {"a": "0", "b": "0.5"}
    assert rows["cap"]["nudge"] == "season_weight: 0 to 0.5"
    assert rows["cap"]["label"] == "Rest-of-season weight"
    assert "baseline's is 0 and the nudges add a weight" in md.LEVERS["season_weight"]["words"]
    assert rows["base-exact"]["both"] == {"season_weight": "0.5"}
    assert rows["base"]["both"] == {}


def test_two_rulesets_sharing_a_lever_agree_or_differ():
    a, b = two_screens()
    shared = {s["key"]: s for s in built([a, b])["knobs"]["shared"]}
    assert shared["up"]["signs"] == "agree" and shared["up"]["cleared"] == "agree"
    assert shared["down"]["signs"] == "differ" and shared["down"]["cleared"] == "split"
    assert shared["cap"]["signs"] == "differ" and shared["cap"]["cleared"] is None
    assert shared["base"]["signs"] == "one or none"
    assert "small" not in shared


def test_the_luck_arithmetic():
    assert md.ONE_SE == pytest.approx(0.3173, abs=1e-4)
    assert md.TWO_SE == pytest.approx(0.0455, abs=1e-4)
    lk = md.luck([3.5, -2.5, 1.5, 0.5, None])
    assert lk["tries"] == 5
    bar = NormalDist().inv_cdf(1 - 0.025 / 5)
    assert lk["bar"] == pytest.approx(bar)
    seen = [b["seen"] for b in lk["bars"]]
    assert seen == [3, 2, 1]
    assert [b["luck"] for b in lk["bars"]] == pytest.approx([5 * md.ONE_SE, 5 * md.TWO_SE, 0.05])
    assert md.luck([])["bar"] is None and len(md.luck([])["bars"]) == 2


def test_did_nothing_rows_are_not_tries():
    a, _ = two_screens()
    rs = built([a])["rulesets"][0]
    assert rs["checks"]["luck"]["tries"] == 5


def test_the_watch_flags_trip():
    a, _ = two_screens()
    rs = built([a])["rulesets"][0]
    assert flag(rs, "One season")["level"] == "watch"
    assert flag(rs, "One seed")["level"] == "watch"
    assert flag(rs, "Shared baseline")["level"] == "watch"
    assert flag(rs, "Tiers")["level"] == "ok"  # one row played on the exact tier
    assert flag(rs, "Strict bar")["level"] == "watch"  # 2.4 SE is short of the bar for 5
    assert flag(rs, "Direction")["level"] == "watch"  # 2 better, 1 worse of 3
    assert flag(rs, "Size of what cleared")["level"] == "ok"  # 1 of 3 within two SE
    fast = screen("s-fast", ONE_WIN, [row("base", "pool", 0.0), row("x", "pool", 0.9, 0.5)])
    rs = built([fast])["rulesets"][0]
    assert flag(rs, "Fast tier only")["level"] == "watch"
    assert flag(rs, "Size of what cleared")["level"] == "watch"


def test_the_ok_sides_of_seasons_seeds_and_the_strict_bar():
    rows = [row("base", "pool", 0.0), row("big", "pool", 5.0, 0.5)]
    one = screen("s-1", ONE_WIN, rows, seasons=(2022,), seed=1)
    two = screen(
        "s-2",
        ONE_WIN,
        [row("base", "pool", 0.0), row("big", "pool", 5.0, 0.5)],
        seasons=(2023,),
        seed=2,
        started="2026-01-05T10:00:00+00:00",
        finished="2026-01-05T11:00:00+00:00",
    )
    rs = built([one, two])["rulesets"][0]
    assert flag(rs, "Seasons")["level"] == "ok"
    assert flag(rs, "Seeds")["level"] == "ok"
    assert flag(rs, "Strict bar")["level"] == "ok"


def test_the_problem_flags_trip():
    a, _ = two_screens()
    bad = screen("s-bad", ONE_WIN, a["record"]["rows"], breaches={"up": 1})
    rs = built([bad])["rulesets"][0]
    assert flag(rs, "Audit")["level"] == "problem"
    assert rs["checks"]["level"] == "problem"
    # the confirmation season played by a screen
    seen = screen("s-seen", ONE_WIN, [row("base", "pool", 0.0, season="2024")], seasons=(2024,))
    m = built([seen], [tune("t-1", ONE_WIN)])
    rs = m["rulesets"][0]
    assert flag(rs, "Confirmation season")["level"] == "problem"
    # the hold-out in a run's seasons
    held = screen("s-held", ONE_WIN, [row("base", "pool", 0.0, season="2025")], seasons=(2025,))
    rs = built([held])["rulesets"][0]
    assert flag(rs, "Hold-out")["level"] == "problem"
    # a record that names another hold-out
    other = screen("s-other", ONE_WIN, [row("base", "pool", 0.0)], hold_out=2024)
    assert flag(built([other])["rulesets"][0], "Hold-out")["level"] == "watch"
    a, _ = two_screens()
    rs = built([a])["rulesets"][0]
    assert flag(rs, "Hold-out")["level"] == "ok"
    assert flag(rs, "Audit")["level"] == "ok"


def test_a_flag_about_one_rulesets_world_comes_from_the_notes():
    a, b = two_screens()
    notes = md.notes_of(
        {
            "rulesets": {
                md.ruleset_key(ONE_WIN): {
                    "flags": [{"level": "watch", "title": "Quiet rivals", "text": "made up"}]
                }
            }
        }
    )
    m = built([a, b], notes=notes)
    one = next(x for x in m["rulesets"] if x["key"] == md.ruleset_key(ONE_WIN))
    each = next(x for x in m["rulesets"] if x["key"] == md.ruleset_key(EACH))
    assert flag(one, "Quiet rivals")["from"] == "notes"
    assert all(f["title"] != "Quiet rivals" for f in each["checks"]["flags"])


def test_a_tune_with_a_confirmation():
    a, _ = two_screens()
    m = built([a], [tune("t-1", ONE_WIN, taken=0.6, kept=0.3)])
    t = m["tunes"][0]
    assert t["gains"]["search"]["mean"] == pytest.approx(0.6)
    assert t["gains"]["search"]["se"] is None
    assert t["gains"]["confirm"]["run"]["mean"] == pytest.approx(0.3)
    assert t["gains"]["confirm"]["static"]["mean"] == pytest.approx(0.15)
    assert t["gains"]["kept"]["run"] == pytest.approx(0.5)
    assert t["steps"][0]["values"][0]["taken"] is True
    assert t["steps"][0]["values"][1]["standing"] == "below"
    assert t["final"]["set"] == {"pool": "20"}
    assert t["confirmation"]["season_words"] == "2023-24"
    stages = m["rulesets"][0]["stages"]
    assert [s["tag"] for s in stages] == ["played", "unconfirmed", "searched", "played"]
    assert stages[3]["value"]["mean"] == pytest.approx(0.3)
    run = next(r for r in m["runs"] if r["kind"] == "tune")
    assert run["hours"] == pytest.approx(1.0)
    ledger = {s["season"]: s for s in m["seasons"]}
    assert ledger[2024]["role"] == "confirm" and ledger[2024]["confirmations"] == 1
    assert ledger[2023]["searches"] == 1 and ledger[2023]["screens"] == 1


def test_no_tune_leaves_the_last_two_stages_not_run():
    a, _ = two_screens()
    stages = built([a])["rulesets"][0]["stages"]
    assert [s["tag"] for s in stages[2:]] == ["not run", "not run"]
    assert all(s["value"] is None for s in stages[2:])


def test_the_seasons_ledger_takes_the_notes_roles_and_says_when_there_are_none():
    a, _ = two_screens()
    m = built([a])
    ledger = {s["season"]: s for s in m["seasons"]}
    assert ledger[2025]["role"] == "holdout" and ledger[2025]["from"] == "code"
    assert ledger[2023]["role"] == "search"
    assert any("withheld season" in x for x in m["generated"]["lacks"])
    notes = md.notes_of({"seasons": [{"id": "2023-24", "role": "confirm", "note": "kept"}]})
    m = built([a], notes=notes)
    ledger = {s["season"]: s for s in m["seasons"]}
    assert ledger[2024]["role"] == "confirm" and ledger[2024]["from"] == "notes"
    assert flag(m["rulesets"][0], "Confirmation season")["level"] == "ok"
    assert not any("withheld season" in x for x in m["generated"]["lacks"])


def test_runs_have_their_pieces_on_one_time_line():
    a, b = two_screens()
    runs = built([a, b])["runs"]
    assert [r["name"] for r in runs] == ["s-each", "s-one"]
    assert runs[0]["pieces"][0]["at"][0] == 0.0
    assert runs[1]["pieces"][0]["at"][1] == 1.0
    assert runs[1]["hours"] == pytest.approx(2.0)
    assert runs[1]["pairs_done"] == 6 and runs[1]["not_played"] == 1
    assert runs[1]["code_sha"] == "abcdef0"


def test_a_written_replay_is_a_run():
    rec = pair(row("x", "pool", 0.5))
    rec |= {
        "name": "r-1",
        "seasons": [2023],
        "paths": 8,
        "seed": 3,
        "design": "paired",
        "code_sha": "1234567890",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:30:00+00:00",
        "league": {"rules": ONE_WIN, "shapes": [SHAPE]},
        "cells": {"2023": {"prior": {"served": True}}},
    }
    m = built(replays=[{"file": "r-1.json", "record": rec}])
    run = m["runs"][0]
    assert run["kind"] == "replay" and run["hours"] == pytest.approx(0.5)
    assert m["rulesets"][0]["stages"][0]["tag"] == "not recorded"


# --------------------------------------------------------------------------- lab 2
#: A string drawn from a record, as Python's repr would write a list or a mapping of them.
REPR = re.compile(r"\[['\"]|\{['\"]|['\"]\]|['\"]: ")


def strings(x, where=""):
    """Every string in the model, with where it is."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield from strings(v, f"{where}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from strings(v, f"{where}[{i}]")
    elif isinstance(x, str):
        yield where, x


def old_replay(**more) -> dict:
    """A written replay shaped as the one on the box (made-up values): one ``season``, its
    ``forecasters`` a mapping, ``results`` by forecaster and seat, no ``league``."""
    one = {o: {"mean": 1.0, "se": 0.1, "n": 4} for o in md.OUTCOMES}
    rec = {
        "kind": "replay",
        "name": "r-old",
        "season": 2023,
        "forecasters": {"prior": {"name": "prior", "source": "made up"}},
        "results": {"prior": {"R": one, "S": one}},
        "specs": {"R": {"name": "R", "tier": "surrogate"}, "S": {"name": "S", "tier": "exact"}},
        "paths": 4,
        "seed": 7,
        "code_sha": "fedcba9876543210",
        "started_at": "2026-01-01T09:00:00+00:00",
        "finished_at": "2026-01-01T09:30:00+00:00",
        "audit": {"breaches": [], "paths_voided": 0},
        "counts": {},
    }
    return {"file": "r-old.json", "record": rec | more}


def test_the_roster_chip_counts_the_slots_and_nothing_shows_a_repr():
    a, b = two_screens()
    m = built([a, b], replays=[old_replay()])
    rs = next(x for x in m["rulesets"] if x["key"] == md.ruleset_key(ONE_WIN))
    assert "13 roster spots" in rs["chips"]
    bad = [(w, v) for w, v in strings(m) if REPR.search(v)]
    assert bad == []
    # not vacuous: the word helpers are what keeps a list out
    assert md.chips({}, {}, [SHAPE])[1] == "13 roster spots"
    assert REPR.search(str(SLOTS))


def test_a_replay_written_with_one_season_is_read_and_counted():
    m = built(replays=[old_replay()])
    run = m["runs"][0]
    assert run["seasons"] == [2023] and run["season_words"] == ["2022-23"]
    assert run["forecasters"] == "prior"
    assert run["tiers"] == ["exact", "surrogate"]
    ledger = {s["season"]: s for s in m["seasons"]}
    assert ledger[2023]["replays"] == 1 and ledger[2023]["role"] == "replay"
    # the newer form is still read
    new = old_replay(name="r-new", seasons=[2022, 2023], cells={"2022": {"espn": {}}})
    del new["record"]["season"], new["record"]["forecasters"]
    m = built(replays=[old_replay(), new])
    ledger = {s["season"]: s for s in m["seasons"]}
    assert ledger[2023]["replays"] == 2 and ledger[2022]["replays"] == 1
    assert next(r for r in m["runs"] if r["name"] == "r-new")["forecasters"] == "espn"


def test_a_ruleset_with_no_screen_and_no_tune_is_not_listed():
    a, _ = two_screens()
    m = built([a], replays=[old_replay()])
    listed = [x for x in m["rulesets"] if x["listed"]]
    assert [x["key"] for x in listed] == [md.ruleset_key(ONE_WIN)]
    assert listed[0]["tone"] == 0
    other = next(x for x in m["rulesets"] if not x["listed"])
    assert other["key"] == md.ruleset_key({}) and other["runs"] == ["r-old"]
    assert m["rulesets"][-1] is other  # the listed come first
    lines = sv.check_lines(m | {"generated": m["generated"] | GENERATED})
    assert lines[1].startswith("rulesets: 2, 1 listed")
    assert "runs only, not listed" in lines[1]
    assert [x.split(":")[0] for x in lines if x.startswith("checks")] == [
        f"checks {md.ruleset_key(ONE_WIN)}"
    ]


GENERATED = {
    "read": {
        "screens": 0,
        "screen_pairs": 0,
        "tunes": 0,
        "tune_pairs": 0,
        "replays": 0,
        "other_runs": {},
        "ledger_lines": 0,
    },
    "refused": [],
    "notes": {"state": "none"},
    "explainer": False,
}


def test_the_confirmation_season_flag_in_its_three_states():
    notes = md.notes_of({"seasons": [{"id": "2023-24", "role": "confirm"}]})
    a, _ = two_screens()  # plays 2022-23
    ok = flag(built([a], notes=notes)["rulesets"][0], "Confirmation season")
    assert ok["level"] == "ok"
    assert ok["text"] == "2023-24 and 2025-26 have not been played by any screen or search."
    # a written replay on it: a watch, named
    rep = old_replay(season=2024, name="r-on-confirm")
    watch = flag(built([a], replays=[rep], notes=notes)["rulesets"][0], "Confirmation season")
    assert watch["level"] == "watch"
    assert watch["text"] == (
        "2023-24 is kept to confirm on: 1 written replay(s) played it (r-on-confirm). "
        "No screen or search has played it."
    )
    # a look on the confirmation ledger: a watch, named; a tune's own confirmation is not one
    looks = [
        {"look": 1, "name": "a-look", "design": "paired", "seasons": [2024]},
        {"look": 2, "name": "t-1", "design": "tune", "seasons": [2024]},
    ]
    watch = flag(built([a], looks=looks, notes=notes)["rulesets"][0], "Confirmation season")
    assert watch["level"] == "watch"
    assert "1 look(s) on the confirmation ledger name it (a-look)" in watch["text"]
    assert "t-1" not in watch["text"]
    only_tune = flag(built([a], looks=looks[1:], notes=notes)["rulesets"][0], "Confirmation season")
    assert only_tune["level"] == "ok"
    # a screen on it is a problem, and wins over the watch
    seen = screen("s-seen", ONE_WIN, [row("base", "pool", 0.0, season="2024")], seasons=(2024,))
    problem = flag(
        built([a, seen], replays=[rep], looks=looks, notes=notes)["rulesets"][0],
        "Confirmation season",
    )
    assert problem["level"] == "problem"
    assert "a screen or a search has played it" in problem["text"]


def test_a_second_confirmation_by_one_ruleset_on_one_season_is_a_watch():
    notes = md.notes_of({"seasons": [{"id": "2023-24", "role": "confirm"}]})
    a, b = two_screens()
    once = built([a], [tune("t-1", ONE_WIN)], notes=notes)
    assert flag(once["rulesets"][0], "Confirmation season")["level"] == "ok"
    twice = built([a], [tune("t-1", ONE_WIN), tune("t-2", ONE_WIN)], notes=notes)
    f = flag(twice["rulesets"][0], "Confirmation season")
    assert f["level"] == "watch"
    assert "this ruleset's tunes confirmed on it 2 times (t-1, t-2)" in f["text"]
    # two rulesets each confirming once on it: ok for both
    each = built([a, b], [tune("t-1", ONE_WIN), tune("t-2", EACH)], notes=notes)
    assert {flag(x, "Confirmation season")["level"] for x in each["rulesets"]} == {"ok"}


def test_the_ledger_counts_looks_a_season():
    m = built(looks=[{"look": 1, "seasons": [2026]}, {"look": 2, "seasons": [2026]}])
    ledger = {s["season"]: s for s in m["seasons"]}
    assert ledger[2026]["looks"] == 2
    assert '<th class="n">Looks</th>' in (STATIC / "app.js").read_text()


def test_times_with_and_without_an_offset_sort_together():
    a = screen(
        "s-naive",
        ONE_WIN,
        [row("base", "pool", 0.0)],
        started="2026-01-02T10:00:00",
        finished="2026-01-02T11:00:00",
    )
    b = screen(
        "s-offset",
        ONE_WIN,
        [row("base", "pool", 0.0)],
        started="2026-01-02T03:30:00-06:00",
        finished="2026-01-02T04:00:00-06:00",
    )
    m = built(
        [a, b],
        replays=[
            old_replay(started_at="2026-01-02T09:00:00", finished_at="2026-01-02T09:30:00+00:00")
        ],
    )
    assert [r["name"] for r in m["runs"]] == ["r-old", "s-offset", "s-naive"]
    for r in m["runs"]:
        for piece in r["pieces"]:
            assert piece["started_at"].endswith("+00:00") or piece["started_at"].endswith("-06:00")
            assert 0.0 <= piece["at"][0] <= piece["at"][1] <= 1.0
    assert m["timeline"] == {
        "start": "2026-01-02T09:00:00+00:00",
        "end": "2026-01-02T11:00:00+00:00",
    }
    assert m["runs"][1]["hours"] == pytest.approx(0.5)


def test_a_model_that_fails_to_build_answers_500_with_its_kind(tmp_path):
    class Broken(sv.Lab):
        def build(self):
            raise RuntimeError("made up")

    with serving(Broken(tmp_path)) as port:
        code, _, body = ask(port, "/api/model")
        assert code == 500
        assert body == b"the model could not be built: RuntimeError\n"
        assert ask(port, "/healthz")[0] == 200  # the server stands


MARK = "<x-mark>"
#: The model's fields drawn from a record (or the notes), marked to find any drawn unescaped.
MARK_STRINGS = {
    "name", "label", "nudge", "why", "note", "cell", "forecaster", "forecasters", "code_sha",
    "title", "what", "text", "size", "say", "result", "issue", "cost", "date", "words",
    "standing", "status", "from",
}  # fmt: skip
MARK_NUMBERS = {
    "paths", "seed", "teams", "breaches", "voided", "pairs_done", "pairs_left", "not_played",
    "screens", "searches", "confirmations", "replays", "looks", "done", "better", "worse",
    "pass", "traces", "path", "differ_days",
}  # fmt: skip
MARK_LISTS = {"chips", "season_words", "seasons", "searched", "tiers"}
MARK_MAPS = {"values", "set", "both"}


def marked(x, key=""):
    if key == "outcomes":  # the model's own table of outcomes, not a record's
        return x
    if isinstance(x, dict):
        if key in MARK_MAPS:
            return {k: MARK + str(v) for k, v in x.items()}
        return {k: marked(v, k) for k, v in x.items()}
    if isinstance(x, list):
        if key in MARK_LISTS:
            return [MARK + v if isinstance(v, str) else marked(v, key) for v in x]
        return [marked(v, key) for v in x]
    if isinstance(x, str) and key in MARK_STRINGS:
        return MARK + x
    if isinstance(x, int) and not isinstance(x, bool) and key in MARK_NUMBERS:
        return MARK + str(x)
    return x


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_draws_every_tab_escapes_every_record_value_and_keeps_its_place(tmp_path):
    a, b = two_screens()
    notes = md.notes_of(GOOD | {"rulesets": {}})
    traces = [tv.summary("t-made", made_trace())]
    m = built([a, b], [tune("t-1", ONE_WIN)], [old_replay()], notes=notes, traces=traces)
    m = marked(json.loads(json.dumps(m, default=str)))
    first, nxt = tmp_path / "m1.json", tmp_path / "m2.json"
    first.write_text(json.dumps(m))
    later = copy.deepcopy(m)
    later["generated"]["at"] = "2026-01-05T00:00:00+00:00"
    nxt.write_text(json.dumps(later))
    harness = Path(__file__).with_name("lab_page_harness.js")
    got = subprocess.run(
        [
            "node",
            str(harness),
            str(STATIC / "app.js"),
            str(first),
            str(nxt),
            str(STATIC / "season.js"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    out = json.loads(got.stdout)
    assert out["problems"] == []
    assert out["marks"] == []
    assert out["renders"] > 7 and out["escaped"] > 7  # the marks were drawn, escaped
    r = out["refresh"]
    assert r["same_build_writes"] == 0
    assert r["new_build_writes"] == 1
    assert r["kept"]["hash"] == "#knobs" and r["kept"]["sort"] == "strength"
    assert r["kept"]["unit"] == "se" and r["best_first_on"] is True
    assert r["failed_writes"] == 0
    assert (
        "The model could not be built (the model could not be built: RuntimeError)"
        in (r["failed_header"])
    )


# --------------------------------------------------------------------------- the notes
GOOD = {
    "state": {"running": None, "text": "made-up state"},
    "queue": [{"title": "a", "what": "b", "state": "word", "size": "c", "say": "d"}],
    "assessments": [{"date": "2026-01-01", "level": "watch", "text": "t", "run": "s-one"}],
    "looks": [{"name": "n", "date": "2026-01-01", "what": "w", "result": "r", "issue": "#1"}],
    "openings": [{"title": "t", "why": "w", "state": "idea", "cost": "c"}],
    "proposals": [],
    "seasons": [{"id": "2022-23", "role": "search"}],
    "rulesets": {"rs-x": {"name": "N", "order": 1, "flags": []}},
}


def test_a_good_notes_file():
    n = md.notes_of(GOOD)
    assert n["seasons"][0]["season"] == 2023
    assert n["state"]["running"] is None
    assert n["rulesets"]["rs-x"]["name"] == "N"
    assert md.notes_of({})["queue"] == []


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"extra": []}, "'extra' is not a section"),
        ({"queue": {}}, "queue: a list"),
        ({"queue": [{"title": "a", "what": "b"}]}, "queue[0]: 'state' is missing"),
        ({"queue": [{"title": "a", "what": "b", "state": "soon"}]}, "queue[0].state: 'soon'"),
        ({"queue": [{"title": "a", "what": "b", "state": "word", "x": "y"}]}, "'x' is not a field"),
        ({"assessments": [{"date": "1 Jan", "level": "ok", "text": "t"}]}, "is not a date"),
        ({"assessments": [{"date": "2026-01-01", "level": "fine", "text": "t"}]}, "level"),
        ({"seasons": [{"id": "2022-24", "role": "search"}]}, "is not a season"),
        ({"seasons": [{"id": "2022-23", "role": "keep"}]}, "role: 'keep'"),
        ({"state": {"text": ""}}, "state.text: a non-empty text"),
        ({"rulesets": {"rs-x": {"order": "first"}}}, "rulesets.rs-x.order: a whole number"),
        ({"rulesets": {"rs-x": {"flags": [{"level": "bad", "title": "t", "text": "x"}]}}}, "level"),
    ],
)
def test_a_malformed_notes_file_is_refused_by_name(change, words):
    with pytest.raises(md.NotesError, match=re.escape(words)):
        md.notes_of(GOOD | change)


def test_a_notes_file_that_is_not_json_is_refused(tmp_path):
    p = tmp_path / "notes.json"
    p.write_text("{not json")
    with pytest.raises(md.NotesError, match="is not JSON"):
        rd.read_notes(p)
    with pytest.raises(md.NotesError, match="notes:"):
        rd.read_notes(tmp_path / "missing.json")
    p.write_text(json.dumps(GOOD))
    assert rd.read_notes(p)["queue"][0]["title"] == "a"
    assert rd.read_notes(None) is None


# --------------------------------------------------------------------------- the records
def write_records(data: Path) -> None:
    a, b = two_screens()
    for s in (a, b):
        d = data / "sim" / "screens" / s["folder"]
        d.mkdir(parents=True)
        (d / "screen.json").write_text(json.dumps(s["record"]))
        for name, p in s["pairs"].items():
            (d / name).write_text(json.dumps(p))
    t = tune("t-1", ONE_WIN)
    d = data / "sim" / "tunes" / "t-1"
    d.mkdir(parents=True)
    (d / "tune.json").write_text(json.dumps(t["record"]))
    runs = data / "sim" / "runs"
    runs.mkdir(parents=True)
    (runs / "v.json").write_text(json.dumps({"kind": "validate"}))
    (runs / "broken.json").write_text("{")


def test_the_records_are_read_and_a_broken_one_refused(tmp_path):
    write_records(tmp_path)
    got = rd.read_all(tmp_path)
    assert got["read"]["screens"] == 2 and got["read"]["tunes"] == 1
    assert got["read"]["other_runs"] == {"validate": 1}
    assert [r["path"].endswith("broken.json") for r in got["refused"]] == [True]
    lab = sv.Lab(tmp_path)
    m = lab.model()
    assert len(m["rulesets"]) == 2 and len(m["tunes"]) == 1
    assert m["generated"]["notes"]["state"] == "none"
    assert lab.model() is m  # kept while nothing changed
    (tmp_path / "sim" / "runs" / "broken.json").write_text("{}")
    assert lab.model() is not m


def test_head_sha_is_read_without_a_process(tmp_path):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/x\n")
    (git / "refs" / "heads" / "x").write_text("a" * 40 + "\n")
    assert rd.head_sha(tmp_path) == "a" * 40
    (git / "refs" / "heads" / "x").unlink()
    (git / "packed-refs").write_text("# packed\n" + "b" * 40 + " refs/heads/x\n")
    assert rd.head_sha(tmp_path) == "b" * 40
    assert rd.head_sha(tmp_path / "nowhere") is None


# --------------------------------------------------------------------------- the server
@contextlib.contextmanager
def serving(lab: sv.Lab):
    srv = sv.server(lab, "127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=5)


def ask(port: int, path: str, method: str = "GET") -> tuple[int, dict, bytes]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request(method, path)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def test_each_route_answers(tmp_path):
    write_records(tmp_path)
    ex = tmp_path / "explainer.html"
    ex.write_text("<p>made-up explainer</p>")
    lab = sv.Lab(tmp_path, explainer=ex)
    with serving(lab) as port:
        code, head, body = ask(port, "/")
        assert code == 200 and b"Season Sim Lab" in body
        assert head["X-Content-Type-Options"] == "nosniff"
        for f in ("app.css", "app.js"):
            code, _, body = ask(port, f"/static/{f}")
            assert code == 200 and body
        code, head, body = ask(port, "/api/model")
        assert code == 200 and head["Content-Type"].startswith("application/json")
        assert json.loads(body) == json.loads(json.dumps(lab.model(), default=str))
        code, _, body = ask(port, "/explainer")
        assert code == 200 and b"made-up explainer" in body and body.startswith(b"<!doctype html>")
        assert ask(port, "/healthz")[:3:2] == (200, b"ok\n")
        assert ask(port, "/nowhere")[0] == 404


def test_only_get_is_served(tmp_path):
    with serving(sv.Lab(tmp_path)) as port:
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            code, head, _ = ask(port, "/api/model", method)
            assert code == 405 and head["Allow"] == "GET"


def test_a_path_outside_static_is_refused(tmp_path):
    with serving(sv.Lab(tmp_path)) as port:
        for path in (
            "/static/../model.py",
            "/static/%2e%2e/model.py",
            "/static/..%2fserver.py",
            "/static/",
            "/static/../../__init__.py",
            "/static/index.html%00.js",
        ):
            assert ask(port, path)[0] == 404, path
    assert sv.static_file("/static/app.js") == sv.STATIC / "app.js"
    assert sv.static_file("/static/../model.py") is None


def test_no_explainer_file_says_so(tmp_path):
    with serving(sv.Lab(tmp_path)) as port:
        code, _, body = ask(port, "/explainer")
    assert code == 200 and b"No explainer file given" in body


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "*", "[::]", " 0.0.0.0 "])
def test_a_wildcard_host_is_refused(host):
    assert sv.host_refused(host)
    with pytest.raises(ValueError, match="every interface"):
        sv.server(sv.Lab(Path(".")), host, 0)


def test_one_address_is_allowed():
    assert sv.host_refused("127.0.0.1") is None
    assert sv.host_refused("::1") is None
    assert sv.host_refused("100.64.0.1") is None
    assert sv.host_refused("localhost") is None


#: What the lab never imports: a process, a request out, a second machine.
LAB_NEVER = {"subprocess", "multiprocessing", "requests", "httpx", "urllib.request", "http.client",
             "ssl", "smtplib", "ftplib", "os", "shutil", "tempfile", "sqlite3", "pickle"}  # fmt: skip
#: What the lab never calls: a write to a file or a change to a folder.
LAB_NEVER_CALLS = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "rename",
                   "symlink_to", "chmod", "system", "popen", "Popen", "open"}  # fmt: skip


def test_the_lab_writes_nothing_and_starts_nothing():
    import ast

    for f in sorted((sv.STATIC.parent).glob("*.py")):
        tree = ast.parse(f.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
        bad = {n for n in names if n in LAB_NEVER or n.split(".")[0] in LAB_NEVER - {"http"}}
        assert not bad, (f.name, bad)
        calls = {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert not calls & LAB_NEVER_CALLS, (f.name, calls & LAB_NEVER_CALLS)


# --------------------------------------------------------------------------- the command
def test_lab_check_prints_a_line_a_section(tmp_path, capsys):
    write_records(tmp_path)
    assert cli.main(["--data", str(tmp_path), "lab", "--check"]) == 0
    out = capsys.readouterr().out.splitlines()
    heads = [line.split(":", 1)[0].split(" ", 1)[0] for line in out]
    assert heads[:3] == ["read", "rulesets", "knobs"]
    assert {"checks", "performance", "runs", "seasons", "notes", "explainer", "not"} <= set(heads)
    assert out[0].startswith("read: 2 screen(s)")


def test_lab_refuses_a_wildcard_host_and_bad_notes(tmp_path, capsys):
    assert cli.main(["--data", str(tmp_path), "lab", "--host", "0.0.0.0"]) == 2
    assert "refused: --host" in capsys.readouterr().out
    bad = tmp_path / "notes.json"
    bad.write_text(json.dumps({"queue": "x"}))
    assert cli.main(["--data", str(tmp_path), "lab", "--notes", str(bad), "--check"]) == 2
    assert "refused: --notes: notes: queue: a list" in capsys.readouterr().out
    assert cli.main(["--data", str(tmp_path), "lab", "--explainer", str(tmp_path / "x")]) == 2
    assert "refused: --explainer" in capsys.readouterr().out


# --------------------------------------------------------------------------- the static files
STATIC = sv.STATIC
BANNED = re.compile(r"optimal|\bpunt|mockup|\bprivate\b|\bpublic\b|league ?id", re.IGNORECASE)


def test_the_static_files_hold_no_banned_word():
    for f in sorted(STATIC.iterdir()):
        text = f.read_text()
        assert not BANNED.search(text), (f.name, BANNED.search(text).group(0))


def test_nothing_is_loaded_from_elsewhere_but_the_two_font_links():
    html = (STATIC / "index.html").read_text()
    links = re.findall(r'(?:src|href)="([^"]+)"', html)
    outside = [u for u in links if not u.startswith("/static/")]
    assert outside == [
        "https://fonts.googleapis.com",
        (
            "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700"
            "&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
        ),
    ]
    js = (STATIC / "app.js").read_text()
    assert not re.search(r"https?://", js)
    assert re.findall(r'fetch\("([^"]+)"', js) == ["/api/model"]
    assert not re.search(r"@import|url\(", (STATIC / "app.css").read_text())


#: The numbers app.js may hold: layout (positions, clamps, a tip's offsets, a table's five
#: columns, a font weight), percent scaling and digits, the refresh's minute, never a run's
#: figure.
JS_NUMBERS = {
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "8",
    "14",
    "50",
    "60",
    "100",
    "500",
    "1000",
    "0.5",
    "0.6",
    "3.8",
}
#: The bare numbers app.css may hold: font weights, layers, line heights, two opacities (a
#: leaving player's chip on the Season tab), a grid's count, row or column (the Season tab's
#: three on a phone), an order, and a flex share.
CSS_NUMBERS = {"0", "0.45", "0.75", "0.95", "1", "1.45", "2", "3", "4", "5", "20", "500", "600", "700"}  # fmt: skip
#: The numbers season.js may hold (PR viewer): a day's three steps (the solve to a quarter, the
#: ride to six tenths), a day's seconds at one speed, the ride's slowing, the speeds, the clamp
#: on a frame's step, the ring's turns, the charts' margins, heights and week spacing, the week
#: strip's resize wait, the jumps shown before the rest fold, an ordinal's 11th to 13th, and
#: the smoothstep's.
SEASON_NUMBERS = {
    "0", "1", "2", "3", "4", "6", "10", "11", "12", "13", "22", "26", "44", "56", "100", "104",
    "168", "200", "260", "560", "1000", "1440", "0.001", "0.01", "0.1", "0.25", "0.5", "0.6",
    "1.5",
}  # fmt: skip


def test_the_static_files_hold_no_figure():
    js = (STATIC / "app.js").read_text()
    js = re.sub(r"^\s*//[^\n]*", "", js, flags=re.MULTILINE)
    js = re.sub(r"\d+px\b", "", js)  # the inline styles' sizes
    js = re.sub(r"[A-Za-z_$][\w$]*", "x", js)  # names, and the t0, c1 inside them
    found = set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", js))
    assert found <= JS_NUMBERS, sorted(found - JS_NUMBERS)
    css = (STATIC / "app.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", "", css)  # colours
    css = re.sub(r"\d*\.?\d+(?:%|(?:px|em|vh|dvh|vw|fr|ms|s)\b)", "", css)  # sizes
    css = re.sub(r"[a-zA-Z_-][\w-]*", "x", css)
    found = set(re.findall(r"(?<![\w.])\d*\.?\d+", css))
    assert found <= CSS_NUMBERS, sorted(found - CSS_NUMBERS)
    html = (STATIC / "index.html").read_text()
    assert not re.search(r"\d+\.\d+", html)


def test_season_js_holds_no_figure_and_asks_only_for_a_trace():
    js = (STATIC / "season.js").read_text()
    assert not re.search(r"https?://", js)
    assert re.findall(r'fetch\("([^"]+)"', js) == ["/api/trace/"]
    assert '<script src="/static/season.js"></script>' in (STATIC / "index.html").read_text()
    js = re.sub(r"^\s*//[^\n]*", "", js, flags=re.MULTILINE)
    js = re.sub(r"\d+px\b", "", js)
    js = re.sub(r"[A-Za-z_$][\w$]*", "x", js)
    found = set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", js))
    assert found <= SEASON_NUMBERS, sorted(found - SEASON_NUMBERS)


def test_the_page_is_titled_and_has_every_tab():
    html = (STATIC / "index.html").read_text()
    assert "<title>Season Sim Lab</title>" in html
    js = (STATIC / "app.js").read_text()
    for tab in ("Overview", "Knobs", "Checks", "Runs", "Season", "Openings", "Explainer"):
        assert f'["{tab}",' in js
    assert 'src="/explainer"' in js


# --------------------------------------------------------------------------- the Season tab (PR viewer)
CATS9 = ["fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"]
NAMES = {101: "Ann Alpha", 102: "Bea Beta", 103: "Cy Gamma", 104: "Di Delta", 105: "Ed Eps", 106: "Flo Zeta"}  # fmt: skip


def mine(k: int) -> dict:
    """The seat's totals on the k-th morning of a week (made up)."""
    return {"pts": 10.0 * k, "reb": 5.0 * k, "ast": 3.0 * k, "stl": 1.0 * k, "blk": 1.0 * k,
            "threes": 2.0 * k, "tov": 2.0 * k, "fgm": 4.0 * k, "fga": 9.0 * k, "ftm": 2.0 * k,
            "fta": 3.0 * k}  # fmt: skip


def theirs(k: int) -> dict:
    return {"pts": 9.0 * k, "reb": 6.0 * k, "ast": 3.0 * k, "stl": 0.0, "blk": 1.0 * k,
            "threes": 1.0 * k, "tov": 1.0 * k, "fgm": 4.0 * k, "fga": 10.0 * k, "ftm": 2.0 * k,
            "fta": 2.0 * k}  # fmt: skip


def decision(**got) -> dict:
    d = {"tier": "surrogate", "solves": 0, "set": [], "held": [], "plan": [], "plan_leads": False,
         "past_guard": False, "union_refused": None, "queued": [], "claims": [], "unqueued": [],
         "landed": [], "cleared": [], "lost": []}  # fmt: skip
    return d | got


def made_trace(*, status: str = "checked", drift=(), season: int = 2023, b_weight: float = 0.25):
    """A trace as the ``trace`` command writes one, by hand: four teams, the seat team 1, three
    weeks (the last a bracket week), two arms whose rosters part on day 3 (B adds 104 for 103)
    and day 10 (A adds 105 for 102); A's season weight 0, B's ``b_weight``."""
    from datetime import date, timedelta

    start = date(2022, 10, 17)  # a Monday
    weeks = [
        {"week": n, "start": (start + timedelta(7 * (n - 1))).isoformat(),
         "end": (start + timedelta(7 * n - 1)).isoformat(), "bracket": n == 3,
         "pairs": [] if n == 3 else ([[1, 2], [3, 4]] if n == 1 else [[1, 3], [2, 4]])}
        for n in (1, 2, 3)
    ]  # fmt: skip
    opp = {1: 2, 2: 3, 3: 4}

    def arm(side: str) -> dict:
        roster = [[101, "PG"], [102, "SG"], [103, "BN"]]
        days, blocks, adds = [], [], 0
        for i in range(21):
            day, wk, k = start + timedelta(i), i // 7 + 1, i % 7
            if k == 0:
                adds = 0
                before = [{"team": t, "rank": t, "wins": (wk - 1) * (t != 2), "losses": (wk - 1) * (t == 2),
                           "ties": 0, "category_wins": 0.0} for t in (1, 2, 3, 4)]  # fmt: skip
                blocks.append({"week": wk, "opponent": opp[wk], "standings_before": before if wk > 1 else
                               [dict(r, wins=0, losses=0) for r in before]})  # fmt: skip
            d = decision()
            if side == "b" and i == 2:
                d = decision(solves=1, set=[[104, 103]], queued=[[104, 103]],
                             unqueued=[[106, 101, "daily cap"]])  # fmt: skip
            if side == "b" and i == 3:
                roster = [[101, "PG"], [102, "SG"], [104, "C"]]
                d, adds = decision(landed=[[104, 103]]), adds + 1
            if side == "a" and i == 5:
                d = decision(solves=1, claims=[{"add": 106, "drop": 101, "clears": "2022-10-24",
                                                "bid": 3, "churn": False}])  # fmt: skip
            if side == "a" and i == 7:
                d = decision(cleared=[{"add": 106, "drop": 101, "won": False, "bid": 3}],
                             lost=[[106, 101]])  # fmt: skip
            if side == "a" and i == 9:
                d = decision(solves=2, set=[[105, 102]], queued=[[105, 102]])
            if side == "a" and i == 10:
                roster = [[101, "PG"], [105, "SG"], [103, "BN"]]
                d, adds = decision(landed=[[105, 102]]), adds + 1
            if i == 12:
                d = decision(solves=1)  # a tier that found nothing
            days.append({
                "date": day.isoformat(), "week": wk, "bracket": wk == 3,
                "knobs": {"season_weight": 0.0 if side == "a" else b_weight,
                          "season_weight_later": 0.0 if side == "a" else b_weight,
                          "later_share": 1.0, "playoff_weight": 1.0, "stake": 0.0,
                          "stake_level": 0.1 * wk, "reads_stake": False, "adds_week": adds,
                          "adds_week_cap": 4, "adds_today": 1 if d["queued"] else 0,
                          "adds_today_cap": 2},
                "decision": d, "roster": [list(r) for r in roster],
                "matchup": {"opponent": opp[wk], "me": mine(k), "them": theirs(k)},
            })  # fmt: skip
        for b in blocks:
            b["final"] = {"me": mine(7), "them": theirs(7)}
            b["result"] = {"won": 5.0, "lost": 3.0, "tied": 1.0, "outcome": "W", "cats": {}}
        end = {"outcome": {"rank": 1, "made_playoffs": True, "title": side == "b",
                           "record": [2, 0, 0], "category_wins": 10.0, "matchup_wins": 2.0},
               "standings": [], "bracket": {"seeds": {"1": 1, "2": 4},
                                            "rounds": [[[1, 2, 1 if side == "b" else 2]]],
                                            "champion": 1 if side == "b" else 4},
               "counts": {}, "executed": 1, "gone": 0, "forced_drops": 0, "breaches": [],
               "bracket_unread": None}  # fmt: skip
        return {"days": days, "weeks": blocks, "end": end}

    arms = {s: arm(s) for s in "ab"}
    key = lambda d: (d["decision"]["set"], d["decision"]["queued"],
                     [(c["add"], c["drop"]) for c in d["decision"]["claims"]])  # fmt: skip
    differ = sorted(
        a["date"]
        for a, b in zip(arms["a"]["days"], arms["b"]["days"], strict=True)
        if key(a) != key(b)
    )
    knobs = {"season_weight": 0.0, "daily_cap": 2, "playoff_weight": 1.0}
    return {
        "kind": "trace", "trace_version": 1, "name": "t-made", "code_sha": "c" * 40,
        "finished_at": "2026-01-03T10:00:00+00:00", "hash_seed": "0",
        "source": {"form": "screen", "name": "s-made", "row": "season_weight-quarter",
                   "pair_name": "s-made-season_weight-quarter"},
        "check": {"status": status, "drift": list(drift), "record_hash_seed": "0"},
        "season": season, "forecaster": "prior", "seed": 1, "path": 0,
        "league": {"rules": ONE_WIN, "label": "made-up rules", "shape": 0, "turn": 0,
                   "shape_label": "4 teams, 3 slots"},
        "pair": {"lever": "season_weight", "nudge": "to a quarter: 0 to 0.25",
                 "values": {"a": 0.0, "b": b_weight}, "arms": {"a": "base", "b": "base:sw"},
                 "specs": {"a": {"name": "base", "tier": "surrogate", "knobs": knobs},
                           "b": {"name": "base:sw", "tier": "surrogate",
                                 "knobs": knobs | {"season_weight": b_weight}}},
                 "knobs": {"a": knobs, "b": knobs | {"season_weight": b_weight}}},
        "outcomes": {"a": {"rank": 1}, "b": {"rank": 1}, "difference": {"rank": 0}},
        "seat": 1, "teams": [1, 2, 3, 4], "cats": CATS9, "scoring": "categories",
        "same_day": False, "weeks": weeks,
        "players": {str(k): {"name": v, "team": "XYZ", "positions": ["G"]} for k, v in NAMES.items()},
        "arms": arms,
        "differ": {"days": differ, "first": differ[0] if differ else None, "count": len(differ)},
    }  # fmt: skip


def test_the_check_words_are_the_trace_command_s():
    assert (tv.CHECKED, tv.WORLD_ONLY, tv.DRIFTED, tv.UNCHECKED) == (
        cli.CHECKED,
        cli.WORLD_ONLY,
        cli.DRIFTED,
        cli.UNCHECKED,
    )


def test_a_category_s_share_its_lead_and_the_score_so_far():
    got = tv.matchup(CATS9, mine(1), theirs(1))
    share = dict(zip(CATS9, got["share"], strict=True))
    lead = dict(zip(CATS9, got["lead"], strict=True))
    assert share["pts"] == pytest.approx(10 / 19, abs=1e-3) and lead["pts"] == 1.0
    assert share["reb"] == pytest.approx(5 / 11, abs=1e-3) and lead["reb"] == 0.0
    assert share["ast"] == 0.5 and lead["ast"] == 0.5
    # the lower turnovers win: the seat's share is the opponent's part
    assert share["tov"] == pytest.approx(1 / 3, abs=1e-3) and lead["tov"] == 0.0
    # a percentage from makes and attempts, to three decimals, as a week is scored
    assert lead["fg_pct"] == 1.0 and lead["ft_pct"] == 0.0
    assert share["fg_pct"] == pytest.approx(0.444 / (0.444 + 0.4), abs=1e-3)
    assert got["score"] == [4, 3, 2]
    # before a game: every category level, no share leaning
    none = tv.matchup(CATS9, mine(0), theirs(0))
    assert none["score"] == [0, 0, 9] and set(none["share"]) == {0.5}
    assert tv.matchup(CATS9, mine(1), None) is None
    assert tv.lower_wins("tov") and not tv.lower_wins("pts")


def test_the_view_works_out_what_the_tab_draws():
    v = tv.view("t-made", made_trace())
    json.dumps(v, allow_nan=False)
    assert len(v["days"]) == 21 and [w["label"] for w in v["weeks"]] == ["W1", "W2", "PO1"]
    d1 = v["days"][1]
    assert (d1["dow"], d1["label"]) == ("TUE", "W1")
    # the morning's matchup, and the evening's: the next morning's totals
    assert d1["sides"]["a"]["am"]["score"] == [4, 3, 2]
    assert d1["sides"]["a"]["pm"] == tv.matchup(CATS9, mine(2), theirs(2))
    # the week's last day ends on the week's final
    assert v["days"][6]["sides"]["a"]["pm"] == tv.matchup(CATS9, mine(7), theirs(7))
    # the arrivals: B's 104 takes 103's spot on day 3, lit that day, and only B holds him
    d3 = v["days"][3]["sides"]["b"]
    assert d3["rides"] == [{"in": 104, "out": 103, "spot": 2}]
    assert d3["roster"][2] == [104, "C", True, True]
    assert v["days"][4]["sides"]["b"]["roster"][2] == [104, "C", True, False]
    assert v["days"][3]["sides"]["a"]["roster"][2] == [103, "BN", True, False]
    assert v["days"][2]["sides"]["a"]["roster"][2] == [103, "BN", False, False]
    # A's 105 takes 102's spot on day 10; the two arms now differ in two spots
    d10 = v["days"][10]["sides"]
    assert d10["a"]["rides"] == [{"in": 105, "out": 102, "spot": 1}]
    assert [r[2] for r in d10["a"]["roster"]] == [False, True, True]
    # whether the arms did the same today
    assert v["days"][0]["compare"] == "no move in either arm today"
    assert (
        v["days"][2]["compare"] == "the arms decide differently today" and not v["days"][2]["same"]
    )
    # the differ days as jumps, the first marked by the trace
    assert [j["day"] for j in v["jumps"]] == [2, 5, 9] and v["differ"]["first"] == 2
    assert v["jumps"][0]["label"] == "W1 WED"
    # the race: no place before the first week, the bracket in words
    assert v["weeks"][0]["a"]["before"] is None
    assert v["weeks"][1]["a"]["before"] == {"rank": 1, "record": [1, 0, 0]}
    assert v["end"]["b"]["bracket"] == [
        "seeded 1",
        "round 1: won against team 4",
        "champion: the seat",
    ]
    assert v["end"]["a"]["bracket"][-1] == "champion: team 4"
    assert v["playoff_teams"] == 2
    assert v["players"]["104"]["short"] == "D. Delta"


def test_the_bracket_in_words_reads_its_rounds_as_seeds():
    # six teams, two byes, as league.Playoffs keeps it: rounds of (higher seed, lower seed,
    # winner's seed), seeds to teams, the champion a team
    end = {
        "bracket": {
            "seeds": {"1": 7, "2": 1, "3": 9, "4": 3, "5": 5, "6": 2},
            "rounds": [[[3, 6, 6], [4, 5, 4]], [[1, 6, 1], [2, 4, 4]], [[1, 4, 1]]],
            "champion": 7,
        }
    }
    assert tv._bracket_words(end, 1) == [
        "seeded 2",
        "round 1: a bye",
        "round 2: lost against team 3",
        "champion: team 7",
    ]
    assert tv._bracket_words(end, 2) == [
        "seeded 6",
        "round 1: won against team 9",
        "round 2: lost against team 7",
        "champion: team 7",
    ]
    assert tv._bracket_words(end, 7)[-2:] == ["round 3: won against team 3", "champion: the seat"]
    assert tv._bracket_words(end, 4) == ["missed the playoffs", "champion: team 7"]


def test_the_day_s_line_in_words():
    v = tv.view("t-made", made_trace())
    b2 = v["days"][2]["sides"]["b"]["line"]
    assert b2[0] == "fast tier: 1 solve"
    assert "the set: add Di Delta for Cy Gamma" in b2
    assert "queued: add Di Delta for Cy Gamma" in b2
    assert "not queued: add Flo Zeta for Ann Alpha (daily cap)" in b2
    a5 = v["days"][5]["sides"]["a"]["line"]
    assert "claim: add Flo Zeta for Ann Alpha, $3" in a5
    a7 = v["days"][7]["sides"]["a"]["line"]
    assert "claim lost: Flo Zeta, $3" in a7 and "lost: add Flo Zeta for Ann Alpha" in a7
    # a tier that found nothing says only that
    assert v["days"][12]["sides"]["a"]["line"] == ["fast tier: 1 solve", "found nothing to do"]
    assert v["days"][0]["sides"]["a"]["line"] == ["fast tier: no solve today"]


def test_which_knobs_get_a_chart():
    v = tv.view("t-made", made_trace())
    charts = {c["key"]: c for c in v["charts"]}
    # a chart is for what moves (the lead's decision): the adds move, in both arms
    assert set(charts) == {"adds_week", "adds_today"}
    assert charts["adds_week"]["moves"] and charts["adds_week"]["differs"]
    # a count and its cap on one chart, and the cap never alone; the legend says both
    assert charts["adds_week"]["cap"]["same"] and charts["adds_week"]["cap"]["a"][0] == 4
    assert charts["adds_week"]["lo"] == 0 and charts["adds_week"]["hi"] == 4
    assert charts["adds_week"]["say"]["b"][3] == "1 of 4"
    # constant all season in each arm: no chart, even where the arms differ; one row says
    # both values, the differing ones marked
    flat = {x["key"]: x for x in v["flat"]}
    assert set(flat) == {
        "season_weight", "season_weight_later", "later_share", "playoff_weight", "stake",
    }  # fmt: skip
    assert flat["season_weight"] == {
        "key": "season_weight",
        "label": "Season weight, this week's games",
        "a": "0",
        "b": "0.25",
        "differs": True,
    }
    assert not flat["stake"]["differs"]
    # the stake level moves, but neither arm reads it: a line, no chart; a flag gets none
    assert [x["key"] for x in v["unread"]] == ["stake_level"]
    assert "reads_stake" not in charts and "reads_stake" not in flat
    t = made_trace()
    t["arms"]["b"]["days"][4]["knobs"]["reads_stake"] = True
    got = tv.view("t", t)
    assert "stake_level" in {c["key"] for c in got["charts"]} and got["unread"] == []
    # drawn from the keys: a knob the trace adds later gets a chart with no change here
    t = made_trace()
    for i, d in enumerate(t["arms"]["b"]["days"]):
        d["knobs"]["a_new_schedule"] = 0.1 * (i // 7)
    for d in t["arms"]["a"]["days"]:
        d["knobs"]["a_new_schedule"] = 0.0
    got = {c["key"]: c for c in tv.view("t", t)["charts"]}["a_new_schedule"]
    assert got["label"] == "a_new_schedule" and got["differs"] and got["moves"]


def test_a_small_value_never_reads_as_zero():
    t = made_trace()
    for i, d in enumerate(t["arms"]["b"]["days"]):
        d["knobs"]["season_weight"] = 0.0004 * (i >= 7)
    c = {c["key"]: c for c in tv.view("t", t)["charts"]}["season_weight"]
    assert c["say"]["b"][10] == "0.0004" and c["say"]["a"][10] == "0"
    assert c["ticks"] == [[0.0, "0"], [0.0004, "0.0004"]]
    assert [tv._fmt(x, False) for x in (0.00001234, 0.25, 1.0, 12.345, 100.0, 1500.0)] == [
        "0.0000123", "0.25", "1", "12.3", "100", "1500",
    ]  # fmt: skip


def day(roster, **decided):
    return {"roster": [[p, "BN"] for p in roster], "decision": decision(**decided)}


def test_an_arrival_takes_the_spot_of_the_player_his_move_dropped():
    # two moves a day whose roster order would cross: 105 is listed first but replaced 103
    got = tv.roster_spots(
        [day([101, 102, 103]), day([101, 105, 104], landed=[[104, 102], [105, 103]])]
    )
    assert got[1]["rides"] == [
        {"in": 105, "out": 103, "spot": 2},
        {"in": 104, "out": 102, "spot": 1},
    ]
    assert got[1]["order"] == [101, 104, 105] and got[1]["gone"] == []
    # a claim won pairs the same way; what no move names pairs by order
    got = tv.roster_spots(
        [
            day([101, 102, 103, 106]),
            day(
                [101, 105, 104, 107],
                cleared=[{"add": 104, "drop": 106, "won": True, "bid": 2}],
                landed=[[105, 103]],
            ),
        ]
    )
    rides = {r["in"]: (r["out"], r["spot"]) for r in got[1]["rides"]}
    assert rides == {105: (103, 2), 104: (106, 3), 107: (102, 1)}
    # a claim lost moves nobody
    got = tv.roster_spots(
        [day([101, 102]), day([101, 104], cleared=[{"add": 103, "drop": 102, "won": False}])]
    )
    assert got[1]["rides"] == [{"in": 104, "out": 102, "spot": 1}]


def test_a_move_that_lands_on_the_first_day_rides():
    # a same-day league: day one's roster already holds the add; before it, his drop
    got = tv.roster_spots([day([101, 104, 103], landed=[[104, 102]]), day([101, 104, 103])])
    assert got[0]["rides"] == [{"in": 104, "out": 102, "spot": 1}]
    assert got[0]["order"] == [101, 104, 103] and got[1]["rides"] == []
    t = made_trace()
    d0 = t["arms"]["b"]["days"][0]
    d0["roster"] = [[101, "PG"], [104, "SG"], [103, "BN"]]
    d0["decision"] = decision(landed=[[104, 102]])
    v = tv.view("t", t)
    side = v["days"][0]["sides"]["b"]
    assert side["rides"] == [{"in": 104, "out": 102, "spot": 1}] and side["did"]
    assert side["roster"][1] == [104, "SG", True, True]


def test_the_pair_shows_what_differs_and_folds_the_rest():
    p = tv.view("t-made", made_trace())["pair"]
    assert (p["label"], p["values"]) == ("Rest-of-season weight", {"a": "0", "b": "0.25"})
    assert [(r["key"], r["a"], r["b"]) for r in p["differ"]] == [("season_weight", "0", "0.25")]
    assert {r["key"] for r in p["same"]} == {"daily_cap", "playoff_weight", "tier"}


@pytest.mark.parametrize(
    ("status", "drift", "level"),
    [
        (tv.CHECKED, (), "ok"),
        (tv.WORLD_ONLY, (), "watch"),
        (tv.DRIFTED, ("path 0's seat: the record's is not 3",), "problem"),
        (tv.UNCHECKED, (), "watch"),
    ],
)
def test_a_trace_s_check_is_shown_at_its_level(status, drift, level):
    v = tv.view("t", made_trace(status=status, drift=drift))
    assert v["check"]["level"] == level and v["summary"]["check"]["level"] == level
    assert v["check"]["drift"] == list(drift)
    if status == tv.WORLD_ONLY:
        assert "its record keeps no path's outcome" in v["check"]["words"]


def test_the_ledger_counts_traces_a_season_and_a_confirmation_season_s_trace_is_a_watch():
    notes = md.notes_of({"seasons": [{"id": "2023-24", "role": "confirm"}]})
    a, _ = two_screens()
    t1 = tv.summary("t-on-search", made_trace(season=2023))
    t2 = tv.summary("t-on-confirm", made_trace(season=2024))
    m = built([a], notes=notes, traces=[t1, t2])
    ledger = {s["season"]: s for s in m["seasons"]}
    assert ledger[2023]["traces"] == 1 and ledger[2024]["traces"] == 1
    assert {t["name"] for t in m["traces"]} == {"t-on-search", "t-on-confirm"}
    f = flag(m["rulesets"][0], "Confirmation season")
    assert f["level"] == "watch"
    assert f["text"] == (
        "2023-24 is kept to confirm on: 1 trace(s) played it (t-on-confirm). "
        "No screen or search has played it."
    )
    assert (
        flag(built([a], notes=notes, traces=[t1])["rulesets"][0], "Confirmation season")["level"]
        == "ok"
    )
    held = built([a], traces=[tv.summary("t-held", made_trace(season=2025))])
    f = flag(held["rulesets"][0], "Hold-out")
    assert f["level"] == "problem" and "t-held" in f["text"]
    assert '<th class="n">Traces</th>' in (STATIC / "app.js").read_text()


def write_traces(data: Path) -> Path:
    d = data / "sim" / "traces"
    d.mkdir(parents=True)
    (d / "t-made.json").write_text(json.dumps(made_trace()))
    (d / "not-a-trace.json").write_text(json.dumps({"kind": "replay"}))
    (d / "broken.json").write_text("{")
    return d


def test_the_traces_are_read_and_a_record_that_is_not_one_refused_by_name(tmp_path):
    write_traces(tmp_path)
    got = rd.read_all(tmp_path)
    assert [t["name"] for t in got["traces"]] == ["t-made"] and got["read"]["traces"] == 1
    why = {Path(r["path"]).name: r["why"] for r in got["refused"]}
    assert why["not-a-trace.json"] == "not a trace (its kind is not trace)"
    assert why["broken.json"].startswith("not JSON")
    assert rd.read_trace(tmp_path, "t-made")[0] == 200
    assert rd.read_trace(tmp_path, "nowhere") == (404, "no trace named 'nowhere'")
    code, words = rd.read_trace(tmp_path, "not-a-trace")
    assert code == 422 and words == "not-a-trace: not a trace (its kind is not trace)"
    newer = made_trace() | {"trace_version": 99}
    assert "the lab reads version 1" in rd.not_a_trace(newer)
    lab = sv.Lab(tmp_path)
    assert [t["name"] for t in lab.model()["traces"]] == ["t-made"]


def test_the_trace_routes(tmp_path):
    write_traces(tmp_path)
    lab = sv.Lab(tmp_path)
    with serving(lab) as port:
        code, head, body = ask(port, "/api/traces")
        assert code == 200 and [t["name"] for t in json.loads(body)] == ["t-made"]
        code, head, body = ask(port, "/api/trace/t-made")
        assert code == 200 and head["Content-Type"].startswith("application/json")
        got = json.loads(body)
        assert got == json.loads(json.dumps(tv.view("t-made", made_trace())))
        assert lab.trace("t-made")[1] is lab.trace("t-made")[1]  # kept while the file is
        code, _, body = ask(port, "/api/trace/not-a-trace")
        assert code == 422 and body == b"not-a-trace: not a trace (its kind is not trace)\n"
        for path in (
            "/api/trace/nowhere",
            "/api/trace/t-made.json",
            "/api/trace/..%2fscreens%2fx",
            "/api/trace/../screens/x",
            "/api/trace/%2e%2e",
            "/api/trace/",
            "/api/trace/t-made%00",
        ):
            assert ask(port, path)[0] == 404, path
        assert ask(port, "/api/trace/t-made", "POST")[0] == 405


def view_marked(x, key=""):
    """Every text in a trace's view marked, but the keys the script reads as values."""
    if isinstance(x, dict):
        return {k: view_marked(v, k) for k, v in x.items()}
    if isinstance(x, list):
        return [view_marked(v, key) for v in x]
    if isinstance(x, str) and key not in {"key", "scoring", "name"}:
        return MARK + x
    return x


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_season_tab_plays_a_trace_escapes_it_and_says_when_there_is_none(tmp_path):
    t = made_trace()
    v = view_marked(json.loads(json.dumps(tv.view("t-made", t))))
    m = built(traces=[tv.summary("t-made", t)])
    m = marked(json.loads(json.dumps(m, default=str)))
    m["traces"][0]["name"] = "t-made"  # the name the picker asks the server for
    empty = built()
    files = {}
    for k, x in {
        "model": m,
        "view": v,
        "empty": json.loads(json.dumps(empty, default=str)),
    }.items():
        files[k] = tmp_path / f"{k}.json"
        files[k].write_text(json.dumps(x))
    harness = Path(__file__).with_name("lab_season_harness.js")
    got = subprocess.run(
        ["node", str(harness), str(STATIC / "season.js"), str(STATIC / "app.js"),
         str(files["model"]), str(files["view"]), str(files["empty"])],
        capture_output=True, text=True, timeout=120, check=True,
    )  # fmt: skip
    out = json.loads(got.stdout)
    assert out["problems"] == []
    assert out["marks"] == []
    assert out["escaped"] >= 8  # every day drawn held the marks, escaped
    assert out["start"] == {"loaded": True, "playing": True, "name": "t-made"}  # by itself
    assert out["clock"]["after"] > out["clock"]["before"] and out["clock"]["playing"]
    assert out["jump"] == {"day": v["jumps"][1]["day"], "playing": False}
    assert out["week"] == v["weeks"][1]["first"]
    assert out["speed"] == 10
    assert out["missing"] and "no trace named" in out["missing"]
    assert "No trace on the box yet" in out["empty"]
    assert out["runs_has_trace"] and out["ledger_has_traces"]
