import pandas as pd

from pickandroll.availability import availability, availability_curve


def test_availability_monotone_in_pick():
    adp = pd.Series({"a": 5.0, "b": 40.0, "c": 120.0})
    early = availability(adp, pick=1)
    later = availability(adp, pick=60)
    assert (early >= later).all()
    assert early["a"] > 0.85
    assert later["a"] < 0.01
    assert 0.2 < later["b"] < 0.8 or later["b"] < 0.2  # gone or close to it by pick 60


def test_curve_columns_are_picks():
    adp = pd.Series({"a": 5.0, "b": 40.0})
    curve = availability_curve(adp, [1, 13, 24])
    assert list(curve.columns) == [1, 13, 24]
    assert curve.shape == (2, 3)
