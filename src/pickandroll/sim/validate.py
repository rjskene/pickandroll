"""The gate (#172, PR 1), a pure function on what ``checks`` samples; the command (``cli``)
builds the replay it runs on.

5. Surrogate: its set equals the exact set on four of five sampled league-days, for each of
   three seats of a replay (PR D3).

Gates 2, 3 and 6 read a live league's recorded weeks, scorecard and exports, and gates 1 and 4
scored the drawn world's team weeks and absences against the hold-out and the logs; all five
went with the standalone cut (PR D3). The number is the one gate 5 has always had.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

SURROGATE_NEEDED = 4
SURROGATE_OF = 5


@dataclass(frozen=True)
class Gate:
    """One gate's verdict on one season (or ``None`` for pooled data) with its evidence."""

    name: str
    passed: bool
    season: int | str | None
    detail: dict[str, Any] = field(default_factory=dict)


def surrogate_gate(
    matches: Sequence[bool],
    season: int | str | None = None,
    needed: int = SURROGATE_NEEDED,
    of: int = SURROGATE_OF,
) -> Gate:
    """Gate 5: the surrogate's set equal to the exact set on ``needed`` of the ``of`` sampled
    league-days."""
    m = [bool(x) for x in matches][:of]
    return Gate(
        "surrogate",
        len(m) == of and sum(m) >= needed,
        season,
        {"matched": sum(m), "of": len(m), "needed": needed},
    )
