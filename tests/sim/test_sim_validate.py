"""Gate 5's verdict (#172, PR 1; PR D3: the gates of the drawn world went)."""

from __future__ import annotations

from pickandroll.sim import validate as v


def test_surrogate_gate_needs_four_of_five():
    assert v.surrogate_gate([True, True, True, True, False]).passed
    assert not v.surrogate_gate([True, True, True, False, False]).passed
    assert not v.surrogate_gate([True, True, True, True]).passed
