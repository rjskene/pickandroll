"""The gates (#172, PR 1) on hand-built arrays."""

from __future__ import annotations

import numpy as np

from pickandroll.season.sim import validate as v


def test_pit_counts_below_and_half_of_equal():
    assert v.pit(5.0, [1, 2, 3, 4]) == 1.0
    assert v.pit(2.0, [1, 2, 3, 4]) == 0.375
    assert v.pit(0.0, []) == 0.5
    assert list(v.pits([1.0, 3.0], [[0, 2], [0, 2]])) == [0.5, 1.0]


def test_bucket_gate_passes_uniform_transforms_and_fails_shifted_ones():
    rng = np.random.default_rng(0)
    g = v.bucket_gate(rng.random(5000), season=2025)
    assert g.passed and g.season == 2025 and g.name == "team_weeks"
    assert len(g.detail["buckets"]) == 5
    bad = v.bucket_gate(rng.random(5000) * 0.5)
    assert not bad.passed
    assert bad.detail["worst"] > 0.05
    assert not v.bucket_gate([]).passed


def test_brier_and_its_gate():
    assert v.brier([1.0, 0.0], [1.0, 0.0]) == 0.0
    assert v.brier([0.5], [1.0]) == 0.25
    assert v.brier_gate(0.24, 0.235).passed
    assert not v.brier_gate(0.25, 0.235).passed


def test_band_gate_reads_the_central_band():
    samples = np.linspace(0, 1, 1001)
    assert v.band_gate(0.5, samples).passed
    assert not v.band_gate(0.05, samples).passed
    g = v.band_gate(0.95, samples, season="2026-27")
    assert not g.passed and g.season == "2026-27"
    lo, hi = v.band(samples)
    assert abs(lo - 0.1) < 0.01 and abs(hi - 0.9) < 0.01


def test_absence_gate_is_the_bucket_gate_on_missed_games():
    rng = np.random.default_rng(1)
    samples = rng.poisson(4.0, size=(2000, 400))
    observed = rng.poisson(4.0, size=2000)
    assert v.absence_gate(observed, samples).passed
    assert not v.absence_gate(rng.poisson(8.0, size=2000), samples).passed
    assert list(v.pits([2.0], [[1, 2, 2, 3]], randomize=True, seed=1)) != [0.5]


def test_surrogate_gate_needs_four_of_five():
    assert v.surrogate_gate([True, True, True, True, False]).passed
    assert not v.surrogate_gate([True, True, True, False, False]).passed
    assert not v.surrogate_gate([True, True, True, True]).passed


def test_refresh_gate_brackets_the_implied_kappa():
    rng = np.random.default_rng(2)
    gaps = rng.standard_normal(200)
    steps = 0.2 * gaps + 0.05 * rng.standard_normal(200)
    assert abs(v.implied_kappa(gaps, steps) - 0.2) < 0.02
    good = v.refresh_gate(0.2, gaps, steps, season=2026)
    assert good.passed and good.detail["low"] < 0.2 < good.detail["high"]
    assert not v.refresh_gate(0.6, gaps, steps).passed
    few = v.refresh_gate(0.2, gaps[:5], steps[:5])
    assert not few.passed and few.detail["reason"] == "too few pairs"
