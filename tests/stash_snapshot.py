"""The moves payloads of made-up leagues with a returning player (#373), as main solved them
before the stash threshold had a reader: the snapshot ``test_stash_threshold`` holds the engine
to with the knob unset. Each case is one of ``test_moves``'s, ``test_churn``'s, ``test_stream``'s
or ``test_season_guard``'s fixtures; the solve's timings are left out.

Run ``PYTHONPATH=src python -m tests.stash_snapshot`` on a main without the reader to write it."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from pickandroll.api import season_moves as sm
from pickandroll.season import Player
from pickandroll.season import moves as mv

from .test_moves import WEEKS, build, il_full_league, keep_league, rates, streaming_league
from .test_season_guard import built_of, resting_league
from .test_stream import stream_league

SNAPSHOT = Path(__file__).parent / "fixtures" / "season" / "stash_none.json"
#: Keys whose values are wall-clock times, not answers.
TIMINGS = ("seconds", "elapsed", "_ms")


def _cleared_league() -> mv.MoveProblem:
    """The streaming league with player 5 back from the IL (Q, his slot's status cleared)."""
    roster, cands, rate, sched, opponent, field = streaming_league()
    rate |= {5: rates(1.0)}
    value = {k: 1.0 for k in rate} | {1: 1.2, 3: 0.1}
    back = (5, Player(5, "Back", "MIN", ("C",), status="Q"))
    p = build(
        roster, cands, rate, sched, opponent, field, held=[back], held_slots={5: "IL"}, value=value
    )
    season = {1: 2.0, 2: 0.3, 3: -0.5, 5: 1.5, 10: 0.8, 11: 0.4}
    return replace(p, season_value=season, season_end=WEEKS[3][6] + timedelta(days=14))


def cases() -> dict[str, mv.MoveProblem]:
    """The leagues, by name: an active player out (O, next Monday; a later date; an open IL
    slot or none), a held player back next Monday (a churn's H and a comeback), one out for the
    season, a cleared player's activation, the streaming and the season guard's leagues."""
    keep = keep_league()
    return {
        "keep_open_il": keep,
        "keep_later_date": replace(keep, returns={5: WEEKS[2][3]}),
        "keep_no_il": replace(keep, held_open={}),
        "keep_low_return": replace(keep, season_value={**keep.season_value, 5: 0.2}),
        "held_o_back_monday": il_full_league([(7, "O")], {7: 0.5}),
        "held_o_worth_little": il_full_league([(7, "O")], {7: 0.05}),
        "held_ofs": il_full_league([(7, "OFS")], {7: 0.1}),
        "held_o_claims": replace(il_full_league([(7, "O")], {7: 0.5}), claims=frozenset({11})),
        "cleared_activation": _cleared_league(),
        "streaming": stream_league()[0],
        "resting": resting_league(),
    }


def _clean(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if not any(t in k for t in TIMINGS)}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    return x


def payload(problem: mv.MoveProblem) -> dict[str, Any]:
    """The moves payload of ``problem`` as the route solves it (activations chosen), timings out,
    through JSON so it compares as the route returns it."""
    _, out = sm.solve(built_of(problem))
    return json.loads(json.dumps(_clean(out), default=str, sort_keys=True))


def snapshot() -> dict[str, Any]:
    return {name: payload(p) for name, p in cases().items()}


if __name__ == "__main__":
    SNAPSHOT.write_text(json.dumps(snapshot(), indent=1, sort_keys=True) + "\n")
    print(SNAPSHOT, SNAPSHOT.stat().st_size)
