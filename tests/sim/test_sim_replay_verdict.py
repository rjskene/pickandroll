"""The verdict of a replay's pair by forecaster and season (#172, PR D2), on hand-set numbers: the
pooled change per forecaster (the mean of its season means, the seasons the clusters), the
advisory rule (every cell the rule reads within one SE of zero or above, every forecaster's pooled
change above zero), the rows and cells it does not rest on, and the printed table."""

from __future__ import annotations

import math

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import run as rn

SEASONS = ["2022", "2023", "2024"]


def change(mean: float | None, se: float | None = 0.01, n: int = 24) -> dict:
    """A cell's paired change: playoff odds at ``mean`` with ``se``, every other metric at half."""
    out = {"made_playoffs": {"mean": mean, "se": se, "n": n}}
    for k in rn.METRICS[1:]:
        out[k] = {"mean": None if mean is None else mean / 2, "se": se, "n": n}
    return out


def cells(**by_label: list) -> dict:
    return {
        label.replace("_", ":"): dict(zip(SEASONS, figures, strict=True))
        for label, figures in by_label.items()
    }


# --------------------------------------------------------------------------- the pooled figure
def test_the_pooled_change_and_its_se_from_three_season_means():
    p = rn.pool_seasons([0.01, 0.03, 0.08], 3)
    sd = math.sqrt(((0.01 - 0.04) ** 2 + (0.03 - 0.04) ** 2 + (0.08 - 0.04) ** 2) / 2)
    assert p["mean"] == pytest.approx(0.04) and p["se"] == pytest.approx(sd / math.sqrt(3))
    assert (p["seasons"], p["of"], p["note"]) == (3, 3, "over 3 seasons")


def test_one_season_is_that_seasons_mean_and_says_so():
    p = rn.pool_seasons([0.05], 1)
    assert p["mean"] == 0.05 and p["se"] is None
    assert p["note"] == "over 1 seasons: that season's mean, no SE (it needs two seasons)"


def test_a_skipped_cell_pools_over_two_of_three():
    v = rn.replay_verdict(cells(prior=[change(0.02), None, change(0.04)]), SEASONS)
    p = v["rows"]["prior"]["pooled"]["made_playoffs"]
    assert p["mean"] == pytest.approx(0.03) and p["note"] == "over 2 of 3 seasons"
    assert v["rows"]["prior"]["cells"]["2023"]["mark"] == rn.SKIPPED
    # Every metric is pooled; the payload carries them all.
    assert set(v["rows"]["prior"]["pooled"]) == set(rn.METRICS)
    assert v["rows"]["prior"]["pooled"]["rank"]["mean"] == pytest.approx(0.015)


# --------------------------------------------------------------------------- the rule
def test_the_rule_holds_when_every_cell_is_within_one_se_and_every_pool_is_above_zero():
    v = rn.replay_verdict(
        cells(
            prior=[change(0.02), change(-0.005, 0.01), change(0.03)],
            espn=[change(0.01), change(0.02), change(0.0, 0.02)],
        ),
        SEASONS,
    )
    assert v["passes"] is True and v["why"] is None and v["failed"] == []
    assert v["read"] == ["prior", "espn"]


def test_the_rule_fails_on_one_cell_below_minus_one_se():
    v = rn.replay_verdict(cells(prior=[change(0.05), change(-0.02, 0.01), change(0.05)]), SEASONS)
    assert v["passes"] is False and v["failed"] == [
        "2023 prior: -0.0200 is below zero by more than its SE 0.0100"
    ]


def test_the_rule_fails_on_a_pooled_change_at_or_below_zero():
    v = rn.replay_verdict(cells(prior=[change(0.01), change(-0.005), change(-0.005)]), SEASONS)
    assert v["passes"] is False and v["failed"] == ["prior pooled: +0.0000 is not above zero"]
    below = rn.replay_verdict(cells(prior=[change(0.0), change(-0.005), change(0.0)]), SEASONS)
    assert below["passes"] is False


def test_no_verdict_when_a_cell_has_no_se_or_the_audit_voided_a_path():
    figures = [change(0.02), change(0.02, None, 1), change(0.02)]
    v = rn.replay_verdict(cells(prior=figures), SEASONS)
    assert v["passes"] is None and v["why"].startswith(
        "no verdict: no SE in the cell(s) 2023 prior"
    )
    clean = [change(0.02), change(0.03), change(0.02)]
    v = rn.replay_verdict(cells(prior=clean), SEASONS, voided=2)
    assert v["passes"] is None and v["why"] == "no verdict: the audit voided 2 path(s)"


def test_an_oracle_row_and_a_frozen_espn_cell_are_shown_and_move_nothing():
    """An oracle's failing figures and a frozen espn season's failing figure leave a holding
    verdict holding; both are in the rows, marked."""
    good = [change(0.02), change(0.03), change(0.02)]
    v = rn.replay_verdict(
        cells(
            prior=good,
            espn=[change(0.02), change(-0.5), change(0.04)],
            oracle_0_1=[change(-0.3), change(-0.3), change(-0.3)],
        ),
        SEASONS,
        yardsticks=["oracle:0:1"],
        frozen={"espn": ["2023"]},
    )
    assert v["passes"] is True and v["read"] == ["prior", "espn"]
    assert v["rows"]["oracle:0:1"]["mark"] == rn.YARDSTICK
    assert v["rows"]["espn"]["cells"]["2023"]["mark"] == rn.FREEZE
    assert v["rows"]["espn"]["cells"]["2023"]["mean"] == -0.5  # shown all the same
    espn = v["rows"]["espn"]["pooled"]["made_playoffs"]
    assert espn["mean"] == pytest.approx(0.03) and espn["note"] == "over 2 of 3 seasons"
    assert v["rows"]["oracle:0:1"]["pooled"]["made_playoffs"]["mean"] == pytest.approx(-0.3)


def test_a_run_whose_only_forecaster_is_an_oracle_gives_no_verdict():
    v = rn.replay_verdict(
        cells(oracle_0_1=[change(0.2), change(0.2), change(0.2)]),
        SEASONS,
        yardsticks=["oracle:0:1"],
    )
    assert v["passes"] is None and "no forecaster the rule may rest on" in v["why"]


# --------------------------------------------------------------------------- the table
def test_the_printed_table_has_a_row_a_forecaster_and_a_column_a_season_and_the_pool():
    v = rn.replay_verdict(
        cells(
            prior=[change(0.02), None, change(0.04)],
            espn=[change(0.01), change(-0.5), change(0.03)],
            oracle_0_1=[change(0.1), change(0.1), change(0.1)],
        ),
        SEASONS,
        yardsticks=["oracle:0:1"],
        frozen={"espn": ["2023"]},
    )
    lines = ss.verdict_lines(v | {"notes": ["a note"]})
    header = lines[1].split()
    assert header == ["forecaster", *SEASONS, "pooled"]
    rows = lines[2:5]
    assert [r.split()[0] for r in rows] == ["prior", "espn", "oracle:0:1"]
    assert rows[0].split()[1:] == ["+2.0", "(1.0)", "n/a", "+4.0", "(1.0)", "+3.0", "(1.0)"]
    assert "[f]" in rows[1] and "[y]" in rows[2]
    assert "  prior pooled: over 2 of 3 seasons" in lines
    assert any(x.startswith("  [y] an oracle") for x in lines)
    assert any(x.startswith("  [f] espn's stored projection") for x in lines)
    assert any(x.startswith("  n/a n/a: the forecaster cannot serve") for x in lines)
    assert "note: a note" in lines
    assert lines[-1] == f"verdict ({rn.REPLAY_VERDICT_RULE}, advisory): holds"
