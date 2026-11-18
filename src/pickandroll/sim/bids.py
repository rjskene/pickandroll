"""The rivals' price book (#172, PR Fd): what the public leagues' managers paid for the claims they
won, and a market rival's bid drawn on it.

Pure: the book from the winning-bids table's rows (:func:`book_of`), its quantile
(:func:`quantile`) and a rival's bid on it (:func:`book_bid`). Reading the table, checking its hash
and writing the book are ``sim.readers``' and the ``fit-bids`` command's. Nothing here is
imported from ``pickandroll.api``: the table's column names and its marks of the user's own claims
are restated (``api/sim_bids.py`` wrote the table).

**The book** (``data/sim/bids/<date>/book.json``, never committed):

- ``prices``: the rivals' winning bids (the rows whose ``ours`` is empty) as shares of their
  league's budget, ``amount / faab_budget``, as the distinct shares with their counts;
- ``adds``: the rivals' wins per rival team (``teams - 1``) per league-week, Monday to Sunday by the
  claim's date, over the whole weeks inside a league's first and last claim dates in the table (a
  week with no rival win counts 0): the median and the quartiles over the league-weeks;
- ``ours``: the user's claims won and lost in the table.

A ``lost`` row repeats a rival's win already in the table (beside the user's losing bid) and a
``won`` row is the user's own rule, so neither is a price. The fit reads no player and no team:
of the table's columns only :data:`READ`.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

#: The table the book is fitted on, under ``data/external/bids/``, with its ``.sha256`` beside it.
TABLE = "winning_bids.csv"
#: The only columns of the table the fit reads (the table's own names, restated).
READ = ("league", "teams", "faab_budget", "at", "amount", "ours", "our_bid")
#: ``ours``: a rival's win (empty), the user's win, the user's lost claim beside the rival's win.
RIVAL, WON, LOST = "", "won", "lost"
#: What the book says it does not model (the README's list), in its ``notes``.
NOTES = (
    (
        "the book is of winning bids, not of all bids: where several claims meet, a rival drawn "
        "on it bids as a winner did, so the simulated winning prices sit above the book"
    ),
    (
        "the table holds a few weeks of one season, its leagues' own team counts and budgets: "
        "late-season bidding is assumed alike, and --rival-scale is the sweep"
    ),
    "a rival's bid on the book reads neither its dollars left (beyond the clamp) nor the player",
    (
        "the market rivals' rate and among are the arm's, set by hand against adds and ours: no "
        "figure of the book is a default in the code"
    ),
    "one view for every rival: among stands for the managers' different tastes and needs",
    (
        "adds is a lower bound: each read of a league keeps a limited number of transactions, so "
        "a busy week's wins can be missed"
    ),
    (
        "adds counts the whole Monday-to-Sunday weeks inside a league's first and last claim "
        "dates in the table, a week with no rival win counted 0"
    ),
)


class BookError(ValueError):
    """The table's rows cannot make a book, in words."""


def _day(at: str) -> date:
    try:
        return datetime.fromisoformat(at).date()
    except ValueError:
        raise BookError(f"claim time {at!r}: not an ISO date and time") from None


def _number(value: str, column: str) -> float:
    try:
        x = float(value)
    except ValueError:
        raise BookError(f"{column} {value!r}: not a number") from None
    if not math.isfinite(x) or x < 0:
        raise BookError(f"{column} {value!r}: not a number of 0 or more")
    return x


def _spread(xs: Sequence[float]) -> dict[str, float | int | None]:
    """The median and the quartiles of ``xs`` (inclusive quartiles), and how many there are."""
    if not xs:
        return {"weeks": 0, "q1": None, "median": None, "q3": None}
    if len(xs) == 1:
        return {"weeks": 1, "q1": xs[0], "median": xs[0], "q3": xs[0]}
    q1, mid, q3 = statistics.quantiles(xs, n=4, method="inclusive")
    return {"weeks": len(xs), "q1": q1, "median": mid, "q3": q3}


def week_adds(rows: Sequence[Mapping[str, str]]) -> list[float]:
    """The rivals' wins per rival team in each whole league-week of ``rows``: by league, the
    Monday-to-Sunday weeks whose Monday is on or after the league's first claim date and whose
    Sunday is on or before its last, each week's rival wins over the league's ``teams - 1``."""
    by_league: dict[str, list[Mapping[str, str]]] = {}
    for r in rows:
        by_league.setdefault(r["league"], []).append(r)
    out: list[float] = []
    for league in sorted(by_league):
        mine = by_league[league]
        teams = {r["teams"] for r in mine}
        if len(teams) != 1:
            raise BookError(f"league {league}: its rows disagree on the teams ({sorted(teams)})")
        n = int(_number(teams.pop(), "teams"))
        if n < 2:
            raise BookError(f"league {league}: {n} team, no rival")
        days = [_day(r["at"]) for r in mine]
        first, last = min(days), max(days)
        monday = first + timedelta((7 - first.weekday()) % 7)
        wins = Counter(_day(r["at"]) for r in mine if r["ours"] == RIVAL)
        while monday + timedelta(6) <= last:
            got = sum(wins[monday + timedelta(i)] for i in range(7))
            out.append(got / (n - 1))
            monday += timedelta(7)
    return out


def book_of(rows: Iterable[Mapping[str, str]], table_sha256: str) -> dict[str, Any]:
    """The book from the table's ``rows`` (each holding at least :data:`READ`, as
    ``readers.bids_rows`` gives them) and the table's hash. BookError, in words, on a row it
    cannot read."""
    rows = [{k: r[k] for k in READ} for r in rows]
    if not rows:
        raise BookError("the table has no row")
    for r in rows:
        if r["ours"] not in (RIVAL, WON, LOST):
            raise BookError(f"ours {r['ours']!r}: one of empty, {WON!r}, {LOST!r}")
    kept = [r for r in rows if r["ours"] == RIVAL]
    if not kept:
        raise BookError("the table holds no rival's win")
    shares: Counter[float] = Counter()
    for r in kept:
        budget = _number(r["faab_budget"], "faab_budget")
        if budget <= 0:
            raise BookError(f"league {r['league']}: a budget of {r['faab_budget']!r}")
        shares[_number(r["amount"], "amount") / budget] += 1
    days = [_day(r["at"]) for r in rows]
    ours = Counter(r["ours"] for r in rows)
    return {
        "table": TABLE,
        "table_sha256": table_sha256,
        "rows_read": len(rows),
        "rows_kept": len(kept),
        "leagues": sorted({r["league"] for r in rows}),
        "first_claim": min(days).isoformat(),
        "last_claim": max(days).isoformat(),
        "prices": [[s, shares[s]] for s in sorted(shares)],
        "adds": {
            "unit": "the rivals' wins per rival team per league-week",
            **_spread(week_adds(rows)),
        },
        "ours": {"won": ours[WON], "lost": ours[LOST]},
        "notes": list(NOTES),
    }


def prices_of(book: Mapping[str, Any]) -> tuple[tuple[float, int], ...]:
    """A book's prices as ``state.Setup`` carries them: (share, count), the shares ascending.
    BookError, in words, on prices that are not."""
    out = tuple((float(s), int(n)) for s, n in book.get("prices", ()))
    if not out or any(n < 1 for _, n in out) or any(s < 0 for s, _ in out):
        raise BookError("the book's prices: none, or a count below 1, or a share below 0")
    if [s for s, _ in out] != sorted({s for s, _ in out}):
        raise BookError("the book's prices: each share once, ascending")
    return out


def quantile(prices: Sequence[tuple[float, int]], u: float) -> float:
    """The book's quantile: the least share at or below which a fraction ``u`` (0 to 1) of the
    kept bids falls, over ``prices`` (share, count), the shares ascending."""
    total = sum(n for _, n in prices)
    need = u * total
    seen = 0
    for share, n in prices:
        seen += n
        if seen >= need:
            return share
    return prices[-1][0]


def rank_of(
    recent: Sequence[tuple[date, float]], day: date, gain: float, days: int
) -> tuple[int, int]:
    """How many of the market rivals' moves of the ``days`` before ``day`` (``state.market_recent``,
    the pool ``policy.market_typical`` reads) gained less than ``gain`` on the view, and how many
    there are."""
    since = day - timedelta(days)
    gains = [x for d, x in recent if since < d < day]
    return sum(1 for x in gains if x < gain), len(gains)


def book_u(below: int, n: int, noise: float, least: int) -> float:
    """Where on the book a rival's bid is drawn: ``(below + noise) / (n + 1)``, its move's rank
    among the fortnight's ``n`` market moves smoothed by its noise draw on [0, 1); the draw alone
    until there are ``least`` such moves."""
    return noise if n < least else (below + noise) / (n + 1)


def book_bid(
    gain: float,
    recent: Sequence[tuple[date, float]],
    day: date,
    dollars: int,
    scale: float,
    budget: int,
    noise: float,
    prices: Sequence[tuple[float, int]],
    days: int,
    least: int,
) -> int:
    """A market rival's bid on the book: ``round(scale x budget x Q(u))`` whole dollars, half up
    (as ``bid_of`` rounds), at least 0 and at most its ``dollars`` left, ``Q`` the book's
    :func:`quantile` and ``u`` :func:`book_u` of its move's rank (:func:`rank_of`)."""
    below, n = rank_of(recent, day, gain, days)
    price = scale * budget * quantile(prices, book_u(below, n, noise, least))
    return max(0, min(int(dollars), math.floor(price + 0.5)))


__all__ = [
    "LOST",
    "NOTES",
    "READ",
    "RIVAL",
    "TABLE",
    "WON",
    "BookError",
    "book_bid",
    "book_of",
    "book_u",
    "prices_of",
    "quantile",
    "rank_of",
    "week_adds",
]
