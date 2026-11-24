"""Made-up leagues for the simulator's tests (#172, PR 2b): a small in-memory setup the policy,
runner and checks run on, a made-up recorded season it replays (PR D3: the simulator has no
drawn world), and a fixture data folder the readers and the commands read: synthetic game logs
only. Every player and team here is synthetic or from the anonymised season fixtures."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pickandroll.season import weekly as wk
from pickandroll.sim import gamelogs as gl
from pickandroll.sim import league as lg
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim import state as sst
from pickandroll.sim.engine import EACH_CATEGORY
from tests.sim.draws import between
from tests.sim.sim_fixtures import run_length, synthetic_lines
from tests.sim.test_gamelogs import entry

FIXTURES = Path(__file__).parents[1] / "fixtures" / "season"
NINE = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov")
#: The knobs the tests' arms start from. The plan floors sit at 0, where a plan whose gap over its
#: set is a float's noise is taken or not with the process's hash seed: the usual leagues here
#: draw no plan, so it never shows, but a test that reads a plan floor sets it away from 0. The
#: take-in's five (#172, PR take-in) sit at the rule before it (``policy.TAKEIN_OFF``): the
#: field's later weeks uncapped, no blend and no spread, so every test written before it plays
#: as it did; a test of the take-in names what it turns on.
KNOBS: dict[str, Any] = {
    "system": "bbm",
    "blend": None,
    "horizon_weight": "natural",
    "protection_floor": 0.0,
    "plan_floor_cats": 0.0,
    "plan_floor_points": 0.0,
    "stash_threshold": None,
    "faab_sizing": None,
    "daily_cap": 1,
    "three_weight": 0.33,
    "season_weight": 0.0,
    "playoff_weight": 1.0,
    "later_weeks": "uncapped",
    "rate_shrink": 0.0,
    "rate_shrink_games": 4.0,
    "rate_cv": 0.0,
    "miss_rate": 0.0,
}
NBA = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
POSITIONS = (("PG",), ("SG",), ("SF",), ("PF",), ("C",), ("PG", "SG"), ("SF", "PF"), ("PF", "C"))
MONDAY = date(2026, 10, 26)


def rates(level: float) -> dict[str, float]:
    return {
        "pts": 10 * level,
        "threes": 1 * level,
        "reb": 5 * level,
        "ast": 3 * level,
        "stl": 1 * level,
        "blk": 1 * level,
        "tov": 2.0,
        "fgm": 4.0 * level,
        "fga": 8.0 * level,
        "ftm": 2.0,
        "fta": 2.5,
    }


def alternating_schedule(first: date, days: int, teams=NBA) -> dict[date, frozenset[str]]:
    """Each team plays every other day, the teams staggered."""
    return {
        first + timedelta(i): frozenset(t for j, t in enumerate(teams) if (i + j) % 2 == 0)
        for i in range(days)
    }


def make_setup(
    teams: int = 4,
    spots: int = 5,
    pool: int = 8,
    weeks: int = 6,
    playoff_weeks: int = 1,
    playoff_teams: int = 2,
    seed: int = 3,
    statuses: dict[int, str] | None = None,
    max_weekly_adds: int | None = 4,
    bracket: bool = True,
    held_slots: tuple[str, ...] = (),
) -> sst.Setup:
    """``teams`` seats, ``spots`` players each (snake-drafted on the projection), ``pool`` free
    agents, a Monday-to-Sunday calendar of ``weeks`` weeks with the last ``playoff_weeks`` the
    bracket's, every team playing every other day; ``held_slots`` (IL, IL+, NA) after the bench."""
    rng = np.random.default_rng(seed)
    n = teams * spots + pool
    players = {}
    projection = {}
    for k in range(1, n + 1):
        players[k] = sst.Member(k, f"P{k}", NBA[k % len(NBA)], POSITIONS[k % len(POSITIONS)])
        projection[k] = rates(between(rng, 0.6, 1.4))
    cal = sst.weeks_from(MONDAY, weeks)
    regular = tuple(range(1, weeks - playoff_weeks + 1))
    ids = tuple(range(1, teams + 1))
    pairings = sst.round_robin(ids, regular)
    schedule = alternating_schedule(cal.weeks[0].start, 7 * weeks)
    value = wk.per_game_values(projection, NINE, None)
    keys = list(players)
    rosters = sst.snake_draft(keys, value, ids, spots)
    taken = {k for r in rosters.values() for k, _ in r}
    rounds = max(1, int(np.ceil(np.log2(playoff_teams))))
    spec = lg.LeagueSpec(
        ids,
        pairings,
        tuple(range(weeks - playoff_weeks + 1, weeks + 1)),
        NINE,
        "categories",
        None,
        playoff_teams,
        2**rounds - playoff_teams,
    )
    return sst.Setup(
        start=cal.weeks[0].start,
        calendar=cal,
        pairings=pairings,
        teams=ids,
        players=players,
        rosters=rosters,
        pool=tuple(k for k in keys if k not in taken),
        projection=projection,
        schedule=schedule,
        roster_slots=("PG", "SG", "G", "C", "Util", "BN", *held_slots),
        cats=NINE,
        max_weekly_adds=max_weekly_adds,
        statuses=statuses or {},
        market=value,
        market_rate=0.2,
        spec=spec if bracket else None,
        bracket_unread=None if bracket else "the settings page has not been read",
    )


def every_category(setup: sst.Setup) -> sst.Setup:
    """``setup`` counting every category (the format PR), as ``run.replay_setup`` builds one under
    ``--h2h each_category``: its seats weigh expected categories and its standings order the
    teams by the category percentage, then head to head. ``make_setup`` keeps the default, one
    win per matchup."""
    spec = setup.spec and replace(setup.spec, h2h=EACH_CATEGORY, tiebreak=lg.TIEBREAK_EACH)
    return replace(setup, h2h=EACH_CATEGORY, spec=spec)


def of_format(setup: sst.Setup, h2h: str) -> sst.Setup:
    """A one-win ``setup`` (``make_setup``'s) in the format ``h2h``: itself, or
    :func:`every_category`'s. A setup and its spec count one format (``state.Setup`` refuses
    two), so a test names the format here, never on one half."""
    return every_category(setup) if h2h == EACH_CATEGORY else setup


# --------------------------------------------------------------------------- a recorded season
#: A made-up recorded season's chance of a new absence after a played game.
ABSENCE_HAZARD = 0.12


def _out_through(setup: sst.Setup, player: int, days: list[date]) -> int:
    """The last game index the player misses by the status read on day one; -1 when in."""
    s = setup.statuses.get(player)
    if s is None or not days:
        return -1
    if s in wk.OUT_ALL:
        return len(days) - 1
    if s in wk.OUT_THIS_WEEK:
        ret = setup.returns.get(player) or setup.start + timedelta(policy.DEFAULT_ABSENCE_DAYS)
        return sum(1 for d in days if d < ret) - 1
    return -1


def _count(g: np.random.Generator, rate: float) -> int:
    """A whole count around ``rate``: ``rate`` times a :func:`between` draw from 0.4 to 1.6,
    rounded. Python's arithmetic on one ``random()`` draw, so alike on every machine (no
    ``poisson``, whose draws rest on the machine's ``exp`` and ``log``)."""
    return round(rate * between(g, 0.4, 1.6))


def recorded_lines(
    setup: sst.Setup, seed: int = 11, hazard: float = ABSENCE_HAZARD
) -> dict[int, dict[date, dict[str, float]]]:
    """A made-up recorded season for ``setup``: each player's whole-number line on each of his
    team's game days (``run.game_days_of``) around his projection (:func:`_count`; the makes no
    more than the attempts, the threes no more than the field goals made, the points from the
    three), a new absence after a played game with chance ``hazard`` for
    ``sim_fixtures.run_length`` games, and the status read on day one kept (out all season, or
    out until his return date or the default absence). Each player's draws are his own
    (``[seed, player]``)."""
    out: dict[int, dict[date, dict[str, float]]] = {}
    for k, days in rn.game_days_of(setup).items():
        r = setup.projection.get(k)
        if r is None:
            continue
        g = np.random.default_rng([seed, k])
        out_until = _out_through(setup, k, days)
        played: dict[date, dict[str, float]] = {}
        for i, day in enumerate(days):
            if i <= out_until:
                continue
            fga = _count(g, r["fga"])
            fgm = min(fga, _count(g, r["fgm"]))
            fta = _count(g, r["fta"])
            ftm = min(fta, _count(g, r["ftm"]))
            threes = min(fgm, _count(g, r["threes"]))
            line = {
                "fga": fga,
                "fgm": fgm,
                "fta": fta,
                "ftm": ftm,
                "threes": threes,
                "pts": 2 * fgm + threes + ftm,
                **{s: _count(g, r[s]) for s in ("reb", "ast", "stl", "blk", "tov")},
            }
            played[day] = {s: float(line[s]) for s in wk.STATS}
            if g.random() < hazard:
                out_until = i + run_length(g)
        out[k] = played
    return out


def replay_of(
    setup: sst.Setup, seed: int, path: int, lag: int = 1, season: int = 11, **kw: Any
) -> rn.World:
    """A replay world on ``setup``'s made-up recorded season (:func:`recorded_lines` at
    ``season``, its seed): path ``path`` of seed ``seed``, the absences heard ``lag`` days on."""
    return rn.replay_world(setup, recorded_lines(setup, season), lag, seed, path, **kw)


def arm(name: str = "A", tier: str = "exact", opponents: str = "market", **knobs: Any) -> rn.Arm:
    return rn.Arm(name, tier, {**KNOBS, **knobs}, {"kind": opponents})


# --------------------------------------------------------------------------- a data folder
def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def fixture_players() -> list[dict[str, Any]]:
    """The made-up league's players, read from the season fixture's player list in its order:
    each row's name (first and last, else its ``name``) and positions; a row with no name or no
    id is skipped. Parsed here, not by a source's reader: nothing under ``tests/sim/`` imports
    ``pickandroll.sources`` (``test_boundary.py``)."""
    service = json.loads(fixture("players.json")).get("service") or {}
    out = []
    for p in service.get("player_list") or []:
        name = " ".join(x for x in (p.get("fname"), p.get("lname")) if x).strip() or p.get("name")
        if not name or p.get("id") is None:
            continue
        positions = [x for x in (p.get("display_pos") or "").split(",") if x]
        out.append({"name": name, "positions": positions})
    return out


#: A projection block's games when the logs carry blocks (:func:`write_logs`); every
#: :data:`BLOCK_WITHOUT_GAMES`-th player's block has no games count.
BLOCK_GAMES = 70
BLOCK_WITHOUT_GAMES = 7


def projection_block(season: int, i: int, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """A made-up stored projection for player ``i`` from his season's per-game ``entries``: his
    played totals per game scaled by 1.05, over :data:`BLOCK_GAMES` games (no games count for
    every :data:`BLOCK_WITHOUT_GAMES`-th player)."""
    played = [e["stats"] for e in entries if e["stats"]]
    totals: dict[str, float] = {}
    for raw in played:
        for k, v in raw.items():
            totals[k] = totals.get(k, 0.0) + float(v)
    n = max(1, len(played))
    raw = {k: round(1.05 * v / n * BLOCK_GAMES, 3) for k, v in totals.items()}
    if i % BLOCK_WITHOUT_GAMES:
        raw[gl.GAMES_ID] = BLOCK_GAMES
    return entry(season, 0, raw, split=gl.SEASON_TOTAL, source=gl.PROJECTED)


#: The made-up logs' draft positions (#172, PR D4a): a player's figure is a :func:`between` draw
#: from 1 to :data:`ADP_TOP` on a generator of its own (no line's draw moves); a draw past
#: :data:`ADP_CEILING` is an undrafted player, who carries the ceiling itself, the figure the most
#: players share. A season in ``flat_adp`` carries the ceiling for everyone: no table.
ADP_TOP = 200.0
ADP_CEILING = 150.0


def draft_positions(season: int, pids: list[int], flat: bool = False) -> dict[int, float]:
    """The made-up average draft position of each of ``pids`` in ``season``'s log."""
    if flat:
        return dict.fromkeys(pids, ADP_CEILING)
    g = np.random.default_rng([300, season])
    out = {}
    for k in sorted(pids):
        x = between(g, 1.0, ADP_TOP)
        out[k] = min(x, ADP_CEILING)
    return out


def write_logs(
    data: Path,
    seasons: tuple[int, ...],
    players: list[dict[str, Any]],
    projection: bool = False,
    flat_adp: tuple[int, ...] = (),
) -> None:
    """ESPN-shaped logs for ``seasons``: the fixture players under numeric ids (1000 + i), on six
    pro teams, with their positions as eligible slots and a made-up average draft position
    (:func:`draft_positions`; one figure for everyone in a season of ``flat_adp``), which no
    reader reads but the draft table's. ``projection``: each player's log also carries a stored
    projection block (:func:`projection_block`), which no per-game reader reads."""
    folder = data / "external" / "espn" / "gamelogs"
    folder.mkdir(parents=True, exist_ok=True)
    slots = {"PG": 0, "SG": 1, "SF": 2, "PF": 3, "C": 4}
    for si, season in enumerate(seasons):
        rows = synthetic_lines(seed=200 + si, players=len(players), games=45, season=season)
        by_pid: dict[str, list] = {}
        for ln in rows:
            raw = (
                {
                    "0": ln.stats.get("pts"),
                    "1": ln.stats.get("blk"),
                    "2": ln.stats.get("stl"),
                    "3": ln.stats.get("ast"),
                    "6": ln.stats.get("reb"),
                    "11": ln.stats.get("tov"),
                    "13": round(0.47 * ln.stats.get("fga", 0.0)),
                    "14": ln.stats.get("fga"),
                    "15": round(0.78 * ln.stats.get("fta", 0.0)),
                    "16": ln.stats.get("fta"),
                    "17": ln.stats.get("threes"),
                    "40": ln.minutes,
                }
                if ln.played
                else {}
            )
            raw = {k: v for k, v in raw.items() if v is not None}
            i = int(ln.player[1:])
            by_pid.setdefault(str(1000 + i), []).append(
                entry(season, ln.period, raw, team=1 + i % 6)
            )
        if projection:
            for pid, stats in by_pid.items():
                stats.append(projection_block(season, int(pid) - 1000, list(stats)))
        adp = draft_positions(season, [int(pid) for pid in by_pid], season in flat_adp)
        body = {
            "players": [
                {
                    "player": {
                        "id": int(pid),
                        "fullName": players[int(pid) - 1000]["name"],
                        "proTeamId": 1 + (int(pid) - 1000) % 6,
                        "defaultPositionId": slots.get(players[int(pid) - 1000]["positions"][0], 0)
                        + 1,
                        "eligibleSlots": [
                            slots[p] for p in players[int(pid) - 1000]["positions"] if p in slots
                        ]
                        + [11, 12],
                        "ownership": {"averageDraftPosition": adp[int(pid)], "leagueType": 0},
                        "stats": stats,
                    }
                }
                for pid, stats in by_pid.items()
            ]
        }
        (folder / f"{season}.json").write_text(json.dumps({"season": season, "body": body}))


#: The positions the replay's extra players cycle through (:func:`make_data_dir`'s ``wire``).
WIRE_POSITIONS = (["PG"], ["SG"], ["SF"], ["PF"], ["C"], ["PG", "SG"], ["SF", "PF"], ["PF", "C"])


def wire_players(n: int) -> list[dict[str, Any]]:
    """``n`` made-up players for the logs only: in no league's state, so a replay's draft has
    more projected players than its seats take and the rest are on its wire."""
    return [
        {"name": f"Wire Player{i}", "positions": WIRE_POSITIONS[i % len(WIRE_POSITIONS)]}
        for i in range(n)
    ]


def make_data_dir(
    tmp: Path,
    seasons: tuple[int, ...] = (2023, 2024, 2025, 2026),
    wire: int = 0,
    projection: bool = False,
    flat_adp: tuple[int, ...] = (2026,),
) -> Path:
    """A data folder with synthetic logs of the anonymised fixtures' 93 players and no fit yet: no
    league's state, export or id file (the simulator reads none since PR D3).

    ``wire`` made-up players join the logs after the fixture's (:func:`wire_players`), and
    nowhere else. The fixture's 93 are fewer than a replay's twelve seats take (thirteen
    spots each), so its draft takes every projected player and its wire is empty: no seat can
    move. With ``wire`` 120 a replay of 2024 projects 191 of its 213 players (those with 20
    games in 2023), drafts 156 and leaves 35 projected free agents beside the newcomers. The
    first 93 players' lines are the same either way (they are drawn first), and ``wire`` 0 is
    the folder as it always was. ``projection``: the logs carry stored projection blocks
    (:func:`write_logs`), for the ``espn`` forecaster; without it they carry none. Every log
    carries made-up draft positions but a season of ``flat_adp`` (the confirmation season by
    default, as on the box), whose players all carry one figure (#172, PR D4a)."""
    data = tmp / "data"
    data.mkdir(parents=True)
    write_logs(data, seasons, fixture_players() + wire_players(wire), projection, flat_adp)
    return data


__all__ = [
    "ABSENCE_HAZARD",
    "ADP_CEILING",
    "ADP_TOP",
    "KNOBS",
    "NINE",
    "arm",
    "draft_positions",
    "make_data_dir",
    "make_setup",
    "rates",
    "recorded_lines",
    "replay_of",
]
