"""SEASON SIM (#172, PR take-in): an arm with every change of the take-in off plays the
simulator before it, outcome for outcome.

The take-in brought in live's odds calibration of 2026-11-23 (#485, #486, #487), each change a
knob of the arm. With ``later_weeks`` ``uncapped`` and the three rates at 0
(``policy.TAKEIN_OFF``, the tests' own arms, ``sim_league.KNOBS``) a season must be the one the
version before played: the same rosters, moves, claims, bids and starters on every day. The
digests below were taken on the simulator before the take-in (main ``faf143c`` with #490, head
``122a247``), each a season of the made-up league (``takein_matrix``): a one-win league, one
with a held slot and two players out on day one, a points league, waivers by priority, by FAAB,
continuous waivers, a league that counts every category and one whose free agents play the
same day; each on the exact tier, the surrogate, the queue's rule and an arm that executes its
plan on plan floors of -1, all with mirror rivals; and a split ``yahoo`` and ``blend`` seat on
the split test's season. A digest holds whole numbers only, and the seats' choices rest on the
made-up league's floats as every pinned outcome of the suite does."""

from __future__ import annotations

import pytest

from tests.sim import takein_matrix as tm

#: Each season's digest before the take-in, by league and arm (``takein_matrix.season``) and by
#: split seat (``takein_matrix.split_season``).
BEFORE = {
    "plain/exact": "f014bed9b74abb15",
    "plain/surrogate": "45c7a3c30c1e02ca",
    "plain/queue": "f014bed9b74abb15",
    "plain/plan": "f014bed9b74abb15",
    "held/exact": "583584b5a7bfe7b3",
    "held/surrogate": "fb51dc0789f8ae73",
    "held/queue": "583584b5a7bfe7b3",
    "held/plan": "583584b5a7bfe7b3",
    "points/exact": "02c26b4ba8c30417",
    "points/surrogate": "5c2f2f787619b705",
    "points/queue": "507e68dfd5b912c7",
    "points/plan": "cdcc3622993cfc98",
    "priority/exact": "aeea6504b92d35de",
    "priority/surrogate": "45c7a3c30c1e02ca",
    "priority/queue": "aeea6504b92d35de",
    "priority/plan": "aeea6504b92d35de",
    "faab/exact": "21ae245f56dc9c20",
    "faab/surrogate": "45c7a3c30c1e02ca",
    "faab/queue": "21ae245f56dc9c20",
    "faab/plan": "21ae245f56dc9c20",
    "continuous/exact": "227050d2d84ac360",
    "continuous/surrogate": "a11e901e27473282",
    "continuous/queue": "227050d2d84ac360",
    "continuous/plan": "227050d2d84ac360",
    "each/exact": "3a3892229167ed04",
    "each/surrogate": "270e8a0d40b98d96",
    "each/queue": "3a3892229167ed04",
    "each/plan": "3a3892229167ed04",
    "same_day/exact": "2a923c4cae8684b3",
    "same_day/surrogate": "e39ca9df7bf4582f",
    "same_day/queue": "75817ff0171b8832",
    "same_day/plan": "2a923c4cae8684b3",
    "split_yahoo": "9a3d1754fa59bd44",
    "split_blend": "0f35f6d8ae918a4b",
}


@pytest.mark.parametrize("league", list(tm.LEAGUES))
def test_every_change_off_plays_the_version_before_in_each_league(league):
    got = {f"{league}/{name}": tm.season(league, a) for name, a in tm.arms().items()}
    assert got == {k: v for k, v in BEFORE.items() if k.startswith(f"{league}/")}


@pytest.mark.parametrize("name", list(tm.SPLITS))
def test_every_change_off_plays_the_version_before_for_a_split_seat(name):
    assert tm.split_season(name) == BEFORE[name]
