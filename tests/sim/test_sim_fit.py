"""The world's fit on synthetic logs (#172, PR 1): each parameter recovered, the short-game
share kept, seasons compared and pooled, the fit frozen with a hash."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from pickandroll.season.sim import fit as f
from tests.sim_fixtures import TRUE_MIXTURE, TRUE_PHI, rates_table, synthetic_lines


def test_dispersion_recovers_the_residual_phi():
    lines = synthetic_lines(seed=1, players=40, games=70, sigma_m=0.2, hazard=0.0)
    d = f.dispersion(lines)
    for stat in ("pts", "reb", "ast", "fga"):
        assert abs(d.pooled[stat] - TRUE_PHI[stat]) < 0.35, (stat, d.pooled[stat])
    # The raw figure carries the minutes variation the residual one leaves out.
    assert d.raw["pts"] > d.pooled["pts"]
    assert d.fitted_players == 40
    assert all(v >= 1.0 for v in d.pooled.values())


def test_a_player_under_thirty_games_shrinks_to_the_pool():
    many = synthetic_lines(seed=2, players=30, games=60, hazard=0.0)
    few = synthetic_lines(seed=3, players=1, games=12, hazard=0.0, prefix="few")
    d = f.dispersion(many + few)
    assert "few000" not in d.players
    assert "p000" in d.players
    own = f.dispersion([ln for ln in many if ln.player == "p000"], min_games=1, k=0)
    pooled, shrunk = d.pooled["pts"], d.players["p000"]["pts"]
    assert abs(shrunk - pooled) <= abs(own.pooled["pts"] - pooled) + 1e-9


def test_short_games_are_dropped_and_their_share_kept():
    lines = synthetic_lines(seed=4, players=5, games=40, hazard=0.0, short_games=4)
    d = f.dispersion(lines, min_games=10)
    assert d.short_share["p000"] == pytest.approx(0.1)
    assert d.games == 5 * 36
    m = f.minutes_factor(lines)
    assert m.games == 5 * 36


def test_minutes_factor_recovers_sigma():
    lines = synthetic_lines(seed=5, players=30, games=60, sigma_m=0.25, hazard=0.0)
    m = f.minutes_factor(lines)
    assert abs(m.sigma - 0.25) < 0.04
    assert len(m.players) == 30


def test_hazard_recovers_the_rate_and_the_mixture():
    lines = synthetic_lines(seed=6, players=60, games=82, hazard=0.15)
    h = f.hazard(lines)
    assert abs(h.rate - 0.15) < 0.03
    assert len(h.components) == 3
    for comp, (lo, hi, w) in zip(h.components, TRUE_MIXTURE):
        assert comp.lo == lo
        assert abs(comp.weight - w) < 0.10, (comp, w)
        assert sum(comp.lengths.values()) == pytest.approx(1.0)
    assert h.components[-1].hi is None
    assert h.played > 0 and h.runs > 0


def test_leading_games_are_dropped_and_an_open_run_is_censored():
    base = synthetic_lines(seed=7, players=2, games=20, hazard=0.0)
    late = [
        f.GameLine("late", 2026, g + 1, "T1", g >= 10, 30.0 if g >= 10 else 0.0, {"pts": 10.0})
        for g in range(20)
    ]
    hurt = [
        f.GameLine("hurt", 2026, g + 1, "T1", g < 12, 30.0 if g < 12 else 0.0, {"pts": 10.0})
        for g in range(20)
    ]
    h = f.hazard(base + late + hurt)
    assert h.leading == 10
    assert h.censored == 1
    assert h.runs == 0
    assert h.rate == 0.0


def test_agree_flags_a_season_whose_hazard_shifted():
    fits = [
        f.fit_season(synthetic_lines(seed=10 + i, players=30, games=60, season=2022 + i), 2022 + i)
        for i in range(3)
    ]
    shifted = f.fit_season(
        synthetic_lines(seed=20, players=30, games=60, season=2025, hazard=0.30), 2025
    )
    a = f.agree([*fits, shifted])
    assert a.outliers == (2025,)
    assert not a.ok
    pooled = f.pool([*fits, shifted], a)
    assert pooled.seasons == (2022, 2023, 2024)
    assert set(pooled.separate) == {2025}
    assert pooled.hazard.played == sum(x.hazard.played for x in fits)
    assert abs(pooled.minutes.sigma - 0.2) < 0.04


def test_pool_without_outliers_takes_every_season():
    fits = [
        f.fit_season(synthetic_lines(seed=30 + i, players=20, games=50, season=2023 + i), 2023 + i)
        for i in range(3)
    ]
    pooled = f.pool(fits)
    assert pooled.seasons == (2023, 2024, 2025)
    assert pooled.agreement.ok
    assert pooled.dispersion.games == sum(x.dispersion.games for x in fits)


def test_freeze_hashes_stably_and_refuses_the_hold_out():
    fits = [
        f.fit_season(synthetic_lines(seed=40 + i, players=20, games=50, season=2023 + i), 2023 + i)
        for i in range(2)
    ]
    pooled = f.pool(fits)
    payload, sha = f.freeze(pooled, hold_out=2025, seasons=fits)
    again, sha2 = f.freeze(pooled, hold_out=2025, seasons=fits)
    assert sha == sha2 and payload == again
    assert payload["hold_out"] == 2025
    assert payload["seasons"] == [2023, 2024]
    assert payload["parameters"]["shrink_k"] == f.SHRINK_K
    assert payload["parameters"]["run_cuts"] == list(f.RUN_CUTS)
    assert payload["parameters"]["refresh_defaults"]["lag"] == 1
    assert "short_share" in payload and "p000" in payload["short_share"]
    assert len(payload["per_season"]) == 2
    _, other = f.freeze(pooled, hold_out=2022, seasons=fits)
    assert other != sha
    _, with_tau = f.freeze(pooled, hold_out=2025, seasons=fits, tau={"pts": 0.1})
    assert with_tau != sha
    with pytest.raises(f.HoldOutError):
        f.freeze(pooled, hold_out=2024)
    with pytest.raises(f.HoldOutError):
        f.check_hold_out([2023, 2024], 2024)
    f.check_hold_out([2023, 2024], 2025)


def test_tau_from_systems_reads_the_disagreement():
    players = [f"p{i}" for i in range(400)]
    a = rates_table(1, players)
    rng = np.random.default_rng(2)
    b = {
        p: {s: r * float(np.exp(0.1 * rng.standard_normal())) for s, r in a[p].items()}
        for p in players
    }
    minutes = {p: 30.0 for p in players}
    minutes["p000"] = 10.0
    tau = f.tau_from_systems(a, b, minutes)
    for stat in ("pts", "reb", "ast"):
        assert abs(tau[stat] - 0.1) < 0.02
    # Players under the floor are left out: without the rest the sample is too small.
    assert f.tau_from_systems(a, b, {p: 10.0 for p in players}) == {}


def test_tau_from_residuals_removes_the_sampling_noise():
    players = [f"p{i}" for i in range(300)]
    projected = rates_table(3, players)
    games = {p: 70 for p in players}
    rng = np.random.default_rng(4)
    noisy_only = {
        p: {
            s: r * float(np.exp(rng.standard_normal() * np.sqrt(TRUE_PHI[s] / (r * 70))))
            for s, r in projected[p].items()
        }
        for p in players
    }
    tau0 = f.tau_from_residuals(projected, noisy_only, games, phi=TRUE_PHI)
    assert tau0["pts"] < 0.05
    off = {
        p: {s: r * float(np.exp(0.15 * rng.standard_normal())) for s, r in projected[p].items()}
        for p in players
    }
    tau = f.tau_from_residuals(projected, off, games, phi=TRUE_PHI)
    assert abs(tau["pts"] - 0.15) < 0.04


def test_refresh_rate_from_consecutive_exports():
    players = [f"p{i}" for i in range(50)]
    truth = rates_table(5, players)
    rng = np.random.default_rng(6)
    b0 = {
        p: {s: r * float(np.exp(0.3 * rng.standard_normal())) for s, r in truth[p].items()}
        for p in players
    }
    kappa = 0.2
    b1 = {
        p: {
            s: b0[p][s] * float(np.exp(kappa * (np.log(truth[p][s]) - np.log(b0[p][s]))))
            for s in b0[p]
        }
        for p in players
    }
    r = f.refresh_rate([(date(2026, 11, 2), b0), (date(2026, 11, 9), b1)], truth)
    assert r.fitted
    assert abs(r.kappa - kappa) < 0.01
    assert r.sigma_eta < 0.01
    assert r.pairs > 0
    # Two weeks between exports: the same step is two weeks of a smaller weekly refresh.
    r2 = f.refresh_rate([(date(2026, 11, 2), b0), (date(2026, 11, 16), b1)], truth)
    assert abs(r2.kappa - (1 - (1 - kappa) ** 0.5)) < 0.01
    d = f.refresh_rate([(date(2026, 11, 2), b0)], truth)
    assert not d.fitted and d.kappa == f.REFRESH_DEFAULTS["kappa"]
