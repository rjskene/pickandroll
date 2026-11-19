"""The gate (#172, PR 1), a pure function on what ``checks`` samples; the command (``cli``)
builds the replay it runs on.

5. Surrogate: over five sampled league-days its sets keep at least 95% of the exact search's
   gain, for each of three seats of a replay (PR D3). The rule since PR g5 (the user's ruling of
   2026-11-18); it replaced "the identical set on four of the five days", which asked more than
   the gate is for: whether the fast seat can stand in for the exact one.

Gates 2, 3 and 6 read a live league's recorded weeks, scorecard and exports, and gates 1 and 4
scored the drawn world's team weeks and absences against the hold-out and the logs; all five
went with the standalone cut (PR D3). The number is the one gate 5 has always had.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The share of the exact search's gain a seat's surrogate must keep (the user, 2026-11-18).
SURROGATE_KEEPS = 0.95
#: The league-days sampled for a seat; a seat with fewer compared fails.
SURROGATE_OF = 5
#: A float's last bits never decide: the bar is lowered by this much, far below the least gain a
#: move must make (``policy.MIN_GAIN``, a hundredth).
EPS = 1e-9


@dataclass(frozen=True)
class Gate:
    """One gate's verdict on one season (or ``None`` for pooled data) with its evidence."""

    name: str
    passed: bool
    season: int | str | None
    detail: dict[str, Any] = field(default_factory=dict)


def gains(records: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Each tier's gain over ``records`` (compared days, ``checks.surrogate_records``): its set's
    worth less the worth of standing still, summed over the days."""
    return {
        tier: float(sum(r["worth"][tier] - r["worth"]["standing"] for r in records))
        for tier in ("exact", "surrogate")
    }


def keeps(exact: float, surrogate: float, share: float = SURROGATE_KEEPS) -> bool:
    """Whether a surrogate's gain keeps ``share`` of the exact search's: one inequality and no
    division, ``surrogate >= share x exact``, less :data:`EPS`. So an exact tier that stood still
    (a gain of 0) asks only that the surrogate lose nothing, and a surrogate that found more than
    the exact tier passes. An exact gain below 0 is not one the exact search gives (it keeps a
    set only for a gain); there the bar is the exact gain itself, so the same sets never fail."""
    bar = share * exact if exact > 0 else exact
    return surrogate >= bar - EPS


def surrogate_gate(
    records: Sequence[Mapping[str, Any]],
    season: int | str | None = None,
    needs: float = SURROGATE_KEEPS,
    of: int = SURROGATE_OF,
) -> Gate:
    """Gate 5 for one seat, on its sampled days' records (``checks.surrogate_records``): the seat
    passes when all ``of`` days were compared and, summed over them, the surrogate's gain keeps
    ``needs`` of the exact search's (:func:`gains`, :func:`keeps`). A day left out is not
    compared, so a seat with one fails. The detail: the days on which the two sets are equal
    (``matched``, information: it does not decide) of the days compared (``of``), the two gains
    (``gain``), the share kept (``kept``, the surrogate's gain over the exact search's; None when
    the exact gain is not above 0, where there is no share to name) and the share needed
    (``needs``)."""
    compared = [r for r in records if r["left_out"] is None][:of]
    gain = gains(compared)
    exact, surrogate = gain["exact"], gain["surrogate"]
    return Gate(
        "surrogate",
        len(compared) == of and keeps(exact, surrogate, needs),
        season,
        {
            "matched": sum(bool(r["equal"]) for r in compared),
            "of": len(compared),
            "gain": gain,
            "kept": surrogate / exact if exact > 0 else None,
            "needs": needs,
        },
    )
