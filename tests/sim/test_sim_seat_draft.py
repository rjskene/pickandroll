"""The arm's seat's draft under a table (#172, the draft PR; the user's ruling of 2026-11-18):
under ``--seat-draft market``, the default, the seat drafts as the rival in its seat on that path
would, so a pair's two arms share one league whatever they believe; ``own`` is the rule before
it. The boards and the leagues here, on a made-up season and a made-up table, and a path of
every kind of league under the rule; the command's record and the no-peek check under the rule
are in ``test_sim_market.py``."""

from __future__ import annotations

import contextlib
import io
import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import adp, shapes, world
from pickandroll.sim import cli as ss
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim.engine import wk
from tests.sim.sim_league import KNOBS, make_data_dir

SPREAD = adp.Spread(2.0, 0.1)
SEED = 3
POINTS = shapes.LeagueRules(scoring="points", points=tuple(dict(shapes.POINTS_DEFAULT).items()))
#: The commands' clock here: a weekday morning outside the routines' window.
BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
#: The arms' spec files: a ranking seat, a surrogate seat and a static one, on one forecaster.
TIERS = {"R": "ranking", "U": "surrogate", "S": "static"}


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    """The made-up seasons with a wire of 120 (free agents to add after a draft of twelve
    teams), their fit and the arms' spec files."""
    folder = make_data_dir(tmp_path_factory.mktemp("seat-draft"), wire=120)
    with contextlib.redirect_stdout(io.StringIO()):
        fit = ["--data", str(folder), "--rooms", "0", "fit", "--seasons", "2023-2024"]
        assert ss.main(fit) == 0
    for name, tier in TIERS.items():
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": {"kind": "static"}}
        (folder / f"{name}.json").write_text(json.dumps(spec))
    return folder


@pytest.fixture(scope="module")
def season(data):
    """The made-up season's lines, members, schedule and projection, its made-up table, and a
    second forecaster that disagrees with the run's: each projected player has the rates of
    the one at the mirrored place in the run's forecaster's order."""
    lines, members, scheduled = reader.replay_lines(data, 2024)
    projection = reader.prior_rates(data, 2024)
    table, _ = reader.adp_table(data, 2024, 2025)
    plain = ss.replay_setup_of(2024, lines, members, scheduled, projection)
    order = sorted((k for k in projection if k in members), key=lambda k: (-plain.market[k], k))
    other = {k: projection[order[-1 - i]] for i, k in enumerate(order)}
    return lines, members, scheduled, projection, table, other


#: Two arms that believe apart: A the run's forecaster, B the made-up second one.
ARMS = {"a": SimpleNamespace(forecaster=None), "b": SimpleNamespace(forecaster="other")}
SAME = {"a": SimpleNamespace(forecaster=None), "b": SimpleNamespace(forecaster=None)}


def leagues(season, rule, path=0, turn=None, arms=ARMS, rules=shapes.PLAIN, mp=None):
    """The pair's leagues on one path under ``rule``, by arm, and every call of
    ``run.draft_boards`` made for them: its arguments and the boards it gave."""
    lines, members, scheduled, projection, table, other = season
    calls: list[tuple[tuple, dict]] = []
    real = rn.draft_boards

    def spy(*t, **kw):
        out = real(*t, **kw)
        calls.append((t, out))
        return out

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rn, "draft_boards", spy)
        setups = ss.pair_setups(
            2024,
            lines,
            members,
            scheduled,
            projection,
            (table.picks, SPREAD, rule),
            arms,
            ss.PAIR,
            "prior",
            {"other": other},
            SEED,
            path,
            shapes.FIXED,
            turn,
            rules,
        )
    return setups, calls


def seat_of(path: int, turn: int | None = None) -> int:
    return shapes.FIXED.ids[(path if turn is None else turn) % shapes.FIXED.teams]


@pytest.mark.parametrize("rules", [shapes.PLAIN, POINTS], ids=["categories", "points"])
def test_under_the_market_rule_the_seat_s_board_is_the_rival_s_in_its_seat(season, rules):
    """The arm's seat's board is ``adp.rival_board`` for its team on the path's own draw
    (``world.rng(seed, path, team, 0, draft)``), on the table, the spread and the run's
    forecaster's values every rival reads: in a categories league and in a points league."""
    table = season[4]
    setups, calls = leagues(season, adp.MARKET_DRAFT, path=4, rules=rules)
    ((args, boards),) = calls  # one draft for the pair
    draft, draftable, value = args[0], args[1], args[2]
    assert (draft.picks, draft.spread, draft.seed, draft.path) == (table.picks, SPREAD, SEED, 4)
    assert dict(draft.seats) == {}
    me = seat_of(4)
    for team in shapes.FIXED.ids:
        g = world.rng(SEED, 4, team, 0, world.STREAMS["draft"])
        assert boards[team] == adp.rival_board(table.picks, draftable, value, SPREAD, g)
    # Not vacuous: the seat's own forecaster would rank the same players another way.
    projection, players, cats, points = season[3], args[4], args[5], args[6]
    assert (points is not None) == (rules.scoring == "points") == (setups["a"].scoring == "points")
    own = wk.per_game_values(
        {k: projection[k] for k in projection if k in players}, tuple(cats), points
    )
    assert boards[me] != adp.seat_board(own, draftable)


def test_under_the_market_rule_the_seat_s_board_follows_the_path_and_not_the_arm(season):
    """The board is the path's, as a rival's is: another path gives another, another seed
    another, and the seat the pair sits in changes no board (the draft names no seat)."""
    _, one = leagues(season, adp.MARKET_DRAFT, path=2)
    _, again = leagues(season, adp.MARKET_DRAFT, path=2)
    _, moved = leagues(season, adp.MARKET_DRAFT, path=2, turn=7)
    _, later = leagues(season, adp.MARKET_DRAFT, path=3)
    me = seat_of(2)
    assert one[0][1] == again[0][1] == moved[0][1]
    assert one[0][1][me] != later[0][1][me]
    assert seat_of(2, 7) != me


def test_both_arms_of_a_pair_draft_one_league_under_the_market_rule(season):
    """Under ``market`` the two arms share one league, arms on two forecasters included: one
    draft, the same object, the same rosters. Under ``own`` two arms on two forecasters draft
    apart, as before, and on one forecaster they share a league under either rule."""
    setups, calls = leagues(season, adp.MARKET_DRAFT, path=1)
    assert setups["a"] is setups["b"] and len(calls) == 1
    same, calls = leagues(season, adp.MARKET_DRAFT, path=1, arms=SAME)
    assert same["a"] is same["b"] and len(calls) == 1
    # The arms' beliefs change nothing of the draft.
    assert same["a"].rosters == setups["a"].rosters
    apart, calls = leagues(season, adp.OWN_DRAFT, path=1)
    me = seat_of(1)
    assert apart["a"] is not apart["b"] and len(calls) == 2
    assert apart["a"].rosters[me] != apart["b"].rosters[me]
    own, calls = leagues(season, adp.OWN_DRAFT, path=1, arms=SAME)
    assert own["a"] is own["b"] and len(calls) == 1


def test_the_rule_changes_whom_the_seat_drafts_and_no_rival_s_board(season):
    """The lever does something: on one path the seat's roster under ``market`` is not its
    roster under ``own``, while every rival drafts on the same board under both rules. Under
    ``own`` the seat holds only players its forecaster ranks; under ``market`` it follows the
    table, so its picks stand lower on its own forecaster's board."""
    projection = season[3]
    market, m_calls = leagues(season, adp.MARKET_DRAFT, path=5, arms=SAME)
    own, o_calls = leagues(season, adp.OWN_DRAFT, path=5, arms=SAME)
    me = seat_of(5)
    mine, theirs = market["a"].rosters[me], own["a"].rosters[me]
    assert {k for k, _ in mine} != {k for k, _ in theirs}
    (_, m_boards), (o_args, o_boards) = m_calls[0], o_calls[0]
    assert dict(o_args[0].seats).keys() == {me}
    assert all(m_boards[t] == o_boards[t] for t in shapes.FIXED.ids if t != me)
    assert m_boards[me] != o_boards[me]
    # The seat's own forecaster's order: its own draft's picks stand higher on it.
    value = wk.per_game_values({k: projection[k] for k in projection}, market["a"].cats, None)
    rank = {k: i for i, k in enumerate(sorted(value, key=lambda k: (-value[k], k)))}
    worst = len(rank)
    assert sum(rank.get(k, worst) for k, _ in theirs) < sum(rank.get(k, worst) for k, _ in mine)


def test_a_room_s_seats_each_draft_as_a_rival_under_the_market_rule(season):
    """A room: every seat holds an arm. Under ``market`` the draft names no seat, so each seat
    drafts as a rival; under ``own`` every seat is named with its arm's forecaster's
    projection."""
    lines, members, scheduled, projection, table, other = season
    arms = {"R": SimpleNamespace(forecaster=None), "S": SimpleNamespace(forecaster="other")}
    args = (arms, ("R", "S"), "prior", projection, {"other": other}, SEED, 6)
    draft = ss.room_draft((table.picks, SPREAD, adp.MARKET_DRAFT), *args)
    assert draft == adp.Draft(table.picks, SPREAD, SEED, 6, {})
    named = ss.room_draft((table.picks, SPREAD, adp.OWN_DRAFT), *args)
    assert sorted(named.seats) == list(shapes.FIXED.ids) and named.path == 6
    assert ss.room_draft(None, *args) is None
    setup = ss.replay_setup_of(2024, lines, members, scheduled, projection, draft)
    apart = ss.replay_setup_of(2024, lines, members, scheduled, projection, named)
    assert setup.rosters != apart.rosters


def test_the_rules_are_two_and_the_market_s_is_the_default():
    assert adp.SEAT_DRAFTS == ("market", "own")
    table = SimpleNamespace(adp="espn", seat_draft=None)
    assert ss.seat_draft_of(table) == "market"
    assert ss.seat_draft_of(SimpleNamespace(adp="espn", seat_draft="own")) == "own"
    assert ss.seat_draft_of(SimpleNamespace(adp="none", seat_draft=None)) is None
    for texts in (ss.ADP_SEAT, ss.ADP_LIMIT, ss.ADP_SHARED, ss.ADP_DRAFT):
        assert set(texts) == set(adp.SEAT_DRAFTS)


# --------------------------------------------------------------------------- every league kind
def dry(data: Path, arm: str, *extra: str) -> tuple[int, str, dict[str, float]]:
    """A pair's dry run under the table, naming no rule: ``arm`` against the static seat, its
    first task played to the season's end and audited. The exit code, the output and arm A's
    counts in that task."""
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024"]
    argv += ["--arms", str(data / f"{arm}.json"), str(data / "S.json")]
    argv += ["--adp", "espn", "--adp-spread", "2,0.1", "--paths", "1", "--workers", "1"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main([*argv, "--seed", "5", "--dry-run", *extra])
    out = buf.getvalue()
    (line,) = [x for x in out.splitlines() if x.startswith("counts, a, the first task: ")] or [""]
    counts = {k: float(v) for k, v in re.findall(r"(\w+) ([0-9.e+-]+)", line.partition(": ")[2])}
    return code, out, counts


KINDS = {
    "held": ("--held", "IL=1,IL+=1"),
    "points": ("--scoring", "points"),
    "priority-each": ("--waivers", "priority", "--h2h", "each_category"),
    "priority-continuous": ("--waivers", "priority", "--waiver-rule", "continuous"),
    "faab": ("--waivers", "faab"),
    "faab-continuous-each": ("--waivers", "faab", "--waiver-rule", "continuous")
    + ("--h2h", "each_category"),
}


@pytest.mark.parametrize("kind", list(KINDS))
def test_a_path_of_every_kind_of_league_plays_clean_under_the_market_rule(data, kind):
    """Under a table that names no rule, one path of each kind of league (held slots, a points
    league, both waivers, both waiver rules, both head-to-head formats): the seat drafts as a
    rival, the ranking seat in it lands adds (a rule under which nobody moves would pass an
    audit on nothing), and the audit finds no breach (a breach exits 3)."""
    code, out, counts = dry(data, "R", *KINDS[kind])
    assert code == 0 and "AUDIT" not in out, out
    assert "the arms' seats draft as rivals do (--seat-draft market)" in out
    assert "draft market, the first task: 1 draft(s)" in out
    assert counts["landed"] >= 1, out
    if "continuous" in kind:
        assert counts["claims_won"] == counts["landed"]


def test_a_surrogate_seat_moves_and_plays_clean_under_the_market_rule(data):
    """A seat that weighs its categories, in the public leagues' kind (FAAB, continuous
    waivers, a win a category). One format only: the format changes no board and no draft,
    the ranking seat's paths above play both, and a surrogate path here costs half a
    minute."""
    code, out, counts = dry(data, "U", *KINDS["faab-continuous-each"])
    assert code == 0 and "AUDIT" not in out, out
    assert counts["landed"] >= 1 and counts["claims_won"] == counts["landed"], out
