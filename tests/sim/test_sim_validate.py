"""The gates (#172, PR 1) on hand-built arrays."""

from __future__ import annotations

import numpy as np

from pickandroll.sim import validate as v


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
