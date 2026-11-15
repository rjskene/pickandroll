"""Each belief's weights are its own forecaster's (#172, PR D2): a replay fits every belief label's
weights on that label's own projection of the earlier seasons, names where they came from (its
own fit, the prior forecaster's, the default), never reads the hold-out, and the world believes
each label at its own weights. Then the count of the drafted players a belief does not project.

The data folders are the synthetic ones (``sim_league.make_data_dir``); a replay of 2024 on a
folder holding 2022 to 2024 fits on 2023, the only earlier season whose own prior is on file."""

from __future__ import annotations

from pathlib import Path

import pytest

from pickandroll.sim import fit as fitmod
from pickandroll.sim import forecast as fc
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import world
from pickandroll.sim.engine import STATS
from tests.sim.test_no_peek import DAYS, SEED, WEIGHTS, recorded

HOLD_OUT = 2025
PRIOR, ESPN, MARCEL = fc.Forecaster("prior"), fc.Forecaster("espn"), fc.Forecaster("marcel")


@pytest.fixture(scope="module")
def three(tmp_path_factory) -> Path:
    """A folder of 2022, 2023 and 2024, with ESPN's projection blocks."""
    from tests.sim.sim_league import make_data_dir

    return make_data_dir(
        tmp_path_factory.mktemp("three"), seasons=(2022, 2023, 2024), projection=True
    )


@pytest.fixture(scope="module")
def two(tmp_path_factory) -> Path:
    """A folder of 2023 and 2024 only: no season before 2024 has its prior season on file."""
    from tests.sim.sim_league import make_data_dir

    return make_data_dir(tmp_path_factory.mktemp("two"), seasons=(2023, 2024))


def fits(data: Path, labels, season: int = 2024, hold_out: int | None = HOLD_OUT, seed: int = 5):
    return reader.label_weights(data, season, hold_out, labels, seed, "stat")


# --------------------------------------------------------------------------- prior, as on main
def test_prior_s_weights_are_main_s_bit_for_bit(three: Path):
    """``readers.belief_weights`` is main's prior fit, unchanged; the prior label's fit through
    the labels' reader is equal to it, number for number, and names itself as its own."""
    main = reader.belief_weights(three, 2024, HOLD_OUT)
    got = fits(three, [PRIOR])["prior"]
    assert main.default is False and main.seasons == (2023,)
    assert got.weights == main and got.source == fitmod.OWN
    assert [w.hex() for w in got.weights.weights.values()] == [
        w.hex() for w in main.weights.values()
    ]
    assert got.left_out == {2022: "prior: season 2021 is not on file"}


# --------------------------------------------------------------------------- each label's own
def exact_espn(data: Path, season: int):
    """A hand-set ``espn`` that is exact: each player's realized rates over the season, with a
    full season's games (so the freeze check passes)."""
    lines, _, _ = reader.replay_lines(data, season)
    rates = fc.realized_rates(lines)
    return rates, dict.fromkeys(rates, 82.0)


def test_a_labels_fit_uses_its_own_projection(three: Path, monkeypatch):
    """An exact forecaster predicts each next game best by its own figure: it gets the grid's
    heaviest weight where the prior forecaster's fit, on last season's rates, does not."""
    monkeypatch.setattr(reader, "espn_rates", exact_espn)
    got = fits(three, [PRIOR, ESPN])
    espn, prior = got["espn"].weights.weights, got["prior"].weights.weights
    heaviest = max(fitmod.W_GRID)
    assert got["espn"].source == fitmod.OWN and got["espn"].weights.seasons == (2022, 2023)
    assert espn["pts"] == heaviest and prior["pts"] < heaviest
    assert sum(espn[s] == heaviest for s in STATS) > sum(prior[s] == heaviest for s in STATS)
    # ESPN's own projection of 2022 serves a sample too: it reads only its own season.
    assert got["espn"].left_out == {}


def test_a_flagged_espn_season_gives_no_sample(three: Path, monkeypatch):
    """A stored projection that saw part of its own season (the short players' projected games
    are their games played) fails the freeze check: that season gives no sample, by name."""

    def updated(data: Path, season: int):
        lines, _, _ = reader.replay_lines(data, season)
        rates = fc.realized_rates(lines)
        games = {k: float(len(lines[k])) for k in rates}
        return rates, games

    monkeypatch.setattr(reader, "espn_rates", updated)
    got = fits(three, [ESPN])["espn"]
    assert set(got.left_out) == {2022, 2023}
    assert all("fails the freeze check" in why for why in got.left_out.values())
    assert got.source == fitmod.PRIOR_FORECASTER  # no sample: the prior forecaster's


def test_a_sample_that_read_the_hold_out_is_refused(three: Path):
    """The fit refuses a sample whose projection read the hold-out; the reader never makes one,
    and never opens what it would read."""
    lines, _, _ = reader.replay_lines(three, 2023)
    rates = fc.realized_rates(lines)
    with pytest.raises(fitmod.HoldOutError):
        fitmod.belief_weights([fitmod.BeliefSample(2023, None, rates, lines, (2022,))], 2022)
    # With 2022 as the hold-out, prior's sample of 2023 would read it, marcel's would too.
    got = fits(three, [PRIOR, MARCEL], hold_out=2022)
    assert (
        got["prior"].left_out[2023] == "prior: its projection of 2023 would read the hold-out 2022"
    )
    assert got["prior"].left_out[2022] == "2022 is the hold-out"
    assert got["prior"].source == fitmod.DEFAULT and got["marcel"].source == fitmod.DEFAULT


def test_the_fallback_names_each_of_its_three_cases(three: Path, two: Path):
    got = fits(three, [PRIOR, MARCEL])
    assert got["prior"].source == fitmod.OWN
    # marcel's projection of 2023 would need two seasons before it: none, so the prior's.
    assert got["marcel"].source == fitmod.PRIOR_FORECASTER
    assert got["marcel"].weights == got["prior"].weights
    assert "marcel needs 2 earlier seasons on file, it has 1" in got["marcel"].left_out[2023]
    none = fits(two, [PRIOR, MARCEL])
    assert none["prior"].source == fitmod.DEFAULT == none["marcel"].source
    assert none["marcel"].weights.weights == dict.fromkeys(STATS, fitmod.W_DEFAULT)
    record = got["marcel"].payload()
    assert record["source"] == "the prior forecaster's" and record["seasons"] == [2023]
    assert set(record["left_out"]) == {"2022", "2023"}


def test_a_system_label_fits_where_both_stand_ins_serve(three: Path, monkeypatch):
    monkeypatch.setattr(reader, "espn_rates", exact_espn)
    system = fc.SystemBelief("yahoo", None, PRIOR, ESPN)
    got = fits(three, [system])[system.label]
    assert system.label == "yahoo(espn else prior)"
    # 2022: prior cannot serve it (2021 is not on file); 2023: both serve.
    assert got.source == fitmod.OWN and got.weights.seasons == (2023,)
    assert "the first stand-in cannot serve it" in got.left_out[2022]


# --------------------------------------------------------------------------- an oracle's fit draw
def test_an_oracles_fit_draw_shares_no_key_with_a_path(three: Path, monkeypatch):
    """Every generator an oracle's fit draws from (the run's oracle and each role's) is one no
    path of any run draws from: path 0's oracle, either role's, in either shape."""
    lines, _, _ = reader.replay_lines(three, 2023)
    seen: list[tuple[int, ...]] = []
    real = world.rng

    def spy(seed, path, *keys):
        seen.append((seed, path, *keys))
        return real(seed, path, *keys)

    monkeypatch.setattr(world, "rng", spy)
    keys: dict[str, set[tuple[int, ...]]] = {"fit": set(), "path": set()}
    for role in (None, "bbm", "yahoo"):
        for shape in fc.SHAPES:
            seen.clear()
            fit = fc.oracle(lines, 0.2, 7, 0, shape, role=role, fit_season=2023)
            keys["fit"] |= set(seen)
            seen.clear()
            path = fc.oracle(lines, 0.2, 7, 0, shape, role=role)
            keys["path"] |= set(seen)
            assert fit != path
    assert keys["fit"] and keys["path"] and not keys["fit"] & keys["path"]
    # The fit draws of two roles, and of two seasons, are apart too.
    assert fc.oracle(lines, 0.2, 7, 0, role="bbm", fit_season=2023) != fc.oracle(
        lines, 0.2, 7, 0, role="yahoo", fit_season=2023
    )
    assert fc.oracle(lines, 0.2, 7, 0, fit_season=2023) != fc.oracle(
        lines, 0.2, 7, 0, fit_season=2024
    )
    assert set(fc.FIT_KEYS.values()).isdisjoint(fc.ROLE_KEYS.values())


def test_an_oracle_label_is_fitted_on_its_own_draws(three: Path):
    named = fc.parse("oracle:0.05")
    got = fits(three, named)["oracle:0.05"]
    assert got.source == fitmod.OWN and got.weights.seasons == (2022, 2023)
    assert fits(three, named) == {"oracle:0.05": got}  # the same seed, the same weights


# --------------------------------------------------------------------------- the world
def test_the_world_believes_each_label_at_its_own_weights():
    """Two labels on one projection, at different weights, believe alike before any game and
    apart once games are played; a label the weights do not name takes the run's."""
    setup, lines = recorded()
    proj = dict(setup.projection)
    light, heavy = dict.fromkeys(STATS, 2.0), dict.fromkeys(STATS, 100.0)
    w = rn.replay_world(
        setup,
        lines,
        1,
        SEED,
        0,
        WEIGHTS,
        label="run",
        forecasts={"light": proj, "heavy": proj, "plain": proj},
        weights_of={"light": light, "heavy": heavy},
    )
    first, later = rn.first_day(setup), DAYS[-1]
    assert first is not None and first < min(d for by_day in lines.values() for d in by_day)
    # Before any game each is its projection (w·x / w, to the last bit or so).
    a, b = w.beliefs_on(first, "light"), w.beliefs_on(first, "heavy")
    assert a.keys() == b.keys() and all(a[k] == pytest.approx(b[k], rel=1e-12) for k in a)
    assert w.beliefs_on(later, "light") != w.beliefs_on(later, "heavy")
    assert w.others["light"].weights == light and w.others["heavy"].weights == heavy
    assert w.others["plain"].weights == WEIGHTS == w.causal.weights
    assert w.beliefs_on(later, "plain") == w.beliefs_on(later)


# --------------------------------------------------------------------------- the unprojected count
def test_the_unprojected_count_on_a_hand_built_league():
    """A stand-in that leaves out three of team 1's drafted players and two of team 2's: counted
    on the seats that hold it and on every roster; zero for the run's own label; a split label
    counts its rostered side's table."""
    setup, lines = recorded()
    out = [k for k, _ in setup.rosters[1][:3]] + [k for k, _ in setup.rosters[2][:2]]
    short = {k: v for k, v in setup.projection.items() if k not in out}
    w = rn.replay_world(
        setup,
        lines,
        1,
        SEED,
        0,
        WEIGHTS,
        label="run",
        forecasts={"short": short, "split": dict(setup.projection)},
        split={"split": "short"},
    )
    got = rn.unprojected(setup, w, {1: "short", 2: None, 3: "split", 4: None})
    assert got == {
        "short": {"seats": 3, "all": 5},
        "run": {"seats": 0, "all": 0},
        "split": {"seats": 0, "all": 5},
    }
    assert rn.unprojected(setup, w, {2: "short", 1: None}) == {
        "short": {"seats": 2, "all": 5},
        "run": {"seats": 0, "all": 0},
    }
