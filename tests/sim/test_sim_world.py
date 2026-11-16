"""What is left of the world's draws (#172, PR 1; PR D3): the seeded generator, an oracle's
error and the streams' numbers. The drawn world (game lines, minutes, absences, the refresh)
went with the standalone cut."""

from __future__ import annotations

import numpy as np
import pytest

from pickandroll.sim import world as w


def test_an_oracles_error_is_drawn_alike_and_the_streams_keep_their_numbers():
    eps = w.errors(1, 3, ["a", "b"], ["pts"], 0.0, {}, {"pts": 0.1})
    assert eps == w.errors(1, 3, ["a", "b"], ["pts"], 0.0, {}, {"pts": 0.1})
    assert eps != w.errors(1, 4, ["a", "b"], ["pts"], 0.0, {}, {"pts": 0.1})
    # Every recorded path reads the news, market and oracle streams by these numbers; the
    # removed streams keep theirs, so none moves.
    assert dict(w.STREAMS) == {
        "error": 0,
        "minutes": 1,
        "line": 2,
        "absence": 3,
        "duration": 4,
        "refresh": 5,
        "news": 6,
        "market": 7,
        "forecast": 8,
        "draft": 9,
    }


def test_errors_have_the_shrunk_mean_and_the_spread():
    players = [f"p{i}" for i in range(3000)]
    gap = {p: {"pts": 0.4} for p in players}
    eps = w.errors(5, 0, players, ["pts"], 0.5, gap, {"pts": 0.2})
    draws = np.array([eps[p]["pts"] for p in players])
    assert abs(draws.mean() + 0.2) < 0.02
    assert abs(draws.std() - 0.2) < 0.02
    truth = w.true_rates({"p0": {"pts": 10.0}}, {"p0": {"pts": np.log(1.1)}})
    assert truth["p0"]["pts"] == pytest.approx(11.0)
