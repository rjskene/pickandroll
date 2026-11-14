"""The two sources' stand-ins (#172, PR D1): ``replay --bbm-as`` and ``--yahoo-as`` name the
forecasters standing in for the two live sources, and an arm's seat believes by its ``system``
knob, which is then read. The systems' tables by hand (a ``yahoo`` or ``blend`` seat reads
them for the players on no roster only: ``test_sim_split.py``), the reads table, the flags'
refusals, the oracle stand-ins' own draws, and a room of a ``bbm``, a ``yahoo`` and a ``blend``
arm."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import forecast as fc
from pickandroll.sim import nopeek, policy, world
from pickandroll.sim import run as rn
from pickandroll.sim.engine import BLEND
from tests.sim.sim_league import KNOBS, arm, make_data_dir
from tests.sim.test_no_peek import SEED, WEIGHTS, recorded
from tests.sim.test_sim_forecast import many_lines, oracle_lines

# --------------------------------------------------------------------------- the tables
FIRST = {
    1: {"pts": 20.0, "reb": 4.0, "fgm": 5.0, "fga": 10.0},
    2: {"pts": 10.0, "reb": 8.0},
    3: {"pts": 30.0},
}
SECOND = {
    2: {"pts": 14.0, "ast": 2.0},
    3: {"pts": 24.0, "reb": 6.0},
    4: {"pts": 9.0, "fgm": 6.0, "fga": 5.0},  # only the second projects 4
}


def test_bbm_is_the_first_sources_forecast_as_it_is():
    got = fc.system_rates("bbm", None, FIRST, SECOND)
    assert got == FIRST and got is not FIRST


def test_yahoos_table_is_the_seconds_line_where_it_projects_and_the_firsts_elsewhere():
    got = fc.system_rates("yahoo", None, FIRST, SECOND)
    assert got[1] == FIRST[1]  # the second has no line for 1
    assert got[2] == SECOND[2] and got[3] == SECOND[3]  # its line whole, not stat by stat
    assert got[4] == {"pts": 9.0, "fgm": 5.0, "fga": 5.0}  # through consistent


def test_blends_table_mixes_stat_by_stat_where_the_second_projects():
    got = fc.system_rates("blend", 0.25, FIRST, SECOND)
    assert got[1] == FIRST[1]
    # 2: a quarter of the second's and three quarters of the first's, a missing stat as 0.
    assert got[2] == pytest.approx({"pts": 0.75 * 10 + 0.25 * 14, "reb": 0.75 * 8, "ast": 0.5})
    assert got[3] == pytest.approx({"pts": 0.75 * 30 + 0.25 * 24, "reb": 0.25 * 6})
    assert got[4] == {"pts": 9.0, "fgm": 5.0, "fga": 5.0}  # the second's alone, consistent
    # No share under system blend is the engine's default.
    assert fc.share_of("blend", None) == BLEND == 0.5
    half = fc.system_rates("blend", None, FIRST, SECOND)
    assert half[2]["pts"] == pytest.approx(0.5 * 10 + 0.5 * 14)
    assert fc.share_of("bbm", 0.5) is None and fc.share_of("yahoo", None) is None


def test_the_belief_labels_name_the_system_and_the_stand_ins():
    assert fc.system_label("bbm", 0.3, "espn", "marcel") == "espn"
    assert fc.system_label("yahoo", None, "espn", "marcel") == "yahoo(marcel else espn)"
    assert fc.system_label("blend", None, "espn", "marcel") == "blend:0.5(marcel with espn)"
    assert fc.system_label("blend", 0.25, "a", "b") == "blend:0.25(b with a)"
    with pytest.raises(ValueError, match="system 'hashtag'"):
        fc.system_label("hashtag", None, "a", "b")


# --------------------------------------------------------------------------- the flags
def test_the_two_flags_name_both_stand_ins_or_none():
    assert ss.sources_of(None, None) is None
    first, second = ss.sources_of("espn", "marcel")
    assert (first.label, second.label) == ("espn", "marcel")
    first, second = ss.sources_of("oracle:0.2", "oracle:0.2")  # two draws of their own
    assert (first.label, second.label) == ("oracle:0.2@bbm", "oracle:0.2@yahoo")
    for bbm, yahoo, why in (
        ("espn", None, "--bbm-as without the other"),
        (None, "espn", "--yahoo-as without the other"),
        ("espn", "espn", "both name espn"),
        ("prior", "gospel", "forecaster 'gospel'"),
        ("prior,espn", "marcel", "forecaster 'prior,espn'"),
    ):
        with pytest.raises(ValueError) as e:
            ss.sources_of(bbm, yahoo)
        assert why in str(e.value)


# --------------------------------------------------------------------------- the oracle stand-ins
def test_two_oracle_stand_ins_draw_apart_from_each_other_and_from_the_runs():
    lines = oracle_lines()
    run = fc.oracle(lines, 0.2, 7, 3)
    bbm = fc.oracle(lines, 0.2, 7, 3, role="bbm")
    yahoo = fc.oracle(lines, 0.2, 7, 3, role="yahoo")
    assert run != bbm and run != yahoo and bbm != yahoo
    assert fc.oracle(lines, 0.2, 7, 3, role="bbm") == bbm  # by seed and path
    assert fc.oracle(lines, 0.2, 7, 4, role="bbm") != bbm
    assert fc.oracle(lines, 0.2, 8, 3, role="bbm") != bbm
    # Each still has the spread it names, on many players; the two are uncorrelated.
    many = many_lines(800)
    truth = fc.realized_rates(many)
    errs = {}
    for role in (None, "bbm", "yahoo"):
        got = fc.oracle(many, 0.2, 5, 0, role=role)
        errs[role] = np.array([math.log(got[k]["pts"] / truth[k]["pts"]) for k in sorted(got)])
        assert errs[role].std(ddof=1) == pytest.approx(0.2, rel=0.08)
    assert abs(np.corrcoef(errs["bbm"], errs["yahoo"])[0, 1]) < 0.1
    assert abs(np.corrcoef(errs[None], errs["bbm"])[0, 1]) < 0.1
    # The minutes shape keeps its split on a role's stream too.
    # The minutes shape on a role's keys: its stat draw at 2·key, its player draw at 2·key + 1.
    m = fc.oracle(many, 0.2, 5, 0, shape="minutes", role="yahoo")
    s = fc.oracle(many, 0.2, 5, 0, role="yahoo")
    k, at = 17, 2 * fc.ROLE_KEYS["yahoo"]
    shared = world.rng(5, 0, k, at + 1, world.STREAMS["forecast"]).standard_normal()
    z_pts = math.log(s[k]["pts"] / truth[k]["pts"]) / 0.2
    want = 0.2 * (math.sqrt(fc.MINUTES_SHARE) * shared + math.sqrt(1 - fc.MINUTES_SHARE) * z_pts)
    assert math.log(m[k]["pts"] / truth[k]["pts"]) == pytest.approx(want)
    with pytest.raises(ValueError, match="role"):
        fc.oracle(lines, 0.2, 7, 3, role="hashtag")


def test_a_real_forecaster_is_the_same_forecast_wherever_it_is_named():
    assert fc.standin(fc.Forecaster("espn"), "bbm") == fc.Forecaster("espn")
    assert fc.standin(fc.Forecaster("oracle", 0.2), "yahoo").label == "oracle:0.2@yahoo"


# --------------------------------------------------------------------------- the reads table
def test_system_and_blend_are_read_once_the_run_names_the_stand_ins():
    none, named = policy.Shape(), policy.Shape(standins=True)
    for tier in (*policy.TIERS, "static"):
        a = arm("A", tier, "market")
        assert policy.reads(a, none)["system"] == policy.NO_STANDINS
        assert policy.reads(a, none)["blend"] == policy.NO_STANDINS
        assert policy.reads(a, named)["system"] == policy.READ  # its lineup, at the least
        assert policy.reads(a, named)["blend"] == "the arm's system is not blend"
        blend = arm("A", tier, "market", system="blend")
        assert policy.reads(blend, named)["blend"] == policy.READ
        # A mirror rival holds the run's forecaster: the arm's own seat reads the two, no rival.
        mirror = arm("A", tier, "mirror", system="blend")
        assert policy.reads(mirror, none, mirrored=True)["system"] == policy.NO_STANDINS
        assert policy.reads(mirror, none, mirrored=True)["blend"] == policy.NO_STANDINS
        assert policy.reads(mirror, named, mirrored=True)["blend"] == policy.READ
    assert "stand-ins named" in named.label() and "stand-ins" not in none.label()
    # Only the arm's seat names a forecaster: its mirror rivals hold the run's.
    setup, lines = recorded()
    w = rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS, label="first", forecasts={"b": {}})
    a = replace(arm("A", "surrogate", "mirror", system="blend"), forecaster="b")
    variant = {**rn.opponents_of(setup, a, 1), 1: a.seat()}
    assert rn.holds_of(w, variant) == {1: "b"}
    assert "--bbm-as" in policy.WHEN_READ["system"] and "PR D" not in policy.WHEN_READ["system"]


def test_two_arms_that_differ_only_in_system_are_the_same_seat_without_stand_ins():
    a = arm("A", "exact", "market")
    b = replace(a, name="B", knobs={**a.knobs, "system": "yahoo"})
    same = rn.same_seat(a, b, [policy.Shape()], rivals=False)
    assert same and same[0].startswith("system (the run names no stand-ins")
    assert rn.same_seat(a, b, [policy.Shape(standins=True)], rivals=False) is None
    # With the stand-ins named each believes by its system: their labels differ too.
    arms = ss.believing({"A": a, "B": b}, ss.sources_of("espn", "marcel"))
    assert (arms["A"].forecaster, arms["B"].forecaster) == ("espn", "yahoo(marcel else espn)")
    # A blend share is not read under system bbm: the same seat, by name.
    c = replace(a, name="C", knobs={**a.knobs, "blend": 0.5})
    same = rn.same_seat(a, c, [policy.Shape(standins=True)], rivals=False)
    assert same and same[0].startswith("blend (the arm's system is not blend")


def test_the_table_matches_what_the_seats_do_on_a_replay():
    """Two arms that differ only in ``system`` part their records on a replay with stand-ins;
    two that differ only in ``blend`` under system ``bbm`` do not."""
    setup, lines = recorded()
    first = dict(setup.projection)
    second = {k: {s: v * (1.4 if k % 3 else 0.7) for s, v in r.items()} for k, r in first.items()}
    sources = (fc.Forecaster("first"), fc.Forecaster("second"))

    def records(a, b):
        arms = ss.believing({"A": a, "B": b}, sources)
        forecasts = {}
        for x in arms.values():
            system, share = str(x.knobs["system"]), x.knobs["blend"]
            forecasts[x.forecaster] = fc.system_rates(system, share, first, second)
        w = rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS, label="first", forecasts=forecasts)
        out = []
        for x in arms.values():
            got: list[dict[str, str]] = []
            variant = {**rn.opponents_of(setup, x, 1), 1: x.seat()}
            rn.simulate(setup, w, [variant], on_day=lambda r, got=got: got.append(nopeek.digest(r)))
            out.append(got)
        return out

    a = arm("A", "ranking", "static")
    ra, rb = records(a, replace(a, name="B", knobs={**a.knobs, "system": "yahoo"}))
    assert ra != rb
    ra, rb = records(a, replace(a, name="B", knobs={**a.knobs, "blend": 0.5}))
    assert ra == rb


# --------------------------------------------------------------------------- the room
@pytest.fixture(scope="module")
def systems_data(tmp_path_factory) -> Path:
    """The synthetic folder, fitted, with a ``bbm``, a ``yahoo`` and a ``blend`` arm."""
    data = make_data_dir(tmp_path_factory.mktemp("systems"))
    assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, system, blend in (
        ("bbm", "bbm", None),
        ("yahoo", "yahoo", None),
        ("blend", "blend", 0.25),
    ):
        spec = {
            "name": name,
            "tier": "ranking",
            "knobs": {**KNOBS, "system": system, "blend": blend},
            "opponents": {"kind": "market"},
        }
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


def run_args(data: Path, *extra: str) -> list[str]:
    seats = [str(data / f"{n}.json") for n in ("bbm", "yahoo", "blend")]
    return [
        "--data",
        str(data),
        "--rooms",
        "0",
        "replay",
        "--season",
        "2024",
        "--seats",
        *seats,
        "--workers",
        "1",
        *extra,
    ]


def test_a_room_of_the_three_systems_names_each_arms_belief(systems_data: Path, capsys):
    data = systems_data
    flags = ("--forecasters", "prior", "--bbm-as", "prior", "--yahoo-as", "oracle:0.2")
    assert ss.main(run_args(data, *flags, "--paths", "1")) == 0
    out = capsys.readouterr().out
    (line,) = [x for x in out.splitlines() if x.startswith("written: ")]
    p = json.loads(Path(line.removeprefix("written: ")).read_text())
    assert p["audit"]["paths_voided"] == 0 and p["audit"]["breaches"] == []
    assert p["beliefs"] == {
        "bbm": "prior",
        "yahoo": "yahoo(oracle:0.2@yahoo else prior)",
        "blend": "blend:0.25(oracle:0.2@yahoo with prior)",
    }
    src = p["sources"]
    assert (src["bbm"], src["yahoo"]) == ("prior", "oracle:0.2@yahoo")
    assert src["note"] == (
        "the result is about two sources with these errors, not about the two real sources"
    )
    assert "upper bound" in src["oracle"] and src["differs"] == list(fc.LIVE_DIFFERENCES)
    assert set(src["systems"]) == set(p["beliefs"].values())
    assert src["systems"]["blend:0.25(oracle:0.2@yahoo with prior)"]["share"] == 0.25
    # A yahoo or blend seat's rostered players read the first stand-in's line.
    assert {x["system"]: x["rostered"] for x in src["systems"].values()} == {
        "bbm": None,
        "yahoo": "prior",
        "blend": "prior",
    }
    assert src["rule"] == fc.SYSTEMS_RULE and "every rostered player" in src["rule"]
    assert p["forecasters"]["prior"]["stands_for"] == ["bbm"]
    assert p["forecasters"]["oracle:0.2@yahoo"]["stands_for"] == ["yahoo"]
    assert p["forecasters"]["oracle:0.2@yahoo"]["error"]["median_spread"] == pytest.approx(
        0.2, abs=0.05
    )
    assert "stand-ins named" in p["shape"]
    reads = p["reads"]["bbm"][p["shape"]]["knobs"]
    assert reads["system"] == policy.READ and reads["blend"] == "the arm's system is not blend"
    assert p["reads"]["blend"][p["shape"]]["knobs"]["blend"] == policy.READ
    assert set(p["results"]) == {"prior"}  # the stand-ins add no task


def test_the_no_peek_check_holds_on_the_room_of_the_three_systems(systems_data: Path, capsys):
    flags = ("--bbm-as", "prior", "--yahoo-as", "oracle:0.2", "--no-peek", "2023-11-20")
    assert ss.main(run_args(systems_data, *flags)) == 0
    assert "agree through 2023-11-20" in capsys.readouterr().out


def test_a_stand_in_that_cannot_serve_the_season_refuses_the_run(systems_data: Path, capsys):
    data = systems_data
    for flags, why in (
        (("--bbm-as", "marcel", "--yahoo-as", "prior"), "marcel needs 2 earlier seasons"),
        (("--bbm-as", "espn", "--yahoo-as", "prior"), "espn: season 2024's log holds no"),
        (("--bbm-as", "prior"), "--bbm-as without the other"),
        (("--bbm-as", "prior", "--yahoo-as", "prior"), "both name prior"),
    ):
        assert ss.main(run_args(data, *flags, "--paths", "1")) == 2
        assert why in capsys.readouterr().out
    # Without stand-ins the three arms differ only in what nobody reads: the same seat.
    assert ss.main(run_args(data, "--paths", "1")) == 2
    assert "the same seat" in capsys.readouterr().out
