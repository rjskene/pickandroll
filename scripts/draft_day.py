"""Draft day, the API side (#67): the commands docs/DRAFT_DAY.md runs for one league.

    python scripts/draft_day.py status 238174     # Yahoo's view of the draft, the folder, the servers
    python scripts/draft_day.py servers --start   # check :8000 and :5173, start the launch.json entries
    python scripts/draft_day.py refresh 238174    # re-fetch the league's players file (public, no sign-in)
    python scripts/draft_day.py attach 238174     # wait for the draft tab's seat, attach the room
    python scripts/draft_day.py monitor 238174    # follow the room to the last pick, Mac kept awake
    python scripts/draft_day.py finish 238174     # save the ledger and snapshots, write the scorecard
    python scripts/draft_day.py run 238174        # all of it, in that order (run it in the background)

Nothing here arms a room: the attach names no mode, so the room comes up in autopilot only when the
user pre-armed the league in the dashboard (data/leagues/<id>/armed.json), and mirrors otherwise.
Nothing here signs in anywhere: Yahoo's settings, draft status and players endpoints are public.

Exit codes: 0 done, 1 error, 2 the league is gone (dissolved at the draw), 3 the draft moved,
4 the servers are down or predate #67, 5 no draft tab with a seat in time, 6 the draft tab went
quiet, 7 Yahoo finished the draft before the room did, 8 the room's log is an earlier run's.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pickandroll.fidelity import read_events
from pickandroll.sources.yahoo import load_players_file

DATA = ROOT / "data"
API = os.environ.get("PICKANDROLL_API", "http://127.0.0.1:8000").rstrip("/")
WEB = os.environ.get("PICKANDROLL_WEB", "http://127.0.0.1:5173").rstrip("/")
LAUNCH = Path.home() / "code" / ".claude" / "launch.json"
YAHOO = "https://pub-api.fantasysports.yahoo.com/fantasy/v3"
#: A moved draft this many hours off or more is the master's to reschedule, not this run's.
MOVE_WAIT_H = 6.0
#: A room log first attached this many hours or more before the draft is an earlier run's (a
#: rehearsal under the league's id): rebuilt, it would bring back that run's session and mode.
STALE_LOG_H = 6.0
#: The attach waits for the draft tab until this long after the draft's start.
ATTACH_GRACE_S = 15 * 60
#: The leagues' draft times are Pacific; the Mac may keep another zone.
PACIFIC = ZoneInfo("America/Los_Angeles")

OK, ERROR, GONE, MOVED, DOWN, NO_TAB, QUIET, YAHOO_DONE, STALE = range(9)


class Stop(Exception):
    """A step that cannot go on: its message is printed and its code is the exit code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


#: The league's run log, data/fidelity/draft_day_<league>.log (the scheduled task's log file).
LOG: Path | None = None


def say(message: str) -> None:
    line = f"{datetime.now(UTC).astimezone():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    if LOG is not None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------- http
def call(method: str, url: str, body: Any = None, timeout: float = 30.0) -> tuple[int | None, Any]:
    """(status, parsed JSON or text); status None when nothing answered."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "pickandroll-draft-day")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return None, str(exc)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def api(method: str, path: str, body: Any = None, timeout: float = 60.0) -> Any:
    status, out = call(method, API + path, body, timeout)
    if status is None:
        raise Stop(DOWN, f"the API on {API} does not answer ({out})")
    if status >= 400:
        detail = out.get("detail") if isinstance(out, dict) else out
        raise Stop(ERROR, f"{method} {path}: {status} {detail}")
    return out


def yahoo_settings(league: str) -> dict[str, Any] | None:
    """Yahoo's public settings for the league, or None when Yahoo has no such league."""
    status, out = call("GET", f"{YAHOO}/settings/nba/{league}?format=json")
    if status is None:
        raise Stop(ERROR, f"cannot reach Yahoo ({out})")
    if not isinstance(out, dict) or "service" not in out:
        return None
    return out["service"]


# --------------------------------------------------------------------------- the folder
def folder(league: str) -> Path:
    path = DATA / "leagues" / league
    if not (path / "settings.json").exists():
        raise Stop(ERROR, f"no data/leagues/{league}/settings.json")
    return path


def settings(league: str) -> dict[str, Any]:
    return json.loads((folder(league) / "settings.json").read_text())


def newest_projections() -> str:
    files = sorted(DATA.glob("bbm_projections_*.csv"))
    if not files:
        raise Stop(ERROR, "no data/bbm_projections_*.csv")
    return files[-1].name


def run_dir(league: str) -> Path:
    path = DATA / "draft_day" / league
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------- status
def status(league: str, accept_move: bool = False) -> str:
    """Yahoo's view of the draft against the folder's: gone and moved stop; otherwise Yahoo's
    draft status (``predraft``, ``postdraft``, ...)."""
    mine = settings(league)
    y = yahoo_settings(league)
    if y is None:
        raise Stop(
            GONE,
            f"league {league}: Yahoo has no such league now (dissolved at the draw, or deleted)",
        )
    ys = y.get("settings") or {}
    joined, size = y.get("num_teams"), ys.get("max_teams") or mine.get("num_teams")
    at = datetime.fromtimestamp(int(ys["draft_time"]), UTC) if ys.get("draft_time") else None
    planned = datetime.fromisoformat(mine["draft"]["time"]) if mine.get("draft") else None
    armed = (folder(league) / "armed.json").exists()
    players = folder(league) / "yahoo_players.json"
    when = (
        f"draft at {at.astimezone(PACIFIC):%a %Y-%m-%d %H:%M %Z} ({at.astimezone():%H:%M %Z} here)"
        if at
        else "draft time unknown"
    )
    say(
        f"league {league}: {mine['scoring']}, {joined} of {size} teams joined, Yahoo draft "
        f"status {y.get('draft_status')}, {when}"
    )
    say(
        f"  {'ARMED by the user' if armed else 'not armed: the room will mirror'}; players file "
        + (
            f"from {datetime.fromtimestamp(players.stat().st_mtime, UTC).astimezone():%Y-%m-%d %H:%M}"
            if players.exists()
            else "MISSING"
        )
    )
    if y.get("draft_status") == "postdraft":
        say(f"  Yahoo says the draft of {league} is over")
        return "postdraft"
    if at and planned and abs((at - planned).total_seconds()) > 60:
        hours = (at - datetime.now(UTC)).total_seconds() / 3600
        if accept_move and -1 < hours < MOVE_WAIT_H:
            mine["draft"]["time"] = at.astimezone(PACIFIC).isoformat()
            (folder(league) / "settings.json").write_text(json.dumps(mine, indent=1) + "\n")
            say(f"  the draft moved to {at.astimezone(PACIFIC):%a %H:%M %Z}: settings.json updated")
            return str(y.get("draft_status"))
        raise Stop(
            MOVED,
            f"league {league}: the draft moved, Yahoo says {at.astimezone(PACIFIC):%a %H:%M %Z}, "
            f"settings.json says {planned.astimezone(PACIFIC):%a %H:%M %Z}",
        )
    return str(y.get("draft_status"))


# --------------------------------------------------------------------------- servers
def launch_entry(name: str) -> dict[str, Any]:
    entries = json.loads(LAUNCH.read_text())["configurations"]
    for entry in entries:
        if entry["name"] == name:
            return entry
    raise Stop(ERROR, f"no {name} in {LAUNCH}")


def servers(start: bool = False) -> int:
    """The draft API on :8000 with the league endpoints (#67) and the dashboard on :5173; with
    ``start``, the missing ones are started from their launch.json entries."""
    for name, check in (
        ("pickandroll-api-draft", API + "/leagues"),
        ("pickandroll-web", WEB + "/"),
    ):
        code, out = call("GET", check, timeout=10)
        if code == 200:
            say(f"{name}: up")
            continue
        if code is not None:
            raise Stop(
                DOWN,
                f"{name}: {check} answers {code}: the server predates #67; restart it on main "
                "(docs/DRAFT_DAY.md, 'Servers'), but never while another league's room is live",
            )
        if not start:
            raise Stop(DOWN, f"{name}: down ({out}); start it from launch.json")
        entry = launch_entry(name)
        log = run_dir("servers") / f"{name}.log"
        say(f"{name}: starting from {LAUNCH.name}, log {log.relative_to(ROOT)}")
        with log.open("ab") as out_file:
            subprocess.Popen(
                [entry["runtimeExecutable"], *entry.get("runtimeArgs", [])],
                cwd=ROOT,
                stdout=out_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        for _ in range(60):
            time.sleep(2)
            if call("GET", check, timeout=5)[0] == 200:
                say(f"{name}: up")
                break
        else:
            raise Stop(DOWN, f"{name}: did not come up in 120 s; see {log}")
    live = api("GET", "/rooms")
    if live:
        say(f"live rooms on the API: {', '.join(str(r.get('draft_id')) for r in live)}")
    return OK


# --------------------------------------------------------------------------- players
def refresh(league: str) -> int:
    """Yahoo's players list for the league, with its ADP, o_rank and eligibility (public)."""
    path = folder(league) / "yahoo_players.json"
    url = f"{YAHOO}/players/nba/{league}?format=json&projected=1&average=1"
    code, out = call("GET", url, timeout=60)
    if code != 200 or not isinstance(out, dict) or "service" not in out:
        say(f"players file not refreshed (Yahoo answered {code}); keeping the one on disk")
        return OK
    tmp = path.with_suffix(".new")
    tmp.write_text(json.dumps(out))
    try:
        count = len(load_players_file(tmp))
    except (KeyError, ValueError) as exc:
        tmp.unlink()
        say(f"players file not refreshed ({exc}); keeping the one on disk")
        return OK
    if count < 300:
        tmp.unlink()
        say(f"players file not refreshed (only {count} players); keeping the one on disk")
        return OK
    tmp.replace(path)
    say(f"players file refreshed: {count} players")
    return OK


# --------------------------------------------------------------------------- attach
def live_room(league: str) -> dict[str, Any] | None:
    for room in api("GET", "/rooms"):
        if str(room.get("draft_id")) == league:
            return room
    return None


def check_log(league: str, mine: dict[str, Any]) -> None:
    """Stop (exit 8) when the league's room log was first attached ``STALE_LOG_H`` or more before
    this draft. The attach would rebuild that run's room from it, with its session and mode, and
    the user's pre-arm is read only at a log's first attach."""
    path = DATA / "fidelity" / f"{league}.jsonl"
    planned = (mine.get("draft") or {}).get("time")
    if not path.exists() or not planned:
        return
    first = next(
        (e["t"] for e in read_events(path) if e.get("type") == "attach" and e.get("t")), None
    )
    if first is None:
        return
    attached = datetime.fromisoformat(str(first))
    draft = datetime.fromisoformat(planned)
    hours = (draft - attached).total_seconds() / 3600
    if hours < STALE_LOG_H:
        return
    aside = path.with_name(f"{league}_{attached.astimezone(PACIFIC):%Y-%m-%d}_earlier.jsonl")
    raise Stop(
        STALE,
        f"{path.relative_to(ROOT)} is an earlier run's log: first attached "
        f"{attached.astimezone(PACIFIC):%a %Y-%m-%d %H:%M %Z}, {hours:.0f} h before this draft "
        f"({draft.astimezone(PACIFIC):%a %H:%M %Z}). Move it aside "
        f"(mv {path.relative_to(ROOT)} {aside.relative_to(ROOT)}; if GET /rooms lists room "
        f"{league}, DELETE /rooms/{league} first) and run again",
    )


def attach(league: str, wait_s: float | None) -> int:
    """Attach the league's draft room once the user's draft tab reports its seat (waiting
    ``wait_s``, by default until 15 minutes after the draft's start). Names no mode: the user's
    pre-arm, or mirror. An earlier run's log under the league's id stops it (``check_log``)."""
    mine = settings(league)
    check_log(league, mine)
    if wait_s is None:
        start = datetime.fromisoformat(mine["draft"]["time"])
        wait_s = max(600.0, (start - datetime.now(UTC)).total_seconds() + ATTACH_GRACE_S)
    room = live_room(league)
    if room is not None:
        say(f"room {league} is already attached (mode {room.get('mode')})")
        return OK
    if (DATA / "fidelity" / f"{league}.jsonl").exists():
        # The API restarted mid-draft: rebuild the room from its log, mode as last set.
        room = api("POST", "/rooms", {"draft_id": league}, timeout=300)
        say(
            f"room {league} rebuilt from its log: mode {room['mode']}, {room['picks_applied']} picks"
        )
        return OK
    deadline = time.monotonic() + wait_s
    last_note = 0.0
    last_yahoo = time.monotonic()
    while True:
        seen = [r for r in api("GET", "/rooms/seen") if str(r.get("draft_id")) == league]
        if seen and seen[0].get("slot"):
            break
        if time.monotonic() > deadline:
            raise Stop(
                NO_TAB,
                f"no draft tab for {league} with a seat after {wait_s / 60:.0f} min: is the room "
                "open in Chrome on the draftclient page (docs/DRAFT_DAY.md, step 3)?",
            )
        if time.monotonic() - last_note > 60:
            say("waiting for the draft tab: " + ("seen, no seat yet" if seen else "not seen"))
            last_note = time.monotonic()
        if time.monotonic() - last_yahoo > 120:
            if yahoo_settings(league) is None:
                raise Stop(GONE, f"league {league}: Yahoo has no such league now (dissolved)")
            last_yahoo = time.monotonic()
        time.sleep(5)
    slot, room_teams = int(seen[0]["slot"]), seen[0].get("room_teams")
    teams = int(room_teams or mine.get("num_teams") or 12)
    session = {"projection_file": newest_projections(), "league": league, "num_teams": teams}
    body: dict[str, Any] = {
        "draft_id": league,
        "slot": slot,
        "clock_s": float((mine.get("draft") or {}).get("pick_seconds") or 60),
        "session": session,
    }
    if room_teams:
        body["room_teams"] = int(room_teams)
    say(
        f"attaching room {league}: seat {slot} of {teams}, projections {session['projection_file']}"
    )
    room = api("POST", "/rooms", body, timeout=300)
    armed = room["mode"] == "autopilot"
    say(
        f"attached: session {room['session_id']}, mode {room['mode']} "
        + ("(the user's pre-arm)" if armed else "(not armed: Yahoo autopicks the user's turns)")
    )
    (run_dir(league) / "attach.json").write_text(json.dumps(room, indent=1, default=str))
    return OK


# --------------------------------------------------------------------------- monitor
def keep_awake() -> None:
    """caffeinate for as long as this process runs: the display woken and kept on, no idle or
    system sleep."""
    if shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())], start_new_session=True)


def monitor(league: str, quiet_s: float, give_up_s: float, limit_s: float) -> int:
    """Follow the room to its last pick. A draft tab quiet past ``quiet_s`` is reported, past
    ``give_up_s`` ends the monitor (exit 6) so the session can look at the tab."""
    keep_awake()
    started = time.monotonic()
    last_pick, last_alert, last_yahoo, down_since = -1, 0.0, 0.0, None
    ext = None
    while True:
        code, room = call("GET", f"{API}/rooms/{league}", timeout=60)
        now = time.monotonic()
        if code != 200:
            down_since = down_since or now
            say(f"ALERT the room does not answer ({code}: {str(room)[:120]})")
            if now - down_since > give_up_s:
                raise Stop(DOWN, f"the API has not answered for room {league} in {give_up_s:.0f} s")
            time.sleep(15)
            continue
        down_since = None
        version = (room.get("heartbeat") or {}).get("ext_version")
        if version and version != ext:
            ext = version
            old = tuple(int(x) for x in str(version).split(".")[:3] if x.isdigit()) < (0, 3, 0)
            say(
                f"{'ALERT ' if old else ''}the draft tab runs extension {version}"
                + (": older than 0.3.0, the seat may be wrong in a real league room" if old else "")
            )
        picks = int(room["picks_applied"])
        total = int(room["num_teams"]) * int(room["rounds"])
        if picks != last_pick:
            say(
                f"pick {picks}/{total}, mode {room['mode']}, my next {room.get('my_next_pick')}, "
                f"tab heartbeat {room.get('heartbeat_age_s')} s ago"
            )
            last_pick = picks
        if room.get("complete"):
            say(f"room {league} complete: {picks}/{total} picks")
            return OK
        age = room.get("heartbeat_age_s")
        if age is not None and age > quiet_s and now - last_alert > 60:
            say(
                f"ALERT the draft tab has been quiet for {age:.0f} s (docs/DRAFT_DAY.md, 'Quiet tab')"
            )
            last_alert = now
            if age > give_up_s:
                raise Stop(QUIET, f"the draft tab for {league} has been quiet for {age:.0f} s")
        if now - last_yahoo > 300:
            y = yahoo_settings(league)
            if y is not None and y.get("draft_status") == "postdraft":
                raise Stop(
                    YAHOO_DONE, f"Yahoo says the draft is over; the room has {picks}/{total} picks"
                )
            last_yahoo = now
        if now - started > limit_s:
            raise Stop(ERROR, f"the draft of {league} ran past {limit_s / 3600:.1f} h")
        time.sleep(15)


# --------------------------------------------------------------------------- finish
def finish(league: str) -> int:
    """Copy the room log and the session's snapshots next to it, and write the scorecard and
    the comment for #67 (no team names, no projection numbers beyond the scorecard's own)."""
    code, room = call("GET", f"{API}/rooms/{league}", timeout=120)
    if code != 200:
        raise Stop(ERROR, f"no room {league} on the API ({code})")
    sid = room["session_id"]
    out = DATA / "fidelity" / f"{league}_{datetime.now(UTC).astimezone():%Y-%m-%d}_session_{sid}"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(DATA / "fidelity" / f"{league}.jsonl", out / "ledger.jsonl")
    snapshots = {
        "room.json": f"/rooms/{league}",
        "session.json": f"/sessions/{sid}",
        "board.json": f"/sessions/{sid}/board?limit=1000",
        "teams.json": f"/sessions/{sid}/teams",
        "picks.json": f"/sessions/{sid}/picks",
        "score.json": f"/sessions/{sid}/score",
        "scorecard.json": f"/rooms/{league}/fidelity",
    }
    for name, path in snapshots.items():
        code, body = call("GET", API + path, timeout=120)
        if code == 200:
            (out / name).write_text(json.dumps(body, indent=1, default=str))
        else:
            say(f"  {name}: {code}, not saved")
    code, card = call("GET", f"{API}/rooms/{league}/fidelity?format=md", timeout=120)
    card = (
        card if code == 200 and isinstance(card, str) else "(no scorecard: the room log has none)\n"
    )
    (out / "scorecard.md").write_text(card)
    mine = settings(league)
    armed = room["mode"] == "autopilot"
    kind = "H2H points" if mine["scoring"] == "points" else "H2H categories"
    head = (
        f"### Cash league {league} ({kind}), draft {datetime.now(UTC).astimezone():%Y-%m-%d}\n\n"
        f"Run by `scripts/draft_day.py` (docs/DRAFT_DAY.md). Mode {room['mode']}"
        + (
            " from the user's own pre-arm in the dashboard"
            if armed
            else ", not armed: Yahoo autopicked the user's turns"
        )
        + f"; {room['picks_applied']}/{int(room['num_teams']) * int(room['rounds'])} picks"
        + (", complete" if room.get("complete") else ", NOT complete")
        + ". Ledger and snapshots saved locally.\n\n"
    )
    (out / "comment.md").write_text(head + card)
    say(f"saved {out.relative_to(ROOT)}: " + ", ".join(sorted(p.name for p in out.iterdir())))
    say(f"post it: gh issue comment 67 --body-file {out / 'comment.md'}")
    print(head + card)
    return OK


# --------------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command", choices=["status", "servers", "refresh", "attach", "monitor", "finish", "run"]
    )
    parser.add_argument("league", nargs="?", help="the Yahoo league id (data/leagues/<id>/)")
    parser.add_argument("--start", action="store_true", help="servers: start what is down")
    parser.add_argument(
        "--wait", type=float, help="attach: seconds to wait for the tab (default: start + 15 min)"
    )
    parser.add_argument(
        "--accept-move",
        action="store_true",
        help=f"status, run: take Yahoo's new draft time when it is under {MOVE_WAIT_H:g} h away",
    )
    parser.add_argument(
        "--quiet", type=float, default=180, help="monitor: seconds before a quiet-tab alert"
    )
    parser.add_argument(
        "--give-up", type=float, default=1200, help="monitor: seconds before exit 6"
    )
    parser.add_argument(
        "--limit", type=float, default=5 * 3600, help="monitor: longest draft, seconds"
    )
    args = parser.parse_args()
    if args.command != "servers" and not args.league:
        parser.error(f"{args.command} needs a league id")
    if args.league and not str(args.league).isdigit():
        parser.error(f"a Yahoo league id is digits, not {args.league!r}")
    league = str(args.league) if args.league else ""
    if league:
        global LOG
        LOG = DATA / "fidelity" / f"draft_day_{league}.log"
        say(f"draft_day {args.command} {league}")
    try:
        if args.command == "status":
            status(league, args.accept_move)
            return OK
        if args.command == "servers":
            return servers(start=args.start)
        if args.command == "refresh":
            return refresh(league)
        if args.command == "attach":
            return attach(league, args.wait)
        if args.command == "monitor":
            return monitor(league, args.quiet, args.give_up, args.limit)
        if args.command == "finish":
            return finish(league)
        keep_awake()
        if status(league, args.accept_move) == "postdraft" and live_room(league) is None:
            return OK
        servers(start=True)
        refresh(league)
        attach(league, args.wait)
        code = OK
        try:
            monitor(league, args.quiet, args.give_up, args.limit)
        except Stop as exc:
            say(f"STOP {exc} (exit {exc.code})")
            code = exc.code
        finish(league)
        return code
    except Stop as exc:
        say(f"STOP {exc} (exit {exc.code})")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
