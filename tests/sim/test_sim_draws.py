"""The made-up leagues draw the same numbers on every machine (#172).

numpy's ``Generator.uniform(low, high)`` computes ``low + (high - low) * u`` in compiled code. The
arm64 build (the Mac) fuses the multiply and the add into one step that rounds once; the x86-64
build (the droplet) rounds twice. The two differ in the last bit on about one draw in five, and a
made-up league turns a last bit into a different draft and season: a test then passes on one
machine and fails on the other. So neither the simulator nor its tests call ``uniform``: the
tests draw with :func:`tests.sim.draws.between` and the no-peek check with ``nopeek._scale``, the
same one ``random()`` draw with the arithmetic in Python, which rounds each step on every machine.
"""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import date
from fractions import Fraction
from pathlib import Path

import numpy as np

from pickandroll.sim import nopeek
from pickandroll.sim.engine import wk
from tests.sim.draws import between
from tests.sim.sim_fixtures import rates_table
from tests.sim.sim_league import NINE, make_setup
from tests.sim.test_no_peek import recorded
from tests.sim.test_sim_replay import league as replay_league

ROOT = Path(__file__).resolve().parents[2]
TREES = (ROOT / "src" / "pickandroll" / "sim", ROOT / "tests" / "sim")

#: ``between(default_rng(3), 0.5, 1.6)``, its first eight draws, as the two-rounding arithmetic
#: gives them on every machine. The sixth is one the fused form rounds otherwise.
PINNED = (
    "0x1.303cd411fc3d4p-1",
    "0x1.855f263e9842dp-1",
    "0x1.61a38e417fdf5p+0",
    "0x1.23efd40c74c6ap+0",
    "0x1.3503647016308p-1",
    "0x1.f3efe54f54b22p-1",
    "0x1.06e69dd07bbcep+0",
    "0x1.59f7076761edcp-1",
)


def uniform_calls(source: str) -> list[int]:
    """The lines of ``source`` that call a function named ``uniform``, as a method
    (``rng.uniform(...)``, ``np.random.uniform(...)``) or by its bare name."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = (
                f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            )
            if name == "uniform":
                found.append(node.lineno)
    return found


def test_the_reader_sees_every_form_of_the_call():
    source = (
        "import numpy as np\n"
        "from numpy.random import uniform\n"
        "a = rng.uniform(0.5, 1.6)\n"
        "b = np.random.default_rng(1).uniform(low=0, high=1)\n"
        "c = uniform(0, 1)\n"
        "d = between(rng, 0.5, 1.6)  # not a call of uniform\n"
        "e = 'rng.uniform(0, 1)'  # a string, not a call\n"
    )
    assert uniform_calls(source) == [3, 4, 5]


def test_no_draw_in_the_simulator_or_its_tests_calls_uniform():
    found = {
        str(p.relative_to(ROOT)): lines
        for tree in TREES
        for p in sorted(tree.rglob("*.py"))
        if (lines := uniform_calls(p.read_text()))
    }
    assert found == {}, f"numpy's uniform rounds differently on arm64 and x86-64: {found}"
    # Not vacuous: the trees were read.
    assert any(TREES[0].rglob("nopeek.py")) and any(TREES[1].rglob("sim_league.py"))


def test_the_helper_rounds_alike_on_every_machine():
    rng = np.random.default_rng(3)
    got = [between(rng, 0.5, 1.6).hex() for _ in PINNED]
    assert got == list(PINNED)


def test_the_pins_tell_the_two_roundings_apart():
    """At least one pinned draw is one the fused form (one rounding of ``low + range * u``)
    gives otherwise, so the pins fail on a machine whose helper rounds once."""
    u = np.random.default_rng(3).random(len(PINNED))
    rng_ = 1.6 - 0.5
    fused = [float(Fraction(0.5) + Fraction(rng_) * Fraction(float(x))).hex() for x in u]
    assert sum(f != p for f, p in zip(fused, PINNED, strict=True)) >= 1


def test_the_no_peek_scale_draws_in_its_range_from_one_random_draw():
    g, h = np.random.default_rng([7, 1, 739000]), np.random.default_rng([7, 1, 739000])
    lo, hi = nopeek.SCALE
    for _ in range(50):
        x = nopeek._scale(g)
        assert lo <= x < hi
        assert x == lo + (hi - lo) * float(h.random())


# --------------------------------------------------------------------------- the value's columns
#: A column whose spread is below this share of its size holds rounding noise, not players. The
#: noise of a column summed over n players is at most about n·2⁻⁵³ of its size, under 1e-13 for
#: the few hundred players these leagues hold; a real column's spread is a few hundredths of its
#: size or more. 1e-6 sits seven orders above the one and four below the other.
NOISE = 1e-6


def columns(projection) -> dict[str, tuple[float, float]]:
    """Each category's column of the engine's per-game value, as the engine's public scorer
    (``wk.scorer_of``) reports it: its spread over the pool the engine chooses, after the guard
    that takes a spread of exactly 0 as 1 (so an exactly flat column reads 1.0 and a noise column
    reads the noise), and its size over the projection (a percentage's mean makes, a counting
    stat's mean size)."""
    keys = list(projection)
    scorer = wk.scorer_of(projection, NINE)["cats"]
    out = {}
    for cat, c in scorer.items():
        stat = wk.PCT[cat][0] if cat in wk.PCT else cat
        size = sum(abs(float(projection[k].get(stat, 0.0))) for k in keys) / len(keys)
        out[cat] = (c["sd"], size)
    return out


def made_up_projections() -> dict[str, dict]:
    """The projections of the made-up leagues the tests build from in-memory builders. The
    replay leagues built from :func:`sim_league.write_logs` take their projection from whole-
    number lines (makes rounded game by game), so their percentages differ between players by
    whole makes, never by a last bit."""
    out = {"recorded": recorded()[0].projection}
    for name, kw in {
        "make_setup": {},
        "make_setup(seed 5)": {"seed": 5},
        "make_setup(6x4, pool 20)": {"teams": 6, "spots": 4, "pool": 20},
    }.items():
        out[name] = make_setup(**kw).projection
    out["replay.league"] = replay_league()[0].projection
    out["rates_table"] = rates_table(5, [f"p{i:03d}" for i in range(40)])
    return out


def test_no_value_column_of_a_made_up_league_is_rounding_noise():
    noisy = {}
    for name, projection in made_up_projections().items():
        for cat, (sd, size) in columns(projection).items():
            if sd < NOISE * size:
                noisy[f"{name}.{cat}"] = (sd, size)
    assert noisy == {}, f"a column holds only rounding noise, scaled up by the value: {noisy}"


def test_the_noise_reader_finds_main_s_shooting():
    """Not vacuous: a league whose players all shoot alike, as ``recorded()`` had them (makes
    4.2 and 2.3 times the level, attempts 9 and 3 times it), has both percentage columns noisy;
    one whose makes are an exact power-of-two share is flat, which the engine's guard reads as a
    spread of 1, and is not flagged."""
    levels = [0.5 + 1.1 * i / 39 for i in range(40)]
    alike = {
        k: {"fgm": 4.2 * x, "fga": 9 * x, "ftm": 2.3 * x, "fta": 3 * x}
        for k, x in enumerate(levels)
    }
    got = columns(alike)
    for cat in ("fg_pct", "ft_pct"):
        sd, size = got[cat]
        assert 0.0 < sd < NOISE * size
    flat = {k: {"fgm": 4.0 * x, "fga": 8.0 * x} for k, x in enumerate(levels)}
    sd, size = columns(flat)["fg_pct"]
    assert sd == 1.0 and not sd < NOISE * size


#: SHA-256 of ``recorded()``'s stand-in projection and lines, every number written as float hex.
#: The same on every machine; an edit to ``recorded()`` re-pins it.
RECORDED = "55953c05288a514788fad4bffaad8da0011898fcf000a7f0c79b3b7f5165240e"


def digest(x) -> str:
    def canon(v):
        if isinstance(v, float):
            return v.hex()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, dict):
            return [[canon(k), canon(w)] for k, w in sorted(v.items())]
        return v

    return hashlib.sha256(json.dumps(canon(x)).encode()).hexdigest()


def test_recorded_is_the_same_league_on_every_machine():
    """``recorded()``'s numbers, pinned: a machine that rounds a draw otherwise holds another
    league, and fails here before any test that plays it. An edit to the fixture re-pins it."""
    setup, lines = recorded()
    assert digest({"projection": setup.projection, "lines": lines}) == RECORDED
