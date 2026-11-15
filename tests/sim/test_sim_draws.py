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
from fractions import Fraction
from pathlib import Path

import numpy as np

from pickandroll.sim import nopeek
from tests.sim.draws import between

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
