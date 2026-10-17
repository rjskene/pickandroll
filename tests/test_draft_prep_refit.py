"""#77 (scripts/draft_prep/refit.py): a finished real draft goes into its format's archive,
``refit`` rewrites the format's survival table from the drafts of the league's size in both
formats (the other's at half weight), blended toward the ADP formula by ``D/(D+1)``, a league
session reads its own table, then the shared one, then simulates, and a league's attach asks
for the league curve once its format has a table. Synthetic drafts and players only."""

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app, leagues
from pickandroll.api.league_curve import fit_league_curve
from pickandroll.availability import (
    LeagueSurvivalTable,
    availability,
    blend_with_formula,
    fit_survival_table,
    survival_frame,
)

from .test_league_curve import CATS, picks, projections
from .test_leagues import QUICK, write_league
from .test_yahoo_room import build_league

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "draft_day.py"
ROSTER = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN", "IL"]


@pytest.fixture
def runbook(tmp_path, monkeypatch):
    """The script as a module, its root moved to a scratch folder."""
    spec = importlib.util.spec_from_file_location("draft_day_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = tmp_path / "data"
    (data / "fidelity").mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA", data)
    return module


def refit_module(runbook):
    return runbook.PREP["refit"]


def league_folder(runbook, league, scoring="points", teams=12, day="2026-10-17", **extra):
    folder = runbook.DATA / "leagues" / league
    folder.mkdir(parents=True, exist_ok=True)
    settings = {
        "league_id": int(league),
        "scoring": scoring,
        "num_teams": teams,
        "draft": {"time": f"{day}T11:00:00-07:00", "pick_seconds": 60},
        "roster": ROSTER,
        **({"points": {"pts": 1.0, "reb": 1.2, "ast": 1.5}} if scoring == "points" else {}),
        **extra,
    }
    (folder / "settings.json").write_text(json.dumps(settings))
    return folder


def players(n=220, with_adp=190):
    """Yahoo's players list: ``n`` players, the first ``with_adp`` with an ADP."""
    return [
        {
            "id": 7000 + i,
            "fname": f"First{chr(65 + i % 26)}",
            "lname": f"Last{i:03d}",
            "team_abbr": "FA",
            "pos": ["G", "Util"],
            "average-pick": f"{1 + i * 0.65:.1f}" if i < with_adp else "-",
            "o_rank": i + 1,
        }
        for i in range(n)
    ]


def finished_draft(runbook, league, teams=12, rounds=13, seed=0, picks_made=None, day=None):
    """A finished room's folder for ``league``: its ledger (attach, every turn and pick) and the
    league's players file at draft time. The room takes players by ADP plus noise."""
    folder = runbook.DATA / "leagues" / league
    roster = players()
    (folder / "yahoo_players.json").write_text(json.dumps(roster))
    rng = np.random.default_rng(seed)
    adp = np.array(
        [float(p["average-pick"]) if p["average-pick"] != "-" else 200.0 for p in roster]
    )
    order = np.argsort(adp + rng.normal(0, 2 + 0.1 * adp), kind="stable")
    total = teams * rounds
    events = [{"type": "attach", "t": "2026-10-17T17:30:00Z", "session": {"league": league}}]
    for overall in range(1, (picks_made or total) + 1):
        rnd, at = divmod(overall - 1, teams)
        slot = at + 1 if rnd % 2 == 0 else teams - at
        p = roster[int(order[overall - 1])]
        events.append({"type": "turn_start", "overall": overall, "slot": slot, "team": 20 + slot})
        events.append(
            {"type": "room_pick", "overall": overall, "slot": slot, "yid": str(p["id"])}
            | {"name": f"{p['fname']} {p['lname']}"}
        )
    saved = runbook.DATA / "fidelity" / f"{league}_{day or '2026-10-17'}_session_s{seed}"
    saved.mkdir(parents=True)
    (saved / "ledger.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    return saved


def archive_dir(runbook, scoring="points"):
    return runbook.DATA / "leagues" / "_shared" / scoring


# --------------------------------------------------------------------------- the archive
def test_a_finished_draft_goes_into_its_formats_archive(runbook, capsys):
    league_folder(runbook, "111")
    saved = finished_draft(runbook, "111")
    assert refit_module(runbook).archive(runbook, "111", saved) == 1
    shared = archive_dir(runbook)
    picks_csv = pd.read_csv(shared / "picks.csv", dtype={"player_id": str})
    assert list(picks_csv.columns) == refit_module(runbook).PICK_COLUMNS
    assert len(picks_csv) == 156 and picks_csv["overall"].tolist() == list(range(1, 157))
    first, thirteenth = picks_csv.iloc[0], picks_csv.iloc[12]
    assert (first["season"], first["draft_year"], first["draft_date"]) == (
        "2026-27",
        2026,
        "2026-10-17",
    )
    assert (first["round"], first["pick_in_round"], first["slot"], first["team"]) == (
        1,
        1,
        1,
        "team 21",
    )
    assert (thirteenth["round"], thirteenth["slot"], thirteenth["team"]) == (2, 12, "team 32")
    row = next(p for p in players() if str(p["id"]) == first["player_id"])
    assert first["adp"] == pytest.approx(float(row["average-pick"]))
    assert first["rank"] == row["o_rank"]
    adp_csv = pd.read_csv(shared / "adp.csv", dtype={"player_id": str})
    assert len(adp_csv) == 190, "every player with an ADP, drafted or not"
    drafted = adp_csv["overall"].notna()
    assert drafted.sum() == picks_csv["adp"].notna().sum() and (~drafted).sum() > 0
    # The players file at draft time is kept beside the ledger.
    assert (saved / "yahoo_players.json").exists()
    assert (
        "archived 111's draft of 2026-10-17 in _shared/points: 156 picks" in capsys.readouterr().out
    )


def test_archiving_a_draft_again_replaces_it(runbook):
    league_folder(runbook, "111")
    league_folder(runbook, "222", day="2026-10-18")
    module = refit_module(runbook)
    saved = finished_draft(runbook, "111")
    module.archive(runbook, "111", saved)
    assert module.archive(runbook, "111", saved) == 1
    assert len(pd.read_csv(archive_dir(runbook) / "picks.csv")) == 156
    assert (
        module.archive(runbook, "222", finished_draft(runbook, "222", seed=1, day="2026-10-18"))
        == 2
    )
    assert len(pd.read_csv(archive_dir(runbook) / "adp.csv")) == 380


def test_only_a_finished_real_draft_is_archived(runbook):
    module = refit_module(runbook)
    league_folder(runbook, "111")
    with pytest.raises(ValueError, match="holds 155 of 156 picks: not a finished draft"):
        module.archive(runbook, "111", finished_draft(runbook, "111", picks_made=155))
    # A ledger that is another league's.
    league_folder(runbook, "333")
    other = finished_draft(runbook, "111", seed=3)
    with pytest.raises(ValueError, match="is league 111's ledger, not 333's"):
        module.archive(runbook, "333", other)
    # A mock's room has no league folder.
    with pytest.raises(runbook.Stop, match="no data/leagues/999/settings.json"):
        module.archive(runbook, "999", other)
    assert not (archive_dir(runbook) / "picks.csv").exists()


def test_finish_archives_the_draft_it_saved(runbook, monkeypatch, capsys):
    league_folder(runbook, "111")
    saved = finished_draft(runbook, "111")
    (runbook.DATA / "fidelity" / "111.jsonl").write_text((saved / "ledger.jsonl").read_text())
    room = {"session_id": "abc", "mode": "mirror", "picks_applied": 156, "num_teams": 12}
    room |= {"rounds": 13, "complete": True}

    def call(method, url, body=None, timeout=30.0):
        if url.endswith("/rooms/111"):
            return 200, room
        if url.endswith("format=md"):
            return 200, "card\n"
        return 200, {}

    monkeypatch.setattr(runbook, "call", call)
    assert runbook.finish("111") == runbook.OK
    assert len(pd.read_csv(archive_dir(runbook) / "picks.csv")) == 156
    # An incomplete room is saved as ever, and not archived.
    league_folder(runbook, "444")
    short = finished_draft(runbook, "444", picks_made=100)
    (runbook.DATA / "fidelity" / "444.jsonl").write_text((short / "ledger.jsonl").read_text())
    monkeypatch.setattr(
        runbook,
        "call",
        lambda m, u, b=None, timeout=30.0: (200, room) if u.endswith("/rooms/444") else call(m, u),
    )
    assert runbook.finish("444") == runbook.OK
    assert "not archived (" in capsys.readouterr().out
    assert len(pd.read_csv(archive_dir(runbook) / "picks.csv")) == 156


# --------------------------------------------------------------------------- the refit
def three_drafts(runbook, scoring="points"):
    module = refit_module(runbook)
    for i, league in enumerate(("111", "222", "333")):
        league_folder(runbook, league, scoring=scoring, day=f"2026-10-1{7 + i}")
        module.archive(
            runbook, league, finished_draft(runbook, league, seed=i, day=f"2026-10-1{7 + i}")
        )


def test_refit_writes_the_table_from_the_drafts_of_the_leagues_size(runbook, capsys):
    three_drafts(runbook)
    league_folder(runbook, "555", teams=10)
    refit_module(runbook).archive(runbook, "555", finished_draft(runbook, "555", teams=10, seed=9))
    league_folder(runbook, "666")  # the next draft
    report = refit_module(runbook).refit(runbook, "666")
    out = capsys.readouterr().out
    assert (
        "archive _shared/points: 3 drafts of 12 x 13 (111 2026-10-17, 222 2026-10-18, 333 2026-10-19); 1 of another size left out"
        in out
    )
    shared = archive_dir(runbook)
    table = LeagueSurvivalTable.from_frame(pd.read_csv(shared / "survival_by_adp.csv"))
    assert table.picks == 156 and table.max_adp == report["max_adp"]
    assert f"answering ADP 90-{table.max_adp}" in out
    assert "blend: 3 drafts toward the ADP formula" in out
    written = json.loads((shared / "survival_by_adp.json").read_text())
    assert [d["league"] for d in written["drafts"]] == ["111", "222", "333"]
    assert written["min_count"] == 20 and written["counts"]["at_max_adp"] >= 20
    assert written["blend"] == {"drafts": 3, "same_format": 3, "other_format": 0, "weight": 0.5}
    # The core's fit on the archive's ADP list, three parts drafts to one part formula.
    adp = pd.read_csv(shared / "adp.csv")
    adp = adp[adp["league_id"] != 555]
    raw, _ = fit_survival_table(adp["adp"].to_numpy(float), adp["overall"].to_numpy(float), 156)
    expected = blend_with_formula(raw, 3)
    assert table.max_adp == expected.max_adp
    assert table.table.to_numpy() == pytest.approx(expected.table.to_numpy(), abs=1e-4)
    cell = 0.75 * raw.table.loc[100, 110] + 0.25 * availability(pd.Series([100.0]), 110).iloc[0]
    assert table.table.loc[100, 110] == pytest.approx(cell, abs=1e-4)


def test_a_thin_archive_writes_no_table_and_drops_a_stale_one(runbook, capsys):
    three_drafts(runbook)
    league_folder(runbook, "666", refit={"min_count": 10_000})
    shared = archive_dir(runbook)
    refit_module(runbook).refit(runbook, "111")
    assert (shared / "survival_by_adp.csv").exists()
    report = refit_module(runbook).refit(runbook, "666")
    assert report["table"] is None and not (shared / "survival_by_adp.csv").exists()
    assert report["reason"].startswith("3 drafts, ") and report["reason"].endswith(", under 10000")
    assert json.loads((shared / "survival_by_adp.json").read_text())["reason"] == report["reason"]
    assert "survival: no table (archive: 3 drafts, " in capsys.readouterr().out
    # No draft of the league's size is no table either.
    league_folder(runbook, "777", scoring="categories", teams=10)
    report = refit_module(runbook).refit(runbook, "777")
    assert report["drafts"] == [] and report["reason"] == "no drafts of 10 x 13 yet"


def test_one_draft_is_half_the_formula_and_the_formats_pool(runbook, capsys):
    """From the first draft the table is the blend: one draft is half the ADP formula. Another
    format's draft counts half (``D`` 1.5), or as the league sets it; half a draft alone is too
    thin near ADP 90, and the league simulates and says why."""
    module = refit_module(runbook)
    league_folder(runbook, "111")
    module.archive(runbook, "111", finished_draft(runbook, "111"))
    league_folder(runbook, "222", day="2026-10-18")
    report = module.refit(runbook, "222")
    assert report["table"] == "_shared/points/survival_by_adp.csv"
    assert report["blend"] == {"drafts": 1, "same_format": 1, "other_format": 0, "weight": 0.5}
    shared = archive_dir(runbook)
    table = LeagueSurvivalTable.from_frame(pd.read_csv(shared / "survival_by_adp.csv"))
    adp = pd.read_csv(shared / "adp.csv")
    raw, _ = fit_survival_table(adp["adp"].to_numpy(float), adp["overall"].to_numpy(float), 156)
    formula = availability(pd.Series([95.0]), 100).iloc[0]
    assert table.table.loc[95, 100] == pytest.approx(
        0.5 * raw.table.loc[95, 100] + 0.5 * formula, abs=1e-4
    )
    assert leagues.session_defaults(runbook.DATA, "222")["survival"] == "league"
    assert leagues.archive_note(runbook.DATA, "222") is None
    capsys.readouterr()
    # A categories draft joins the points table at half weight.
    league_folder(runbook, "333", scoring="categories", day="2026-10-19")
    module.archive(runbook, "333", finished_draft(runbook, "333", seed=3, day="2026-10-19"))
    report = module.refit(runbook, "222")
    out = capsys.readouterr().out
    assert report["blend"] == {"drafts": 1.5, "same_format": 1, "other_format": 1, "weight": 0.5}
    assert [(d["league"], d["format"], d["weight"]) for d in report["drafts"]] == [
        ("111", "points", 1.0),
        ("333", "categories", 0.5),
    ]
    assert (
        "archive _shared/points: 1 draft of 12 x 13 (111 2026-10-17); categories: 1 draft at x0.5 "
        "(333 2026-10-19)" in out
    )
    assert "blend: 1.5 drafts toward the ADP formula" in out
    module.on_status(runbook, "222")
    assert "blend: 1.5 drafts (1 of the format, 1 of the other at x0.5)" in capsys.readouterr().out
    # The league sets the other format's weight; at zero it is left out.
    league_folder(runbook, "222", day="2026-10-18", refit={"cross_format_weight": 0})
    assert module.refit(runbook, "222")["blend"]["drafts"] == 1
    # A categories league with only the points draft at half weight: too thin near ADP 90.
    league_folder(runbook, "444", scoring="categories", teams=12, day="2026-10-20")
    (archive_dir(runbook, "categories") / "adp.csv").unlink()
    (archive_dir(runbook, "categories") / "picks.csv").unlink()
    report = module.refit(runbook, "444")
    assert report["table"] is None and report["blend"] is None
    assert report["reason"].startswith("0.5 drafts, ") and report["reason"].endswith(", under 20")
    assert leagues.session_defaults(runbook.DATA, "444")["survival"] == "simulate"
    assert leagues.archive_note(runbook.DATA, "444") == f"archive: {report['reason']}"


def test_the_command_archives_then_refits(runbook, monkeypatch, capsys):
    league_folder(runbook, "111")
    saved = finished_draft(runbook, "111")
    monkeypatch.setattr(sys, "argv", ["draft_day.py", "refit", "111", "--add-draft", str(saved)])
    assert runbook.main() == runbook.OK
    out = capsys.readouterr().out
    assert out.index("archived 111's draft") < out.index("archive _shared/points: 1 draft")
    monkeypatch.setattr(sys, "argv", ["draft_day.py", "refit", "111", "--add-draft", "/no/such"])
    assert runbook.main() == runbook.ERROR


# --------------------------------------------------------------------------- the session's path
def write_table(folder: Path, picks: int = 156) -> None:
    adps = np.arange(1, 201, dtype=float)
    overall = np.where(adps <= picks, adps, np.nan)
    table, _ = fit_survival_table(np.tile(adps, 3), np.tile(overall, 3), picks)
    folder.mkdir(parents=True, exist_ok=True)
    survival_frame(table).to_csv(folder / leagues.SURVIVAL, index=False)


def test_the_league_reads_its_own_table_then_the_formats_then_simulates(tmp_path):
    write_league(tmp_path, players=False, roster=ROSTER)
    d = leagues.session_defaults(tmp_path, "555")
    assert d["survival"] == "simulate"
    shared = leagues.shared_dir(tmp_path, "points")
    write_table(shared, picks=130)  # a ten-team format's table does not cover the draft
    assert leagues.session_defaults(tmp_path, "555")["survival"] == "simulate"
    write_table(shared)
    d = leagues.session_defaults(tmp_path, "555")
    assert (d["survival"], d["survival_file"]) == (
        "league",
        "leagues/_shared/points/survival_by_adp.csv",
    )
    write_league(tmp_path, league="556", players=False, roster=ROSTER, scoring="categories")
    assert leagues.session_defaults(tmp_path, "556")["survival"] == "simulate", "another format's"
    write_table(tmp_path / "leagues" / "555")
    d = leagues.session_defaults(tmp_path, "555")
    assert d["survival_file"] == "leagues/555/survival_by_adp.csv", "the league's own table first"


def test_a_league_session_names_the_shared_table_and_its_fit(tmp_path):
    build_league(tmp_path)
    write_league(tmp_path)
    shared = leagues.shared_dir(tmp_path, "points")
    write_table(shared)
    blend = {"drafts": 1.5, "same_format": 1, "other_format": 1, "weight": 0.5}
    report = {
        "drafts": [{"league": "111", "date": "2026-10-17"}],
        "min_count": 20,
        "max_adp": 140,
        "blend": blend,
    }
    (shared / "survival_by_adp.json").write_text(json.dumps(report))
    quick = {k: v for k, v in QUICK.items() if k != "survival"}
    with TestClient(create_app(SessionStore(), data_dir=tmp_path)) as client:
        r = client.post("/sessions", json={**quick, "league": "555"})
        assert r.status_code == 201, r.text
        s = r.json()
    assert s["availability_source"] == "league"
    assert s["survival"]["source"] == "league:leagues/_shared/points/survival_by_adp.csv"
    assert s["survival"]["fit"]["drafts"] == report["drafts"]
    assert s["survival"]["blend"] == blend
    assert s["survival"]["from_adp"] == 90 and s["survival"]["max_adp"] > 90


def test_a_league_without_a_table_simulates_with_the_archive_in_its_note(tmp_path):
    build_league(tmp_path)
    write_league(tmp_path)
    shared = leagues.shared_dir(tmp_path, "points")
    shared.mkdir(parents=True)
    report = {"table": None, "reason": "0.5 drafts, 18.5 players near ADP 90, under 20"}
    (shared / "survival_by_adp.json").write_text(json.dumps(report))
    quick = {k: v for k, v in QUICK.items() if k != "survival"}
    with TestClient(create_app(SessionStore(), data_dir=tmp_path)) as client:
        r = client.post("/sessions", json={**quick, "league": "555", "survival_sims": 10})
        assert r.status_code == 201, r.text
        s = r.json()
    assert s["survival"]["mode"] == "simulate"
    assert s["survival"]["note"] == "archive: 0.5 drafts, 18.5 players near ADP 90, under 20"


# --------------------------------------------------------------------------- the curve
def test_a_leagues_attach_asks_for_the_league_curve_once_its_format_has_a_table(runbook, capsys):
    module = refit_module(runbook)
    league_folder(runbook, "888")
    assert module.session_fields(runbook, "888") == {}, "nothing archived"
    league_folder(runbook, "111", scoring="categories")
    module.archive(runbook, "111", finished_draft(runbook, "111"))
    league_folder(runbook, "999", scoring="categories", day="2026-10-18")
    module.refit(runbook, "999")
    assert (
        "curve: league, from the rosters of 1 draft, blended toward today's simulated run"
        in capsys.readouterr().out
    )
    assert module.session_fields(runbook, "999") == {"curve": "league"}
    assert "curve: league, from the archive's 1 draft, blended toward" in capsys.readouterr().out
    # The points league has only the categories draft at half weight: no table, no curve.
    module.refit(runbook, "888")
    assert "curve: simulated (archive: 0.5 drafts, " in capsys.readouterr().out
    assert module.session_fields(runbook, "888") == {}
    league_folder(runbook, "222", day="2026-10-18")
    module.archive(runbook, "222", finished_draft(runbook, "222", seed=2, day="2026-10-18"))
    module.refit(runbook, "888")
    assert module.session_fields(runbook, "888") == {"curve": "league"}
    assert "from the archive's 1.5 drafts" in capsys.readouterr().out
    # A league with its own table reads its own folder: no shared rosters beside it.
    write_table(runbook.DATA / "leagues" / "999")
    assert module.session_fields(runbook, "999") == {}


def test_the_attach_falls_back_to_the_simulated_curve(runbook, monkeypatch, capsys):
    league_folder(runbook, "999", scoring="categories")
    (runbook.DATA / "bbm_projections_2026-10-17.csv").write_text("")
    monkeypatch.setattr(refit_module(runbook), "session_fields", lambda *a: {"curve": "league"})
    posts = []

    def api(method, path, body=None, timeout=60.0):
        if path == "/rooms" and method == "GET":
            return []
        if path == "/rooms/seen":
            return [{"draft_id": "999", "slot": 4}]
        posts.append(json.loads(json.dumps(body)))
        if len(posts) == 1:
            raise runbook.Stop(runbook.ERROR, "POST /rooms: 400 curve=league: no season to fit")
        return {"mode": "mirror", "session_id": "s1"}

    monkeypatch.setattr(runbook, "api", api)
    assert runbook.attach("999", 30) == runbook.OK
    assert posts[0]["session"]["curve"] == "league" and "curve" not in posts[1]["session"]
    assert (
        "ALERT POST /rooms: 400 curve=league: no season to fit: attaching with the simulated curve"
        in capsys.readouterr().out
    )
    # Any other refusal stops the attach as before.
    posts.clear()

    def refuse(method, path, body=None, timeout=60.0):
        if method == "GET":
            return api(method, path)
        raise runbook.Stop(runbook.ERROR, "POST /rooms: 400 slot is required")

    monkeypatch.setattr(runbook, "api", refuse)
    with pytest.raises(runbook.Stop, match="slot is required"):
        runbook.attach("999", 30)


def test_run_refits_before_the_attach(runbook, monkeypatch, capsys):
    league_folder(runbook, "111")
    order = []
    monkeypatch.setattr(runbook, "status", lambda *a, **k: "predraft")
    for step in ("keep_awake", "servers", "refresh", "monitor", "finish"):
        monkeypatch.setattr(runbook, step, lambda *a, **k: runbook.OK)
    monkeypatch.setattr(
        refit_module(runbook), "refit", lambda rb, league, args=None: order.append("refit")
    )
    monkeypatch.setattr(runbook, "attach", lambda *a: order.append("attach") or runbook.OK)
    monkeypatch.setattr(sys, "argv", ["draft_day.py", "run", "111"])
    assert runbook.main() == runbook.OK
    assert order == ["refit", "attach"]


def test_the_shared_archive_fits_each_leagues_draft_on_its_own(tmp_path):
    """Two leagues' drafts of one season: two drafts of four rosters each, labelled by league."""
    df, z = projections(30, 26)
    names = [f"Player {i}" for i in range(30)]
    archive = pd.concat(
        [
            picks(2026, 4, 3, names[:12]).assign(league_id=111),
            picks(2026, 4, 3, names[12:24]).assign(league_id=222),
            picks(2026, 4, 2, names[24:]).assign(league_id=333),
        ]
    )
    archive.to_csv(tmp_path / "picks.csv", index=False)
    fit = fit_league_curve(
        tmp_path, {2026: (df, z)}.get, CATS, num_teams=4, roster_size=3, season=2026
    )
    assert [(s["year"], s["league"], s["rosters"]) for s in fit.seasons] == [
        (2026, "111", 4),
        (2026, "222", 4),
    ]
    assert fit.skipped == [
        {"year": 2026, "league": "333", "reason": "4 teams x 2 rounds, the session drafts 4 x 3"}
    ]
    assert (
        fit.curve.source == "league rosters 2026 111, 2026 222 (8 rosters, 24 of 24 picks scored)"
    )


def test_the_curve_pools_the_other_formats_rosters_at_their_weight(tmp_path):
    """A categories archive and a points archive: the points league's four rosters count half,
    the fit's ``drafts`` is 1.5, and the curve is the weighted fit over all eight."""
    df, z = projections(30, 26)
    names = [f"Player {i}" for i in range(30)]
    own, other = tmp_path / "categories", tmp_path / "points"
    own.mkdir()
    other.mkdir()
    picks(2026, 4, 3, names[:12]).assign(league_id=111).to_csv(own / "picks.csv", index=False)
    picks(2026, 4, 3, names[12:24]).assign(league_id=222).to_csv(other / "picks.csv", index=False)
    scores = {2026: (df, z)}.get
    fit = fit_league_curve(own, scores, CATS, 4, 3, 2026, others=[(other, 0.5)])
    assert fit.drafts == 1.5 and fit.to_dict()["drafts"] == 1.5
    assert [(s["league"], s.get("format"), s.get("weight")) for s in fit.seasons] == [
        ("111", None, None),
        ("222", "points", 0.5),
    ]
    assert fit.curve.source.startswith("league rosters 2026 111, 2026 222 (points x0.5) (8 rosters")
    alone = fit_league_curve(own, scores, CATS, 4, 3, 2026)
    half = fit_league_curve(other, scores, CATS, 4, 3, 2026)
    # The weighted mean of the two drafts' rosters: two parts own to one part other.
    expected = (2 * alone.curve.mu[CATS[0]] + half.curve.mu[CATS[0]]) / 3
    assert fit.curve.mu[CATS[0]] == pytest.approx(expected)
    assert alone.drafts == 1.0
    # Only the other format's archive: it alone is fitted, at its weight.
    (own / "picks.csv").unlink()
    only = fit_league_curve(own, scores, CATS, 4, 3, 2026, others=[(other, 0.5)])
    assert only.drafts == 0.5 and only.curve.mu[CATS[0]] == pytest.approx(half.curve.mu[CATS[0]])


def test_a_league_tables_session_runs_the_simulation_for_its_curve(tmp_path):
    """Beside the shared table the session runs the simulation for its curve alone: the table
    stays the survival, the run's curve becomes the prior the rosters blend toward (the flat
    fpts curve stands in until it lands), and a rebuild of an older log runs none."""
    build_league(tmp_path)
    write_league(tmp_path)
    shared = leagues.shared_dir(tmp_path, "points")
    write_table(shared)
    blend = {"drafts": 1, "same_format": 1, "other_format": 0, "weight": 0.5}
    (shared / "survival_by_adp.json").write_text(json.dumps({"blend": blend}))
    proj = pd.read_csv(tmp_path / "proj.csv")
    names = (proj["first_name"] + " " + proj["last_name"]).tolist()
    picks(2026, 12, 13, names).assign(league_id=111).to_csv(shared / "picks.csv", index=False)
    quick = {k: v for k, v in QUICK.items() if k != "survival"}
    store = SessionStore()
    with TestClient(create_app(store, data_dir=tmp_path)) as client:
        body = {**quick, "league": "555", "curve": "league", "survival_sims": 10}
        r = client.post("/sessions", json=body)
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["availability_source"] == "league" and s["survival"]["blend"] == blend
        assert s["curve_fit"]["blend"]["prior_status"] == "static"
        assert s["curve_fit"]["blend"]["prior"].startswith("flat default")
        deadline = time.time() + 60
        while s["survival"]["curve_run"]["status"] == "building" and time.time() < deadline:
            time.sleep(0.1)
            s = client.get(f"/sessions/{s['id']}").json()
        assert s["survival"]["curve_run"]["status"] == "ready", s["survival"]["curve_run"]
        assert (s["survival"]["status"], s["availability_source"]) == ("ready", "league")
        assert s["curve_fit"]["blend"]["prior_status"] == "ready"
        prior = s["curve_fit"]["blend"]["prior"]
        assert prior.startswith("simulated league (10 drafts")
        assert s["curve"]["source"].endswith(f"blend: 1 draft toward {prior}")
        session = store.get(s["id"])
        assert session.state.survival is None, "the run's table is dropped"
        assert session.league_curve[1] == 1
        assert (session.create_params["fit_curve"], session.create_params["curve_run"]) == (
            True,
            True,
        )
        # Without curve=league there is no blend to give a prior: the table's session runs
        # nothing and keeps the simulated curve.
        plain = client.post("/sessions", json={**quick, "league": "555"}).json()
        assert plain["availability_source"] == "league" and "curve_run" not in plain["survival"]
        params = store.get(plain["id"]).create_params
        assert (params["fit_curve"], params["curve_run"]) == (False, False)
    # A rebuild keeps what the session ran on: a record from before #77 beside a table ran no
    # simulation for its curve, a record that says it did runs it again.
    from pickandroll.api import yahoo_room

    old = [{"type": "attach", "session": {**body, "survival": "league", "fit_curve": True}}]
    assert yahoo_room.logged_session(old)["fit_curve"] is False
    new = [{"type": "attach", "session": {**body, "survival": "league", "fit_curve": True}}]
    new[0]["session"]["curve_run"] = True
    rebuilt = yahoo_room.logged_session(new)
    assert rebuilt["fit_curve"] is True and "curve_run" not in rebuilt
    simulated = [{"type": "attach", "session": {**body, "survival": "simulate", "fit_curve": True}}]
    assert yahoo_room.logged_session(simulated)["fit_curve"] is True
