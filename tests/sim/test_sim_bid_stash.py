"""The bid policy beside the stash threshold (#172, PR F2 built on PR G). The two PRs edit the
same things: a seat's decision (the threshold decides its moves and names whom a returning held
player sends, the block what its claims bid on), the queue (the names and the seat's moves on
the horizons a bid weighs leave by one ``replace``), the state and its key, a claim (the
count of returning players dropped reads an open claim's drop, the bid policy gave a claim its
value), the counts of a row, a mirror rival and the screen's list. This file holds what each
must still do with the other in force: an arm that names both.

Made-up leagues, fixed seeds. The days and the morning are G's and Fc's made-up ones
(``test_sim_stash``, ``test_sim_held_morning``), by FAAB: their seats weigh on one made-up day
and compare decisions made in the same run, or are scripted, so they name no format. The
seasons name one each and say why. No test here pins a literal outcome of a replay: each
compares arms of one world, on a found world (the seed and path beside each)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from pickandroll.sim import bid_policy as bp
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, mv, wk
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import WON, Waiting, initial
from tests.sim.sim_league import arm, of_format, recorded_lines
from tests.sim.test_sim_bid_seasons import EVERY_KEY, RIVALS, decided, in_force
from tests.sim.test_sim_continuous import morning
from tests.sim.test_sim_faab import claim
from tests.sim.test_sim_held_morning import found, full_with_one_held, play
from tests.sim.test_sim_screen import BID_NAMES, base, differ
from tests.sim.test_sim_stash import NEVER, SHARE, TEAM, a_day, held_league, mornings_named

DAY = timedelta(1)
#: The tiers that search with the engine and bid by the live rule.
TIERS = ("surrogate", "exact")
RULES = (DROPPED, CONTINUOUS)
#: PR G's seasons' rivals: market rivals on the draft day's view, at a low rate.
QUIET = op.Market(0.3)


def both(tier: str, threshold: float | None, block=EVERY_KEY, opponents: str = "market") -> rn.Arm:
    """An arm that names a stash threshold and ``block`` as its ``bid`` (None: no ``bid``), its
    categories plan floor at 0.1 as the bid policy's seasons have it."""
    u = arm("U", tier, opponents, stash_threshold=threshold, plan_floor_cats=0.1)
    return replace(u, bid=None if block is None else bp.of(block))


# --------------------------------------------------------------------------- a made-up day
def faab_day(rule: str, wait: int = 1):
    """G's made-up day of a plain drop (``test_sim_stash.a_day``: the star, far above everyone,
    for ``gone``, an active player who is out and back after the three weeks) in a FAAB league
    under ``rule``. Under the dropped rule the star is on waivers for ``wait`` mornings; under
    continuous waivers every add is a claim decided the next morning. The setup, the state, the
    statuses, the return dates, the star and ``gone``."""
    setup, state, status, returns, star, gone, _ = a_day(churn=False)
    setup = replace(setup, waivers="faab", waiver_days=2, waiver_rule=rule)
    s = replace(initial(setup), rosters=state.rosters, pool=state.pool)
    if rule == DROPPED:
        s = replace(s, waivers={star: Waiting(s.day + wait * DAY, 2)})
    return setup, s, status, returns, star, gone


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("tier", TIERS)
def test_a_claim_s_drop_is_the_threshold_s_and_its_bid_the_block_s(tier, rule):
    """One arm names both. The seat's decision goes through the tier (PR G: the threshold on
    its problem, the returning players read) and then through ``policy.with_bid`` (PR F2), as
    the runner makes it (``opponents.Seat.decide``):

    - the block changes what the claim bids on and nothing else of the decision: the moves and
      the returning players read are the same seat's that names no ``bid``;
    - the threshold decides the claim's drop under the block: at none the star's claim drops
      the returning player, at a threshold no add clears it drops another;
    - the claim's bid and value are the block's (they part from the no-bid seat's claim on the
      same move).

    Then the runner's own steps to the morning the claim is won (the reading, the queue, the
    morning, the count), the claim waiting one morning, and two under the dropped rule: while
    it is open the count's reading still finds its drop (``Tally.reading`` reads each open
    claim, which since PR F2 carries a value), so the returning player it drops is counted
    once, beside the bid policy's counts in the same row, and none is counted at the
    threshold."""
    waits = (1, 2) if rule == DROPPED else (1,)
    for threshold in (None, NEVER):
        for wait in waits:
            setup, s, status, returns, star, gone = faab_day(rule, wait)
            value = wk.per_game_values(setup.projection, setup.cats, None)
            named, plain = both(tier, threshold), both(tier, threshold, None)
            tally = ct.Tally(setup, stash=True)
            g = np.random.default_rng(0)
            first = None
            for n in range(wait):
                at = (setup, s, TEAM, setup.projection, status, returns, g)
                decision, bare = named.seat().decide(*at), plain.seat().decide(*at)
                assert replace(decision, basis=bare.basis) == bare
                tally.reading(TEAM, decision.returning, s)
                queue = (1, setup.max_weekly_adds, False, setup.spots(), setup)
                placed = policy.queue(s, TEAM, decision, *queue)
                if n == 0:
                    assert [m.add for m in decision.moves] == [star]
                    assert gone in decision.returning
                    assert (decision.moves[0].drop == gone) == (threshold is None)
                    assert decision.basis.bid == named.bid and bare.basis.bid is None
                    (first,) = placed.claims[TEAM]
                    (other,) = policy.queue(s, TEAM, bare, *queue).claims[TEAM]
                    assert first.move == other.move == decision.moves[0]
                    assert first.bid > 1 and first.bid != other.bid and first.value != other.value
                else:
                    # The claim is still open, and its drop is off the seat's problem: the
                    # returning player is no longer read where the claim drops him.
                    assert placed.claims[TEAM] == (first,) and not decision.moves
                    assert (gone in decision.returning) == (threshold is not None)
                assert gone in dict(s.rosters[TEAM])
                s = replace(morning(setup, placed, s.day + DAY, status, value), day=s.day + DAY)
                tally.left(placed, s)
            assert first is not None
            row = tally.rows(s)[TEAM]
            assert star in s.active(TEAM) and not s.claims.get(TEAM)
            assert (gone in s.pool) == (threshold is None)
            assert s.won_bids == ((s.day, TEAM, first.bid),)
            assert s.value_won == {TEAM: first.value} and first.value > 0
            assert row["claims_won"] == 1.0 and row["dollars_spent"] == first.bid
            assert row["value_won"] == first.value
            assert row["returning_dropped"] == (1.0 if threshold is None else 0.0), wait
            assert list(row)[-len(ct.BIDS) - 1 :] == [*ct.BIDS, *ct.STASH]


# --------------------------------------------------------------------------- the morning
@pytest.mark.parametrize("way", ("claim", "dropped_claim"))
def test_a_named_drop_leaves_before_a_claim_bid_by_a_block_is_decided(way):
    """The morning's order of Fc's review (``arrive``, ``clear_waivers``, ``land``) with both
    PRs' parts in it, by FAAB under each waiver rule (``claim``: continuous waivers;
    ``dropped_claim``: a dropped player's, the rule not named). Team 2's held ``z`` clears the
    morning its claim on ``x`` for ``y`` is decided; its decision names ``extra`` for ``z`` (PR
    G) and its basis names a ``bid`` block that weighs the week and the season (PR F2).

    - The queue writes both by one ``replace``: the names, and the seat's moves on the
      horizons the block weighs, beside the claim, whose bid and value are the block's.
    - In the morning the named player leaves first, the claim finds its drop and is won at
      its bid, and the winning bid and the value won are kept; the names are spent.
    - With the names taken off (the rule before PR G) the trim takes ``y``, the claim's drop:
      the claim fails, nothing is paid and no winning bid or value is kept.

    The seat's moves are scripted, so the case names no format."""
    setup, s, x, z, extra, y = full_with_one_held("faab", way)
    rule = bp.of(EVERY_KEY)
    live = policy.Basis(policy.LIVE, (6.0,), floor=1.0)
    basis = replace(live, bid=rule, week=(3.0,), season=(2.0,))
    decision = policy.Decision((mv.Move(x, y),), basis=basis, sends=((z, extra),))
    value = {k: 10.0 for k, _ in s.rosters[2]} | {x: 1.0, y: 5.0}
    placed, out = play(setup, s, 2, decision, {}, value)
    (c,) = placed.claims[2]
    (plain,) = play(setup, s, 2, replace(decision, basis=live), {}, value)[0].claims[2]
    assert c.move == plain.move == mv.Move(x, y)
    assert c.bid > 0 and c.bid != plain.bid and 0 < c.value != plain.value
    assert placed.sends == {2: ((z, extra),)}
    assert placed.recent == {2: ((s.day, 6.0),)}
    assert placed.recent_by == {bp.WEEK: {2: ((s.day, 3.0),)}, bp.SEASON: {2: ((s.day, 2.0),)}}
    # The morning: the named player first, then the claim, at its bid.
    assert out.sends == {} and out.recent_by == placed.recent_by
    assert x in out.active(2) and z in out.active(2) and y in out.pool and extra in out.pool
    assert out.forced_by == {2: 1} and not out.gone_by.get(2)
    assert [(r.team, r.add, r.outcome, r.bid) for r in out.resolved] == [(2, x, WON, c.bid)]
    assert out.won_bids == ((out.day, 2, c.bid),) and out.value_won == {2: c.value}
    assert out.dollars[2] == setup.budget - c.bid
    assert found(setup, placed, out) == []
    # The rule before PR G, which a seat that names none still gets: the trim takes the drop.
    bare = morning(setup, replace(placed, sends={}), setup.start + DAY, {}, value)
    assert x in bare.pool and y in bare.pool and extra in bare.active(2)
    assert bare.won_bids == () and bare.value_won == {} and bare.dollars[2] == setup.budget


# --------------------------------------------------------------------------- the key
def test_neither_the_names_nor_a_claim_s_value_is_in_the_key_and_no_decision_reads_either():
    """What a decision depends on (``SimState.key``) holds neither the names (PR G) nor an
    open claim's value (PR F2), and no decision reads either: two states apart only in them
    are one key and give one decision to a seat that names both a threshold and a block, on
    each tier, and to its mirror rival. The queue then replaces the team's own names with the
    day's and keeps every other team's, whatever stood. Made on one made-up day, the two
    decisions compared: no format is named."""
    setup, s, status, returns, star, gone = faab_day(CONTINUOUS)
    waiting = min(k for k in s.pool if k != star)
    held = claim(waiting, s.rosters[2][-1][0], s.day + DAY, 3)
    one = replace(s, claims={2: (replace(held, value=0.4),)})
    two = replace(
        s, claims={2: (replace(held, value=7.0),)}, sends={TEAM: ((gone, star),), 2: ((1, 2),)}
    )
    assert one != two and one.key() == two.key()
    for strategy in (
        both("surrogate", NEVER).seat(),
        both("exact", NEVER).seat(),
        rn.opponents_of(setup, both("surrogate", NEVER, opponents="mirror"), 2)[TEAM],
    ):
        got = []
        for state in (one, two):
            at = (setup, state, TEAM, setup.projection, status, returns, np.random.default_rng(3))
            decision = strategy.decide(*at)
            out = policy.queue(
                state, TEAM, decision, 1, setup.max_weekly_adds, False, setup.spots(), setup
            )
            assert out.sends.get(TEAM, ()) == decision.sends
            assert {t: x for t, x in out.sends.items() if t != TEAM} == {
                t: x for t, x in state.sends.items() if t != TEAM
            }
            assert out.claims[2] == state.claims[2]
            got.append((decision, out.claims[TEAM], replace(out, claims={}, sends={})))
        assert got[0] == got[1], strategy
        assert got[0][0].moves and got[0][1], strategy


# --------------------------------------------------------------------------- a mirror rival
def test_a_mirror_rival_takes_the_block_and_keeps_no_threshold():
    """A mirror rival takes the arm's ``bid`` block (PR F2) and keeps the stash threshold at
    None (PR G, ``policy.rival_knobs``). So two arms apart only in the threshold face one rival,
    block and all, and share its decisions; two apart in the block face two. On G's made-up day
    the rival of an arm at a threshold no add clears drops the returning player, as at none,
    and its claim bids by the block. One made-up day, no format named."""
    setup, s, status, returns, star, gone = faab_day(CONTINUOUS)
    rule = bp.of(EVERY_KEY)
    arms = {
        key: both("surrogate", threshold, block, "mirror")
        for key, threshold, block in (
            ("both", NEVER, EVERY_KEY),
            ("block", None, EVERY_KEY),
            ("threshold", NEVER, None),
        )
    }
    rivals = {key: rn.opponents_of(setup, a, 2)[TEAM] for key, a in arms.items()}
    for key, rival in rivals.items():
        assert isinstance(rival, op.Mirror) and rival.knobs["stash_threshold"] is None
        assert rival.bid == arms[key].bid
    assert rivals["both"] == rivals["block"] and repr(rivals["both"]) == repr(rivals["block"])
    assert rivals["both"] != rivals["threshold"] and rivals["both"].bid == rule
    # The arm's own seat keeps the threshold; its rival does not, and bids by the block.
    at = (setup, s, TEAM, setup.projection, status, returns, np.random.default_rng(0))
    own = arms["both"].seat().decide(*at)
    rival, bare = rivals["both"].decide(*at), rivals["threshold"].decide(*at)
    assert [m.add for m in rival.moves] == [m.add for m in own.moves] == [star]
    assert [m.drop for m in rival.moves] == [gone] != [m.drop for m in own.moves]
    assert rival.moves == bare.moves and rival.basis.bid == rule and bare.basis.bid is None
    queue = (1, setup.max_weekly_adds, False, setup.spots(), setup)
    (c,) = policy.queue(s, TEAM, rival, *queue).claims[TEAM]
    (plain,) = policy.queue(s, TEAM, bare, *queue).claims[TEAM]
    assert c.move == plain.move and c.bid != plain.bid


# --------------------------------------------------------------------------- the seasons
#: The seasons: the tier, the waiver rule, the format, the rivals (``mirror``: the arm's own)
#: and the world's seed and path. Each is a found world of G's held league by FAAB
#: (``~/sim-notes/vm/scratch/f2/refit/``; the handoff says what was tried): on it the seat's
#: bids part with the block and its days with the threshold. Each tier is played under each
#: waiver rule, and each of those in one format: the two formats alternate, since what is held
#: (who names, what a claim bids on, where a count goes) reads no format, and the exact tier's
#: season is some four times the surrogate's.
SEASONS = (
    ("surrogate", CONTINUOUS, EACH_CATEGORY, "mirror", (1, 0)),
    ("surrogate", DROPPED, ONE_WIN, QUIET, (1, 0)),
    ("exact", CONTINUOUS, ONE_WIN, QUIET, (1, 1)),
    ("exact", DROPPED, EACH_CATEGORY, RIVALS, (1, 0)),
)
#: The seasons of :data:`SEASONS` in which the seat names a drop on a day a claim of its own
#: is open (the queue's ``replace`` carries both, and the count's reading meets an open claim):
#: every one but the mirror rivals'.
NAMES_BESIDE_A_CLAIM = SEASONS[1:]


def played(setup, arms, rivals, path):
    """One world, a season an arm in seat 1 among ``rivals`` (``mirror``: each arm's own): each
    arm's result, its days and its seats, the returning players dropped counted as a run that
    names a threshold counts them (``run.stash_named``)."""
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *path)
    days: list[list[rn.DayRecord]] = [[] for _ in arms]
    variants = [
        {
            **(
                rn.opponents_of(setup, a, TEAM)
                if rivals == "mirror"
                else dict.fromkeys(setup.teams, rivals)
            ),
            TEAM: a.seat(),
        }
        for a in arms
    ]
    results = rn.simulate(
        setup,
        w,
        variants,
        on_day=lambda r: days[r.variant].append(r),
        stash=rn.stash_named(arms),
    )
    return list(zip(results, days, variants, strict=True))


@pytest.mark.parametrize(
    "case", SEASONS, ids=lambda c: "-".join(x for x in c[:4] if isinstance(x, str))
)
def test_a_season_with_a_block_and_a_threshold_plays_clean_with_both_in_force(case):
    """Every league kind the two meet in (the lesson of Fc's review): FAAB with an IL slot, on
    each tier under each waiver rule. Three arms through one world: the arm that names both,
    the same arm without the block, the same arm without the threshold. The audit finds
    nothing in any season, and in the season of the arm that names both:

    - the block is in force (its bids part from the arm's without it) and so is the threshold
      (its days part from the arm's without it);
    - the seat holds a player, names a drop for him, and a morning takes the name; every day
      the names the state holds are its decision's (no ``replace`` of the queue loses them),
      on a day a claim of its own is open too (:data:`NAMES_BESIDE_A_CLAIM`);
    - its row ends with the bid policy's three counts and then the stash count, and it paid
      what its won claims bid;
    - a market rival holds no value and has no stash count; a mirror rival is made with the
      block and without the threshold (one rival for the two arms that share the block), bids
      by the block, names too and has both counts."""
    tier, rule, h2h, rivals, path = case
    setup = of_format(held_league("categories", "faab", rule), h2h)
    mirror = "mirror" if rivals == "mirror" else "market"
    arms = [
        both(tier, SHARE, opponents=mirror),
        both(tier, SHARE, None, mirror),
        both(tier, None, opponents=mirror),
    ]
    (named, days, seats), (bare, no_block, bare_seats), (loose, no_threshold, loose_seats) = played(
        setup, arms, rivals, path
    )
    assert named.breaches == bare.breaches == loose.breaches == ()
    assert in_force(days, no_block)
    assert [r.state.rosters[TEAM] for r in days] != [r.state.rosters[TEAM] for r in no_threshold]
    # The names.
    assert mornings_named(days)
    assert all(r.state.sends.get(TEAM, ()) == r.decisions[TEAM].sends for r in days)
    beside = [r for r in days if r.state.sends.get(TEAM) and r.state.claims.get(TEAM)]
    assert bool(beside) == (case in NAMES_BESIDE_A_CLAIM)
    # The counts.
    row = named.counts[TEAM]
    assert list(row)[-len(ct.BIDS) - 1 :] == [*ct.BIDS, *ct.STASH]
    assert row["held_stints"] >= 1 and row["forced_drops"] >= 1
    assert row["claims_won"] >= 1 and row["value_won"] > 0
    assert row["returning_dropped"] is not None
    assert row["dollars_spent"] == sum(bid for _, _, bid in decided(days, WON))
    others = [t for t in setup.teams if t != TEAM]
    if rivals != "mirror":
        for t in others:
            assert named.counts[t]["returning_dropped"] is None
            assert named.counts[t]["value_won"] == 0
        return
    rule_ = bp.of(EVERY_KEY)
    for t in others:
        assert seats[t] == loose_seats[t] != bare_seats[t]
        assert seats[t].bid == rule_ and seats[t].knobs["stash_threshold"] is None
        assert bare_seats[t].bid is None
        assert in_force(days, no_block, t)
        assert named.counts[t]["returning_dropped"] is not None
    assert any(mornings_named(days, t) for t in others)
    won = [t for t in others if named.counts[t]["claims_won"]]
    assert won and all(named.counts[t]["value_won"] > 0 for t in won)


def test_a_pair_s_rows_and_its_note_hold_the_bid_s_counts_and_then_the_stash_count():
    """One run's rows and note (``run.paired``, ``cli.paired_blocks``), by FAAB with an IL
    slot: when arm B names a block and a threshold, every row holds the bid policy's three
    counts (a FAAB run's, whatever an arm names) and then the stash count (a named run's
    only), and the note says both; when no arm names a threshold the rows end with the bid
    policy's three and there is no stash count (Fa's lesson, with PR F2's keys in the row).
    The payload lists the arm's block. One format (the league's own, one win): what is held is
    where the keys go, which reads no format."""
    setup = held_league("categories", "faab", CONTINUOUS)

    def world():
        return rn.replay_world(setup, recorded_lines(setup, 11), 1, 1, 0)

    none, named = arm("A", "surrogate"), replace(both("surrogate", SHARE), name="B")
    keys = (*ct.METRICS, *ct.CLAIMS, *ct.BIDS)
    pair = rn.paired(setup, world(), none, named, me=TEAM)
    assert pair["breaches"] == [] and set(pair["counts"]) == {"a", "b", "rivals"}
    assert all(tuple(row) == (*keys, *ct.STASH) for row in pair["counts"].values())
    assert pair["counts"]["b"]["returning_dropped"] is not None
    assert pair["counts"]["b"]["value_won"] > 0
    plain = rn.paired(setup, world(), none, replace(named, knobs=none.knobs), me=TEAM)
    assert all(tuple(row) == keys for row in plain["counts"].values())
    assert plain["counts"]["a"] == {m: pair["counts"]["a"][m] for m in keys}
    # The command's blocks, on the runner's results with what a task adds to one.
    key = {"season": 2024, "forecaster": "prior"}
    task = {"seat": TEAM, "unprojected": {"a": {}, "b": {}}}
    arms = {"a": none, "b": named}
    block = ss.paired_blocks([key], [{**pair, **task}], arms, 1, waivers="faab")["counts"]
    assert block["note"] == ss.counts_note("faab", True)
    assert tuple(block["note"])[-len(ct.PACING) - 1 :] == (*ct.PACING, *ct.STASH)
    cell = block["by_season"]["2024"]["prior"]
    assert cell["b"]["returning_dropped"]["n"] == cell["b"]["value_won"]["n"] == 1
    unnamed = {"a": none, "b": replace(named, knobs=none.knobs)}
    quiet = ss.paired_blocks([key], [{**plain, **task}], unnamed, 1, waivers="faab")["counts"]
    assert quiet["note"] == ss.counts_note("faab") and not set(ct.STASH) & set(quiet["note"])
    assert set(ct.PACING) <= set(quiet["note"])
    assert ss.bid_block(arms) == {"bid": {"b": named.bid.payload()}, "bid_note": ss.BID_NOTE}


# --------------------------------------------------------------------------- the screen
def test_the_screen_s_rows_of_each_pr_keep_the_other_s_setting_in_both_arms():
    """The screen's list holds both PRs' rows (the list's own test names them all). Under a
    baseline that names a ``bid`` block and a stash threshold, in a FAAB league with a held
    slot: the threshold's rows keep the block in both arms and the block's rows keep the
    threshold, each pair apart in its own lever alone; and "did nothing" sets aside the value
    the claims were sized on (PR F2) and never the stash count (PR G), which counts what a
    seat did."""
    shape = policy.Shape(waivers="faab", held=True, h2h=EACH_CATEGORY)
    ctx = sc.Context("categories", "faab", 0.8, sc.NO_RATIO)
    block = {"week": 0.25, "season": 0.25, "routine": 1}
    spec = base({"stash_threshold": 0.5}, bid=block)
    got = {r.key: r for r in sc.rows_of(spec, ["stash_threshold", *BID_NAMES], [shape], ctx)}
    assert {r.lever for r in got.values()} == {"stash_threshold", *BID_NAMES}
    assert all(r.status == sc.PLAY and r.tier == "surrogate" for r in got.values()), got
    rule = bp.of(block)
    for r in got.values():
        a, b = rn.arm_of(r.a), rn.arm_of(r.b)
        assert differ(a, b) == {r.lever}, r.key
        assert rn.same_seat(a, b, [shape]) is None
        if r.lever == "stash_threshold":
            assert a.bid == b.bid == rule
            assert (a.knobs["stash_threshold"], b.knobs["stash_threshold"]) == (0.5, r.values["b"])
        else:
            assert a.knobs["stash_threshold"] == b.knobs["stash_threshold"] == 0.5
            assert a.bid != b.bid
    assert sorted(got["stash_threshold-0"].values.items()) == [("a", 0.5), ("b", 0.0)]
    assert not set(sc.SIZED_ON) & set(ct.STASH) and set(sc.SIZED_ON) <= set(ct.BIDS)
