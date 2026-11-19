"""The head-to-head format (#172, the format PR): one win per matchup, or every category.

The rule (``shapes.LeagueRules.h2h``, ``replay --h2h``), the standings that read it
(``league.standings``), the playoffs that do not, the league ``run.replay_setup`` builds; the
seat's measure (``MoveProblem.one_win``), the plan floor's reads, the bid's typical gain, the
season scale's note, a replay in each format, Rule 2's pins and ``validate --h2h``. Every test of
the format runs in both formats. Made-up leagues only."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import forecast as fc
from pickandroll.sim import league as lg
from pickandroll.sim import policy, shapes
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, mv, st, wk
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, every_category, make_setup, of_format
from tests.sim.test_sim_points import TABLE, setup_of
from tests.sim.test_sim_rules_run import pinned_clock, replay, spec, wire, written  # noqa: F401
from tests.sim.test_sim_seasons import rounded

FORMATS = (ONE_WIN, EACH_CATEGORY)
#: Nine categories a higher total wins, so a week's margin is set by how many each side takes.
CATS = ("pts", "reb", "ast", "stl", "blk", "threes", "fgm", "ftm", "fta")
#: Four teams, three regular weeks, a final between the top two in week 4.
PAIRS = {1: ((1, 2), (3, 4)), 2: ((1, 3), (2, 4)), 3: ((1, 4), (2, 3))}


def league(h2h: str, pairs=PAIRS) -> lg.LeagueSpec:
    tiebreak = lg.TIEBREAK_EACH if h2h == EACH_CATEGORY else lg.TIEBREAK
    return lg.LeagueSpec((1, 2, 3, 4), pairs, (4,), CATS, playoff_teams=2, byes=0,
                         tiebreak=tiebreak, h2h=h2h)  # fmt: skip


def week(a: int, b: int, won: int, tied: int = 0) -> dict[int, dict[str, float]]:
    """``a``'s and ``b``'s totals in a week ``a`` wins ``won`` categories of and ties ``tied``."""
    mine = {c: 2.0 if i < won else 1.0 if i < won + tied else 0.0 for i, c in enumerate(CATS)}
    return {a: mine, b: {c: 2.0 - x for c, x in mine.items()}}


def season(weeks: dict[int, list[tuple[int, ...]]], final: tuple[int, ...] = (1, 2, 5)):
    """Week to each pair's ``(a, b, a's categories won[, tied])``, and the final's, as totals."""
    totals = {w: {t: x for p in ps for t, x in week(*p).items()} for w, ps in weeks.items()}
    totals[4] = week(*final)
    return totals


#: Team 1 wins every week narrowly (5-4), team 2 loses to it narrowly and wins its other two weeks
#: 9-0: one win per matchup ranks team 1 first (3-0 against 2-1), every category team 2 (22 of 27
#: categories against 15).
NARROW_AND_WIDE = season(
    {1: [(1, 2, 5), (3, 4, 5)], 2: [(1, 3, 5), (2, 4, 9)], 3: [(1, 4, 5), (2, 3, 9)]}
)


# --------------------------------------------------------------------------- the rule
def test_the_format_is_one_win_per_matchup_by_default_and_every_category_when_named():
    assert shapes.H2H == (ONE_WIN, EACH_CATEGORY) == ("one_win", "each_category")
    assert shapes.PLAIN.h2h == ONE_WIN and shapes.PLAIN.one_win
    assert shapes.parse_h2h("categories", None) == ONE_WIN
    for h2h in FORMATS:
        assert shapes.parse_h2h("categories", h2h) == h2h
        assert shapes.parse_h2h("categories", h2h.upper()) == h2h
    each = shapes.LeagueRules(h2h=EACH_CATEGORY)
    assert not each.one_win and each != shapes.PLAIN
    # Hashable and told apart by the format alone.
    assert len({shapes.PLAIN, each, shapes.LeagueRules(h2h=ONE_WIN)}) == 2


def test_a_format_named_with_points_or_out_of_the_two_is_refused_by_name():
    for h2h in FORMATS:
        with pytest.raises(ValueError, match=f"--h2h {h2h}: a points league's week is one result"):
            shapes.parse_h2h("points", h2h)
    with pytest.raises(ValueError, match="--h2h each: one of one_win, each_category"):
        shapes.parse_h2h("categories", "each")
    with pytest.raises(ValueError, match="with scoring points: a points league's week is one"):
        shapes.LeagueRules("points", shapes.POINTS_DEFAULT, h2h=EACH_CATEGORY)
    with pytest.raises(ValueError, match="'roto' is not one of one_win, each_category"):
        shapes.LeagueRules(h2h="roto")
    # A points league holds the default: its measure is its own, not the matchup's odds.
    points = shapes.LeagueRules("points", shapes.POINTS_DEFAULT)
    assert points.h2h == ONE_WIN and not points.one_win


def test_the_label_says_every_category_and_leaves_the_default_unsaid():
    each = shapes.LeagueRules(held=("IL",), waivers="priority", h2h=EACH_CATEGORY)
    assert each.label() == (
        "the nine categories, every category counted, one IL slot, waivers by priority after 2 days"
    )
    assert shapes.LeagueRules(held=("IL",), waivers="priority").label() == (
        "the nine categories, one IL slot, waivers by priority after 2 days"
    )


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_payload_names_the_format_in_a_categories_league_and_none_in_points(h2h):
    rules = shapes.LeagueRules(h2h=h2h)
    assert rules.payload() == {"scoring": "categories", "points": None, "held": [], "h2h": h2h}
    assert "h2h" not in shapes.LeagueRules("points", shapes.POINTS_DEFAULT).payload()


def test_replay_refuses_a_format_with_points_or_unknown_before_any_path(wire: Path):  # noqa: F811
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--dry-run")
    for flags, why in (
        (("--scoring", "points", "--h2h", "one_win"), "--h2h one_win: a points league's week"),
        (("--scoring", "points", "--h2h", "each_category"), "--h2h each_category: a points"),
        (("--h2h", "roto"), "--h2h roto: one of one_win, each_category"),
    ):
        code, out = replay(wire, *room, *flags)
        assert code == 2 and f"refused: {why}" in out, out
        assert "tasks (" not in out


# --------------------------------------------------------------------------- the standings
@pytest.mark.parametrize("h2h", FORMATS)
def test_the_two_formats_order_a_narrow_winner_and_a_wide_one_apart(h2h):
    result = lg.season(league(h2h), NARROW_AND_WIDE)
    order = [s.team for s in result.standings]
    assert order == ([1, 2, 3, 4] if h2h == ONE_WIN else [2, 1, 3, 4])
    rows = {s.team: (s.wins, s.losses, s.ties, s.category_wins) for s in result.standings}
    # The weeks' results and the category wins are kept in either format.
    assert rows[1] == (3, 0, 0, 15.0) and rows[2] == (2, 1, 0, 22.0)


def test_the_format_moves_the_rank_and_what_rests_on_it_and_nothing_else():
    one = lg.season(league(ONE_WIN), NARROW_AND_WIDE)
    each = lg.season(league(EACH_CATEGORY), NARROW_AND_WIDE)
    assert one.results == each.results
    strip = lambda s: (s.team, s.wins, s.losses, s.ties, s.category_wins, s.points_for)
    assert sorted(map(strip, one.standings)) == sorted(map(strip, each.standings))
    for team in (1, 2, 3, 4):
        a, b = lg.summary(one, team), lg.summary(each, team)
        assert set(a) == set(b)
        same = ("category_wins", "matchup_wins", "record")
        assert {k: a[k] for k in same} == {k: b[k] for k in same}
    assert (lg.summary(one, 1)["rank"], lg.summary(each, 1)["rank"]) == (1, 2)
    assert (lg.summary(one, 2)["rank"], lg.summary(each, 2)["rank"]) == (2, 1)


def test_every_category_breaks_a_tie_on_head_to_head_then_on_the_team_s_number():
    """Teams 1 and 2 take 14 of 27 categories each; team 2 won their meeting, so it ranks first
    though its number is the higher. When they tied the meeting (14.5 each), the number decides."""
    beat = season({1: [(1, 2, 4), (3, 4, 9)], 2: [(1, 3, 5), (2, 4, 5)], 3: [(1, 4, 5), (2, 3, 4)]})
    table = lg.standings(lg.season(league(EACH_CATEGORY), beat).results, league(EACH_CATEGORY))
    assert [s.team for s in table] == [3, 2, 1, 4]
    assert table[1].category_wins == table[2].category_wins == 14.0
    # A tied meeting (4 won, 4 lost, 1 tied each), the rest the same totals: the number decides.
    tied = season(
        {1: [(1, 2, 4, 1), (3, 4, 9)], 2: [(1, 3, 5), (2, 4, 5)], 3: [(1, 4, 5), (2, 3, 5)]}
    )
    table = lg.standings(lg.season(league(EACH_CATEGORY), tied).results, league(EACH_CATEGORY))
    assert table[1].category_wins == table[2].category_wins
    assert [s.team for s in table][1:3] == [1, 2]


def test_a_points_league_ignores_the_format_field():
    """A points league's week is one result: its standings read the win percentage whatever its
    spec's ``h2h`` holds."""
    pairs = {1: ((1, 2), (3, 4))}
    points = {"pts": 1.0}
    totals = {1: {1: {"pts": 10.0}, 2: {"pts": 9.0}, 3: {"pts": 30.0}, 4: {"pts": 1.0}}}
    for h2h in FORMATS:
        s = lg.LeagueSpec((1, 2, 3, 4), pairs, (2,), (), "points", points, 2, 0,
                          lg.TIEBREAK_POINTS, h2h=h2h)  # fmt: skip
        assert [x.team for x in lg.season(s, totals).standings] == [3, 1, 2, 4]


# --------------------------------------------------------------------------- the playoffs
@pytest.mark.parametrize("final", [(1, 2, 5), (1, 2, 4), (1, 2, 4, 1)])
def test_the_playoffs_are_the_same_bracket_play_in_both_formats(final):
    """One seeding and one week's totals give one bracket in either format: the side with more
    categories through, the higher seed through a tie (4 won, 4 lost, 1 tied)."""
    totals = season({1: [(1, 2, 5), (3, 4, 5)]}, final)
    seeds = {1: 1, 2: 2}
    one = lg.playoffs(seeds, totals, league(ONE_WIN))
    each = lg.playoffs(seeds, totals, league(EACH_CATEGORY))
    assert one == each
    assert one.champion == (2 if final == (1, 2, 4) else 1)


# --------------------------------------------------------------------------- the replay's league
@pytest.mark.parametrize("h2h", FORMATS)
def test_a_replay_s_league_carries_the_format_into_its_standings(h2h):
    _, setup = setup_of(h2h=h2h)
    assert setup.h2h == setup.spec.h2h == h2h
    assert setup.one_win == (h2h == ONE_WIN)
    assert setup.spec.tiebreak == (lg.TIEBREAK if h2h == ONE_WIN else lg.TIEBREAK_EACH)


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_setup_and_its_spec_count_one_format(h2h):
    """The seat's half of the format (``Setup.h2h``) and the standings' (``spec.h2h``) are one
    rule: a categories spec of another format is refused by name, on either half."""
    setup = of_format(make_setup(pool=12), h2h)
    assert setup.h2h == setup.spec.h2h == h2h
    other = EACH_CATEGORY if h2h == ONE_WIN else ONE_WIN
    words = f"head-to-head format '{other}' with a spec of the format '{h2h}'"
    with pytest.raises(ValueError, match=words):
        replace(setup, h2h=other)
    with pytest.raises(ValueError, match=f"head-to-head format '{h2h}' with a spec of the format '{other}'"):  # fmt: skip
        replace(setup, spec=replace(setup.spec, h2h=other))
    # No bracket read, nothing to disagree with; a points spec names no format.
    assert replace(setup, spec=None, bracket_unread="unread", h2h=other).h2h == other
    _, points = setup_of(scoring="points", points=TABLE)
    assert replace(points, spec=replace(points.spec, h2h=EACH_CATEGORY)).h2h == ONE_WIN
    assert every_category(make_setup(pool=12, bracket=False)).spec is None


def test_a_replay_s_points_league_names_no_format_and_refuses_one():
    _, points = setup_of(scoring="points", points=TABLE)
    assert points.h2h == ONE_WIN and not points.one_win
    assert points.spec.tiebreak == lg.TIEBREAK_POINTS
    with pytest.raises(ValueError, match="head-to-head format 'each_category' with scoring"):
        setup_of(scoring="points", points=TABLE, h2h=EACH_CATEGORY)


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_league_block_names_the_format_and_every_category_says_how_it_ranks(h2h):
    rules = shapes.LeagueRules(h2h=h2h)
    block = ss.league_block(shapes.FIXED_GRID, [shapes.visit(0, shapes.FIXED_GRID)], [], rules)
    assert block["rules"]["h2h"] == h2h
    assert ("h2h_note" in block) == (h2h == EACH_CATEGORY)
    if h2h == EACH_CATEGORY:
        assert "category percentage" in block["h2h_note"] and "working default" in block["h2h_note"]


# --------------------------------------------------------------------------- the seat's measure
def built_in(setup, team: int = 1, **knobs):
    s = replace(initial(setup), day=setup.start)
    return policy.problem_of(setup, s, team, {**KNOBS, **knobs}, setup.projection, {}, {})


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_seat_weighs_a_week_in_its_format_s_measure(h2h):
    """The problem says the format, as the live build passes ``SeasonSettings.one_win``, and the
    engine's evaluator then values a week as the matchup's odds or its expected categories."""
    setup = of_format(make_setup(pool=12), h2h)
    b = built_in(setup)
    one_win = h2h == ONE_WIN
    assert b.problem.one_win is one_win
    assert policy.measure_of(setup) == mv.measure_of(b.problem)
    assert mv.measure_of(b.problem) == (mv.MATCHUP if one_win else mv.CATEGORIES)
    ev = mv.Evaluator(b.problem)
    won = wk.matchup_won if one_win else wk.expected_won
    for key in ("week", "three"):
        weeks = [w for w in ev.odds(key, ()) if w]
        assert weeks
        want = sum(sum(won(o) for o in w) / len(w) for w in weeks)
        assert ev.value(key, ()) == pytest.approx(want)
    # The odds are the same in both formats: only the week's measure of them differs.
    other = built_in(of_format(make_setup(pool=12), EACH_CATEGORY if one_win else ONE_WIN))
    assert mv.Evaluator(other.problem).odds("week", ()) == ev.odds("week", ())


def test_a_points_league_passes_no_format_and_weighs_its_points():
    _, setup = setup_of(scoring="points", points=TABLE)
    b = built_in(setup)
    assert b.problem.one_win is False and b.problem.points
    assert policy.measure_of(setup) == mv.measure_of(b.problem) == mv.POINTS
    for points, one_win, want in (
        (False, True, mv.MATCHUP),
        (False, False, mv.CATEGORIES),
        (True, False, mv.POINTS),
        (True, True, mv.POINTS),
    ):
        assert policy.measure(points, one_win) == want


# --------------------------------------------------------------------------- the reads
PLANS = rn.Arm("E", "exact", KNOBS, {}, with_plan=True, execute_plan=True)


@pytest.mark.parametrize("h2h", FORMATS)
def test_plan_floor_cats_is_read_only_where_the_league_counts_every_category(h2h):
    each = h2h == EACH_CATEGORY
    want = policy.READ if each else policy.ONE_WIN_FLOOR
    for waivers in ("none", "faab"):
        assert (
            policy.reads(PLANS, policy.Shape(waivers=waivers, h2h=h2h))["plan_floor_cats"] == want
        )
    bidder = rn.Arm("U", "surrogate", KNOBS, {})
    assert policy.reads(bidder, policy.Shape(waivers="faab", h2h=h2h))["plan_floor_cats"] == want
    # Every other knob, and every knob of a seat that would not read it anyway, reads as in the
    # other format: the format reaches the categories plan floor alone.
    for arm in (PLANS, bidder, rn.Arm("R", "ranking", KNOBS, {}), rn.Arm("S", "static", KNOBS, {})):
        for waivers in ("none", "priority", "faab"):
            one = policy.reads(arm, policy.Shape(waivers=waivers, h2h=ONE_WIN))
            two = policy.reads(arm, policy.Shape(waivers=waivers, h2h=EACH_CATEGORY))
            assert {k for k in one if one[k] != two[k]} <= {"plan_floor_cats"}
            if two["plan_floor_cats"] != policy.READ:
                assert one == two
    # A points league names no format.
    points = policy.Shape("points", h2h=h2h)
    assert policy.reads(PLANS, points)["plan_floor_points"] == policy.READ


def test_a_pair_apart_only_on_plan_floor_cats_is_one_seat_in_a_one_win_run_and_two_otherwise():
    b = replace(PLANS, name="G", knobs={**KNOBS, "plan_floor_cats": 0.5})
    (why,) = rn.same_seat(PLANS, b, [policy.Shape(h2h=ONE_WIN)], rivals=False)
    assert why == (
        f"plan_floor_cats ({policy.ONE_WIN_FLOOR}; read by the exact tier drawing and executing "
        "the week plan, or executing queue, in a categories league), and in a categories FAAB "
        "run by a seat that bids (the exact or the surrogate tier, a mirror rival), its typical "
        "gain until ten moves; either only in a league that counts every category "
        "(--h2h each_category)"
    )
    assert rn.same_seat(PLANS, b, [policy.Shape(h2h=EACH_CATEGORY)], rivals=False) is None


def test_replay_refuses_the_pair_in_a_one_win_run_and_reads_it_under_every_category(wire: Path):  # noqa: F811
    (wire / "G.json").write_text(
        json.dumps(
            {
                "name": "G",
                "knobs": {**KNOBS, "plan_floor_cats": 0.5},
                "opponents": {"kind": "static"},
                "tier": "exact",
                "with_plan": True,
                "execute_plan": True,
            }
        )
    )
    code, out = replay(wire, "--arms", *spec(wire, "E", "G"), "--paths", "1", "--dry-run")
    assert code == 2 and "they differ only in plan_floor_cats (a one-win league's plan" in out, out
    arms = {k: rn.arm_of(json.loads((wire / f"{n}.json").read_text())) for k, n in (("a", "E"), ("b", "G"))}  # fmt: skip
    rules = shapes.LeagueRules(h2h=EACH_CATEGORY)
    r = ss.read_season(wire, 2024, fc.parse("prior"), None, arms, 5, "stat", rules)
    assert r.shape.h2h == EACH_CATEGORY
    assert ss.same_seats(arms, [r.shape], rivals=True) is None


# --------------------------------------------------------------------------- the bid
@pytest.mark.parametrize("h2h", FORMATS)
def test_a_seat_that_bids_scales_by_the_engine_s_floor_in_its_format(h2h):
    """In a one-win FAAB league the typical gain until ten moves is the engine's floor in odds,
    not ``plan_floor_cats``; under every category the knob, as in PR Fb."""
    setup = of_format(replace(make_setup(pool=12), waivers="faab", waiver_days=2), h2h)
    b = built_in(setup, plan_floor_cats=0.25)
    floor = st.PLAN_FLOOR_ODDS if h2h == ONE_WIN else 0.25
    assert st.floor_of(b.problem) == floor
    for decision in (policy.exact(b, with_plan=False), policy.surrogate(b)):
        assert decision.basis is not None and decision.basis.floor == floor


# --------------------------------------------------------------------------- the season scale
def test_the_season_scale_s_note_says_its_gain_is_in_odds_in_a_one_win_league():
    assert ss.scale_note("categories", ONE_WIN) == ss.SCALE_NOTE + ss.SCALE_NOTE_ONE_WIN
    assert ss.scale_note("categories", EACH_CATEGORY) == ss.SCALE_NOTE
    assert ss.scale_note("points") == ss.SCALE_NOTE + ss.SCALE_NOTE_POINTS
    assert "matchup's win odds" in ss.SCALE_NOTE_ONE_WIN
    assert "season_weight set in one format is not the other's" in ss.SCALE_NOTE_ONE_WIN


# --------------------------------------------------------------------------- a replay in each format
#: The replays' arm that weighs: a surrogate seat on a small pool, two weeks ahead, solving on
#: Mondays, so a path is a few seconds.
SEATS = {
    "U": {
        "tier": "surrogate",
        "opponents": {"kind": "static"},
        "pool": 8,
        "weeks_ahead": 2,
        "surrogate_days": [0],
    },
}


@pytest.fixture(scope="module")
def seats(wire: Path) -> Path:  # noqa: F811
    for name, extra in SEATS.items():
        (wire / f"{name}.json").write_text(json.dumps({"name": name, "knobs": KNOBS, **extra}))
    return wire


@pytest.fixture(scope="module")
def formats(seats: Path) -> dict[str, tuple]:
    """One path of a room of the surrogate seat and a static one in each format, with every move
    problem's format and every standings table the run built: the payload, the problems' flags,
    the tables (with their spec and results) and what the run printed."""
    built: list[bool] = []
    tables: list[tuple] = []
    real_problem, real_standings = policy.problem_of, lg.standings

    def problem_of(*a, **k):
        b = real_problem(*a, **k)
        if b is not None:
            built.append(b.problem.one_win)
        return b

    def standings(results, spec_):
        table = real_standings(results, spec_)
        tables.append((spec_, results, table))
        return table

    out = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(policy, "problem_of", problem_of)
        mp.setattr(lg, "standings", standings)
        for h2h in FORMATS:
            built.clear()
            tables.clear()
            room = ("--seats", *spec(seats, "U", "S"), "--paths", "1", "--h2h", h2h)
            code, text = replay(seats, *room)
            assert code == 0, text
            out[h2h] = (written(text), list(built), list(tables), text)
    return out


def first_key(spec_, results, s) -> float:
    """What the format orders a team by: its win percentage, or its category percentage."""
    if spec_.h2h == ONE_WIN:
        return s.pct
    played = sum(r.won + r.lost + r.tied for w in results.values() if (r := w.get(s.team)))
    return s.category_wins / played


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_replay_s_seats_and_its_standings_follow_one_format(formats, h2h):
    """The test that catches a format that moves one half only: a run's record names the format
    and the measure, every move problem it built weighs in that measure, and every standings
    table it built orders the teams by that format's percentage. Not vacuous: the surrogate seat
    lands an add in each format (a problem built is not a seat that moved)."""
    p, built, tables, text = formats[h2h]
    for by_forecaster in p["counts"]["by_season"].values():
        for row in by_forecaster.values():
            assert row["U"]["landed"]["mean"] >= 1, h2h
    one_win = h2h == ONE_WIN
    assert p["league"]["rules"]["h2h"] == h2h
    assert p["measure"] == (mv.MATCHUP if one_win else mv.CATEGORIES)
    assert p["executions"] == policy.EXECUTIONS
    assert ("h2h_note" in p["league"]) is not one_win
    assert p["season_scale"]["note"] == ss.scale_note("categories", h2h)
    assert built and set(built) == {one_win}
    assert tables
    for spec_, results, table in tables:
        assert spec_.h2h == h2h
        keys = [first_key(spec_, results, s) for s in table]
        assert keys == sorted(keys, reverse=True)
    assert ("every category counted" in text) is not one_win


def figures_digest(p: dict) -> str:
    """SHA-256 of a run's results, counts and season scale figures, each rounded to nine places
    (as ``test_sim_seasons.figures_digest``)."""
    figures = rounded(
        {
            "results": p["results"],
            "counts": p["counts"]["by_season"],
            "scale": p["season_scale"]["by_season"],
        }
    )
    return hashlib.sha256(json.dumps(figures, sort_keys=True).encode()).hexdigest()


#: Rule 2's pin: the figures digest of the run under every category as the format PR's first
#: commit (3deb431) gave it, before the seats weighed in the format's measure
#: (``~/sim-notes/vm/scratch/format/rule2_digests.py`` on that commit: the same flags, seed and
#: digest). Rule 2's other pin, a room of seats that hold no odds under the default (a ranking and
#: a static seat), is ``test_sim_seasons.py``'s ``BEFORE``, which holds unedited.
EACH_BEFORE = "8237a27a31d762ad41ce9fec01c4092e88fdb9bf92515dff7d4f2908d51e6a9f"


def test_rule_2_a_run_under_every_category_plays_as_the_commit_before(formats):
    assert figures_digest(formats[EACH_CATEGORY][0]) == EACH_BEFORE


# --------------------------------------------------------------------------- validate
#: Gate 5's answers under the default on this folder (seed 1, lag 1, path 0), by seat: the two
#: tiers, both weighing the matchup's odds, differ on one day for one seat (14 of 15; each set
#: holds four moves). Under every category they are ``WIRE_MATCHES``, gate 5's answers before the
#: format PR (13 of 15; ``test_season_sim_script``'s gate 5 tests name that format).
ONE_WIN_MATCHES = {
    1: [True, True, True, True, True],
    6: [True, True, True, True, False],
    12: [True, True, True, True, True],
}


def test_validate_plays_gate_five_in_the_format_named(wire: Path):  # noqa: F811
    """``validate`` under the default compares the two tiers in the matchup's odds: its block
    names the format, and its answers are :data:`ONE_WIN_MATCHES`, on days where the exact tier's
    set holds a move (not vacuous: two empty sets agree too). A format it does not know is
    refused before any solve."""
    base = ["--data", str(wire), "--rooms", "0", "validate", "--season", "2024"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(base)
    out = buf.getvalue()
    assert code == 0, out
    p = written(out)
    assert p["surrogate_gate"]["rules"] == {
        "scoring": "categories",
        "points": None,
        "held": [],
        "h2h": ONE_WIN,
    }
    assert "measure" not in p
    moved = 0
    for g in p["gates"]:
        d = g["detail"]
        assert [x["equal"] for x in d["records"]] == ONE_WIN_MATCHES[d["seat"]]
        assert d["matched"] == sum(ONE_WIN_MATCHES[d["seat"]])
        moved += sum(1 for x in d["records"] if x["equal"] and x["exact"])
    assert moved > 0  # days where the two tiers agree on a set that holds a move
    assert "under the nine categories, no held slot, one win per matchup" in out
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert ss.main([*base, "--h2h", "roto", "--dry-run"]) == 2
    assert "refused: --h2h roto: one of one_win, each_category" in buf.getvalue()
