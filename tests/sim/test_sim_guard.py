"""The season guard as an arm's choice, and the weight that reads the week's stake (#172, the
guard PR): an arm's ``guard`` (``block``, live's, or ``off``) and its ``stake`` (0 to 1), how
they are parsed and refused, the allowed set a tier's searches take, the season figure a stake
splits at the running week's last day, the stake the runner sets once a week, the counts, the
record, Rule 1, no peek and every league kind once. The pure stake is ``test_sim_stake.py``'s;
the screen's two rows are held by ``test_sim_screen.py``'s list tests and the ones at the end
here.

Made-up leagues, fixed seeds. A test whose seat weighs runs in both head-to-head formats, or
says why it names one."""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import nopeek, policy, shapes
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim import stake as stk
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, mv, wk
from pickandroll.sim.shapes import CONTINUOUS
from pickandroll.sim.state import Member, initial
from tests.sim.sim_league import (
    KNOBS,
    NINE,
    arm,
    make_data_dir,
    make_setup,
    of_format,
    rates,
    replay_of,
)
from tests.sim.test_no_peek import DAYS, SEED, WEIGHTS, recorded
from tests.sim.test_sim_knobs import points_setup
from tests.sim.test_sim_split import SOURCES, fixed_of, second_of

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
FORMATS = (ONE_WIN, EACH_CATEGORY)
#: The count keys the two fields bring, in the payload's order.
SEASON_KEYS = tuple(m for group in ct.SEASON.values() for m in group)
#: The made-up players of :func:`disagreeing`.
SOON, LATE, DEAD = 101, 102, 103


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


def spec(name="A", tier="surrogate", opponents="static", knobs=None, **more) -> dict:
    return {
        "name": name,
        "tier": tier,
        "knobs": {**KNOBS, **(knobs or {})},
        "opponents": {"kind": opponents},
        **more,
    }


def armed(name="A", tier="surrogate", opponents="static", knobs=None, **more) -> rn.Arm:
    return rn.arm_of(spec(name, tier, opponents, knobs, **more))


def disagreeing(teams: int = 2, holds: int = DEAD, h2h: str = ONE_WIN):
    """A league where the three weeks and the season disagree (after ``test_sim_knobs``'s flip
    league, with ``teams`` seats, the top two in a one-week final after five regular weeks):
    free agent ``SOON`` is a modest player whose team plays every day of weeks 2 to 4 (the
    three weeks' horizon on day one) and never after; ``LATE`` is a far better one whose team
    plays only in weeks 5 and 6. Seat 1's six slots are full, and ``holds`` is who sits in the
    last.

    ``DEAD``: a near-empty line whose team never plays, beside the seat's five drafted players,
    with ``LATE`` a free agent; over the three weeks the seat takes ``SOON`` for him, over the
    season ``LATE``. ``LATE``: the seat drafted six and holds the late player in the last's
    place; ``SOON`` comes in for one of the seat's players, a swap that gains over the three
    weeks and loses the rest of the season: the set the season guard refuses."""
    base = make_setup(
        teams=teams, spots=6 if holds == LATE else 5, pool=0, weeks=6, playoff_teams=2
    )
    weeks = base.calendar.weeks
    schedule = {d: set(t) for d, t in base.schedule.items()}
    for w in weeks[1:4]:
        for d in w.days():
            schedule[d].add("WWW")
    for w in weeks[4:6]:
        for d in w.days():
            schedule[d].add("SSS")
    players = {
        **base.players,
        SOON: Member(SOON, "Soon", "WWW", ("PG",)),
        LATE: Member(LATE, "Late", "SSS", ("PG",)),
    }
    projection = {**base.projection, SOON: rates(0.7), LATE: rates(2.5)}
    mine = list(base.rosters[1])
    slot = mine[-1][1]
    if holds == DEAD:
        players[DEAD] = Member(DEAD, "Dead", "ZZZ", ("PG",))
        projection[DEAD] = {s: 0.05 * x for s, x in rates(0.1).items()}
        mine.append((DEAD, slot))
        pool: tuple[int, ...] = (SOON, LATE)
    else:
        pool = (SOON, mine[-1][0])
        mine[-1] = (LATE, slot)
    setup = replace(
        base,
        players=players,
        projection=projection,
        schedule={d: frozenset(t) for d, t in schedule.items()},
        rosters={**base.rosters, 1: tuple(mine)},
        pool=pool,
        market=wk.per_game_values(projection, NINE, None),
    )
    return of_format(setup, h2h)


def built_of(setup, **knobs) -> policy.Built:
    """Seat 1's problem on day one, on the projection."""
    built = policy.problem_of(
        setup, initial(setup), 1, {**KNOBS, **knobs}, setup.projection, {}, {}
    )
    assert built is not None
    return built


def adds(decision: policy.Decision) -> set[int]:
    return {m.add for m in decision.moves}


def drops(decision: policy.Decision) -> set[int | None]:
    return {m.drop for m in decision.moves}


# --------------------------------------------------------------------------- the two fields
def test_an_arm_names_its_guard_and_its_stake_or_holds_the_defaults():
    plain = armed()
    assert (plain.guard, plain.stake, plain.named) == ("block", 0.0, ())
    assert plain.season_payload() == {}
    named = armed(knobs={"season_weight": 0.4}, guard="off", stake=0.5)
    assert (named.guard, named.stake, named.named) == ("off", 0.5, ("guard", "stake"))
    assert named.season_payload() == {"guard": "off", "stake": 0.5}
    assert (named.seat().guard, named.seat().stake) == ("off", 0.5)
    # An arm that names the defaults is the seat of one that names nothing; its payload still
    # says what it named.
    same = armed(guard="block", stake=0)
    assert same.named == policy.SEASON_FIELDS == ("guard", "stake")
    assert same.season_payload() == {"guard": "block", "stake": 0.0}
    assert same.seat() == plain.seat() and repr(same.seat()) == repr(plain.seat())
    assert armed(stake=0).season_payload() == {"stake": 0.0}
    assert armed(guard=None, stake=None).named == ()
    # The two are keys of an arm's spec, and neither is one of the four fields or a knob.
    assert set(policy.SEASON_FIELDS) <= set(rn.SPEC_KEYS)
    assert not set(policy.SEASON_FIELDS) & {*policy.FIELDS, *policy.KNOBS}
    assert policy.GUARDS == ("block", "off") and policy.GUARDED_TIERS == ("exact", "surrogate")


@pytest.mark.parametrize(
    ("more", "words"),
    [
        ({"guard": "maybe"}, "guard 'maybe': one of block, off"),
        (
            {"tier": "ranking", "guard": "off"},
            "guard 'off' named on tier 'ranking': the ranking tier has no season guard",
        ),
        (
            {"tier": "static", "guard": "block"},
            "guard 'block' named on tier 'static': a static seat has no season guard",
        ),
        ({"stake": 1.5}, "stake 1.5: a number from 0 to 1"),
        ({"stake": -0.1}, "stake -0.1: a number from 0 to 1"),
        ({"stake": "0.5"}, "stake '0.5': a number from 0 to 1"),
        ({"stake": True}, "stake True: a number from 0 to 1"),
        ({"stake": float("nan")}, "stake nan: a number from 0 to 1"),
        ({"stake": 0.5}, "stake 0.5 with season_weight 0: the stake scales the season term"),
    ],
)
def test_a_field_out_of_its_choices_or_with_nothing_to_act_on_is_refused_by_name(more, words):
    with pytest.raises(ValueError, match=re.escape(words)):
        rn.arm_of(spec(**more))


def test_a_stake_in_a_league_whose_bracket_is_not_read_is_refused_before_any_day():
    """The cut line and the bracket's weeks are not trusted there: the plan refuses the arm by
    name, the runner refuses its seat before a day is played, and a seat asked to decide says
    the same."""
    staked = armed(knobs={"season_weight": 0.4}, stake=0.5)
    unread = policy.Shape(bracket=False)
    assert rn.stake_refused(staked, [policy.Shape(), unread]) == (
        "arm A names stake 0.5: a stake reads the cut line and the bracket's weeks, and the "
        "league's bracket is not read, so it is not trusted"
    )
    assert rn.stake_refused(staked, [policy.Shape()]) is None
    assert rn.stake_refused(armed(guard="off"), [unread]) is None
    # By the field, on any tier: a ranking arm and a static one read no stake (their reads
    # rows say so) and are refused there the same, as a stake with no season weight is.
    for tier in ("ranking", "static"):
        unreading = armed("U", tier, knobs={"season_weight": 0.4}, stake=0.5)
        assert policy.season_reads(unreading, unread)["stake"] != policy.READ
        assert rn.stake_refused(unreading, [unread]).startswith("arm U names stake 0.5: a stake")
        assert rn.stake_refused(unreading, [policy.Shape()]) is None
    setup = make_setup(bracket=False)
    assert setup.spec is None and policy.shape_of(setup) == unread
    days: list = []
    why = "names stake 0.5: a stake reads the cut line and the bracket's weeks, and this league"
    with pytest.raises(ValueError, match=why) as e:
        rn.paired(setup, replay_of(setup, 2, 0), armed(), staked, 1, on_day=days.append)
    assert "the settings page has not been read" in str(e.value) and not days
    ranked = armed("B", "ranking", knobs={"season_weight": 0.4}, stake=0.5)
    with pytest.raises(ValueError, match=why):
        rn.paired(setup, replay_of(setup, 2, 0), armed(), ranked, 1, on_day=days.append)
    assert not days
    built = built_of(setup, season_weight=0.4)
    with pytest.raises(ValueError, match="the bracket is not trusted"):
        policy.guarded(built, setup, initial(setup), stake=0.5)
    # The guard reads no bracket: off plays there.
    assert policy.guarded(built, setup, initial(setup), policy.OFF).guard == policy.OFF


def test_arms_that_differ_only_on_a_field_neither_reads_are_refused_as_for_knobs():
    weight = {"season_weight": 0.3}
    shape = policy.Shape()
    a, b = armed("A", "ranking", knobs=weight), armed("B", "ranking", knobs=weight, stake=0.5)
    why = (
        "stake (the ranking tier ranks by value times games and holds no odds; read by a "
        "season_weight above 0 on the exact or the surrogate tier, in a league whose bracket is "
        "read)"
    )
    assert rn.same_seat(a, b, [shape]) == [why]
    assert ss.same_seats({"a": a, "b": b}, [shape], rivals=True).startswith(
        "arms a and b are the same seat: they differ only in stake (the ranking tier"
    )
    # Read where a tier reads it: the pair is two seats.
    for tier in policy.GUARDED_TIERS:
        a, b = armed("A", tier, knobs=weight), armed("B", tier, knobs=weight, stake=0.5)
        assert rn.same_seat(a, b, [shape]) is None
        assert rn.same_seat(armed("A", tier), armed("B", tier, guard="off"), [shape]) is None
        # Naming the defaults is no difference at all: the same arm twice, which a run may
        # play to check that the difference is zero.
        named = armed("B", tier, guard="block", stake=0)
        assert rn.same_seat(armed("A", tier), named, [shape]) is None


def test_the_reads_table_s_rows_for_the_two_fields():
    one, unread = policy.Shape(), policy.Shape(bracket=False)
    weighted = {"season_weight": 0.3}
    for tier in policy.GUARDED_TIERS:
        assert policy.season_reads(armed(tier=tier, knobs=weighted), one) == {
            "guard": policy.READ,
            "stake": policy.READ,
        }
        assert policy.season_reads(armed(tier=tier), one) == {
            "guard": policy.READ,
            "stake": "season_weight is 0: there is no season term to scale",
        }
        assert policy.season_reads(armed(tier=tier, knobs=weighted), unread) == {
            "guard": policy.READ,
            "stake": "the league has no bracket read",
        }
    assert policy.season_reads(armed(tier="ranking", knobs=weighted), one) == {
        "guard": "the ranking tier searches no set, so no season guard blocks one",
        "stake": "the ranking tier ranks by value times games and holds no odds",
    }
    assert policy.season_reads(armed(tier="static"), one) == {
        "guard": policy.STATIC,
        "stake": policy.STATIC,
    }
    # The record's table carries a field's row only for an arm that names it.
    named = armed("B", knobs=weighted, guard="off", stake=1)
    table = ss.reads_of({"a": armed(knobs=weighted), "b": named}, [one], rivals=True)
    assert list(table["a"][one.label()]["fields"]) == list(policy.FIELDS)
    assert list(table["b"][one.label()]["fields"]) == [*policy.FIELDS, *policy.SEASON_FIELDS]
    assert table["b"][one.label()]["fields"]["stake"] == policy.READ
    only = ss.reads_of({"a": armed(guard="off")}, [one], rivals=True)
    assert list(only["a"][one.label()]["fields"]) == [*policy.FIELDS, "guard"]


# --------------------------------------------------------------------------- the block and off
def test_a_seat_at_the_defaults_decides_on_the_problem_as_it_was_built():
    """Rule 1 where a seat decides: with neither field the problem is the one built, the allowed
    set is the season guard and the term is the season figure itself at the knob's weight."""
    setup = disagreeing()
    state = initial(setup)
    built = built_of(setup, season_weight=0.37)
    assert (built.guard, built.stake, built.level) == (policy.BLOCK, 0.0, 0.0)
    assert policy.guarded(built, setup, state) is built
    assert policy.guarded(built, setup, state, policy.BLOCK, 0.0) is built
    assert policy.later_share(built) == 1.0
    # Rule 1 to the bit: with no stake whatever the week's stake, and at a stake in a week
    # whose stake is 0, the term reads the season figure as it was, on the path it had: the
    # one class, never the split one at a share of 1.
    ev = mv.Evaluator(built.problem)
    for same in (built, replace(built, level=1.0), replace(built, stake=1.0)):
        assert type(policy.season_figure_of(same)) is policy.SeasonFigure
        term = policy.seasoned(same, ev, policy.QUEUE_SET)
        assert type(term.figure) is policy.SeasonFigure and term.weight == 0.37
    assert policy.allowed_of(built) is not None
    assert policy.allowed_of(replace(built, guard=policy.OFF)) is None
    with pytest.raises(ValueError, match="guard 'maybe': one of block, off"):
        policy.guarded(built, setup, state, "maybe")


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_the_block_refuses_the_three_weeks_best_set_and_off_queues_it(tier, h2h):
    setup = disagreeing(holds=LATE, h2h=h2h)
    state = initial(setup)
    built = built_of(setup)
    guard = policy.guard_of(built)
    ev = mv.Evaluator(built.problem)
    block = policy.decide(built, tier, with_plan=False)
    off = policy.decide(policy.guarded(built, setup, state, policy.OFF), tier, with_plan=False)
    # Off: the player of the three weeks comes in for one of the seat's, a set the season guard
    # refuses (its rest of the season is below 0), and the decision says so.
    figure = policy.SeasonFigure(built, 1.0)
    assert SOON in adds(off) and None not in drops(off)
    assert not guard(off.moves) and off.past_guard and figure.of(off.moves) < 0
    # The block: an allowed set, worth less over the three weeks.
    assert block.moves != off.moves and guard(block.moves) and not block.past_guard
    assert ev.value(policy.QUEUE_SET, off.moves) > ev.value(policy.QUEUE_SET, block.moves)
    # What holds a set back under off is the season term: at a season weight where the term
    # outweighs that set's gain ten times, the seat decides no set that loses the season.
    weight = 10 * ev.gain(policy.QUEUE_SET, off.moves) / -figure.of(off.moves)
    heavy = policy.guarded(built_of(setup, season_weight=weight), setup, state, policy.OFF)
    kept = policy.decide(heavy, tier, with_plan=False)
    assert kept.moves != off.moves and figure.of(kept.moves) >= 0


def policy_calls(monkeypatch) -> list[tuple[str, object]]:
    """Every search the policy asks of the engine from here on, with the allowed set it hands
    over: ``moves.search``, ``moves.recommend`` and ``stream.plan`` as ``sim/policy.py`` calls
    them (the engine's own calls of one another are not kept)."""
    seen: list[tuple[str, object]] = []
    for module, name in ((policy.mv, "search"), (policy.mv, "recommend"), (policy.st, "plan")):
        real = getattr(module, name)
        signature = inspect.signature(real)

        def spy(*a, _real=real, _sig=signature, _name=name, **k):
            if sys._getframe(1).f_code.co_filename.endswith("sim/policy.py"):
                seen.append((_name, _sig.bind(*a, **k).arguments.get("allowed")))
            return _real(*a, **k)

        monkeypatch.setattr(module, name, spy)
    return seen


@pytest.mark.parametrize("h2h", FORMATS)
def test_under_off_no_search_of_a_tier_is_handed_an_allowed_set(h2h, monkeypatch):
    """The exact tier's four searches (the recommended set or the weighted one, the week's set
    and the week's plan) and the surrogate's one: each takes the season guard under the block
    and nothing under off."""
    setup = disagreeing(holds=LATE, h2h=h2h)
    built = built_of(setup, plan_floor_cats=0.1)
    off = policy.guarded(built, setup, initial(setup), policy.OFF)
    seen = policy_calls(monkeypatch)
    runs = {
        ("recommend", "search", "plan"): lambda b: policy.exact(b),
        ("search", "search", "plan"): lambda b: policy.exact(b, executes=policy.WEIGHTED),
        ("search",): lambda b: policy.surrogate(b),
    }
    for names, run in runs.items():
        for b, none in ((built, False), (off, True)):
            seen.clear()
            run(b)
            assert tuple(n for n, _ in seen) == names
            assert all((allowed is None) is none for _, allowed in seen), (names, none)


def test_a_mirror_rival_stays_on_the_block_and_reads_no_stake(monkeypatch):
    """One format: the mirror is the surrogate on the arm's knobs, and what is asked is what
    its problem carries, not what it weighs."""
    setup = disagreeing(teams=4, holds=LATE)
    a = armed(opponents="mirror", knobs={"season_weight": 0.5}, guard="off", stake=1)
    rival = rn.opponents_of(setup, a, 1)[2]
    assert isinstance(rival, op.Mirror) and rival.knobs["season_weight"] == 0.5
    seen: list[tuple] = []
    real = policy.allowed_of

    def spy(built):
        seen.append((built.team, built.guard, built.stake, built.level))
        return real(built)

    monkeypatch.setattr(policy, "allowed_of", spy)
    state = replace(initial(setup), stakes={1: 0.4, 2: 0.9})
    rival.decide(setup, state, 2, setup.projection, {}, {}, None)
    a.seat().decide(setup, state, 1, setup.projection, {}, {}, None)
    assert seen == [(2, policy.BLOCK, 0.0, 0.0), (1, policy.OFF, 1.0, 0.4)]


# --------------------------------------------------------------------------- the stake in force
def by_hand(built: policy.Built, move: mv.Move, share: float, playoff: float = 1.0) -> float:
    """A move's season figure split by hand (nobody away): each player's season value above a
    dead spot times his team's games from the day the move counts to the running week's last
    day, plus ``share`` times his games after it, a bracket day's game counted ``playoff``
    times in both parts; the add's less the drop's."""
    p = built.problem
    day = mv.day_of(p, move)
    players = {**dict(p.candidates), **dict(p.roster)}

    def worth(key: int) -> float:
        team = players[key].nba_team
        days = [d for d, teams in p.schedule.items() if team in teams and day <= d <= p.season_end]
        games = {d: playoff if d in built.bracket else 1.0 for d in days}
        this = sum(g for d, g in games.items() if d <= built.week.end)
        return (p.season_value[key] - p.dead) * (this + share * (sum(games.values()) - this))

    return worth(move.add) - (0.0 if move.drop is None else worth(move.drop))


def test_a_stake_splits_the_season_figure_at_the_running_week_s_last_day():
    """The rule: ``season_weight x (this week's part + (1 - stake x L) x the rest)``. A move's
    figure in a week that has a stake counts its games from its landing to the running week's
    last day in full and its games after ``1 - stake x L`` times. One format: the figure is a
    value times games and weighs nothing by format."""
    setup = disagreeing(teams=4)
    state = initial(setup)
    built = built_of(setup, season_weight=1.0)
    whole = policy.SeasonFigure(built, 1.0)
    mine = [k for k, _ in built.problem.roster if k != DEAD]
    moves = [
        mv.Move(LATE, DEAD),
        mv.Move(SOON, DEAD),
        mv.Move(SOON, mine[0]),
        mv.Move(LATE, mine[-1]),
    ]
    week = built.week
    assert week.number == 1 and all(mv.day_of(built.problem, m) <= week.end for m in moves)
    for stake, level in ((1.0, 1.0), (0.5, 1.0), (1.0, 0.25)):
        staked = policy.guarded(built, setup, replace(state, stakes={1: level}), stake=stake)
        share = policy.later_share(staked)
        assert share == 1 - stake * level
        figure = policy.season_figure_of(staked)
        assert type(figure) is policy.StakedFigure
        assert (figure.share, figure.later) == (share, week.end + timedelta(1))
        for m in moves:
            assert figure.move(m) == pytest.approx(by_hand(built, m, share), abs=1e-9)
        # The split is of the figure as it was: at a share of 1 the two parts are the whole.
        assert all(whole.move(m) == pytest.approx(by_hand(built, m, 1.0), abs=1e-9) for m in moves)
        # A player whose games are all after this week keeps only his share of the term; one of
        # the seat's, who plays this week, keeps this week's games in full beside it.
        assert figure.move(moves[0]) == pytest.approx(share * whole.move(moves[0]), abs=1e-9)
        kept = by_hand(built, moves[2], 0.0)
        assert kept < 0 and figure.move(moves[2]) == pytest.approx(
            kept + share * (whole.move(moves[2]) - kept), abs=1e-9
        )
    # A set's figure is its moves' summed, as the figure's it splits (here at a share of 0.75).
    assert figure.of(moves[:2]) == figure.move(moves[0]) + figure.move(moves[1]) > 0
    # A bracket day counts playoff_weight times in both parts, as in the figure it splits: on
    # the last regular week's Monday at a playoff weight of 2 the late player's games that week
    # count once each and the final's twice, times the share.
    last = setup.calendar.weeks[4]
    heavy, at = on_day(setup, last.start, {"playoff_weight": 2.0}, stakes={1: 0.5})
    figure = policy.season_figure_of(policy.guarded(heavy, setup, at, stake=1.0))
    assert (figure.playoff_weight, figure.share) == (2.0, 0.5)
    for m in (mv.Move(LATE, DEAD), mv.Move(LATE, mine[0])):
        assert figure.move(m) == pytest.approx(by_hand(heavy, m, 0.5, playoff=2.0), abs=1e-9)
        assert figure.move(m) != pytest.approx(by_hand(heavy, m, 0.5), abs=1e-9)


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_a_decisive_week_takes_the_term_off_the_later_season_and_turns_the_choice(tier, h2h):
    """At a season weight the seat adds the late player, whose games are all after the three
    weeks. With a stake of 1 in a week whose stake is 1 the games after the running week count
    nothing: a player whose value is all after this week has lost his season term, and the seat
    adds the one who plays the three weeks, as an arm with no season weight does. The running
    week's games still count: he comes in for the spot that plays nothing, not for a player
    who plays this week. In a week whose stake is 0 nothing changes."""
    setup = disagreeing(h2h=h2h)
    state = initial(setup)
    built = built_of(setup, season_weight=1.0)
    plain = policy.decide(built_of(setup), tier, with_plan=False)
    full = policy.decide(built, tier, with_plan=False)
    assert LATE in adds(full) and LATE not in adds(plain) and SOON in adds(plain)
    decisive = policy.guarded(built, setup, replace(state, stakes={1: 1.0}), stake=1.0)
    assert (decisive.guard, decisive.stake, decisive.level) == (policy.BLOCK, 1.0, 1.0)
    assert policy.later_share(decisive) == 0.0
    late = mv.Move(LATE, DEAD)
    assert policy.SeasonFigure(built, 1.0).move(late) > 0
    assert policy.season_figure_of(decisive).move(late) == 0.0
    got = policy.decide(decisive, tier, with_plan=False)
    assert adds(got) == adds(plain) == {SOON} and drops(got) == {DEAD}
    idle = policy.guarded(built, setup, replace(state, stakes={1: 0.0}), stake=1.0)
    assert policy.later_share(idle) == 1.0
    assert type(policy.season_figure_of(idle)) is policy.SeasonFigure
    assert policy.decide(idle, tier, with_plan=False).moves == full.moves
    # In between the share is 1 - stake x L, and the term is built on it at the knob's weight.
    half = policy.guarded(built, setup, replace(state, stakes={1: 0.25}), stake=0.5)
    assert policy.later_share(half) == 1 - 0.5 * 0.25 == 0.875
    ev = mv.Evaluator(half.problem)
    term = policy.seasoned(half, ev, policy.QUEUE_SET)
    assert isinstance(term, policy.Seasoned) and term.weight == 1.0
    assert type(term.figure) is policy.StakedFigure and term.figure.share == 0.875
    # At a share of 0 the term is still built: the running week's games count.
    last = policy.seasoned(decisive, ev, policy.QUEUE_SET)
    assert isinstance(last, policy.Seasoned) and last.figure.share == 0.0
    # The season scale is measured without the term and reads no stake: the same in a decisive
    # week, where the split figure of the swap it is measured on is 0.
    scale = policy.scale_of(built, tier)
    assert scale.ratio is not None and policy.scale_of(decisive, tier) == scale
    if tier == "exact":
        # The strategy route's weighted set takes the same term on its own key: the late player
        # goes with his term there too, and the player of the three weeks comes in for the spot
        # that plays nothing.
        whole, split = (
            policy.exact(b, executes=policy.WEIGHTED, with_plan=False) for b in (built, decisive)
        )
        assert LATE in adds(whole) and adds(split) == {SOON} and drops(split) == {DEAD}


def test_the_week_s_stake_is_the_runner_s_figure_or_the_same_function_of_the_finished_weeks():
    """One format: the stake reads the standings, which this day has none of."""
    setup = disagreeing(teams=4)
    state = initial(setup)
    built = built_of(setup, season_weight=1.0)
    own = stk.level(setup.spec, state.totals, 1, 1)
    assert own == stk.swing(0.0, 4) and 0 < own < 0.5
    assert policy.stake_of(setup, state, 1, 1) == own
    assert policy.guarded(built, setup, state, stake=1.0).level == own
    held = replace(state, stakes={1: 0.5, 2: 0.9})
    assert policy.guarded(built, setup, held, stake=1.0).level == 0.5
    # A seat that names the guard alone reads no stake.
    assert policy.guarded(built, setup, held, policy.OFF).level == 0.0


# --------------------------------------------------------------------------- the counts
def test_the_counts_carry_the_new_keys_only_on_the_seats_a_run_counts():
    setup = make_setup()
    state = initial(setup)
    assert not set(SEASON_KEYS) & set(ct.Tally(setup).rows(state)[1])
    assert ct.SEASON == {
        "guard": ("sets_past_guard",),
        "stake": ("stake_mean", "stake_weeks_above_half"),
    }
    tally = ct.Tally(setup, {1: ("guard", "stake"), 2: ("stake",), 3: ()})
    past = policy.Decision(past_guard=True)
    for week, levels in ((1, {1: 0.2, 2: 0.6}), (2, {1: 0.9, 2: 0.5}), (3, {1: 1.0, 2: 0.0})):
        for _ in range(2):  # two days a week: the week's stake is kept once
            for team in setup.teams:
                tally.decided(team, past if (team, week) != (1, 3) else policy.NONE)
            tally.day(week, replace(state, stakes=levels))
    rows = tally.rows(state)
    assert rows[1]["sets_past_guard"] == 4.0
    assert rows[1]["stake_mean"] == pytest.approx(0.7) and rows[1]["stake_weeks_above_half"] == 2.0
    assert "sets_past_guard" not in rows[2]
    assert rows[2]["stake_mean"] == pytest.approx(1.1 / 3)
    assert rows[2]["stake_weeks_above_half"] == 1.0  # a half is not above a half
    assert not set(SEASON_KEYS) & (set(rows[3]) | set(rows[4]))
    assert ct.metrics_in([rows[1], rows[4]])[-3:] == SEASON_KEYS
    assert ct.metrics_in([rows[4]]) == ct.metrics_in([ct.Tally(setup).rows(state)[1]])
    # A league whose bracket is not read holds no stake: the keys are there, with no figure.
    bare = ct.Tally(setup, {1: ("stake",)})
    bare.day(1, state)
    assert bare.rows(state)[1]["stake_mean"] is None
    assert bare.rows(state)[1]["stake_weeks_above_half"] is None


def test_a_run_counts_what_any_of_its_arms_names_on_its_arms_seats():
    plain, ranked = armed("P"), armed("R", "ranking")
    off = armed("O", guard="off")
    staked = armed("S", knobs={"season_weight": 0.3}, stake=1)
    assert rn.counted_of([plain, ranked]) == ()
    assert rn.counted_of([plain, off]) == ("guard",)
    assert rn.counted_of([staked, off, plain]) == ("guard", "stake")
    assert rn._counted([plain, ranked], {1: plain, 2: ranked}) == {}
    # Both arms' seats on a tier that reads the fields, not a ranking arm's.
    assert rn._counted([plain, off, ranked], {1: plain, 2: off, 3: ranked}) == {
        1: ("guard",),
        2: ("guard",),
    }
    assert ss.counts_note("none") is ss.COUNTS_NOTE and ss.counts_note("none", ()) is ss.COUNTS_NOTE
    both = ss.counts_note("faab", ("guard", "stake"))
    assert list(both)[-3:] == list(SEASON_KEYS)
    # The record says what the guard's count is not: how often the block would bind.
    assert "a lower bound on how often the block would have turned" in both["sets_past_guard"]
    assert {k: v for k, v in both.items() if k not in SEASON_KEYS} == ss.counts_note("faab")
    assert list(ss.counts_note("none", ("stake",)))[-2:] == list(ct.SEASON["stake"])


# --------------------------------------------------------------------------- the record's pieces
def test_the_payload_carries_an_arm_s_fields_only_when_it_names_them(tmp_path):
    plain = armed("A", knobs={"season_weight": 0.3})
    named = armed("B", knobs={"season_weight": 0.3}, guard="off", stake=1)
    p = ss.base_payload(
        "replay", "x", BUSINESS_HOURS, "sha", tmp_path / "fit.json", {}, 1, {"a": plain, "b": named}
    )
    assert p["fields"]["a"] == plain.fields.payload()
    assert p["fields"]["b"] == {**named.fields.payload(), "guard": "off", "stake": 1.0}
    assert list(p["fields"]["b"])[-2:] == ["guard", "stake"]
    assert p["surrogate"]["a"] == p["surrogate"]["b"]
    gate = ss.base_payload("validate", "x", BUSINESS_HOURS, "sha", tmp_path / "fit.json", {}, 1)
    assert gate["fields"] == {"gate": policy.Fields().payload()}


def test_the_season_scale_says_how_many_paths_its_ratio_rests_on():
    """A path whose seat has no swap with a season value has a row and no ratio: ``paths``
    counts the rows, ``paths_with_ratio`` the ratios the mean is over."""
    with_ratio = {"gain": 0.2, "ros": 4.0, "ratio": 0.05, "against": 0.0, "swaps": 3}
    without = {"gain": 0.1, "ros": None, "ratio": None, "against": None, "swaps": 1}
    none = {"gain": None, "ros": None, "ratio": None, "against": None, "swaps": 0}
    got = ss.scale_of([with_ratio, None, without, none])
    assert (got["paths"], got["paths_with_ratio"]) == (3, 1)
    assert got["ratio"] == 0.05 and got["gain"] == pytest.approx(0.15)
    assert list(got)[-2:] == ["paths", "paths_with_ratio"]
    empty = ss.scale_of([without, none])
    assert (empty["paths"], empty["paths_with_ratio"], empty["ratio"]) == (2, 0, None)
    assert ss.scale_of([None, None]) is None


def test_a_made_up_path_with_no_feasible_swap_has_a_scale_row_and_no_ratio():
    """One format: the row is made before the measure is read. A full league with nobody on
    the wire: the seat keeps its whole roster on day one, so there is no swap to measure."""
    setup = make_setup(teams=4, spots=6, pool=0)
    a = armed()
    row = rn.scale_on(setup, replay_of(setup, 2, 0), a, 1)
    assert row is not None and row["swaps"] == 0
    assert (row["ratio"], row["ros"]) == (None, None)
    wired = make_setup(teams=4, pool=8)
    other = rn.scale_on(wired, replay_of(wired, 2, 0), a, 1)
    assert other["ratio"] is not None and other["swaps"] > 0
    got = ss.scale_of([row, other])
    assert (got["paths"], got["paths_with_ratio"]) == (2, 1) and got["ratio"] == other["ratio"]


# --------------------------------------------------------------------------- Rule 1 in a season
@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_rule_1_the_defaults_named_play_the_seasons_of_an_arm_that_names_nothing(tier, h2h):
    """An arm that names ``guard: block`` and ``stake: 0`` plays the season of one that names
    neither: each solves its own days (two names share no solve), and their outcomes and counts
    are equal; the run counts the fields because an arm names them. On both tiers that read the
    fields, the exact one executing its week plan at a plan floor that takes every plan the
    stream draws (``test_sim_knobs.CASES`` says why below zero). A run of two arms that name
    nothing has no new key and the same season: compared on the surrogate, the cheaper pair
    (the counting is one code for both tiers)."""
    setup = of_format(make_setup(teams=4, pool=12), h2h)
    weight = {"season_weight": 0.05}
    more: dict = {}
    if tier == "exact":
        weight["plan_floor_cats"] = -1.0
        more["execute_plan"] = True
    plain = armed("A", tier, "market", weight, **more)
    named = armed("B", tier, "market", weight, guard="block", stake=0, **more)
    got = rn.paired(setup, replay_of(setup, 2, 0), plain, named, 1)
    assert got["a"] == got["b"] and set(got["delta"].values()) == {0.0}
    assert got["counts"]["a"] == got["counts"]["b"]
    assert got["solves_by_arm"][0] == got["solves_by_arm"][1] > 0
    assert got["counts"]["a"]["sets_past_guard"] == 0.0 and got["counts"]["a"]["landed"] > 0
    assert 0 < got["counts"]["a"]["stake_mean"] < 1
    assert not set(SEASON_KEYS) & set(got["counts"]["rivals"])
    if tier == "exact":
        return
    before = rn.paired(setup, replay_of(setup, 2, 0), plain, replace(plain, name="B"), 1)
    assert not set(SEASON_KEYS) & set(before["counts"]["a"])
    assert before["a"] == got["a"] and before["scale"] == got["scale"]
    assert before["counts"]["a"] == {
        k: v for k, v in got["counts"]["a"].items() if k not in SEASON_KEYS
    }
    assert before["counts"]["rivals"] == got["counts"]["rivals"]


def exact_digest(setup, seed: int = 1, path: int = 0) -> str:
    """SHA-256 of a made-up season's outcome on the exact tier (as
    ``test_sim_continuous.season_digest``, whose seats are a surrogate's and a ranking's): an
    exact seat in seat 1 that draws the week plan and executes it, at a plan floor away from 0,
    among market rivals at 0.3 a day; every seat's counts and summary, the last day's rosters
    and the solves, moves and breaches, each figure rounded to nine places."""
    e = replace(arm("E", "exact", "market", plan_floor_cats=0.1), execute_plan=True)
    w = replay_of(setup, seed, path)
    days: list = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, 1: e.seat()}
    (res,) = rn.simulate(setup, w, [variant], [True], on_day=lambda d: days.append(d.state))
    figures = rounded(
        {
            "counts": {str(t): row for t, row in res.counts.items()},
            "summaries": {str(t): s for t, s in res.summaries.items()},
            "rosters": {str(t): sorted(k for k, _ in ro) for t, ro in days[-1].rosters.items()},
            "moves": [res.solves, res.executed, res.gone, len(res.breaches)],
        }
    )
    return hashlib.sha256(json.dumps(figures, sort_keys=True, default=str).encode()).hexdigest()


def rounded(x):
    if isinstance(x, float):
        return round(x, 9)
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [rounded(v) for v in x]
    return x


#: Rule 1's pin for the exact tier: :func:`exact_digest` of the six-week made-up league of four
#: seats and twelve free agents (seed 1, path 0), in each format, as main gives it: ``88af1de``,
#: whose simulator is that of ``4b26577`` (H1's merge, the commit this PR was cut from)
#: (``~/sim-notes/vm/scratch/guard/rule1_exact.py 6 12``: the same digest, run on main and on
#: this PR). The surrogate's and the ranking tier's seasons are Fc's and Fd's pins
#: (``test_sim_continuous.py``, ``test_sim_rivals.py``), which hold unedited.
EXACT_MAIN = {
    ONE_WIN: "24579bc051c742af8936ee8f43c6edec0d33da553e5c5ae1c9d4e080ce40ab21",
    EACH_CATEGORY: "731bdc58ed38e35b9c877f23a6ca6b33bfcf21d28b1feb91c5a153b7f5d413e2",
}


@pytest.mark.parametrize("h2h", FORMATS)
def test_rule_1_an_exact_seat_that_names_neither_field_plays_as_on_main(h2h):
    setup = of_format(make_setup(teams=4, pool=12), h2h)
    assert exact_digest(setup) == EXACT_MAIN[h2h]


# --------------------------------------------------------------------------- the block in a season
@pytest.mark.parametrize("h2h", FORMATS)
def test_a_season_under_off_differs_from_the_block_s_and_counts_the_sets_past_the_guard(h2h):
    """The lever does something: in the league whose best three-week set the guard refuses, an
    arm with the guard off queues that set on day one and its season is another; the count
    says how often it decided a set the block would have refused, and is 0 for the arm on the
    block."""
    setup = disagreeing(holds=LATE, h2h=h2h)
    block, off = armed("A"), armed("B", guard="off")
    seen: dict[int, list[rn.DayRecord]] = {0: [], 1: []}
    got = rn.paired(
        setup, replay_of(setup, 2, 0), block, off, 1, on_day=lambda r: seen[r.variant].append(r)
    )
    assert got["breaches"] == []
    first = [seen[v][0].decisions[1] for v in (0, 1)]
    assert not first[0].past_guard and first[0].moves != first[1].moves
    assert SOON in adds(first[1]) and first[1].past_guard
    past = [sum(1 for r in seen[v] if r.decisions[1].past_guard) for v in (0, 1)]
    assert past[0] == 0 and past[1] >= 1
    assert got["counts"]["a"]["sets_past_guard"] == 0.0
    assert got["counts"]["b"]["sets_past_guard"] == float(past[1])
    assert not set(ct.SEASON["stake"]) & set(got["counts"]["a"])
    assert "sets_past_guard" not in got["counts"]["rivals"]
    # Another season: what the seat queued over it, and what landed.
    queued = [[r.queued.get(1, ()) for r in seen[v]] for v in (0, 1)]
    assert queued[0] != queued[1]
    landed = [[r.landed.get(1, ()) for r in seen[v]] for v in (0, 1)]
    assert landed[0] != landed[1]
    # A room of the two (every seat an arm's, no rival): both arms' seats are counted, and the
    # arm with the guard off, in seat 1 on this turn, decides past the guard there too.
    room = rn.room(setup, replay_of(setup, 2, 0), {"A": block, "B": off}, ["A", "B"], 1)
    assert room["seats"] == {"1": "B", "2": "A"} and room["breaches"] == []
    assert room["counts"]["B"]["sets_past_guard"] >= 1.0
    assert room["counts"]["A"]["sets_past_guard"] == 0.0
    assert not set(ct.SEASON["stake"]) & (set(room["counts"]["A"]) | set(room["counts"]["B"]))


# --------------------------------------------------------------------------- the stake in a season
#: The stake's season: a cap of two moves a day, so a set of two is queued whole on day one.
TWO_A_DAY = {"daily_cap": 2}


def day_one_adds(setup, w, weight: float) -> set[int]:
    """What the surrogate seat's day-one set adds at a season weight, on the world's beliefs."""
    status, returns = w.status_on(setup.start)
    knobs = {**KNOBS, **TWO_A_DAY, "season_weight": weight}
    built = policy.problem_of(
        setup, initial(setup), 1, knobs, w.beliefs_on(setup.start), status, returns
    )
    return adds(policy.decide(built, "surrogate"))


def turning_weight(setup, w) -> float:
    """A season weight at which the seat's day-one set adds the late player, within a tenth
    above one at which it does not: halved in from 0, where it does not, and 1, where it does."""
    lo, hi = 0.0, 1.0
    assert LATE not in day_one_adds(setup, w, lo) and LATE in day_one_adds(setup, w, hi)
    while hi - lo > 0.1 * hi:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if LATE in day_one_adds(setup, w, mid) else (mid, hi)
    return hi


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_season_in_which_the_stake_changes_what_the_seat_queues(h2h):
    """Four seats, two in the final: on day one every seat is level with the line with four
    regular weeks after this one, so the week's stake is the formula's at a lead of 0. The season
    weight is one at which the seat trades the three weeks for the late player, close above one
    at which it does not. A stake of 1 counts the games after the running week ``1 - L`` times
    (none of the three players in the choice plays the running week, so that is the whole of
    each move's figure), which takes the term below the turning point, and the seat adds the
    player of the three weeks instead: it stops trading the weeks near at hand for the later
    season. The runner's figure is the pure function's every day, the same all week, and the
    counts are its mean and the weeks above a half."""
    setup = disagreeing(teams=4, h2h=h2h)
    w = replay_of(setup, 2, 0)
    level = stk.swing(0.0, 4)
    weight = turning_weight(setup, w)
    assert LATE in day_one_adds(setup, w, weight)
    assert LATE not in day_one_adds(setup, w, weight * (1 - level))
    knobs = {**TWO_A_DAY, "season_weight": weight}
    plain, staked = armed("A", knobs=knobs), armed("B", knobs=knobs, stake=1)
    seen: dict[int, list[rn.DayRecord]] = {0: [], 1: []}
    got = rn.paired(setup, w, plain, staked, 1, on_day=lambda r: seen[r.variant].append(r))
    assert got["breaches"] == []
    first = [seen[v][0] for v in (0, 1)]
    assert first[0].state.stakes == first[1].state.stakes == {1: level}
    assert LATE in adds(first[0].decisions[1]) and LATE not in adds(first[1].decisions[1])
    assert SOON in adds(first[1].decisions[1])
    queued = [{m.add for m in first[v].queued[1]} for v in (0, 1)]
    assert LATE in queued[0] and LATE not in queued[1] and SOON in queued[1]
    # The runner's figure: the pure function of the weeks finished before the day's week, kept
    # on the state all week, for the seat that reads it and the one the run counts it for.
    by_week: dict[int, dict[int, float]] = {0: {}, 1: {}}
    for v in (0, 1):
        for r in seen[v]:
            week = setup.week_of(r.day).number
            assert r.state.stakes == {1: stk.level(setup.spec, r.state.totals, 1, week)}
            assert by_week[v].setdefault(week, r.state.stakes[1]) == r.state.stakes[1]
        assert sorted(by_week[v]) == [1, 2, 3, 4, 5, 6]
        # The final's week: full inside the field, nothing outside.
        made = got["ab"[v]]["made_playoffs"]
        assert by_week[v][6] == made and made in (0.0, 1.0)
        row = got["counts"]["ab"[v]]
        levels = list(by_week[v].values())
        assert row["stake_mean"] == pytest.approx(sum(levels) / 6)
        assert row["stake_weeks_above_half"] == float(sum(1 for x in levels if x > 0.5))
        assert "sets_past_guard" not in row
    assert not set(SEASON_KEYS) & set(got["counts"]["rivals"])


# --------------------------------------------------------------------------- the running week
#: A made-up free agent who plays every day of one week and never after.
NOW = 104


def on_day(setup, day, knobs=None, **state):
    """Seat 1's problem on ``day`` at a season weight of 1, and the day's state."""
    at = replace(initial(setup), day=day, **state)
    weighted = {**KNOBS, "season_weight": 1.0, **(knobs or {})}
    built = policy.problem_of(setup, at, 1, weighted, setup.projection, {}, {})
    assert built is not None
    return built, at


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_key_a_seat_queues_on_holds_no_day_of_the_running_week(h2h):
    """Why the stake splits the figure and does not scale it whole: the key both tiers queue on
    holds the weeks after the running one and no day of it, fewer as the season runs out and
    none in its last week. A move lands the day after it is decided, so of a queued set's
    score the season term alone counts the rest of the running week."""
    setup = disagreeing(teams=4, h2h=h2h)
    weeks = setup.calendar.weeks
    held = []
    for week in weeks:
        built, _ = on_day(setup, week.start)
        days = [d for span in built.problem.horizons[policy.QUEUE_SET] for d in span.days]
        assert all(d > week.end for d in days)
        held.append(len(days))
    assert held == [21, 21, 21, 14, 7, 0]
    assert weeks[-1].number in setup.spec.playoff_weeks


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_in_the_final_a_seat_with_a_stake_of_one_still_adds_the_player_who_plays_it(tier, h2h):
    """Full in the playoffs: on the final's Monday a seat inside the field has a week's stake
    of 1, and the key it queues on is empty. The stake takes the term off the season after the
    running week, of which there is none, so at a stake of 1 the seat adds the player who plays
    the final as it does with no stake, on either tier, the exact tier's plan drawn or not. (A
    weight scaled whole would be 0 here and the seat would decide no set.)"""
    setup = disagreeing(teams=4, h2h=h2h)
    final = setup.calendar.weeks[-1]
    # Every regular week a tie: the league's own order puts seat 1 inside the field of two.
    tied: dict = {w: {} for w in setup.spec.regular_weeks}
    assert stk.level(setup.spec, tied, 1, final.number) == 1.0
    built, state = on_day(setup, final.start, totals=tied)
    assert built.problem.horizons[policy.QUEUE_SET] == ()
    plain = policy.decide(built, tier, with_plan=False)
    assert adds(plain) == {LATE} and drops(plain) == {DEAD}
    staked = policy.guarded(built, setup, state, stake=1.0)
    assert staked.level == 1.0 and policy.later_share(staked) == 0.0
    figure = policy.season_figure_of(staked)
    assert figure.later > built.problem.season_end
    assert figure.move(plain.moves[0]) == policy.SeasonFigure(built, 1.0).move(plain.moves[0]) > 0
    assert policy.decide(staked, tier, with_plan=False).moves == plain.moves
    assert policy.decide(staked, tier).moves == plain.moves
    # A seat outside the field reads no stake there, and adds him as before.
    out = policy.guarded(built, setup, replace(state, stakes={1: 0.0}), stake=1.0)
    assert policy.decide(out, tier, with_plan=False).moves == plain.moves


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_in_a_decisive_regular_week_a_seat_still_adds_the_player_who_plays_only_that_week(
    tier, h2h
):
    """A free agent plays every day of the last regular week and never after: his add gains
    nothing on the key the seat queues on and a good deal on the running week, which the season
    term alone counts. In a week whose stake is 1, at a stake of 1, the seat still adds him:
    the running week's part of the term is kept in full."""
    base = disagreeing(teams=4, h2h=h2h)
    week = base.calendar.weeks[4]
    assert week.number == base.spec.regular_weeks[-1]
    schedule = {d: set(t) for d, t in base.schedule.items()}
    for d in week.days():
        schedule[d].add("NNN")
    setup = replace(
        base,
        players={**base.players, NOW: Member(NOW, "Now", "NNN", ("PG",))},
        projection={**base.projection, NOW: rates(2.5)},
        schedule={d: frozenset(t) for d, t in schedule.items()},
        pool=(NOW,),
    )
    built, state = on_day(setup, week.start, stakes={1: 1.0})
    plain = policy.decide(built, tier, with_plan=False)
    assert adds(plain) == {NOW}
    ev = mv.Evaluator(built.problem)
    assert ev.gain(policy.QUEUE_SET, plain.moves) == 0.0 and ev.gain("week", plain.moves) > 0.01
    staked = policy.guarded(built, setup, state, stake=1.0)
    assert policy.later_share(staked) == 0.0
    assert policy.decide(staked, tier, with_plan=False).moves == plain.moves
    # With no season weight nothing counts his games this week, and he is not added.
    bare, _ = on_day(setup, week.start, {"season_weight": 0.0})
    assert NOW not in adds(policy.decide(bare, tier, with_plan=False))


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_a_stated_limit_a_move_decided_on_a_week_s_last_day_is_scaled_whole(tier, h2h):
    """A stated limit, pinned by name (the README's "What a stake moves, and its limit"): a
    move decided on a Sunday lands in the next week, so it has no part in the running week and
    its whole figure is scaled by the ending week's stake, not the stake of the week it plays
    in. At a stake of 1 on the Sunday of a week whose stake is 1, every move's term is 0 and
    the seat decides as one with no season weight, where with no stake it adds the late player
    too; on the Monday after, at the same stake for the new week, a player's games that week
    are in the term again. The surrogate meets the limit only when its days hold a Sunday (its
    default days do not), so it solves on one here."""
    setup = disagreeing(teams=4, h2h=h2h)
    sunday = setup.calendar.weeks[0].end
    assert sunday.weekday() == 6
    built, state = on_day(setup, sunday, stakes={1: 0.6})
    assert built.week.number == 1
    late, soon = mv.Move(LATE, DEAD), mv.Move(SOON, DEAD)
    assert all(mv.day_of(built.problem, m) == sunday + timedelta(1) for m in (late, soon))
    whole = policy.SeasonFigure(built, 1.0)
    part = policy.season_figure_of(policy.guarded(built, setup, state, stake=1.0))
    assert part.share == pytest.approx(0.4)
    for m in (late, soon):
        assert whole.move(m) > 0
        assert part.move(m) == pytest.approx(part.share * whole.move(m), abs=1e-9)
    # At a share of 0 the seat's Sunday is the Sunday of a seat with no season weight.
    decisive = policy.guarded(built, setup, replace(state, stakes={1: 1.0}), stake=1.0)
    none = policy.season_figure_of(decisive)
    assert none.move(late) == none.move(soon) == 0.0
    bare, _ = on_day(setup, sunday, {"season_weight": 0.0})
    sundays = replace(policy.DEFAULT_FIELDS, surrogate_days=(sunday.weekday(),))
    full, got, without = (
        policy.decide(b, tier, with_plan=False, fields=sundays) for b in (built, decisive, bare)
    )
    assert adds(full) == {SOON, LATE}
    assert got.moves == without.moves and adds(got) == {SOON} and drops(got) == {DEAD}
    # The Monday after, the first of the soon player's weeks: his games that week are counted.
    monday, at = on_day(setup, sunday + timedelta(1), stakes={1: 1.0})
    after = policy.season_figure_of(policy.guarded(monday, setup, at, stake=1.0))
    assert after.share == 0.0 and after.move(soon) > 0 and after.move(late) == 0.0


# --------------------------------------------------------------------------- no peek, a split seat
def scale_weight(setup, w) -> float:
    """A season weight of the size of the league's season scale: the surrogate's ratio in seat 1
    on the path's first day, to four digits (as the screen takes it)."""
    scale = rn.scale_on(setup, w, arm("S", "surrogate", "market"), 1)
    assert scale is not None and scale["ratio"]
    return float(f"{scale['ratio']:.4g}")


def staked_arm(name: str, system: str, weight: float) -> rn.Arm:
    return armed(
        name,
        opponents="market",
        knobs={"system": system, "season_weight": weight},
        guard="off",
        stake=1,
    )


def peek_records(setup, lines, first, second, weight):
    """The no-peek test's small season with two seasons in lockstep, each a surrogate seat in
    seat 1 with the guard off and a stake of 1 among market rivals, at the season weight
    ``weight``: one believing as the run does (``bbm``), one a split seat (``yahoo``). Every day
    record, and its digest."""
    arms = ss.believing(
        {"P": staked_arm("P", "bbm", weight), "Y": staked_arm("Y", "yahoo", weight)}, SOURCES
    )
    forecasts = ss.forecasts_of(SOURCES, fixed_of(first, second), lines, SEED, 0, "stat", arms)
    w = rn.replay_world(
        setup,
        lines,
        1,
        SEED,
        0,
        WEIGHTS,
        label="run",
        forecasts=forecasts,
        split=ss.splits_of(SOURCES, arms),
    )
    variants = [{**rn.opponents_of(setup, a, 1), 1: a.seat()} for a in arms.values()]
    kept: dict = {}
    counted = [{1: policy.SEASON_FIELDS}] * 2
    results = rn.simulate(
        setup,
        w,
        variants,
        on_day=lambda r: kept.__setitem__((r.day, r.variant), r),
        counted=counted,
    )
    return arms, w, kept, {k: nopeek.digest(r) for k, r in kept.items()}, results


@pytest.fixture(scope="module")
def peek():
    setup, lines = recorded()
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    second = second_of(first)
    weight = scale_weight(setup, rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS))
    return setup, lines, first, second, weight, peek_records(setup, lines, first, second, weight)


def test_a_seat_with_a_stake_knows_nothing_dated_after_the_day(peek):
    """Rule 3: two worlds equal through a Monday (the day the week's stake is set) and
    different after it. Every record through the day is the same for the plain seat and the
    split one, their stakes and what they decided among it; some record after it differs. One
    format (the no-peek league's): what is asked is what the seat could know, not what it
    weighs."""
    setup, lines, first, second, weight, (_, _, kept, base, results) = peek
    day = DAYS[0]
    assert day.weekday() == 0 and setup.week_of(day).number > 1
    # The check is of something: both seats move, their stake is alive and changes by week.
    for v in (0, 1):
        levels = {r.state.stakes[1] for (_, x), r in kept.items() if x == v}
        assert len(levels) > 2 and max(levels) > 0
        assert results[v].counts[1]["landed"] > 0 and results[v].breaches == ()
        assert kept[(day, v)].state.stakes[1] == stk.level(
            setup.spec, kept[(day, v)].state.totals, 1, setup.week_of(day).number
        )
    other = nopeek.perturb(lines, rn.game_days_of(setup), day, SEED)
    _, _, _, got, _ = peek_records(setup, other, first, second, weight)
    assert set(got) == set(base)
    found = nopeek.first_difference(base, got)
    assert found is not None, "the change after the day reached no record: it tested nothing"
    assert found[0] > day, f"a record on {found[0]} saw past {day}: {found[2]}"
    same = [key for key in base if key[0] <= day]
    assert same and all(base[key] == got[key] for key in same)


def test_a_split_seat_s_guard_and_stake_are_judged_on_its_own_table(peek):
    """A ``yahoo`` seat reads a free agent on one table and its roster on another: its day-one
    decision with the guard off and a stake is the one made on the table its seat read, at the
    week's stake the state holds; the mark is the guard asked on that table."""
    setup, _, _, _, _, (arms, w, kept, _, _) = peek
    label = arms["Y"].forecaster
    assert label in w.split and arms["P"].forecaster not in w.split
    r = kept[(setup.start, 1)]
    assert r.holds == {1: label}
    table = r.held[label]
    state = replace(initial(setup), day=setup.start, stakes=dict(r.state.stakes))
    built = policy.problem_of(setup, state, 1, arms["Y"].knobs, table, r.status, r.returns)
    mine = policy.guarded(built, setup, state, policy.OFF, 1.0)
    assert mine.level == r.state.stakes[1] == stk.swing(0.0, 4)
    want = policy.decide(mine, "surrogate", fields=arms["Y"].fields)
    assert r.decisions[1] == want and want.moves
    assert want.past_guard is (not policy.guard_of(built)(want.moves))


# --------------------------------------------------------------------------- every league kind once
def kind_of(name: str):
    """The made-up leagues of the kinds a season is played in: held slots, points, waivers by
    priority and by FAAB under both waiver rules, both formats."""
    if name == "held, FAAB, continuous, every category":
        base = make_setup(teams=4, pool=12, held_slots=("IL",))
        base = replace(base, waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS)
        return of_format(base, EACH_CATEGORY)
    if name == "held, priority, a dropped player waits, one win":
        base = make_setup(teams=4, pool=12, held_slots=("IL",))
        return replace(base, waivers="priority", waiver_days=2)
    if name == "points, FAAB, a dropped player waits":
        return replace(points_setup(), waivers="faab", waiver_days=2)
    assert name == "points, priority, continuous"
    return replace(points_setup(), waivers="priority", waiver_days=2, waiver_rule=CONTINUOUS)


KINDS = (
    "held, FAAB, continuous, every category",
    "held, priority, a dropped player waits, one win",
    "points, FAAB, a dropped player waits",
    "points, priority, continuous",
)


@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
@pytest.mark.parametrize("name", KINDS)
def test_every_league_kind_plays_a_season_with_both_fields_named_and_a_clean_audit(name, tier):
    """The lesson of Fc's review: a season with the guard off and a stake of 1, at a season
    weight of the size of the league's season scale, in each kind of league (seed 1, path 0,
    among market rivals at 0.4 a day), on each tier that reads the fields: the audit finds
    nothing, the seat moves, it decides a set the block would have refused at least once (the
    lever acts in every kind), a held slot is used where the league has one, and the counts
    carry the three keys on the arm's seat alone. The exact seat executes its week plan, at a
    plan floor that takes every plan the stream draws (below zero, as ``test_sim_knobs.CASES``
    says why): under off its three searches and the plan's steps feed the queue with no allowed
    set, and a plan is drawn in every kind but the one-win league's, where the engine's plan
    floor is its own."""
    setup = kind_of(name)
    w = replay_of(setup, 1, 0)
    knobs = {"season_weight": scale_weight(setup, w)}
    more: dict = {}
    if tier == "exact":
        knobs["plan_floor_points" if setup.scoring == "points" else "plan_floor_cats"] = -1.0
        more["execute_plan"] = True
    a = armed("A", tier, "market", knobs, guard="off", stake=1, **more)
    days: list = []
    variant = {**{t: op.Market(0.4) for t in setup.teams}, 1: a.seat()}
    (res,) = rn.simulate(
        setup,
        w,
        [variant],
        [a.execute_plan],
        on_day=days.append,
        counted=[rn._counted([a], {1: a})],
    )
    states = [r.state for r in days]
    assert res.breaches == ()
    if tier == "exact" and not setup.one_win:
        assert any(r.decisions[1].plan for r in days)
    row = res.counts[1]
    assert row["landed"] > 0, row
    assert row["sets_past_guard"] >= 1 and 0 < row["stake_mean"] <= 1
    assert row["held_stints"] >= 1 or "held" not in name
    assert 0 <= row["stake_weeks_above_half"] <= len(setup.calendar.weeks)
    assert all(not set(SEASON_KEYS) & set(res.counts[t]) for t in setup.teams if t != 1)
    assert all(set(s.stakes) == {1} for s in states)
    if "continuous" in name:  # every add is a claim there
        assert row["claims_placed"] > 0, row


# --------------------------------------------------------------------------- the command
#: Four seats of six slots, four adds a week, two in a one-week final after two regular weeks.
SMALL = shapes.one("fixed", shapes.LeagueShape(4, ("PG", "SG", "G", "C", "Util", "BN"), 4, 2, 1))
WEEKS = 3
SPECS = {
    "A": spec("A", knobs={"season_weight": 0.05}),
    "B": spec("B", knobs={"season_weight": 0.05}, guard="off", stake=1),
    "R": spec("R", "ranking", knobs={"season_weight": 0.05}),
    "RS": spec("RS", "ranking", knobs={"season_weight": 0.05}, stake=0.5),
    "RG": spec("RG", "ranking", guard="off"),
}


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    """The made-up seasons with a wire of 120, a made-up frozen fit (a replay reads its lag and
    its hash) and the arms' spec files."""
    folder = make_data_dir(tmp_path_factory.mktemp("guard"), wire=120)
    fit = folder / "sim" / "fit" / "2026-01-01"
    fit.mkdir(parents=True)
    made_up = {"hold_out": 2025, "parameters": {"refresh_defaults": {"lag": 1}}}
    (fit / "fit.json").write_text(json.dumps(made_up))
    for name, body in SPECS.items():
        (folder / f"{name}.json").write_text(json.dumps(body))
    return folder


@pytest.fixture
def small(monkeypatch):
    """The league made small, as ``test_sim_screen_run.py``'s: the fixed shape four seats of
    six slots and a season of three weeks, so a surrogate pair's path is a few seconds."""
    real = rn.replay_setup
    monkeypatch.setitem(ss.GRIDS, "fixed", SMALL)
    monkeypatch.setattr(rn, "replay_setup", lambda *a, **k: real(*a, **{**k, "weeks": WEEKS}))


#: A pair's fewest paths in a league of four seats: every seat is taken once.
PATHS = 4


def replay(data: Path, a: str, b: str, *extra: str) -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024", "--workers", "1"]
    argv += ["--forecasters", "prior", "--seed", "5", "--paths", str(PATHS)]
    argv += ["--arms", str(data / f"{a}.json"), str(data / f"{b}.json"), *extra]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(argv)
    return code, buf.getvalue()


def test_a_replay_s_record_names_the_fields_the_reads_and_the_counts(data: Path, small):
    """The record end to end, one format (the command's default; the pieces are the tests'
    above): arm A names nothing and arm B the guard off and a stake of 1."""
    code, out = replay(data, "A", "B", "--name", "guard")
    assert code == 0, out
    (line,) = [x for x in out.splitlines() if x.startswith("written: ")]
    p = json.loads(Path(line.removeprefix("written: ")).read_text())
    assert p["audit"]["paths_voided"] == 0 and p["audit"]["breaches"] == []
    assert p["specs"]["b"]["guard"] == "off" and "guard" not in p["specs"]["a"]
    assert set(p["fields"]["a"]) == set(policy.FIELDS)
    assert set(p["fields"]["b"]) == {*policy.FIELDS, "guard", "stake"}
    assert (p["fields"]["b"]["guard"], p["fields"]["b"]["stake"]) == ("off", 1.0)
    (shape,) = p["reads"]["a"]
    assert set(p["reads"]["a"][shape]["fields"]) == set(policy.FIELDS)
    assert p["reads"]["b"][shape]["fields"]["guard"] == policy.READ
    assert p["reads"]["b"][shape]["fields"]["stake"] == policy.READ
    assert set(SEASON_KEYS) <= set(p["counts"]["note"])
    cell = p["counts"]["by_season"]["2024"]["prior"]
    for side in ("a", "b"):
        assert set(SEASON_KEYS) <= set(cell[side])
        assert 0 < cell[side]["stake_mean"]["mean"] <= 1
        assert cell[side]["stake_mean"]["n"] == PATHS
        assert cell[side]["landed"]["mean"] > 0
    assert cell["a"]["sets_past_guard"]["mean"] == 0.0
    assert not set(SEASON_KEYS) & set(cell["rivals"])
    for side in ("a", "b"):
        row = p["season_scale"]["by_season"]["2024"][side]
        assert row["paths"] == PATHS and 0 <= row["paths_with_ratio"] <= PATHS
        assert (row["ratio"] is None) is (row["paths_with_ratio"] == 0)


def test_the_command_refuses_before_any_path(data: Path, small, monkeypatch):
    """A guard named on a tier that has none, two arms that differ only on a stake neither
    reads, and a stake in a league whose bracket is not read: refused by name, no task
    planned."""
    code, out = replay(data, "A", "RG", "--dry-run")
    assert code == 2, out
    assert "guard 'off' named on tier 'ranking': the ranking tier has no season guard" in out
    assert "tasks (" not in out
    code, out = replay(data, "R", "RS", "--dry-run")
    assert code == 2, out
    assert "refused: arms a and b are the same seat: they differ only in stake (the ranking" in out
    assert "tasks (" not in out
    # A league whose bracket is not read. No replay has one today (every league a replay builds
    # has a spec), so the season's read is handed back with its shape's bracket unread: the
    # command refuses the arm with a stake by name, on a tier that reads it and on one that
    # does not.
    real = ss.read_season

    def unread(*a, **k):
        read = real(*a, **k)
        return replace(read, shape=replace(read.shape, bracket=False))

    monkeypatch.setattr(ss, "read_season", unread)
    for b, stake in (("B", "1"), ("RS", "0.5")):
        code, out = replay(data, "A", b, "--dry-run")
        assert code == 2, out
        assert f"refused: arm {b} names stake {stake}: a stake reads the cut line" in out
        assert "the league's bracket is not read, so it is not trusted" in out
        assert "tasks (" not in out


# --------------------------------------------------------------------------- the screen's rows
def test_the_screen_s_two_rows_and_where_the_stake_is_read():
    one, unread = policy.Shape(), policy.Shape(bracket=False)
    ctx = sc.Context()
    base = spec("B", knobs={"season_weight": 0.3})
    rows = {r.key: r for r in sc.rows_of(base, ["guard", "stake"], [one], ctx)}
    assert list(rows) == ["guard-off", "stake-0.5", "stake-1"]
    assert all(r.status == sc.PLAY and r.tier == "surrogate" for r in rows.values())
    assert rows["guard-off"].values == {"a": "block", "b": "off"}
    assert rows["guard-off"].nudge == "to off: block to off"
    assert rows["stake-0.5"].values == {"a": 0.0, "b": 0.5}
    assert rows["stake-1"].values == {"a": 0.0, "b": 1.0}
    assert rows["stake-1"].b["stake"] == 1.0 and "stake" not in rows["stake-1"].a
    # A baseline on another tier is screened on the surrogate, where the two are read.
    exact = sc.rows_of({**base, "tier": "exact"}, ["guard"], [one], ctx)
    assert exact[0].status == sc.PLAY and exact[0].both == {"tier": "surrogate"}
    # The stake is read only where the baseline has a season weight, in a league whose bracket
    # is read; the guard everywhere the surrogate plays.
    (no_weight,) = sc.rows_of(spec("B"), ["stake"], [one], ctx)
    assert (no_weight.status, no_weight.why) == (sc.NOT_READ, policy.NO_TERM)
    (no_bracket,) = sc.rows_of(base, ["stake"], [one, unread], ctx)
    assert (no_bracket.status, no_bracket.why) == (sc.NOT_READ, "the league has no bracket read")
    assert sc.rows_of(spec("B"), ["guard"], [unread], ctx)[0].status == sc.PLAY
    # A nudge equal to the baseline's value is refused by name, as for every lever.
    (already,) = sc.rows_of({**base, "guard": "off"}, ["guard"], [one], ctx)
    assert already.status == sc.REFUSED and "lever guard: its nudge to off" in already.why
    half = {r.key: r.status for r in sc.rows_of({**base, "stake": 0.5}, ["stake"], [one], ctx)}
    assert half == {"stake-0.5": sc.REFUSED, "stake-1": sc.PLAY}
