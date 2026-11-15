"""The tests' draws, alike on every machine (#172).

numpy's ``Generator.uniform(low, high)`` computes ``low + (high - low) * u`` in compiled code. The
arm64 build does the multiply and the add as one fused step and rounds once; the x86-64 build
rounds twice. Their draws differ in the last bit (912 of 5,000 for one seed), and a made-up league
built on them is then not the same league on the two machines. :func:`between` takes the same one
draw ``u`` (``rng.random()``) and does the arithmetic in Python, which rounds each step on every
machine: it equals the x86-64 ``uniform`` draw for draw, so on that machine nothing moves.
``tests/sim/test_sim_draws.py`` refuses a call of ``uniform`` in the simulator and its tests.
"""

from __future__ import annotations

import numpy as np


def between(rng: np.random.Generator, low: float, high: float) -> float:
    """A draw from ``[low, high)`` as ``rng.uniform(low, high)`` takes it, rounded alike on every
    machine."""
    return low + (high - low) * float(rng.random())
