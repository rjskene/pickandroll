"""The rivals' adds and bids (#172, PR Fd): a market rival whose view follows the season and that
picks among its best few (the arm's ``opponents`` block, ``view`` and ``among``), the price book
``fit-bids`` writes from the public leagues' winning bids, a rival's bid drawn on it
(``--rival-bids book``), the record, a season with a held slot under the public leagues' rules
and the new rivals, and Rule 1's pins. Made-up leagues and a made-up table,
fixed seeds. A test whose seat weighs runs in both head-to-head formats, or says why it names
one (the format PR's Rule 4); a market rival weighs nothing."""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.sim import bids, policy, shapes
from pickandroll.sim import cli as ss
from pickandroll.sim import opponents as op
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, wk
from pickandroll.sim.shapes import ASSUMED, BOOK, CONTINUOUS
from pickandroll.sim.state import LOST, WON, initial
from tests.sim.sim_league import (
    KNOBS,
    arm,
    every_category,
    make_data_dir,
    make_setup,
    of_format,
    rates,
    recorded_lines,
)
from tests.sim.test_sim_continuous import BLOCK_RULES, block_of, league, season_digest, spots_of

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
FORMATS = (ONE_WIN, EACH_CATEGORY)
KINDS = ("priority", "faab")
DAY = timedelta(1)


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


def decide(strategy, setup, state, team=2, beliefs=None, status=None, g=None):
    return strategy.decide(
        setup,
        state,
        team,
        setup.projection if beliefs is None else beliefs,
        status or {},
        {},
        g if g is not None else np.random.default_rng(0),
    )


def after(g) -> float:
    """The generator's next draw: two generators that drew alike so far give the same."""
    return float(g.random())


# --------------------------------------------------------------------------- the two keys
def test_the_market_keys_are_read_and_a_wrong_one_is_refused_by_name():
    named = {"kind": "market", "rate": 0.3, "view": "season", "among": 3}
    op.check_spec(named)
    assert op.of(named, KNOBS, 0.1) == op.Market(0.3, op.SEASON, 3)
    assert op.of({"kind": "market"}, KNOBS, 0.1) == op.Market(0.1) == op.Market(0.1, op.DRAFT, 1)
    assert op.SPEC_KEYS == ("kind", "rate", "view", "among")
    for spec, words in (
        ({"kind": "market", "view": "weekly"}, "opponents view 'weekly': one of draft, season"),
        ({"kind": "market", "among": 0}, "opponents among 0: a whole number, 1 or more"),
        ({"kind": "market", "among": 1.5}, "opponents among 1.5: a whole number, 1 or more"),
        ({"kind": "market", "among": True}, "opponents among True: a whole number, 1 or more"),
        ({"kind": "market", "among": "3"}, "opponents among '3': a whole number, 1 or more"),
        ({"kind": "static", "view": "season"}, "opponents key 'view' is a market rival's: kind "),
        ({"kind": "mirror", "among": 2}, "opponents key 'among' is a market rival's: kind mirror"),
        ({"kind": "market", "taste": 1}, "opponents key 'taste' is not one the simulator reads"),
    ):
        with pytest.raises(ValueError, match="^" + words.replace("(", r"\(").replace(")", r"\)")):
            op.check_spec(spec)
        body = {"name": "A", "tier": "ranking", "knobs": KNOBS, "opponents": spec}
        with pytest.raises(ValueError, match="opponents"):
            rn.arm_of(body)
    a = rn.arm_of({"name": "A", "tier": "ranking", "knobs": KNOBS, "opponents": named})
    assert a.opponents == named


# --------------------------------------------------------------------------- the season's view
def seasoned():
    """A made-up league, its first day, and three free agents: ``darling``, the draft-day market's
    best by far, and ``riser`` and ``second``, whom the day's beliefs make the best and the second
    best of all."""
    base = make_setup()
    s = initial(base)
    darling, riser, second = sorted(s.pool)[:3]
    setup = replace(base, market={**base.market, darling: 99.0})
    beliefs = {**setup.projection, riser: rates(3.0), second: rates(2.5)}
    return setup, s, darling, riser, second, beliefs


def test_a_rival_that_follows_the_season_picks_on_the_day_s_beliefs():
    setup, s, darling, riser, second, beliefs = seasoned()
    draft = decide(op.Market(1.0), setup, s, beliefs=beliefs)
    season = decide(op.Market(1.0, op.SEASON), setup, s, beliefs=beliefs)
    assert draft.moves[0].add == darling
    view = wk.per_game_values(beliefs, setup.cats, None)
    (m,) = season.moves
    assert m.add == riser == max(s.pool, key=lambda k: (view[k], -k))
    assert m.drop == min(s.active(2), key=lambda k: (view[k], k))
    # A player heard out is not picked under the season's view (the draft-day view picks as it
    # did, status or not); the next best is.
    for status in sorted(wk.OUT_ALL | wk.OUT_THIS_WEEK):
        out = decide(op.Market(1.0, op.SEASON), setup, s, beliefs=beliefs, status={riser: status})
        assert out.moves[0].add == second, status
        assert decide(op.Market(1.0), setup, s, beliefs=beliefs, status={darling: status}).moves[0].add == darling  # fmt: skip
    # A day-to-day player is no seat's out: still picked.
    gtd = decide(op.Market(1.0, op.SEASON), setup, s, beliefs=beliefs, status={riser: "GTD"})
    assert gtd.moves[0].add == riser
    # The view draws nothing: the same generator state after either.
    g1, g2 = np.random.default_rng(4), np.random.default_rng(4)
    decide(op.Market(1.0), setup, s, beliefs=beliefs, g=g1)
    decide(op.Market(1.0, op.SEASON), setup, s, beliefs=beliefs, g=g2)
    assert after(g1) == after(g2)


def test_the_season_s_view_is_computed_once_a_morning_and_is_the_runner_s_value():
    """The runner hands every market rival one beliefs mapping a morning; the view of it is
    computed once and is the figure the runner values the day by (``wk.per_game_values``). A
    new mapping, or the same under other categories or a points table, is valued afresh."""
    setup, _, _, riser, _, beliefs = seasoned()
    view = op.Market._view(setup, beliefs)
    assert view == wk.per_game_values(beliefs, setup.cats, None)
    assert op.Market._view(setup, beliefs) is view
    again = dict(beliefs)
    assert op.Market._view(setup, again) is not view and op.Market._view(setup, again) == view
    fewer = replace(setup, cats=setup.cats[:-1])
    assert op.Market._view(fewer, again) == wk.per_game_values(again, fewer.cats, None)
    memo, table = op._LastView(), {"pts": 1.0, "reb": 1.2}
    assert memo.of(again, setup.cats, None) == view
    on_points = memo.of(again, setup.cats, table)
    assert on_points == wk.per_game_values(again, setup.cats, table)
    assert on_points[riser] == pytest.approx(30.0 + 1.2 * 15.0)  # rates(3.0): 30 points, 15 boards


# --------------------------------------------------------------------------- among
def test_among_one_is_today_s_pick_with_today_s_draws():
    setup, s, *_ = seasoned()
    for seed in range(6):
        g1, g2 = np.random.default_rng(seed), np.random.default_rng(seed)
        assert decide(op.Market(0.6), setup, s, g=g1) == decide(op.Market(0.6, among=1), setup, s, g=g2)  # fmt: skip
        assert after(g1) == after(g2)


def test_among_k_takes_one_of_its_best_k_worth_more_than_its_weakest_each_as_likely():
    base = make_setup(pool=10)
    s = initial(base)
    view = dict(base.market)
    weakest = min(view[k] for k in s.active(2))
    ranked = sorted(s.pool, key=lambda k: (-view[k], k))
    # The best three are worth more than the weakest on the roster; the rest less.
    lift = {k: weakest + 1.0 + i for i, k in enumerate(reversed(ranked[:3]))}
    sink = {k: weakest - 1.0 for k in ranked[3:]}
    setup = replace(base, market={**view, **lift, **sink})
    best = sorted(lift, key=lambda k: -lift[k])
    picks = [decide(op.Market(1.0, among=5), setup, s, g=np.random.default_rng(i)).moves[0].add for i in range(300)]  # fmt: skip
    assert set(picks) == set(best), picks
    counts = [picks.count(k) for k in best]
    assert min(counts) > 60, counts
    # One left above the weakest: still a draw, always him.
    one = replace(setup, market={**setup.market, best[1]: weakest - 1.0, best[2]: weakest - 1.0})
    g = np.random.default_rng(9)
    assert decide(op.Market(1.0, among=3), one, s, g=g).moves[0].add == best[0]
    ref = np.random.default_rng(9)
    ref.random(), ref.random()
    assert after(g) == after(ref)
    # None left: no move.
    none = replace(setup, market={**setup.market, **dict.fromkeys(best, weakest - 1.0)})
    assert decide(op.Market(1.0, among=3), none, s) == policy.NONE


def test_among_draws_after_the_rate_and_before_the_bid_s_noise():
    """In a FAAB league under continuous waivers every pick is a claim and draws its noise: the
    rate's draw, then among's, then the noise; with among 1 the noise is the second draw, as
    before PR Fd. On the book the noise is the draw itself."""
    setup, s, *_ = seasoned()
    faab = replace(setup, waivers="faab", waiver_rule=CONTINUOUS)
    for k, nth in ((1, 2), (3, 3)):
        d = decide(op.Market(1.0, among=k), faab, s, g=np.random.default_rng(11))
        ref = np.random.default_rng(11)
        draws = [ref.random() for _ in range(nth)]
        assert d.basis.noise == (policy.market_noise(_fixed(draws[-1])),)
        book = replace(faab, rival_bids=BOOK, rival_prices=((0.0, 1),))
        b = decide(op.Market(1.0, among=k), book, s, g=np.random.default_rng(11))
        assert b.moves == d.moves and b.basis.noise == (draws[-1],)


class _fixed:
    """A generator whose one draw is ``x``."""

    def __init__(self, x: float) -> None:
        self.x = x

    def random(self) -> float:
        return self.x


# --------------------------------------------------------------------------- the book
def table_rows() -> list[dict[str, str]]:
    """A made-up table: league 1 (four teams, $100) from Monday 2026-10-26 to Monday 2026-11-09,
    two whole weeks, its rivals winning four claims in the first and none in the second, the
    user winning one and losing one (its 'lost' row repeating a rival's win); league 2 (three
    teams, $200) from Wednesday 2026-10-28 to Sunday 2026-11-08, one whole week, two rival wins.
    Every column the fit must not read holds a figure that means nothing."""

    def row(league, teams, budget, at, amount, ours="", our_bid=""):
        return {
            "league": league,
            "teams": teams,
            "faab_budget": budget,
            "at": at,
            "player": "1",
            "name": "Anyone",
            "nba_team": "AAA",
            "amount": amount,
            "with_drop": "1",
            "winner_faab_left": "50",
            "winner_faab_read_at": "",
            "pct_rostered": "",
            "ours": ours,
            "our_bid": our_bid,
        }

    return [
        row("1", "4", "100", "2026-10-26T09:00:00", "0"),
        row("1", "4", "100", "2026-10-27T09:00:00", "0"),
        row("1", "4", "100", "2026-10-29T09:00:00", "5"),
        row("1", "4", "100", "2026-11-01T23:00:00", "10"),
        row("1", "4", "100", "2026-11-02T09:00:00", "3", "won", "3"),
        row("1", "4", "100", "2026-11-01T23:00:00", "10", "lost", "4"),
        row("1", "4", "100", "2026-11-09T09:00:00", "0"),
        row("2", "3", "200", "2026-10-28T09:00:00", "20"),
        row("2", "3", "200", "2026-11-03T09:00:00", "0"),
        row("2", "3", "200", "2026-11-05T09:00:00", "20"),
        row("2", "3", "200", "2026-11-08T09:00:00", "0", "won", "0"),
    ]


def test_the_book_keeps_the_rivals_wins_as_shares_and_counts_whole_weeks():
    book = bids.book_of(table_rows(), "abc")
    assert book["table_sha256"] == "abc" and book["table"] == bids.TABLE
    assert (book["rows_read"], book["rows_kept"]) == (11, 8)
    assert book["leagues"] == ["1", "2"]
    assert (book["first_claim"], book["last_claim"]) == ("2026-10-26", "2026-11-09")
    # league 1: 0, 0, 0, 0.05, 0.1; league 2: 0.1, 0, 0.1 (the 'won' and 'lost' rows left out).
    assert book["prices"] == [[0.0, 4], [0.05, 1], [0.1, 3]]
    # league 1's two whole weeks: four wins over three rivals, then none (the Monday after holds
    # a win, but its week is not whole); league 2's one whole week (Monday 11-02 to Sunday
    # 11-08): two wins over two rivals.
    assert sorted(bids.week_adds(table_rows())) == [0.0, 1.0, 4 / 3]
    adds = book["adds"]
    assert adds["weeks"] == 3 and adds["median"] == 1.0
    assert (adds["q1"], adds["q3"]) == (0.5, pytest.approx(7 / 6))
    assert book["ours"] == {"won": 2, "lost": 1}
    assert book["notes"] == list(bids.NOTES)
    assert any("Monday-to-Sunday weeks" in n for n in bids.NOTES)
    assert any("lower bound" in n for n in bids.NOTES)
    # The columns the fit must not read may hold anything.
    noise = [{**r, **{c: "x" * i for i, c in enumerate(r) if c not in bids.READ}} for r in table_rows()]  # fmt: skip
    assert bids.book_of(noise, "abc") == book
    for bad, words in (
        ({"ours": "maybe"}, "ours 'maybe'"),
        ({"amount": "-1"}, "amount '-1'"),
        ({"at": "Tuesday"}, "claim time 'Tuesday'"),
    ):
        with pytest.raises(bids.BookError, match=words):
            bids.book_of([{**table_rows()[0], **bad}], "abc")
    with pytest.raises(bids.BookError, match="no rival's win"):
        bids.book_of([r for r in table_rows() if r["ours"]], "abc")


def write_table(data: Path, rows: list[dict[str, str]], sha: str | None = None) -> Path:
    folder = data / reader.TABLE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    (folder / bids.TABLE).write_bytes(buf.getvalue().encode())
    digest = sha or hashlib.sha256(buf.getvalue().encode()).hexdigest()
    (folder / f"{bids.TABLE}.sha256").write_text(f"{digest}  {bids.TABLE}\n")
    return folder / bids.TABLE


def fit_bids(data: Path, *extra: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(["--data", str(data), "--rooms", "0", "fit-bids", *extra])
    return code, buf.getvalue()


def test_fit_bids_checks_the_hash_reads_its_columns_and_writes_the_book(tmp_path):
    data = tmp_path / "data"
    code, out = fit_bids(data)
    assert code == 2 and "refused: no winning-bids table at" in out
    write_table(data, table_rows(), sha="0" * 64)
    code, out = fit_bids(data)
    assert code == 2 and "the hash beside it does not match the file" in out
    (data / reader.TABLE_DIR / f"{bids.TABLE}.sha256").unlink()
    code, out = fit_bids(data)
    assert code == 2 and f"no {bids.TABLE}.sha256 beside it" in out
    path = write_table(data, [{k: v for k, v in r.items() if k != "amount"} for r in table_rows()])
    code, out = fit_bids(data)
    assert code == 2 and "no column 'amount'" in out
    path = write_table(data, table_rows())
    code, out = fit_bids(data, "--dry-run")
    assert code == 0 and "dry run, nothing written" in out and "8 rivals' winning bids" in out
    assert not (data / reader.BIDS_DIR).exists()
    code, out = fit_bids(data)
    assert code == 0 and "written: " in out
    book, sha, where = reader.newest_book(data)
    assert where.parent.parent == data / reader.BIDS_DIR and where.name == "book.json"
    assert sha == reader.fit_hash(book) == where.with_name("book.sha256").read_text().strip()
    assert book == bids.book_of(table_rows(), hashlib.sha256(path.read_bytes()).hexdigest())
    # The columns it must not read may hold anything: the same book, the table's hash aside.
    noise = [{**r, **{c: f"#{i}" for i, c in enumerate(r) if c not in bids.READ}} for r in table_rows()]  # fmt: skip
    write_table(data, noise)
    rows, other, _ = reader.bids_rows(data)
    assert other != book["table_sha256"]
    assert {**bids.book_of(rows, other), "table_sha256": None} == {**book, "table_sha256": None}
    # A book edited after it was written is refused.
    where.write_text(json.dumps({**book, "rows_kept": 1}))
    with pytest.raises(reader.SimReadError, match="the hash beside it does not match"):
        reader.newest_book(data)


# --------------------------------------------------------------------------- a bid on the book
PRICES = ((0.0, 2), (0.05, 1), (0.1, 1))


def test_the_book_s_quantile_the_rank_and_the_bid():
    assert [bids.quantile(PRICES, u) for u in (0.0, 0.5, 0.51, 0.75, 0.76, 0.999)] == [
        0.0,
        0.0,
        0.05,
        0.05,
        0.1,
        0.1,
    ]
    day = date(2026, 11, 20)
    fortnight = [(day - (i + 1) * DAY, float(i + 1)) for i in range(12)]
    # Today's moves and the fourteenth day back are not the fortnight before today.
    recent = [*fortnight, (day, 0.0), (day - 14 * DAY, 0.0)]
    assert bids.rank_of(recent, day, 6.5, 14) == (6, 12)
    assert bids.rank_of(recent, day, 0.5, 14) == (0, 12)
    assert bids.book_u(6, 12, 0.5, 10) == 6.5 / 13
    assert bids.book_u(6, 9, 0.25, 10) == 0.25  # under ten moves, the draw alone
    # u = (11 + 0.9) / 13 above 0.75: the top share; x 100 dollars x scale, half up, clamped.
    top = (11.5, recent, day, 50, 1.0, 100, 0.9, PRICES, 14, 10)
    assert bids.book_bid(*top) == 10
    assert bids.book_bid(*top[:4], 1.25, *top[5:]) == 13  # 12.5, half up
    assert bids.book_bid(*top[:3], 7, *top[4:]) == 7  # clamped to the dollars left
    assert bids.book_bid(0.5, recent, day, 50, 1.0, 100, 0.1, PRICES, 14, 10) == 0
    # Under ten moves the rank plays no part.
    few = fortnight[:9]
    assert bids.book_bid(11.5, few, day, 50, 1.0, 100, 0.1, PRICES, 14, 10) == 0
    assert bids.book_bid(0.5, few, day, 50, 1.0, 100, 0.9, PRICES, 14, 10) == 10


def test_a_market_rival_s_claim_on_the_book_carries_the_book_s_bid():
    base = replace(league("faab", pool=12), rival_bids=BOOK, rival_prices=PRICES, rival_scale=2.0)
    x = min(initial(base).pool)
    setup = replace(base, market={**base.market, x: 2 * max(base.market.values())})
    spots, _ = spots_of(setup)
    s = initial(setup)
    decision = decide(op.Market(1.0), setup, s, g=np.random.default_rng(5))
    (move,) = decision.moves
    assert move.add == x
    (u,) = decision.basis.noise
    assert 0 <= u < 1
    out = policy.queue(s, 2, decision, 1, 4, False, spots, setup)
    gain = decision.basis.gains[0]
    want = bids.book_bid(gain, (), s.day, 100, 2.0, 100, u, PRICES, 14, 10)
    assert out.claims[2][0].bid == want == min(100, int(np.floor(2 * 100 * bids.quantile(PRICES, u) + 0.5)))  # fmt: skip
    # The assumed form on the same draw and the same move, as before PR Fd.
    plain = replace(setup, rival_bids=ASSUMED, rival_prices=())
    d2 = decide(op.Market(1.0), plain, s, g=np.random.default_rng(5))
    assert d2.moves == decision.moves and d2.basis.noise == (policy.market_noise(_fixed(u)),)


def test_the_rivals_bids_out_of_the_plan_are_refused_by_name():
    for kw, words in (
        ({"rival_bids": "book"}, "rival bids book with waivers none: a rival's bid is a FAAB"),
        ({"waivers": "priority", "rival_bids": "book"}, "rival bids book with waivers priority"),
        ({"waivers": "faab", "rival_bids": "fitted"}, "rival bids 'fitted' is not one of assumed"),
    ):
        with pytest.raises(ValueError, match=words):
            shapes.LeagueRules(**kw)
    assert shapes.parse_rival_bids("faab", None) == ASSUMED
    assert shapes.parse_rival_bids("faab", " Book ") == BOOK
    for waivers, named, words in (
        ("none", "book", "--rival-bids book: a rival's bid is a FAAB league's; it is read only"),
        ("priority", "assumed", "--rival-bids assumed: a rival's bid is a FAAB league's"),
        ("faab", "fitted", "--rival-bids fitted: one of assumed, book"),
    ):
        with pytest.raises(ValueError, match=words):
            shapes.parse_rival_bids(waivers, named)
    base = make_setup()
    with pytest.raises(ValueError, match="rival bids on the book need a FAAB league"):
        replace(base, waivers="faab", rival_bids=BOOK)
    with pytest.raises(ValueError, match="rival bids on the book need a FAAB league"):
        replace(base, waivers="priority", rival_bids=BOOK, rival_prices=PRICES)


def test_the_label_and_the_payload_say_the_book():
    plain = shapes.LeagueRules(waivers="faab")
    book = shapes.LeagueRules(waivers="faab", rival_bids=BOOK, rival_prices=PRICES)
    assert plain.label().endswith("$100 a team, the rivals' bids x1")
    assert book.label().endswith("$100 a team, the rivals' bids on the book x1")
    assert plain.payload()["rival_bids"] == ASSUMED and book.payload()["rival_bids"] == BOOK
    assert list(plain.payload())[-3:] == ["budget", "rival_scale", "rival_bids"]
    # The prices are data, not a rule: never in the label, the payload or the repr.
    assert "0.05" not in book.label() + json.dumps(book.payload()) + repr(book)
    assert "rival_bids" not in shapes.LeagueRules(waivers="priority").payload()
    assert ss.faab_note(book) == ss.FAAB_NOTE.replace(ss.FAAB_ASSUMED, ss.FAAB_BOOK)
    assert ss.faab_note(plain) == ss.FAAB_NOTE and ss.FAAB_NOTE.count(ss.FAAB_ASSUMED) == 1
    both = replace(book, waiver_rule=CONTINUOUS)
    assert ss.faab_note(both) == ss.FAAB_NOTE_CONTINUOUS.replace(ss.FAAB_ASSUMED, ss.FAAB_BOOK)


# --------------------------------------------------------------------------- the claims meet
#: The world's seed and path on which, for every waiver kind and format, the surrogate seat in seat
#: 1 both wins a claim and loses one among rivals that follow the season (found as its docstring
#: says, ``~/sim-notes/vm/scratch/fd/meet_path.py``).
MEET_PATH = (1, 0)


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("waivers", KINDS)
def test_rivals_that_follow_the_season_meet_the_seat_s_claims(waivers, h2h):
    """The claims meet at all (the lesson of D4c): a six-week made-up league of four seats and
    twelve free agents under continuous waivers, the surrogate in seat 1 among market rivals at
    0.6 a day that follow the season and pick among their best three (by FAAB on a made-up book);
    the seat both wins a claim and loses one, and the audit finds nothing. MEET_PATH is the first
    of seeds 1 and 2 and paths 0 to 2, tried in that order, on which it does in both kinds and
    both formats."""
    setup = of_format(league(waivers, pool=12), h2h)
    if waivers == "faab":
        setup = replace(setup, rival_bids=BOOK, rival_prices=PRICES)
    u = arm("U", "surrogate", opponents="market")
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *MEET_PATH)
    seen: list = []
    variant = {**{t: op.Market(0.6, op.SEASON, 3) for t in setup.teams}, 1: u.seat()}
    (result,) = rn.simulate(setup, w, [variant], on_day=lambda r: seen.append(r.state))
    assert result.breaches == ()
    mine = [r for s in seen for r in s.resolved if r.team == 1]
    assert any(r.outcome == WON for r in mine) and any(r.outcome == LOST for r in mine), mine
    rivals = [r for s in seen for r in s.resolved if r.team != 1 and r.outcome == WON]
    assert rivals, "the rivals won no claim"


#: The first of seeds 1 to 3 and paths 0 to 2, tried in that order, on which the season below
#: plays as its test says in both formats (``~/sim-notes/vm/scratch/fd/held_public.py``; all nine
#: do).
HELD_PUBLIC_PATH = (1, 0)


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_season_with_a_held_slot_under_the_public_rules_and_the_new_rivals_plays_clean(h2h):
    """Every new kind played with held slots once (the lesson of Fc's finding 1): a six-week
    made-up league of four seats with an IL slot and twelve free agents under the public leagues'
    rules (FAAB, continuous waivers, a dropped player after two days, $100), the rivals' bids on a
    made-up book, the surrogate in seat 1 among market rivals at 0.6 a day that follow the season
    and pick among their best three. The audit finds nothing, the seat makes a held stint that
    ends and wins a claim, and the rivals win claims. The public leagues count every category;
    the test runs one win too (the format PR's Rule 4)."""
    base = league("faab", held_slots=("IL",), pool=12)
    setup = of_format(replace(base, rival_bids=BOOK, rival_prices=PRICES), h2h)
    assert (setup.waiver_rule, setup.waiver_days, setup.budget) == (CONTINUOUS, 2, 100)
    u = arm("U", "surrogate", opponents="market")
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *HELD_PUBLIC_PATH)
    seen: list = []
    variant = {**{t: op.Market(0.6, op.SEASON, 3) for t in setup.teams}, 1: u.seat()}
    (result,) = rn.simulate(setup, w, [variant], on_day=lambda r: seen.append(r.state))
    assert result.breaches == ()
    assert result.counts[1]["held_stints"] >= 1
    held = [{k for k, slot in s.rosters[1] if slot in mv.HELD} for s in seen]
    active = [set(s.active(1)) for s in seen]
    ended = {k for i, h in enumerate(held) for k in h if any(k in a for a in active[i + 1 :])}
    assert ended, "no held stint of the seat ended"
    assert any(r.team == 1 and r.outcome == WON for s in seen for r in s.resolved)
    assert any(r.team != 1 and r.outcome == WON for s in seen for r in s.resolved)


# --------------------------------------------------------------------------- the record
@pytest.fixture(scope="module")
def wire(tmp_path_factory) -> Path:
    """The made-up seasons with a wire of 120, a fit, a made-up table and its book, and a pair of
    a ranking and a static arm among market rivals that follow the season at 0.5 a day and pick
    among their best three."""
    data = make_data_dir(tmp_path_factory.mktemp("rivals-wire"), wire=120)
    with contextlib.redirect_stdout(io.StringIO()):
        assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    write_table(data, table_rows())
    assert fit_bids(data)[0] == 0
    rivals = {"kind": "market", "rate": 0.5, "view": "season", "among": 3}
    for name, tier in (("RS", "ranking"), ("SS", "static")):
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": rivals}
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


def replay(data: Path, *extra: str) -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024", "--workers", "1"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main([*argv, "--seed", "5", *extra])
    return code, buf.getvalue()


def written(out: str) -> dict:
    (line,) = [x for x in out.splitlines() if x.startswith("written: ")]
    return json.loads(Path(line.removeprefix("written: ")).read_text())


def test_the_rival_bids_out_of_the_plan_are_refused_by_name_before_any_path(wire: Path, tmp_path):
    pair = ("--arms", str(wire / "RS.json"), str(wire / "SS.json"), "--paths", "1", "--dry-run")
    for flags, why in (
        (("--rival-bids", "book"), "--rival-bids book: a rival's bid is a FAAB league's"),
        (("--waivers", "faab", "--rival-bids", "fitted"), "--rival-bids fitted: one of assumed, "),
    ):
        code, out = replay(wire, *pair, *flags)
        assert code == 2 and f"refused: {why}" in out, out
        assert "tasks (" not in out
    # No book on file: refused by name, before any path.
    bare = make_data_dir(tmp_path, seasons=(2023, 2024), wire=120)
    with contextlib.redirect_stdout(io.StringIO()):
        assert ss.main(["--data", str(bare), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    code, out = replay(bare, *pair, "--waivers", "faab", "--rival-bids", "book")
    assert code == 2 and "refused: no price book under" in out, out


def test_a_run_on_the_book_records_its_rules_its_book_and_the_arms_rival_keys(wire: Path):
    """``--waivers faab --waiver-rule continuous --rival-bids book``, the arms naming rivals that
    follow the season among their best three: the league block's rules name the book, its FAAB
    note says how a rival bids on it, the book's hash, file and table hash are recorded with the
    fit's, the arms' opponents blocks are recorded as given, and the audit finds nothing. A room
    (one path; a pair's paths are rounded up to the league's twelve seats) records all of it,
    though its seats are all arms: the paired dry run after it plays one path with the rivals
    bidding on the book, and ``test_rivals_that_follow_the_season_meet_the_seat_s_claims`` holds
    what they do. The line that says the rules is the one a dry run and the no-peek check print."""
    room = ("--seats", str(wire / "RS.json"), str(wire / "SS.json"), "--paths", "1")
    rules = ("--waivers", "faab", "--waiver-rule", "continuous", "--rival-bids", "book")
    code, out = replay(wire, *room, *rules)
    assert code == 0, out
    label = shapes.LeagueRules(waivers="faab", waiver_rule=CONTINUOUS, rival_bids=BOOK).label()
    assert f"league rules, on every path: {label}" in out and "on the book" in label
    p = written(out)
    assert p["replay_version"] == ss.REPLAY_VERSION == 20
    assert "13: the rivals' adds and bids" in p["replay_version_why"]
    assert p["league"]["rules"]["rival_bids"] == BOOK
    assert p["league"]["faab_note"] == ss.FAAB_NOTE_CONTINUOUS.replace(
        ss.FAAB_ASSUMED, ss.FAAB_BOOK
    )
    book, sha, where = reader.newest_book(wire)
    assert (p["book_sha"], p["book_file"]) == (sha, str(where))
    assert p["book_table_sha256"] == book["table_sha256"]
    want = {"kind": "market", "rate": 0.5, "view": "season", "among": 3}
    assert [v["opponents"] for v in p["specs"].values()] == [want, want]
    assert p["audit"]["paths_voided"] == 0 and p["audit"]["breaches"] == []
    # The pair, its rivals bidding on the book: one path plays, clean.
    pair = ("--arms", str(wire / "RS.json"), str(wire / "SS.json"), "--paths", "1", "--dry-run")
    code, out = replay(wire, *pair, *rules)
    assert code == 0 and f"league rules, on every path: {label}" in out, out
    assert "written: " not in out
    # Without the book named, a FAAB run reads none and records none.
    code, out = replay(wire, *room, "--waivers", "faab", "--dry-run")
    assert code == 0 and "on the book" not in out, out


# --------------------------------------------------------------------------- Rule 1
#: Rule 1's pins: Fc's made-up season (``test_sim_continuous.season_digest``, seed 1, path 0) with
#: nothing new named, without waivers and under continuous waivers by priority in one win and by
#: FAAB under every category, as main ``9602e3f`` (Fc's merge, #423) gives them
#: (``~/sim-notes/vm/scratch/fd/rule1_pins.py``: the same digests on Fc's head ``7fa6f15``, on
#: main and on this PR); the dropped rule's are Fc's own (``BEFORE_PRIORITY``, ``BEFORE_FAAB``).
FC_NONE = "5590c9bdfb24161164e8c7af29e901c224ffb94f87a12d15729a8ca11b308a11"
FC_PRIORITY_CONTINUOUS = "74b1a3dd5b76b82beb4d43dc3fef2ba7707f9c662cd204f0670da0d885c1d61f"
FC_FAAB_CONTINUOUS = "ce8652605209047fc0b893ca8550b747352517adb21f6828c8f95cd6e9bd6ea7"


def test_rule_1_with_nothing_new_named_a_season_plays_as_fc_s():
    base = make_setup(teams=4, pool=12)
    priority = replace(base, waivers="priority", waiver_days=2, waiver_rule=CONTINUOUS)
    faab = every_category(replace(base, waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS))
    assert faab.rival_bids == ASSUMED and faab.rival_prices == ()
    assert season_digest(base) == FC_NONE
    assert season_digest(priority) == FC_PRIORITY_CONTINUOUS
    assert season_digest(faab) == FC_FAAB_CONTINUOUS


#: The league block with nothing new named, every key byte for byte as main ``9602e3f`` gives it,
#: as Fc's head ``7fa6f15`` did (the rules' ``rival_bids`` aside: ``assumed`` in every FAAB run, absent in every other), over
#: Fc's six rules and three under continuous waivers (``rule1_pins.py``).
BLOCKS_FC = "42445c1b9de1ea4b33678bf4241ff1b8e31909263e45a9ca430d1acaaaa378d2"
BLOCK_RULES_FD = (
    *BLOCK_RULES,
    shapes.LeagueRules(waivers="priority", waiver_rule=CONTINUOUS),
    shapes.LeagueRules(waivers="faab", waiver_rule=CONTINUOUS),
    shapes.LeagueRules(
        waivers="faab", h2h=EACH_CATEGORY, waiver_rule=CONTINUOUS, budget=50, rival_scale=0.5
    ),
)


def test_rule_1_with_nothing_new_named_the_league_block_and_its_notes_are_fc_s():
    blocks = []
    for rules in BLOCK_RULES_FD:
        block = block_of(rules)
        got = block["rules"].pop("rival_bids", None)
        assert got == (ASSUMED if rules.bidding else None), (rules, got)
        assert ss.FAAB_BOOK not in json.dumps(block)
        blocks.append(block)
    assert hashlib.sha256(json.dumps(blocks, sort_keys=True).encode()).hexdigest() == BLOCKS_FC
