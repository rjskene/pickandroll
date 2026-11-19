"""The arm's seat's draft under a table (#172, the draft PR; the user's ruling of 2026-11-18):
under ``--seat-draft market``, the default, the seat drafts as the rival in its seat on that path
would, less the players its own forecaster cannot value; a pair's two arms share one league
wherever their two drafts come out the same; ``own`` is the rule before it. The boards and the leagues here, on a made-up season and a made-up table, and a path of
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
IDS = shapes.FIXED.ids


def leagues(season, rule, path=0, turn=None, arms=ARMS, rules=shapes.PLAIN, other=None):
    """The pair's leagues on one path under ``rule``, by arm, and every call of
    ``run.draft_boards`` made for them: its arguments and the boards it gave. ``other`` is arm
    B's forecaster's projection (the mirrored one by default)."""
    lines, members, scheduled, projection, table, mirrored = season
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
            {"other": mirrored if other is None else other},
            SEED,
            path,
            shapes.FIXED,
            turn,
            rules,
        )
    return setups, calls


def seat_of(path: int, turn: int | None = None) -> int:
    return IDS[(path if turn is None else turn) % shapes.FIXED.teams]


def rival_boards(calls, path: int) -> dict[int, list[int]]:
    """Every seat's board as a rival's on the path, from a draft's arguments."""
    draft, draftable, value = calls[0][0][:3]
    return {
        t: adp.rival_board(
            draft.picks,
            draftable,
            value,
            draft.spread,
            world.rng(SEED, path, t, 0, world.STREAMS["draft"]),
        )
        for t in IDS
    }


@pytest.mark.parametrize("rules", [shapes.PLAIN, POINTS], ids=["categories", "points"])
def test_under_the_market_rule_the_seat_drafts_the_rival_s_board_less_whom_it_cannot_value(
    season, rules
):
    """The arm's seat's board is ``adp.rival_board`` for its team on the path's own draw
    (``world.rng(seed, path, team, 0, draft)``) less the players its own forecaster has no value
    for, in the rival's order; every other seat's is the rival's board whole. In a categories
    league and in a points league."""
    projection, table = season[3], season[4]
    setups, calls = leagues(season, adp.MARKET_DRAFT, path=4, rules=rules, arms=SAME)
    ((args, boards),) = calls  # one draft for the pair
    draft, draftable, players, cats, points = args[0], args[1], args[4], args[5], args[6]
    me = seat_of(4)
    assert (draft.picks, draft.spread, draft.seed, draft.path) == (table.picks, SPREAD, SEED, 4)
    assert set(draft.seats) == {me} and draft.rule == adp.MARKET_DRAFT
    assert (points is not None) == (rules.scoring == "points") == (setups["a"].scoring == "points")
    mine = wk.per_game_values(
        {k: projection[k] for k in projection if k in players}, tuple(cats), points
    )
    rival = rival_boards(calls, 4)
    assert all(boards[t] == rival[t] for t in IDS if t != me)
    assert boards[me] == [k for k in rival[me] if k in mine]
    # Not vacuous: the table lists players the seat's forecaster has no line for, the seat's
    # board is the rival's without them, and it is not the seat's own forecaster's order.
    passed = [k for k in rival[me] if k not in mine]
    assert passed and all(k in table.picks for k in passed)
    assert boards[me] != adp.seat_board(mine, draftable)
    # The seat holds nobody it cannot value; rivals on the same path do.
    rosters = setups["a"].rosters
    assert all(k in mine for k, _ in rosters[me])
    assert any(k not in mine for t in IDS if t != me for k, _ in rosters[t])


def test_the_draw_does_not_move_with_who_is_passed_and_the_board_follows_the_path(season):
    """The seat's board is its seat's and the path's: the same path gives it again, another
    path another, and a pair sitting in another seat (another turn) changes no rival's board:
    the draw is taken over every listed player, passed or not."""
    _, one = leagues(season, adp.MARKET_DRAFT, path=2, arms=SAME)
    _, again = leagues(season, adp.MARKET_DRAFT, path=2, arms=SAME)
    _, moved = leagues(season, adp.MARKET_DRAFT, path=2, turn=7, arms=SAME)
    _, later = leagues(season, adp.MARKET_DRAFT, path=3, arms=SAME)
    me, there = seat_of(2), seat_of(2, 7)
    assert there != me and one[0][1] == again[0][1]
    assert one[0][1][me] != later[0][1][me]
    rival = rival_boards(one, 2)
    assert all(moved[0][1][t] == rival[t] for t in IDS if t != there)
    assert set(moved[0][1][there]) < set(rival[there])


def test_a_pair_on_two_beliefs_shares_a_league_where_the_two_drafts_come_out_the_same(season):
    """Under ``market`` two arms on one forecaster share one league, as ever. Two arms on two
    forecasters each draft: when both pass on the same players the two drafts are one league and
    the pair shares it (the same object); when arm B's forecaster has no line for a player arm
    A's seat drafted, the seat passes on him in B's league and the pair drafts apart, among the
    same rivals' boards. Under ``own`` two forecasters always draft apart, as before."""
    projection, mirrored = season[3], season[5]
    same, calls = leagues(season, adp.MARKET_DRAFT, path=1, arms=SAME)
    assert same["a"] is same["b"] and len(calls) == 1
    # The mirrored forecaster values the same players another way: it passes on the same ones.
    assert set(mirrored) == set(projection)
    both, calls = leagues(season, adp.MARKET_DRAFT, path=1)
    assert both["a"] is both["b"] and len(calls) == 2
    assert both["a"].rosters == same["a"].rosters
    me = seat_of(1)
    first = same["a"].rosters[me][0][0]
    fewer = {k: v for k, v in mirrored.items() if k != first}
    apart, calls = leagues(season, adp.MARKET_DRAFT, path=1, other=fewer)
    assert apart["a"] is not apart["b"] and len(calls) == 2
    assert apart["a"].rosters == same["a"].rosters
    assert all(k != first for k, _ in apart["b"].rosters[me])
    (_, boards_a), (_, boards_b) = calls
    assert all(boards_a[t] == boards_b[t] for t in IDS if t != me)
    # A player the seat never reaches (the first pick of the draft, a rival's): arm B's
    # forecaster has no line for him, its board differs, and the two drafts are one league.
    assert me != IDS[0]
    gone = same["a"].rosters[IDS[0]][0][0]
    unreached, calls = leagues(
        season, adp.MARKET_DRAFT, path=1, other={k: v for k, v in mirrored.items() if k != gone}
    )
    (_, boards_a), (_, boards_b) = calls
    assert boards_a[me] != boards_b[me] and gone in boards_a[me] and gone not in boards_b[me]
    assert unreached["a"] is unreached["b"] and unreached["a"].rosters == same["a"].rosters
    own, calls = leagues(season, adp.OWN_DRAFT, path=1)
    assert own["a"] is not own["b"] and len(calls) == 2
    assert own["a"].rosters[me] != own["b"].rosters[me]
    own, calls = leagues(season, adp.OWN_DRAFT, path=1, arms=SAME)
    assert own["a"] is own["b"] and len(calls) == 1


def test_the_rule_changes_whom_the_seat_drafts_and_no_rival_s_board(season):
    """The lever does something: on one path the seat's roster under ``market`` is not its
    roster under ``own``, while every rival drafts on the same board under both rules. Under
    ``own`` the seat takes its own forecaster's best left; under ``market`` it follows the
    table, so its picks stand lower on its own forecaster's board."""
    projection = season[3]
    market, m_calls = leagues(season, adp.MARKET_DRAFT, path=5, arms=SAME)
    own, o_calls = leagues(season, adp.OWN_DRAFT, path=5, arms=SAME)
    me = seat_of(5)
    mine, theirs = market["a"].rosters[me], own["a"].rosters[me]
    assert {k for k, _ in mine} != {k for k, _ in theirs}
    (m_args, m_boards), (o_args, o_boards) = m_calls[0], o_calls[0]
    assert set(m_args[0].seats) == set(o_args[0].seats) == {me}
    assert (m_args[0].rule, o_args[0].rule) == (adp.MARKET_DRAFT, adp.OWN_DRAFT)
    assert all(m_boards[t] == o_boards[t] for t in IDS if t != me)
    assert m_boards[me] != o_boards[me] and set(m_boards[me]) == set(o_boards[me])
    # The seat's own forecaster's order: its own draft's picks stand higher on it.
    value = wk.per_game_values({k: projection[k] for k in projection}, market["a"].cats, None)
    rank = {k: i for i, k in enumerate(sorted(value, key=lambda k: (-value[k], k)))}
    assert sum(rank[k] for k, _ in theirs) < sum(rank[k] for k, _ in mine)


def test_a_room_s_seats_each_draft_as_a_rival_less_whom_their_own_arm_cannot_value(season):
    """A room: every seat holds an arm and is named with its arm's forecaster's projection,
    under either rule. Under ``market`` each drafts the rival's board in its seat less the
    players its own arm cannot value, so no roster holds a player without a line, where a room
    of rivals on the same path holds some; under ``own`` each drafts on its arm's own board."""
    lines, members, scheduled, projection, table, other = season
    arms = {"R": SimpleNamespace(forecaster=None), "S": SimpleNamespace(forecaster="other")}
    args = (arms, ("R", "S"), "prior", projection, {"other": other}, SEED, 6)
    draft = ss.room_draft((table.picks, SPREAD, adp.MARKET_DRAFT), *args)
    named = ss.room_draft((table.picks, SPREAD, adp.OWN_DRAFT), *args)
    assert (draft.rule, named.rule) == (adp.MARKET_DRAFT, adp.OWN_DRAFT)
    assert sorted(draft.seats) == sorted(named.seats) == list(IDS)
    assert all(draft.seats[t] is named.seats[t] for t in IDS) and draft.path == named.path == 6
    assert named == adp.Draft(table.picks, SPREAD, SEED, 6, named.seats)
    assert ss.room_draft(None, *args) is None

    def league(d):
        return ss.replay_setup_of(2024, lines, members, scheduled, projection, d)

    setup, apart, rivals = (
        league(draft),
        league(named),
        league(adp.Draft(table.picks, SPREAD, SEED, 6)),
    )
    assert all(k in projection for r in setup.rosters.values() for k, _ in r)
    assert any(k not in projection for r in rivals.rosters.values() for k, _ in r)
    assert setup.rosters != apart.rosters and setup.rosters != rivals.rosters


def test_the_rules_are_two_and_the_market_s_is_the_default():
    assert adp.SEAT_DRAFTS == ("market", "own")
    table = SimpleNamespace(adp="espn", seat_draft=None)
    assert ss.seat_draft_of(table) == "market"
    assert ss.seat_draft_of(SimpleNamespace(adp="espn", seat_draft="own")) == "own"
    assert ss.seat_draft_of(SimpleNamespace(adp="none", seat_draft=None)) is None
    for texts in (ss.ADP_SEAT, ss.ADP_LIMIT, ss.ADP_SHARED, ss.ADP_DRAFT):
        assert set(texts) == set(adp.SEAT_DRAFTS)
    # A draft that names its seats and no rule is the rule before the PR.
    assert adp.Draft({}, SPREAD, 1, 0, {1: {}}).rule == adp.OWN_DRAFT
    with pytest.raises(ValueError, match="one of market, own, not 'rival'"):
        adp.Draft({}, SPREAD, 1, 0, rule="rival")
    assert adp.market_seat_board([5, 2, 9, 4], {4: 1.0, 5: 0.0}) == [5, 4]


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
    assert "less the players they cannot value (--seat-draft market)" in out
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
