#!/usr/bin/env python3
"""Soak comparison (#225): the Mac's live day against the droplet's dry run, from the files
both hosts write under ``data/``: the daily marker, the runner's run logs (the droplet's only;
the Mac's routines are Desktop sessions), the queue, the pass records, the solve decision log,
the executors' log and the exports' names and sizes. Deterministic, read-only, no model in it.

    scripts/soak_compare.py [--date YYYY-MM-DD] [--host USER@ALIAS] [--post]
    scripts/soak_compare.py bundle [--date YYYY-MM-DD] [--data DIR]

The first form runs on the Mac: it bundles the local ``data/``, asks the droplet for its bundle
over ssh (the second form, run there with the system python), compares the two and prints
markdown. ``--post`` puts the markdown on the ops issue as one comment. Exit 0 when nothing is
flagged, 1 when something is, 2 when a side could not be read.

Expected and not flagged: the private league's solve absent on the droplet (``--skip-solve``),
the droplet's post step skipped (``--no-post``), the pass records' and the executors' wording
(live against dry run), the two hosts' own timestamps and export file names.

Standard library only, so the droplet's system python runs the bundle; player and league ids
only, never a name, so the markdown can go on the public issue.
"""

from __future__ import annotations

import argparse
import json
import shlex
import socket
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
#: The decision log's day is the NBA's (``api.season_queue.day_entry``).
NBA_TZ = ZoneInfo("America/New_York")
#: ``routine.report.MARKER_STEPS`` and ``EXPORT_KINDS``, repeated so this file needs no package.
MARKER_STEPS = (
    "api",
    "exports",
    "private_pages",
    "lineup_pages",
    "refresh",
    "solve",
    "digest",
    "post",
)
EXPORT_KINDS = ("ros", "week_this", "week_next", "actual_7d", "actual_14d")
ROUTINES = ("daily", "morning", "late", "evening-build", "evening-pass", "monday", "signin")
EXECUTOR_KINDS = ("lineup", "start_active", "moves", "il")
#: The queue entry fields compared; the solve id, the times and the outcomes are not.
QUEUE_FIELDS = ("set", "judged", "from", "availability", "queued", "struck", "rank")
#: The daily must be done by the window's end (``docs/AUTOPILOT.md`` §3).
DAILY_WINDOW_END = "06:20"
REFRESH_OK = (200, 202)
#: An export this much smaller than the Mac's is flagged.
SMALLER_BY = 0.05
DEFAULT_HOST = "pickandroll@hts-digital-ocean"
DEFAULT_REMOTE_REPO = "pickandroll"
DEFAULT_ISSUE = 225
PRIVATE_LEAGUE = "31822"
REPO = Path(__file__).resolve().parents[1]
MAC, VM = "mac", "droplet"
OK, FLAGGED, UNREAD = 0, 1, 2


# --------------------------------------------------------------------------- the bundle
def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def leagues_of(data: Path) -> list[str]:
    root = data / "leagues"
    if not root.is_dir():
        return []
    return sorted((p.name for p in root.iterdir() if p.is_dir() and p.name.isdigit()), key=int)


def marker_day(marker: Any) -> str | None:
    """The Central day the marker's run started, or None for a marker without one."""
    if not isinstance(marker, dict):
        return None
    when = _when(marker.get("started_at"))
    return when.astimezone(CENTRAL).date().isoformat() if when else None


def bundle(data: Path, day: str) -> dict[str, Any]:
    """Everything the comparison reads from one host's ``data/``, as one JSON document."""
    marker = load(data / "routine" / "daily.json")
    runs: dict[str, Any] = {}
    for path in sorted((data / "routine" / "runs").glob(f"{day}-*.json")):
        runs[path.stem[len(day) + 1 :]] = load(path)
    exports: dict[str, Any] = {}
    if marker_day(marker) == day:
        for kind, name in (marker.get("exports") or {}).items():
            path = data / str(name)
            exports[kind] = {"name": name, "size": path.stat().st_size if path.is_file() else None}
    out: dict[str, Any] = {
        "host": socket.gethostname(),
        "data": str(data),
        "date": day,
        "made_at": datetime.now(CENTRAL).isoformat(timespec="seconds"),
        "marker": marker,
        "runs": runs,
        "queue": load(data / "autopilot" / "queue" / f"{day}.json"),
        "passes": load(data / "autopilot" / "passes" / f"{day}.json"),
        "decisions": {},
        "executor": {},
        "armed": {},
        "exports": exports,
    }
    for league in leagues_of(data):
        folder = data / "leagues" / league
        decisions = load(folder / "season" / "decisions" / f"{day}.json")
        if decisions is not None:
            out["decisions"][league] = decisions
        executor = load(folder / "autopilot" / f"{day}.json")
        if executor is not None:
            out["executor"][league] = executor
        armed = load(folder / "armed.json")
        if isinstance(armed, dict):
            out["armed"][league] = {k: armed.get(k) for k in ("moves", "lineups")}
    return out


def remote_bundle(host: str, repo: str, day: str, run: Callable[..., Any] | None = None) -> Any:
    """The droplet's bundle: this script's ``bundle`` form over ssh, with the system python."""
    where = repo if repo.startswith("/") else f"~/{repo}"
    command = f"cd {where} && python3 scripts/soak_compare.py bundle --date {shlex.quote(day)}"
    result = (run or subprocess.run)(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, command],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh {host}: exit {result.returncode}: {result.stderr.strip()[:300]}")
    return json.loads(result.stdout)


# --------------------------------------------------------------------------- the comparison
class Comparison:
    """The two bundles side by side: markdown lines and the flagged findings among them."""

    def __init__(self, mac: Mapping[str, Any], vm: Mapping[str, Any], day: str, private: str):
        self.mac, self.vm, self.day, self.private = mac, vm, day, private
        self.lines: list[str] = []
        self.flags: list[str] = []

    # ----------------------------------------------------------------- output
    def line(self, text: str = "") -> None:
        self.lines.append(text)

    def flag(self, text: str) -> None:
        self.flags.append(text)
        self.lines.append(f"- **flag:** {text}")

    def table(self, head: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
        self.line("| " + " | ".join(head) + " |")
        self.line("|" + "---|" * len(head))
        for row in rows:
            self.line("| " + " | ".join(str(c) for c in row) + " |")
        self.line()

    def render(self) -> str:
        head = [
            f"# Soak comparison {self.day}",
            f"- {MAC}: {self.mac.get('host')} `{self.mac.get('data')}`, bundled {self.mac.get('made_at')}",
            f"- {VM}: {self.vm.get('host')} `{self.vm.get('data')}`, bundled {self.vm.get('made_at')}",
            f"- executor modes: {MAC} {self.modes(self.mac)}; {VM} {self.modes(self.vm)}",
        ]
        if self.flags:
            head.append(f"- **{len(self.flags)} flagged**: " + "; ".join(self.flags))
        else:
            head.append("- **nothing flagged**")
        return "\n".join([*head, "", *self.lines]).rstrip() + "\n"

    @staticmethod
    def modes(side: Mapping[str, Any]) -> str:
        armed = side.get("armed") or {}
        parts = []
        for key in ("moves", "lineups"):
            counts = Counter(str((a or {}).get(key) or "unset") for a in armed.values())
            parts.append(f"{key} " + (_counter(counts) if counts else "none"))
        return ", ".join(parts)

    # ----------------------------------------------------------------- the sections
    def run(self) -> Comparison:
        self.markers()
        self.runs()
        self.exports()
        self.codes()
        self.queue()
        self.solves()
        self.executors()
        self.passes()
        return self

    def marker_for(self, side: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
        marker = side.get("marker")
        if not isinstance(marker, dict):
            self.flag(f"no daily marker on the {name}")
            return None
        made = marker_day(marker)
        if made != self.day:
            self.flag(f"the {name}'s daily marker is from {made}, not {self.day}")
            return None
        return marker

    def markers(self) -> None:
        self.line("## Daily marker")
        mac, vm = self.marker_for(self.mac, MAC), self.marker_for(self.vm, VM)
        if mac is None or vm is None:
            self.line()
            return
        for name, marker in ((MAC, mac), (VM, vm)):
            started, finished = _when(marker.get("started_at")), _when(marker.get("finished_at"))
            took = (
                f" ({round((finished - started).total_seconds() / 60)} min)"
                if started and finished
                else ""
            )
            self.line(f"- {name}: {_clock(started)}-{_clock(finished)}{took}")
            if name == VM and finished and _clock(finished) > DAILY_WINDOW_END:
                self.flag(
                    f"the {VM}'s daily finished at {_clock(finished)}, after the window's {DAILY_WINDOW_END}"
                )
        details: list[str] = []
        rows = []
        for step in MARKER_STEPS:
            a = (mac.get("steps") or {}).get(step) or {}
            b = (vm.get("steps") or {}).get(step) or {}
            sa, sb = a.get("status", "-"), b.get("status", "-")
            rows.append((step, sa, sb))
            if sa != sb and not _expected_marker(step, b):
                self.flag(f"daily {step}: {MAC} {sa}, {VM} {sb}")
            if a.get("detail") != b.get("detail"):
                details.append(f"- {step}: {MAC} {_trim(a.get('detail'))}")
                details.append(f"  {VM} {_trim(b.get('detail'))}")
        self.line()
        self.table(("step", MAC, VM), rows)
        if details:
            self.line("Details that differ:")
            self.lines.extend(details)
            self.line()

    def runs(self) -> None:
        self.line(f"## The {VM}'s run logs")
        runs = {k: v for k, v in (self.vm.get("runs") or {}).items() if isinstance(v, dict)}
        if not runs:
            self.line(f"- none for {self.day}")
        for name, run in runs.items():
            steps = [s for s in run.get("steps") or [] if isinstance(s, dict)]
            head = f"- **{name}** {_clock(_when(run.get('started_at')))}-{_clock(_when(run.get('finished_at')))}"
            if run.get("refused"):
                head += f", refused: {_trim(run['refused'])}"
            if run.get("stopped"):
                head += ", STOP set"
            self.line(head)
            self.line(
                "  - "
                + (", ".join(f"{s.get('name')} {s.get('status')}" for s in steps) or "no steps")
            )
            for step in steps:
                if step.get("status") == "failed":
                    self.flag(
                        f"{VM} {name}: step {step.get('name')} failed: {_trim(step.get('detail'))}"
                    )
            for alert in run.get("alerts") or []:
                self.flag(f"{VM} {name} alert: {_trim(alert)}")
        missing = [r for r in ROUTINES if r not in runs]
        if missing:
            self.line(f"- no run log yet: {', '.join(missing)}")
        self.line()

    def exports(self) -> None:
        self.line("## Exports")
        mac, vm = self.mac.get("exports") or {}, self.vm.get("exports") or {}
        rows = []
        for kind in EXPORT_KINDS:
            a, b = mac.get(kind), vm.get(kind)
            rows.append((kind, _export_cell(a), _export_cell(b)))
            if a and not b:
                self.flag(f"export {kind} missing on the {VM}")
            elif b and b.get("size") is None:
                self.flag(
                    f"export {kind} on the {VM}: the marker names {b.get('name')} but the file is missing"
                )
            elif a and b and a.get("size") and b.get("size") < a["size"] * (1 - SMALLER_BY):
                pct = round(100 * (1 - b["size"] / a["size"]))
                self.flag(
                    f"export {kind} on the {VM} is {pct}% smaller ({b['size']} against {a['size']} bytes)"
                )
        self.table(("kind", MAC, VM), rows)

    def codes(self) -> None:
        self.line("## Refresh and solve")
        mac = self.mac.get("marker") if marker_day(self.mac.get("marker")) == self.day else None
        for step in ("refresh", "solve"):
            detail = (((mac or {}).get("steps") or {}).get(step) or {}).get("detail")
            self.line(f"- {MAC} {step}: {_trim(detail) if detail else 'no marker'}")
        daily = (self.vm.get("runs") or {}).get("daily")
        if not isinstance(daily, dict):
            self.line(f"- {VM}: no daily run log")
            self.line()
            return
        refresh = _step(daily, "refresh")
        codes = (refresh.get("data") or {}).get("codes") or {}
        self.line(f"- {VM} refresh: {_codes(codes)}")
        for league, code in _by_league(codes):
            if code not in REFRESH_OK:
                self.flag(f"{VM} refresh of {league} answered {code}")
        solve = _step(daily, "solve")
        codes = (solve.get("data") or {}).get("codes") or {}
        left_out = self.left_out()
        self.line(
            f"- {VM} solve: {_codes(codes)}; left out: {', '.join(sorted(left_out, key=_league_key)) or 'none'}"
        )
        for league, code in _by_league(codes):
            if code != 200 and league not in left_out:
                self.flag(f"{VM} solve of {league} answered {code}")
        self.line()

    def left_out(self) -> set[str]:
        """The leagues the droplet's daily left unsolved, the private league always."""
        daily = (self.vm.get("runs") or {}).get("daily")
        out = {self.private}
        if isinstance(daily, dict):
            out.update(
                str(x) for x in (_step(daily, "solve").get("data") or {}).get("left_out") or []
            )
        return out

    def queue(self) -> None:
        self.line("## Queue")
        a, b = self.mac.get("queue"), self.vm.get("queue")
        if not isinstance(a, dict) or not isinstance(b, dict):
            for name, q in ((MAC, a), (VM, b)):
                if not isinstance(q, dict):
                    self.line(f"- no queue file for {self.day} on the {name}")
            if isinstance(a, dict) != isinstance(b, dict):
                self.flag(
                    f"queue file for {self.day} only on the {MAC if isinstance(a, dict) else VM}"
                )
            self.line()
            return
        if a.get("execute_time") != b.get("execute_time"):
            self.flag(
                f"queue execute time: {MAC} {a.get('execute_time')}, {VM} {b.get('execute_time')}"
            )
        ra = {str(r.get("league")): r for r in a.get("leagues") or []}
        rb = {str(r.get("league")): r for r in b.get("leagues") or []}
        rows = []
        for league in sorted(set(ra) | set(rb), key=_league_key):
            x, y = ra.get(league), rb.get(league)
            rows.append((league, _league_cell(x), _league_cell(y)))
            if x is None or y is None:
                self.flag(f"queue league row {league} only on the {MAC if x else VM}")
                continue
            for field in ("status", "decision", "cap", "budget"):
                if x.get(field) != y.get(field):
                    self.flag(
                        f"queue league {league} {field}: {MAC} {x.get(field)}, {VM} {y.get(field)}"
                    )
            if (x.get("adds") or {}).get("left") != (y.get("adds") or {}).get("left"):
                self.flag(
                    f"queue league {league} adds left: {MAC} {(x.get('adds') or {}).get('left')},"
                    f" {VM} {(y.get('adds') or {}).get('left')}"
                )
        self.table(("league", MAC, VM), rows)
        ea = {str(e.get("id")): e for e in a.get("entries") or []}
        eb = {str(e.get("id")): e for e in b.get("entries") or []}
        for entry_id in sorted(set(ea) ^ set(eb)):
            self.flag(f"queue entry {entry_id} only on the {MAC if entry_id in ea else VM}")
        for entry_id in sorted(set(ea) & set(eb)):
            x, y = ea[entry_id], eb[entry_id]
            diffs = [f for f in QUEUE_FIELDS if x.get(f) != y.get(f)]
            if _bid(x) != _bid(y):
                diffs.append("bid")
            if diffs:
                shown = "; ".join(f"{f} {MAC} {_field(x, f)} / {VM} {_field(y, f)}" for f in diffs)
                self.flag(f"queue entry {entry_id} differs in {', '.join(diffs)}: {shown}")
        shared = len(set(ea) & set(eb))
        self.line(
            f"- entries: {len(ea)} on the {MAC}, {len(eb)} on the {VM}, {shared} shared by id"
        )
        oa = Counter(str(e.get("outcome")) for e in ea.values())
        ob = Counter(str(e.get("outcome")) for e in eb.values())
        self.line(f"- outcomes (shown, not counted): {MAC} {_counter(oa)}; {VM} {_counter(ob)}")
        self.line()

    def solves(self) -> None:
        self.line("## Solves (the decision log's last moves solve of the day)")
        da, db = self.mac.get("decisions") or {}, self.vm.get("decisions") or {}
        left_out = self.left_out()
        for league in sorted(set(da) | set(db) | left_out, key=_league_key):
            x, y = _last_moves(da.get(league), self.day), _last_moves(db.get(league), self.day)
            if y is None and league in left_out:
                what = f"{MAC} {_sets(x)}" if x else f"no moves solve on the {MAC} either"
                self.line(f"- {league}: not solved on the {VM} (left out by design); {what}")
                continue
            if x is None and y is None:
                self.line(f"- {league}: no moves solve on either host")
                continue
            if x is None or y is None:
                self.flag(f"{league}: no moves solve on the {MAC if y else VM} today")
                self.line(f"- {league}: {MAC} {_sets(x)}; {VM} {_sets(y)}")
                continue
            fa, fb = (x.get("system") or {}).get("file"), (y.get("system") or {}).get("file")
            if fa != fb:
                self.flag(f"{league} solve system export: {MAC} {fa}, {VM} {fb}")
            sa = {s.get("key"): s for s in x.get("sets") or []}
            sb = {s.get("key"): s for s in y.get("sets") or []}
            same = True
            for key in sorted(set(sa) | set(sb), key=str):
                ma, mb = _moves_of(sa.get(key), key), _moves_of(sb.get(key), key)
                if set(ma) != set(mb):
                    same = False
                    self.flag(f"{league} set {key}: {MAC} {_fmt_moves(ma)}; {VM} {_fmt_moves(mb)}")
            pa, pb = (
                (x.get("plan") or {}).get("recommended"),
                (y.get("plan") or {}).get("recommended"),
            )
            if pa != pb:
                same = False
                self.flag(f"{league} week plan recommended: {MAC} {pa}, {VM} {pb}")
            self.line(
                f"- {league}: {'same sets' if same else 'sets differ'}; {MAC} {_sets(x)}; {VM} {_sets(y)}"
            )
        self.line()

    def executors(self) -> None:
        self.line("## Executors (the extension's log; wording shown, not counted)")
        ea, eb = self.mac.get("executor") or {}, self.vm.get("executor") or {}
        for league in sorted(set(ea) | set(eb), key=_league_key):
            x, y = ea.get(league) or {}, eb.get(league) or {}
            parts = []
            for kind in EXECUTOR_KINDS:
                ca = Counter(f"{e.get('mode')}:{e.get('outcome')}" for e in x.get(kind) or [])
                cb = Counter(f"{e.get('mode')}:{e.get('outcome')}" for e in y.get(kind) or [])
                if ca or cb:
                    parts.append(f"{kind} {MAC} {_counter(ca)} / {VM} {_counter(cb)}")
            self.line(f"- {league}: " + ("; ".join(parts) or "nothing logged"))
            self.lineups(league, x.get("lineup") or [], y.get("lineup") or [])
        if not ea and not eb:
            self.line("- nothing logged on either host")
        self.line()

    def lineups(self, league: str, mac: Sequence[Any], vm: Sequence[Any]) -> None:
        """The droplet's would-set slots against the Mac's lineup for the same page."""
        for entry in vm:
            if not isinstance(entry, dict) or entry.get("mode") != "dry_run":
                continue
            would = (entry.get("controls") or {}).get("would_set") or {}
            if not would:
                continue
            page = entry.get("page")
            match = next(
                (m for m in reversed(mac) if isinstance(m, dict) and m.get("page") == page), None
            )
            if match is None:
                self.line(
                    f"  - lineup {page}: the {VM} would set {len(would)} slots; the {MAC} has no entry for that page"
                )
                continue
            after = _lineup_after(match)
            wrong = {p: (s, after.get(str(p))) for p, s in would.items() if after.get(str(p)) != s}
            if wrong:
                shown = ", ".join(
                    f"{p} to {s} (the {MAC} has {m or 'no slot'})" for p, (s, m) in wrong.items()
                )
                self.flag(f"{league} lineup {page}: the {VM} would set {shown}")
            else:
                self.line(
                    f"  - lineup {page}: the {VM}'s {len(would)} would-set slots match the {MAC}'s lineup"
                )

    def passes(self) -> None:
        self.line("## Passes (shown, not counted)")
        for name, side in ((MAC, self.mac), (VM, self.vm)):
            record = side.get("passes")
            items = record.get("passes") if isinstance(record, dict) else None
            if not items:
                self.line(f"- {name}: no pass record")
                continue
            for x in items:
                outcomes = Counter(str(v) for v in (x.get("outcomes") or {}).values())
                self.line(
                    f"- {name} {x.get('id')}: {x.get('kind')} by {x.get('trigger')}, {x.get('end')},"
                    f" {_trim(x.get('summary'))}; outcomes {_counter(outcomes)}"
                )
        self.line()


# --------------------------------------------------------------------------- helpers
def _when(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=CENTRAL)


def _clock(when: datetime | None) -> str:
    return when.astimezone(CENTRAL).strftime("%H:%M") if when else "-"


def _trim(text: Any, width: int = 160) -> str:
    return " ".join(str(text or "").split())[:width]


def _counter(counts: Counter[str]) -> str:
    return ", ".join(f"{k} x{n}" for k, n in sorted(counts.items())) or "none"


def _league_key(league: str) -> tuple[int, int, str]:
    return (0, int(league), "") if str(league).isdigit() else (1, 0, str(league))


def _by_league(codes: Mapping[str, Any]) -> list[tuple[str, Any]]:
    return sorted(((str(k), v) for k, v in codes.items()), key=lambda kv: _league_key(kv[0]))


def _codes(codes: Mapping[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in _by_league(codes)) or "no codes"


def _step(run: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return next(
        (s for s in run.get("steps") or [] if isinstance(s, dict) and s.get("name") == name), {}
    )


def _lineup_after(entry: Mapping[str, Any]) -> dict[str, Any]:
    """The lineup a Mac entry stands for: what Yahoo showed after a live set, or the lineup it
    read with its own would-set slots laid over it when the Mac too ran in dry run."""
    if entry.get("mode") == "live":
        return dict(entry.get("after") or {})
    would = (entry.get("controls") or {}).get("would_set") or {}
    return {**(entry.get("before") or {}), **{str(k): v for k, v in would.items()}}


def _expected_marker(step: str, vm: Mapping[str, Any]) -> bool:
    """The droplet's post step is skipped by the soak's ``--no-post``: never a finding."""
    return step == "post" and vm.get("status") == "skipped"


def _export_cell(x: Any) -> str:
    if not x:
        return "-"
    size = x.get("size")
    return f"{x.get('name')} ({size if size is not None else 'missing'})"


def _league_cell(row: Any) -> str:
    if not row:
        return "-"
    adds = row.get("adds") or {}
    return f"{row.get('status')}/{row.get('decision')}, cap {row.get('cap')}, left {adds.get('left')}, budget {row.get('budget')}"


def _bid(entry: Mapping[str, Any]) -> Any:
    return (entry.get("bid") or {}).get("amount")


def _field(entry: Mapping[str, Any], name: str) -> Any:
    return _bid(entry) if name == "bid" else entry.get(name)


def _last_moves(entries: Any, day: str) -> Mapping[str, Any] | None:
    """The day's last moves solve, the day on the NBA's clock (``season_queue.day_entry``)."""
    out = None
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or e.get("source") != "moves":
            continue
        when = _when(e.get("at"))
        if when and when.astimezone(NBA_TZ).date().isoformat() == day:
            out = e
    return out


def _moves_of(a_set: Any, key: Any) -> list[tuple[Any, Any, Any]]:
    """A set's moves as (add, drop, gain on the set's own horizon)."""
    out = []
    for m in (a_set or {}).get("moves") or []:
        gain = m.get("gain")
        out.append((m.get("add"), m.get("drop"), gain.get(key) if isinstance(gain, dict) else gain))
    return out


def _fmt_moves(moves: Sequence[tuple[Any, Any, Any]]) -> str:
    return ", ".join(f"+{a}/{f'-{d}' if d else 'open'} ({g})" for a, d, g in moves) or "no moves"


def _sets(entry: Mapping[str, Any] | None) -> str:
    if not entry:
        return "none"
    pool = entry.get("pool") or {}
    parts = [
        f"{s.get('key')}: {_fmt_moves(_moves_of(s, s.get('key')))}" for s in entry.get("sets") or []
    ]
    return (
        f"{(entry.get('system') or {}).get('file')}, pool {pool.get('size')}/{pool.get('candidates')}; "
        + ("; ".join(parts) or "no sets")
    )


# --------------------------------------------------------------------------- the command
def post_comment(markdown: str, issue: int, run: Callable[..., Any] | None = None) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(markdown)
        path = fh.name
    try:
        result = (run or subprocess.run)(
            ["gh", "issue", "comment", str(issue), "--body-file", path],
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=60,
        )
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh issue comment {issue}: {result.stderr.strip()[:300]}")
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else f"#{issue}"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--date", help="the day compared, YYYY-MM-DD (default: today, Central)")
    p.add_argument("--data", type=Path, default=REPO / "data", help="this host's data folder")
    p.add_argument("--host", default=DEFAULT_HOST, help="the droplet's ssh address")
    p.add_argument(
        "--remote-repo", default=DEFAULT_REMOTE_REPO, help="the checkout there (~/ or absolute)"
    )
    p.add_argument(
        "--remote-bundle", type=Path, help="read the droplet's bundle from this file, no ssh"
    )
    p.add_argument(
        "--private", default=PRIVATE_LEAGUE, help="the league never solved on the droplet"
    )
    p.add_argument("--post", action="store_true", help="comment the markdown on the ops issue")
    p.add_argument("--issue", type=int, default=DEFAULT_ISSUE)
    sub = p.add_subparsers(dest="command")
    b = sub.add_parser("bundle", help="print this host's bundle as JSON (run on the droplet)")
    b.add_argument("--date")
    b.add_argument("--data", type=Path, default=REPO / "data")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    day = args.date or datetime.now(CENTRAL).date().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError:
        print(f"not a date: {day}", file=sys.stderr)
        return UNREAD
    if args.command == "bundle":
        print(json.dumps(bundle(args.data, day), ensure_ascii=False))
        return OK
    if not args.data.is_dir():
        print(f"no data folder at {args.data}", file=sys.stderr)
        return UNREAD
    mac = bundle(args.data, day)
    try:
        vm = (
            json.loads(args.remote_bundle.read_text())
            if args.remote_bundle
            else remote_bundle(args.host, args.remote_repo, day)
        )
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"the droplet's bundle could not be read: {exc}", file=sys.stderr)
        return UNREAD
    if not isinstance(vm, dict):
        print("the droplet's bundle is not a JSON object", file=sys.stderr)
        return UNREAD
    comparison = Comparison(mac, vm, day, args.private).run()
    markdown = comparison.render()
    print(markdown, end="")
    if args.post:
        try:
            print(post_comment(markdown, args.issue), file=sys.stderr)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
    return FLAGGED if comparison.flags else OK


if __name__ == "__main__":
    sys.exit(main())
