"""Gate 5's verdict (#172, PR 1; PR D3: the gates of the drawn world went; PR g5: a seat passes on
the gain its surrogate keeps, the user's ruling of 2026-11-18). The pure rule, on records written
by hand in the shape ``checks.surrogate_records`` gives: no league is played here."""

from __future__ import annotations

import pytest

from pickandroll.sim import validate as v

#: What standing still is worth on every made-up day below: a gain is a worth less this.
STANDING = 10.0


def day(exact: float, surrogate: float, equal: bool | None = None, standing: float = STANDING):
    """One compared day's record: each tier's gain over standing still, and whether the two sets
    are equal (by default, when they gain alike; a test of two sets of one worth says False)."""
    return {
        "day": "2023-10-24",
        "left_out": None,
        "equal": exact == surrogate if equal is None else equal,
        "worth": {
            "exact": standing + exact,
            "surrogate": standing + surrogate,
            "standing": standing,
        },
    }


LEFT_OUT = {"day": "2024-04-20", "left_out": "outside the calendar's weeks"}


def test_a_seat_that_keeps_everything_passes_and_says_what_it_kept():
    g = v.surrogate_gate([day(0.5, 0.5)] * 5, season=2024)
    assert g.passed and (g.name, g.season) == ("surrogate", 2024)
    assert g.detail == {
        "matched": 5,
        "of": 5,
        "gain": {"exact": pytest.approx(2.5), "surrogate": pytest.approx(2.5)},
        "kept": pytest.approx(1.0),
        "needs": v.SURROGATE_KEEPS,
    }
    assert v.SURROGATE_KEEPS == 0.95 and v.SURROGATE_OF == 5
    # The rule the gain replaced is gone, not kept beside.
    assert not hasattr(v, "SURROGATE_NEEDED") and "needed" not in g.detail


def test_the_bar_is_the_share_of_the_exact_gain():
    # The exact tier gains 2 over the five days; the surrogate must keep 1.9 of it.
    exact = [day(0.4, 0.4)] * 4
    above = v.surrogate_gate([*exact, day(0.4, 0.31)])
    below = v.surrogate_gate([*exact, day(0.4, 0.29)])
    assert above.passed and above.detail["kept"] == pytest.approx(0.955)
    assert not below.passed and below.detail["kept"] == pytest.approx(0.945)
    # Each differs on one day of five: the count of equal days is information and decides nothing.
    assert above.detail["matched"] == below.detail["matched"] == 4


def test_different_sets_of_equal_worth_on_every_day_pass():
    """The point of the change: the surrogate's set is never the exact tier's, and is worth as
    much every day. Under the rule replaced (equal sets on four days of five) this seat failed."""
    g = v.surrogate_gate([day(0.3, 0.3, equal=False)] * 5)
    assert g.passed
    assert g.detail["matched"] == 0 and g.detail["kept"] == pytest.approx(1.0)


def test_the_gain_is_summed_over_the_days_then_compared():
    # One day keeps half and the five together keep enough: the seat passes on the sum.
    g = v.surrogate_gate([day(0.2, 0.1), *[day(1.0, 1.0)] * 4])
    assert g.passed and g.detail["kept"] == pytest.approx(4.1 / 4.2)
    # A day above the exact tier's makes up a day below it.
    assert v.surrogate_gate([day(0.5, 0.2), day(0.5, 0.8), *[day(0.5, 0.5)] * 3]).passed
    # Four equal days do not carry a fifth that loses too much: this seat passed the rule replaced.
    g = v.surrogate_gate([*[day(0.1, 0.1)] * 4, day(1.0, 0.5)])
    assert not g.passed and g.detail["matched"] == 4


def test_an_exact_tier_that_stood_still_asks_the_surrogate_to_lose_nothing():
    still = v.surrogate_gate([day(0.0, 0.0)] * 5)
    assert still.passed and still.detail["kept"] is None
    assert still.detail["gain"] == {"exact": 0.0, "surrogate": 0.0}
    # A surrogate set worth less than standing still, where the exact tier made no move.
    worse = v.surrogate_gate([*[day(0.0, 0.0)] * 4, day(0.0, -0.02)])
    assert not worse.passed and worse.detail["kept"] is None
    assert worse.detail["gain"]["surrogate"] == pytest.approx(-0.02)
    # And one worth more: there is no share to name, and it passes.
    more = v.surrogate_gate([*[day(0.0, 0.0)] * 4, day(0.0, 0.02)])
    assert more.passed and more.detail["kept"] is None


def test_a_surrogate_above_the_exact_tier_passes():
    g = v.surrogate_gate([*[day(0.4, 0.4)] * 4, day(0.4, 0.6)])
    assert g.passed and g.detail["kept"] == pytest.approx(1.1)
    assert g.detail["matched"] == 4


def test_a_seat_with_a_day_left_out_fails():
    four = [day(0.5, 0.5)] * 4
    for records in (four, [*four, LEFT_OUT]):
        g = v.surrogate_gate(records)
        assert not g.passed
        # What it kept on the days compared is still said.
        assert g.detail["of"] == 4 and g.detail["matched"] == 4
        assert g.detail["kept"] == pytest.approx(1.0)
    # A day left out is skipped wherever it falls, and the five compared decide.
    g = v.surrogate_gate([LEFT_OUT, *four, day(0.5, 0.5)])
    assert g.passed and g.detail["of"] == 5
    assert not v.surrogate_gate([]).passed


def test_a_floats_last_bit_does_not_decide():
    # 0.1 + 0.2 is a last bit above 0.3: the surrogate's worth falls that far under standing
    # still's on a day the exact tier made no move, and the seat passes.
    noise = {
        "day": "2023-10-24",
        "left_out": None,
        "equal": False,
        "worth": {"exact": 0.1 + 0.2, "surrogate": 0.3, "standing": 0.1 + 0.2},
    }
    g = v.surrogate_gate([noise, *[day(0.0, 0.0)] * 4])
    assert g.detail["gain"]["surrogate"] < 0 and g.passed
    # The same between two sets of one worth, at the bar itself.
    assert v.keeps(1.0, v.SURROGATE_KEEPS - v.EPS / 2)
    assert not v.keeps(1.0, v.SURROGATE_KEEPS - 2 * v.EPS)
    assert v.EPS < 1e-6  # far below the least gain a move must make


def test_the_rule_is_one_inequality_on_the_two_gains():
    assert v.keeps(2.0, 1.9) and not v.keeps(2.0, 1.89)
    assert v.keeps(0.0, 0.0) and v.keeps(0.0, 0.5) and not v.keeps(0.0, -0.01)
    assert v.keeps(1.0, 3.0)
    # Another share: the gate takes it and its detail names it.
    assert v.keeps(2.0, 1.0, 0.5) and not v.keeps(2.0, 0.99, 0.5)
    g = v.surrogate_gate([day(1.0, 0.6)] * 5, needs=0.5)
    assert g.passed and g.detail["needs"] == 0.5
    assert not v.surrogate_gate([day(1.0, 0.6)] * 5).passed


def test_an_exact_gain_below_zero_never_fails_the_same_sets():
    """Not a case the exact tier's search gives (it keeps a set only for a gain); the rule still
    answers: the surrogate is held to the exact tier's own gain, so the same sets pass, a
    surrogate above them passes and one below them fails."""
    assert v.keeps(-1.0, -1.0) and v.keeps(-1.0, -0.5) and not v.keeps(-1.0, -1.01)
    g = v.surrogate_gate([day(-0.2, -0.2)] * 5)
    assert g.passed and g.detail["kept"] is None and g.detail["matched"] == 5
