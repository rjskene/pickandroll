"""The bid policy in a season (#172, PR F2): each lever does something at all (the lesson of
D4c), a block naming every key plays clean in every league kind (the lesson of Fc's finding 1),
the walls on a claim decided after the day its bid is sealed, and Rule 1's default member.
Made-up leagues of six weeks, fixed seeds, the rivals PR Fd's (market rivals that follow the
season and pick among their best three) at a high rate. A test whose seat weighs runs in both
head-to-head formats, or says why it names one. No test here pins a figure of a season: each
compares two arms, or two worlds, of one season. Rule 1's pins of main's seasons are main's own
tests (``test_sim_continuous.season_digest`` sets this PR's three count keys aside)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from pickandroll.season import moves as mv
from pickandroll.sim import bid_policy as bp
from pickandroll.sim import counts as ct
from pickandroll.sim import nopeek, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, TYPICAL_MIN, typical_gain
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import LOST, WON
from tests.sim.sim_league import KNOBS, arm, make_setup, of_format, recorded_lines
from tests.sim.test_sim_continuous import league

DAY = timedelta(1)
FORMATS = (ONE_WIN, EACH_CATEGORY)
#: The seed of the no-peek check's second world.
SEED = 7
#: PR Fd's rivals at a high rate: they follow the season and pick among their best three.
RIVALS = op.Market(0.6, op.SEASON, 3)
#: The world's seed and path every season here is played on: the first tried, and the only one
#: (``~/sim-notes/vm/scratch/f2/explore/``; the handoff says what was tried for each test).
PATH = (1, 0)
#: A block naming every key.
EVERY_KEY = {
    "week": 0.25,
    "season": 0.25,
    "pace": {"k": 1, "shape": 1, "reserve": 0.2},
    "routine": 1,
    "rival_cap": True,
    "shade": {"q": 0.5, "least": 3},
}


def public(h2h: str, **kw):
    """Four seats and twelve free agents under the public leagues' rules: FAAB, continuous
    waivers, a dropped player after two days, $100."""
    return of_format(league("faab", pool=12, **kw), h2h)


def seat(block=None, **knobs) -> rn.Arm:
    """The surrogate arm in seat 1, its categories plan floor (the typical gain until ten moves
    where every category counts) at 0.1, naming ``block`` as its ``bid`` (None: no ``bid``)."""
    u = arm("U", "surrogate", **{"plan_floor_cats": 0.1, **knobs})
    return replace(u, bid=None if block is None else bp.of(block))


def seasons(setup, arms, rivals=RIVALS, world=None):
    """One world, one season an arm in seat 1 among ``rivals``: each arm's result and its days."""
    w = world or rn.replay_world(setup, recorded_lines(setup, 11), 1, *PATH)
    days: list[list[rn.DayRecord]] = [[] for _ in arms]
    variants = [{**{t: rivals for t in setup.teams}, 1: a.seat()} for a in arms]
    results = rn.simulate(setup, w, variants, on_day=lambda r: days[r.variant].append(r))
    for result in results:
        assert result.breaches == ()
    return list(zip(results, days, strict=True))


def placed(days, team: int = 1):
    """The claims ``team`` placed: the day, the player, the bid and the value."""
    return [(r.day, c.move.add, c.bid, c.value) for r in days for c in r.claims.get(team, ())]


def decided(days, outcome: str, team: int = 1):
    """``team``'s claims decided as ``outcome``: the morning, the player and the bid."""
    return [
        (r.day, x.add, x.bid)
        for r in days
        for x in r.cleared
        if x.team == team and x.outcome == outcome
    ]


def others_at(days, day, team: int = 1) -> int:
    """The richest other team's dollars on ``day``, after that morning's claims."""
    (state,) = [r.state for r in days if r.day == day]
    return max(d for t, d in state.dollars.items() if t != team)


# --------------------------------------------------------------------------- each lever
@pytest.mark.parametrize("h2h", FORMATS)
def test_a_paced_arm_has_more_dollars_at_the_bracket_than_the_default_arm(h2h):
    """Two arms at ``faab_sizing`` 2 on one world, one of them pacing (``k`` 2, a straight path
    to a reserve of half the budget): the default arm runs dry before the bracket and stands
    weeks at $0, the paced arm reaches the bracket's first day with dollars left and never
    stands at $0."""
    pace = {"pace": {"k": 2, "shape": 1, "reserve": 0.5}}
    (plain, _), (paced, days) = seasons(
        public(h2h), [seat(faab_sizing=2.0), seat(pace, faab_sizing=2.0)]
    )
    a, b = plain.counts[1], paced.counts[1]
    assert b["dollars_at_bracket"] > a["dollars_at_bracket"] == 0
    assert a["weeks_at_zero"] > 0 == b["weeks_at_zero"]
    assert b["claims_won"] >= 1 and a["dollars_spent"] == 100 > b["dollars_spent"] > 0
    # The first claim of the season is ahead of the path (every dollar left, the path below
    # 1 on the morning it is decided): the paced arm bids more on it than its two typicals' worth.
    first_day, _, bid, value = placed(days)[0]
    assert first_day == days[0].day and bid > bp._half_up(bp._half_up(value) * 2.0)


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_shaded_arm_pays_less_for_the_claims_it_wins(h2h):
    """Two arms on one world, one shading at the median of the other teams' winning bids once
    three are seen: both win the same claims on the same mornings, the shaded arm never pays
    more for one and pays less in all; until three wins of other teams are seen its bids are the
    default's."""
    shade = {"shade": {"q": 0.5, "least": 3}}
    (plain, da), (shaded, db) = seasons(public(h2h), [seat(), seat(shade)])
    won_a, won_b = decided(da, WON), decided(db, WON)
    assert [(d, k) for d, k, _ in won_a] == [(d, k) for d, k, _ in won_b] and won_a
    assert all(b <= a for (_, _, a), (_, _, b) in zip(won_a, won_b, strict=True))
    assert sum(b for _, _, b in won_b) < sum(a for _, _, a in won_a)
    assert shaded.counts[1]["dollars_spent"] < plain.counts[1]["dollars_spent"]
    assert shaded.counts[1]["claims_won"] == plain.counts[1]["claims_won"]
    # Off until three of the other teams' wins are seen: the bids placed before are the same.
    seen = {r.day: sum(1 for _, t, _ in r.state.won_bids if t != 1) for r in db}
    early = [(d, k, bid) for d, k, bid, _ in placed(db) if seen[d] < 3]
    assert early and early == [(d, k, bid) for d, k, bid, _ in placed(da)][: len(early)]
    late = [bid for d, _, bid, _ in placed(db) if seen[d] >= 3]
    assert late and len(early) + len(late) == len(placed(db))


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_routine_dollar_wins_a_claim_a_bid_of_nothing_ties_and_loses(h2h):
    """Rivals whose bids are all $0 (the assumed form at a scale of a hundredth): the default
    arm's routine claim bids $0, ties a rival's and loses on the order; the arm whose routine
    claim bids a dollar wins the same player on the same morning. The two arms' seasons are one
    until that claim: every bid before it is above the routine."""
    setup = replace(public(h2h), rival_scale=0.01)
    (plain, da), (dollar, db) = seasons(setup, [seat(), seat({"routine": 1})])
    assert all(row["dollars_spent"] == 0 for t, row in plain.counts.items() if t != 1)
    assert plain.counts[1]["claims_lost_tie"] >= 1
    day, player, bid = decided(da, LOST)[0]
    assert bid == 0
    assert (day, player, 1) in decided(db, WON)
    assert dollar.counts[1]["claims_lost_tie"] < plain.counts[1]["claims_lost_tie"]
    assert dollar.counts[1]["claims_won"] > plain.counts[1]["claims_won"]
    # The routine dollar is the only difference before it.
    before_a = [(d, k, b) for d, k, b, _ in placed(da) if d < day]
    before_b = [(d, k, b) for d, k, b, _ in placed(db) if d < day]
    assert [x[:2] for x in before_a] == [x[:2] for x in before_b]
    assert {(a[2], b[2]) for a, b in zip(before_a, before_b, strict=True) if a != b} == {(0, 1)}


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_rival_cap_binds_once_the_rivals_have_spent(h2h):
    """A league of two teams, $30 each, the one rival bidding high (the assumed form at a scale
    of sixty) and moving every day: once it has spent its budget the capped arm bids a dollar
    more than it holds and still wins, where the default arm pays its typicals' worth. The cap
    reads the richest other team, so the league has one: in the four-team seasons of this file
    one rival holds its whole budget whenever the seat bids, and there the cap never binds (the
    second half)."""
    base = make_setup(teams=2, pool=12)
    two = replace(base, waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS, budget=30)
    setup = of_format(replace(two, rival_scale=60.0), h2h)
    arms = [seat(plan_floor_cats=0.5), seat({"rival_cap": True}, plan_floor_cats=0.5)]
    (plain, da), (capped, db) = seasons(setup, arms, op.Market(1.0, op.SEASON, 3))
    # The rival has spent its budget.
    assert plain.counts[2]["dollars_spent"] == capped.counts[2]["dollars_spent"] == 30
    # No bid of the capped arm is above the rival's dollars that day, plus one ...
    assert all(bid <= others_at(db, d) + 1 for d, _, bid, _ in placed(db))
    # ... and it binds: the same player on the same day, bid a dollar where the default bids
    # more, and won.
    bound = [
        (d, k, a, b)
        for (d, k, a, _), (d2, k2, b, _) in zip(placed(da), placed(db), strict=False)
        if (d, k) == (d2, k2) and b < a
    ]
    assert bound, (placed(da), placed(db))
    d, k, a, b = bound[0]
    assert others_at(db, d) == 0 and b == 1 < a
    assert any(add == k and bid == 1 and day > d for day, add, bid in decided(db, WON))
    assert capped.counts[1]["dollars_spent"] < plain.counts[1]["dollars_spent"]
    assert capped.counts[1]["claims_won"] == plain.counts[1]["claims_won"]
    # Never when one is rich: among three rivals one of whom holds its budget, the capped arm's
    # season is the default arm's.
    (plain, da), (capped, db) = seasons(public(h2h), [seat(), seat({"rival_cap": True})])
    assert all(others_at(da, d) + 1 >= bid for d, _, bid, _ in placed(da)) and placed(da)
    assert plain.counts == capped.counts and plain.summaries == capped.summaries
    assert placed(da) == placed(db)


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_weight_on_the_week_or_the_season_moves_the_bids_on_its_own_fortnight(h2h):
    """A seat that decides every day (so its fortnight reaches ten moves), three arms on one
    world: the default, one that puts half the weight on the week and one that puts it on the
    season. Until ten moves the half counts as typical, so both bid less than the default on
    the season's first claims; each keeps its own fortnight on its horizon alone, the default
    keeps none; and once ten moves are in it the two arms value a claim apart."""
    daily = replace(policy.DEFAULT_FIELDS, surrogate_days=tuple(range(7)))
    arms = [
        replace(seat(block, daily_cap=3), fields=daily)
        for block in (None, {"week": 0.5}, {"season": 0.5})
    ]
    (plain, da), (week, dw), (season, ds) = seasons(public(h2h), arms)
    first = da[0].day
    for days in (dw, ds):
        mine = [(k, bid) for d, k, bid, _ in placed(days) if d == first]
        default = [(k, bid) for d, k, bid, _ in placed(da) if d == first]
        assert [k for k, _ in mine] == [k for k, _ in default] and mine
        assert all(0 < b < a for (_, a), (_, b) in zip(default, mine, strict=True))
    assert all(r.state.recent_by == {} for r in da)
    assert {key for r in dw for key in r.state.recent_by} == {bp.WEEK}
    assert {key for r in ds for key in r.state.recent_by} == {bp.SEASON}
    # Each reaches ten moves in a fortnight, and from then on reads its own typical.
    for days, key in ((dw, bp.WEEK), (ds, bp.SEASON)):
        assert max(len(r.state.recent_by[key].get(1, ())) for r in days) >= TYPICAL_MIN
        assert all(set(r.state.recent_by[key]) == {1} for r in days if r.state.recent_by)
    assert [v for *_, v in placed(dw)] != [v for *_, v in placed(ds)]
    for result in (week, season):
        assert result.counts[1]["dollars_spent"] != plain.counts[1]["dollars_spent"]


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_screen_s_week_pair_and_its_season_pair_part_from_the_seat_s_tenth_move(h2h):
    """The lead's working default (q-6, 2026-11-19). A surrogate seat on its two days a week
    never holds ten moves in a fortnight here, so its typical on the week and on the season is
    the median of its last ten moves whatever their age. The two arms are the screen's own: the
    nudged arm of its ``bid.week`` pair and of its ``bid.season`` pair, one step up each from
    one baseline, on one world. Before the seat's tenth move neither reads a size: a move that
    gains counts as one typical, so the two value a claim alike (but for a gain of nothing or
    less, which counts nothing). From the tenth move each values the claim on its own horizon's
    gain over its own typical, and the two part: the two rows are two levers.

    (The screen's command does not show this on its tests' small league of three weeks: on
    the three seeds tried in both formats its seat placed six claims at most, short of a tenth
    move, so its ``bid.week`` pair and its ``bid.season`` pair differed by a gain's sign in the
    value won, or in nothing.)"""
    spec = {
        "name": "U",
        "tier": "surrogate",
        "knobs": {**KNOBS, "plan_floor_cats": 0.1},
        "opponents": {"kind": "market"},
    }
    shape = policy.Shape(waivers="faab", h2h=h2h)
    names = ["bid.week", "bid.season"]
    rows = {r.key: r for r in sc.rows_of(spec, names, [shape], sc.Context(waivers="faab"))}
    up_week, up_season = rows["bid.week-up"], rows["bid.season-up"]
    assert up_week.status == up_season.status == sc.PLAY and up_week.a == up_season.a
    step = sc.WEIGHT_STEP
    arms = [rn.arm_of(up_week.b), rn.arm_of(up_season.b)]
    assert [(a.tier, a.bid.week, a.bid.season) for a in arms] == [
        ("surrogate", step, 0.0),
        ("surrogate", 0.0, step),
    ]
    (week, dw), (season, ds) = seasons(public(h2h), arms)

    def claims(days, key):
        """By day and player: the claim's value, its move's gain on ``key``, the seat's moves
        through that day, and its typical on ``key`` that day (None before the tenth move)."""
        out, made = {}, 0
        for r in days:
            decision = r.decisions.get(1)
            made += len(decision.moves) if decision is not None else 0
            kept = r.state.recent_by.get(key, {}).get(1, ())
            fortnight = [x for d, x in kept if d > r.day - 14 * DAY]
            assert len(fortnight) < TYPICAL_MIN and len(kept) == min(made, TYPICAL_MIN)
            typical = typical_gain([x for _, x in kept], 0.0)[0] if made >= TYPICAL_MIN else None
            for c in r.claims.get(1, ()):
                gain = getattr(decision.basis, key)[decision.moves.index(c.move)]
                out[(r.day, c.move.add)] = (c.value, gain, made, typical, kept)
        return out

    w, s = claims(dw, bp.WEEK), claims(ds, bp.SEASON)
    early = [k for k in w if w[k][2] < TYPICAL_MIN]
    late = [k for k in w if w[k][2] >= TYPICAL_MIN]
    assert len(early) >= 3 and late and set(early) | {min(late)} <= set(s)
    # Before the tenth move: one typical for a move that gains, on either horizon.
    for k in early:
        (vw, gw, n, tw, _), (vs, gs, m, ts, _) = w[k], s[k]
        assert n == m and tw is None and ts is None
        assert vw - vs == pytest.approx(step * ((gw > 0) - (gs > 0)))
    assert any(w[k][1] > 0 and s[k][1] > 0 and w[k][0] == s[k][0] for k in early)
    # The claim of the tenth move: a size on each horizon, over the median of the seat's last
    # ten moves, some of them older than a fortnight. What is left of each value is the three
    # weeks' share, which the two arms hold alike.
    k = min(late)
    (vw, gw, n, tw, kept), (vs, gs, m, ts, _) = w[k], s[k]
    assert n == m >= TYPICAL_MIN and gw > 0 and gs > 0 and tw > 0 and ts > 0
    assert min(d for d, _ in kept) <= k[0] - 14 * DAY
    assert vw - step * gw / tw == pytest.approx(vs - step * gs / ts)
    assert abs(vw - vs) > 0.01 and gw / tw != pytest.approx(gs / ts)
    # The claim is won in both, so the value won, a count of the screen's record, parts too.
    assert abs(week.counts[1]["value_won"] - season.counts[1]["value_won"]) > 0.01


@pytest.mark.parametrize("h2h", FORMATS)
def test_in_the_bracket_s_last_week_only_an_arm_whose_bid_weighs_the_season_spends(h2h):
    """A bracket of two weeks, three paced arms that decide every day, on one world. In the
    bracket's last week a seat reads no opponent, so a move gains nothing there on the three
    weeks: the arm with no season term makes no move in it; the arm with one whose
    ``bid.season`` is 0 bids the routine on every claim of the week (worth nothing, it never
    rides the pace: the lead's working default, 2026-11-19) and ends the season with the
    dollars it began that week with; the arm that weighs the season values those claims, and
    spends there. In the bracket's first week a claim is valued on the three weeks as in any
    week, and the pace spends its reserve on it whatever ``bid.season`` is."""
    pace = {"k": 1, "shape": 1, "reserve": 0.3}
    daily = replace(policy.DEFAULT_FIELDS, surrogate_days=tuple(range(7)))
    setup = public(h2h, playoff_weeks=2)
    first, last = sorted(
        w.start for w in setup.calendar.weeks if w.number in setup.spec.playoff_weeks
    )
    arms = [
        replace(seat(block, daily_cap=3, **knobs), fields=daily)
        for block, knobs in (
            ({"pace": pace}, {}),
            ({"pace": pace}, {"season_weight": 0.5}),
            ({"pace": pace, "season": 0.5}, {"season_weight": 0.5}),
        )
    ]
    (_, dn), (plain, da), (weighs, dw) = seasons(setup, arms)

    def there(days, since, until=None):
        return [
            (bid, value)
            for day, _, bid, value in placed(days)
            if day >= since and (until is None or day < until)
        ]

    def dollars(days, day):
        (state,) = [r.state for r in days if r.day == day]
        return state.dollars[1]

    # The last week.
    assert not there(dn, last) and all(not r.decisions[1].moves for r in dn if r.day >= last)
    for days in (da, dw):
        gains = [g for r in days if r.day >= last for g in r.decisions[1].basis.gains]
        assert gains and all(abs(g) < 1e-9 for g in gains)
    assert there(da, last) and all(bid == 0 and value == 0 for bid, value in there(da, last))
    assert plain.counts[1]["dollars_left"] == dollars(da, last) > 0
    assert all(value > 0 for _, value in there(dw, last))
    assert any(bid > 0 for bid, _ in there(dw, last))
    assert weighs.counts[1]["dollars_left"] < dollars(dw, last)
    # The first: gains that are not nothing, and a reserve spent on them at ``bid.season`` 0.
    for days in (dn, da, dw):
        gains = [g for r in days if first <= r.day < last for g in r.decisions[1].basis.gains]
        assert any(abs(g) > 1e-9 for g in gains)
    assert any(bid > 1 and value > 0 for bid, value in there(da, first, last))
    assert dollars(da, last) < plain.counts[1]["dollars_at_bracket"]


# --------------------------------------------------------------------------- every league kind
@pytest.mark.parametrize("h2h", FORMATS)
def test_a_bid_naming_every_key_plays_clean_under_the_public_rules_with_a_held_slot(h2h):
    """Every league kind once (the lesson of Fc's finding 1): FAAB, continuous waivers and an
    IL slot, the seat's ``bid`` naming every key. The audit finds nothing (``seasons`` holds
    every season of this file to it), the seat makes a held stint, wins claims it paid for and
    is never below $0, and the rivals win claims. Without the held slot the same seat both wins
    a claim and loses one."""
    ((result, days),) = seasons(public(h2h, held_slots=("IL",)), [seat(EVERY_KEY)])
    row = result.counts[1]
    assert row["held_stints"] >= 1 and row["claims_won"] >= 1
    assert any(bid > 1 for _, _, bid in decided(days, WON))
    assert row["dollars_spent"] == sum(bid for _, _, bid in decided(days, WON))
    assert all(min(r.state.dollars.values()) >= 0 for r in days)
    assert any(decided(days, WON, t) for t in (2, 3, 4))
    held = [{k for k, slot in r.state.rosters[1] if slot in mv.HELD} for r in days]
    assert any(held)
    ((result, days),) = seasons(public(h2h), [seat(EVERY_KEY)])
    assert decided(days, WON) and decided(days, LOST)
    assert result.counts[1]["value_won"] > 0


def test_a_bid_naming_every_key_plays_clean_in_a_points_league_and_under_the_dropped_rule():
    """The other kinds, one season each, the seat's ``bid`` naming every key: a points league
    with an IL slot under the public rules (its week is one result on the points: one format),
    and FAAB under the dropped rule, where only a dropped player is bid on (one win, the
    format the rule's own FAAB season test plays). The audit finds nothing in either."""
    table = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0, "threes": 1.0}
    base = public(ONE_WIN, held_slots=("IL",))
    points = replace(
        base,
        scoring="points",
        points=table,
        cats=("fpts",),
        spec=replace(base.spec, scoring="points", points=table, cats=()),
    )
    ((result, days),) = seasons(points, [seat(EVERY_KEY, plan_floor_points=0.01)])
    assert result.counts[1]["claims_won"] >= 1 and result.counts[1]["dollars_spent"] > 0
    assert result.counts[1]["held_stints"] >= 1
    dropped = league("faab", DROPPED, pool=12)
    ((result, days),) = seasons(dropped, [seat(EVERY_KEY)], op.Market(0.3))
    assert set(ct.PACING) <= set(result.counts[1])
    won = decided(days, WON)
    assert won and any(bid > 0 for _, _, bid in won), placed(days)
    assert result.counts[1]["dollars_spent"] == sum(bid for _, _, bid in won)


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_bid_named_where_nobody_reads_it_moves_nothing(h2h):
    """By priority a ``bid`` is named and read by nobody: the season of an arm that names every
    key is the season of the arm that names none, and no count of the bids is kept. So is a
    ranking seat's in a FAAB league: it bids $0 whatever its arm names."""
    setup = of_format(league("priority", pool=12), h2h)
    (plain, da), (named, db) = seasons(setup, [seat(), seat(EVERY_KEY)])
    assert plain.counts == named.counts and plain.summaries == named.summaries
    assert placed(da) == placed(db) and not set(ct.BIDS) & set(plain.counts[1])
    assert all(r.state.won_bids == () and r.state.recent_by == {} for r in db)
    ranking = replace(seat(), tier="ranking")
    arms = [ranking, replace(ranking, bid=bp.of(EVERY_KEY))]
    (plain, da), (named, db) = seasons(public(h2h), arms)
    assert plain.counts == named.counts and placed(da) == placed(db)
    assert all(bid == 0 for _, _, bid, _ in placed(db)) and plain.counts[1]["value_won"] == 0


def test_a_split_seat_bids_on_its_own_beliefs_and_plays_clean():
    """A seat that believes by a split forecaster (its own table for the players it holds,
    another for the wire, PR D1), its ``bid`` naming every key, in a league that counts every
    category (the format whose typical gain is the arm's own floor): its bids come from its own
    problem, so the season plays clean and its claims carry bids, as the same arm's on the run's
    forecaster do."""
    setup = public(EACH_CATEGORY)
    out = [k for k, _ in setup.rosters[1][:2]]
    short = {k: v for k, v in setup.projection.items() if k not in out}
    w = rn.replay_world(
        setup,
        recorded_lines(setup, 11),
        1,
        *PATH,
        label="run",
        forecasts={"short": short, "split": dict(setup.projection)},
        split={"split": "short"},
    )
    own = replace(seat(EVERY_KEY), forecaster="split")
    (split, ds), (run, dr) = seasons(setup, [own, seat(EVERY_KEY)], world=w)
    for result, days in ((split, ds), (run, dr)):
        assert any(bid > 1 for _, _, bid, _ in placed(days))
        assert result.counts[1]["dollars_spent"] == sum(b for _, _, b in decided(days, WON))


# --------------------------------------------------------------------------- the walls
def digests(setup, lines, block=None):
    """One season of the seat naming ``block`` (every key when None) on the world of ``lines``:
    each day's digest as the no-peek check takes it, and the seat's claims as (the day placed,
    the morning decided)."""
    got: dict = {}
    waits: list = []

    def keep(r: rn.DayRecord) -> None:
        got[(r.day, r.variant)] = nopeek.digest(r)
        waits.extend((r.day, c.clears) for c in r.claims.get(1, ()))

    w = rn.replay_world(setup, lines, 1, *PATH)
    own = seat(EVERY_KEY if block is None else block)
    rn.simulate(setup, w, [{**{t: RIVALS for t in setup.teams}, 1: own.seat()}], on_day=keep)
    return got, waits


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_no_peek_check_holds_with_every_key_named_over_a_claim_decided_after_the_day(h2h):
    """The walls in a season (the lead's answer to q-4): a pace reads the morning its claim is
    decided, a date after the day the bid is sealed. So the no-peek check (two worlds that agree
    on every line before a day and differ from it on) is run with a ``bid`` naming every key on
    the day the seat places the claim that waits longest (a dropped player's, decided two
    mornings later) and on the day between: both days the claim's clear date is after the
    changed day, every record through the day is the same (the claim, its bid and its value are
    in the digest), and a record after it differs."""
    setup = public(h2h)
    lines = recorded_lines(setup, 11)
    base, waits = digests(setup, lines)
    assert waits and all(clears > day for day, clears in waits)
    on, clears = max(waits, key=lambda x: (x[1] - x[0], x[0]))
    assert clears - on > DAY
    for day in (on, on + DAY):
        assert clears > day
        got, _ = digests(setup, nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
        first = nopeek.first_difference(base, got)
        assert first is not None, "the change after the day reached no record: it tested nothing"
        assert first[0] > day, f"a record on {first[0]} saw past {day}: {first[2]}"
        assert all(base[key] == got[key] for key in base if key[0] <= day)
        assert "claims" in base[(on, 0)] and base[(on, 0)]["claims"] == got[(on, 0)]["claims"]


def test_a_bid_that_reads_the_lines_of_the_morning_it_is_decided_is_caught(monkeypatch):
    """The check's power on a bid: a rule whose value also reads what every player scored on
    the claim's clear morning (a peek of a day or two) parts the records by the day the worlds
    part, in the claims. One format: the power is the digest's, whatever the seat weighs."""
    setup = public(EACH_CATEGORY)
    lines = recorded_lines(setup, 11)
    real = bp.value

    def peeking(world):
        def value(rule, seen):
            then = sum(x[seen.when.day]["pts"] for x in world.values() if seen.when.day in x)
            return real(rule, seen) + then / 100

        return value

    monkeypatch.setattr(bp, "value", peeking(lines))
    base, waits = digests(setup, lines)
    day, clears = waits[len(waits) // 2]
    assert clears > day
    other = nopeek.perturb(lines, rn.game_days_of(setup), day, SEED)
    monkeypatch.setattr(bp, "value", peeking(other))
    got, _ = digests(setup, other)
    first = nopeek.first_difference(base, got)
    assert first is not None and first[0] <= day and "claims" in first[2], first


# --------------------------------------------------------------------------- Rule 1
@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("rule", [DROPPED, CONTINUOUS])
def test_rule_1_an_empty_bid_plays_the_season_of_no_bid(rule, h2h):
    """The default member in a season, in both formats and under both waiver rules: an arm that
    names an empty ``bid`` (the family's default member, through ``bid_policy.amount``) and one
    that names none (the live rule itself, ``policy.live_bid``) play one season: the same
    claims at the same bids and values, the same counts, the same finish."""
    setup = of_format(league("faab", rule, pool=12), h2h)
    rivals = RIVALS if rule == CONTINUOUS else op.Market(0.3)
    (none, da), (empty, db) = seasons(setup, [seat(), seat({})], rivals)
    assert none.counts == empty.counts and none.summaries == empty.summaries
    assert placed(da) == placed(db)
    assert [r.cleared for r in da] == [r.cleared for r in db]
    assert da[-1].state.dollars == db[-1].state.dollars
    assert da[-1].state.rosters == db[-1].state.rosters
    if rule == CONTINUOUS:
        assert placed(da) and any(bid > 0 for _, _, bid, _ in placed(da))
