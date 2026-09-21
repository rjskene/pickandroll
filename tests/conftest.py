from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FINE_POSITIONS = ("PG", "SG", "SF", "PF", "C")

DATA = Path(__file__).resolve().parents[1] / "data"


def synthetic_pool(n: int = 60, seed: int = 7) -> pd.DataFrame:
    """A plausible season-total projection table with positions spread over the five spots."""
    rng = np.random.default_rng(seed)
    games = rng.integers(55, 80, n).astype(float)
    minutes = rng.uniform(18, 36, n) * games
    fga = rng.uniform(6, 20, n) * games
    fg_pct = rng.uniform(0.40, 0.58, n)
    fta = rng.uniform(1, 9, n) * games
    ft_pct = rng.uniform(0.60, 0.92, n)
    rows = {
        "player": [f"Player {i}" for i in range(n)],
        "team": rng.choice(["BOS", "LAL", "DEN", "MIL", "OKC"], n),
        "positions": [
            "/".join(sorted(set(rng.choice(FINE_POSITIONS, rng.integers(1, 3)).tolist())))
            for _ in range(n)
        ],
        "games": games,
        "minutes": minutes,
        "pts": (fga * fg_pct * 2.1 + fta * ft_pct),
        "threes": rng.uniform(0.2, 3.5, n) * games,
        "reb": rng.uniform(2, 12, n) * games,
        "ast": rng.uniform(1, 9, n) * games,
        "stl": rng.uniform(0.3, 1.8, n) * games,
        "blk": rng.uniform(0.1, 2.2, n) * games,
        "tov": rng.uniform(0.8, 4.0, n) * games,
        "fgm": fga * fg_pct,
        "fga": fga,
        "ftm": fta * ft_pct,
        "fta": fta,
    }
    df = pd.DataFrame(rows, index=[f"p{i}" for i in range(n)])
    df.index.name = "player_id"
    return df


@pytest.fixture
def pool() -> pd.DataFrame:
    return synthetic_pool()


@pytest.fixture
def bbm_totals_path() -> Path:
    path = DATA / "bbm_sample_ros_totals.xls"
    if not path.exists():
        pytest.skip("no Basketball Monster sample export in data/")
    return path


@pytest.fixture
def bbm_pergame_path() -> Path:
    path = DATA / "bbm_sample_week_pergame.xls"
    if not path.exists():
        pytest.skip("no Basketball Monster sample export in data/")
    return path
