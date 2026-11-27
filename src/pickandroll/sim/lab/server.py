"""SEASON SIM (#172, PR lab): the lab's small read-only server (stdlib only).

    python -m pickandroll.sim [--data DIR] lab [--host H] [--port P] [--notes FILE]
        [--explainer FILE] [--check]

``GET`` only, on the one address the operator names (loopback by default; a wildcard address
is refused by name, since the figures are private). It writes nothing, plays nothing, starts no
process and asks nothing of anywhere. Routes:

- ``/``: the page (``static/index.html``); ``/static/<file>``: its files, and nothing outside
  that folder;
- ``/api/model``: the model as JSON (``model.build``), built from the records again whenever
  they or the notes file change (``records.stamp``);
- ``/api/traces``: the traces' lines (``trace_view.summary``), as the model lists them;
  ``/api/trace/<name>``: one trace as the Season tab plays it (``trace_view.view``), kept until
  its file changes; a name that is not a file of ``data/sim/traces/`` is not found, and a file
  that is not a trace is refused by name (PR viewer);
- ``/api/screen/<name>``: one screen as the Screen tab shows it (``screen_view.view``), at the
  server's clock, from its record and its played pairs' landing times only (PR live screen); a
  name that is not a folder of ``data/sim/screens/`` is not found, and a record that cannot be
  read (or is not a screen) answers the last good read, said so, else is refused by name;
- ``/explainer``: the explainer's built file wrapped in a plain document, or a short page saying
  none was given;
- ``/healthz``: ``ok``.
"""

from __future__ import annotations

import ipaddress
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from . import model as md
from . import records as rd
from . import screen_view as scv

STATIC = Path(__file__).resolve().parent / "static"
#: The files the page is, by suffix, with their types.
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}
HOST = "127.0.0.1"
PORT = 8790
#: The explainer's built file is the page's body as it is published: wrapped as the lead's
#: scratch builder wraps it, so it opens in the Explainer tab's frame.
EXPLAINER_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    "<title>Season Sim Explained</title>"
    "<style>:root{box-sizing:border-box}body{margin:0;padding:0}img{max-width:100%}"
    "[hidden]:not([hidden=until-found i]){display:none!important}</style></head><body>\n"
)
EXPLAINER_TAIL = "\n</body></html>\n"
NO_EXPLAINER = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>No explainer</title>'
    "<style>body{margin:0;padding:40px 24px;background:#0b0f14;color:#9aa7b4;"
    "font:14px system-ui,sans-serif}</style></head><body>"
    "<p>No explainer file given: start the lab with <code>--explainer FILE</code>, the "
    "explainer's built file.</p></body></html>\n"
)


def host_refused(host: str) -> str | None:
    """Why the lab may not bind ``host``; None when it may. A wildcard address (every
    interface: ``0.0.0.0``, ``::``, an empty host) is refused: the operator names the one
    address to serve on (loopback, or the box's own tailnet address)."""
    h = host.strip().strip("[]")
    if h in ("", "*"):
        return "an empty host binds every interface: name the one address to serve on"
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return None
    if ip.is_unspecified:
        return f"{host} is a wildcard address (every interface): name the one address to serve on"
    return None


class Lab:
    """What the server serves: the records' folder, the notes file and the explainer's file;
    the model kept until the records or the notes change."""

    def __init__(
        self,
        data: Path,
        notes: Path | None = None,
        explainer: Path | None = None,
        hold_out: int = 2025,
        confirmation: int = 2026,
        code_sha: str | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.data, self.notes, self.explainer = Path(data), notes, explainer
        self.hold_out, self.confirmation, self.code_sha, self.now = (
            hold_out,
            confirmation,
            code_sha,
            now,
        )
        self._lock = threading.Lock()
        self._stamp: Any = None
        self._model: dict[str, Any] | None = None
        self._views: dict[str, tuple[Any, tuple[int, Any]]] = {}
        # The Screen tab's reads (PR live screen): each screen's last good record and landings,
        # and each pair file's times by path, under a lock of their own (a model's build is slow).
        self._screen_lock = threading.Lock()
        self._screens: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]]]] = {}
        self._pairs: dict[str, tuple[int, int, dict[str, Any]]] = {}

    def build(self) -> dict[str, Any]:
        """The model from the records as they are now (a notes file that is refused is said in
        the model, and the rest is built)."""
        got = rd.read_all(self.data)
        refused = list(got["refused"])
        notes_state: dict[str, Any] = {"file": None if self.notes is None else str(self.notes)}
        try:
            notes = rd.read_notes(self.notes)
            notes_state["state"] = "none" if notes is None else "read"
        except md.NotesError as e:
            notes, notes_state["state"] = None, f"refused: {e}"
            refused.append({"path": str(self.notes), "why": str(e)})
        return md.build(
            got["screens"],
            got["tunes"],
            got["replays"],
            got["looks"],
            notes,
            traces=got["traces"],
            hold_out=self.hold_out,
            confirmation=self.confirmation,
            generated={
                "at": self.now().isoformat(),
                "code_sha": self.code_sha,
                "data": str(self.data),
                "read": got["read"],
                "refused": refused,
                "notes": notes_state,
                "explainer": self.explainer is not None,
            },
        )

    def model(self) -> dict[str, Any]:
        with self._lock:
            now = rd.stamp(self.data, self.notes)
            if self._model is None or now != self._stamp:
                self._model, self._stamp = self.build(), now
            return self._model

    def trace(self, name: str) -> tuple[int, Any]:
        """One trace's view (``records.read_trace``), kept until its file changes. A name that
        is not a trace's shape is not found before any path is made of it."""
        if not rd.TRACE_NAME.fullmatch(name):
            return 404, f"no trace named {name!r}"
        f = self.data / rd.reader.TRACES_DIR / f"{name}.json"
        try:
            st = f.stat()
            key: Any = (st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        with self._lock:
            got = self._views.get(name)
            if key is not None and got is not None and got[0] == key:
                return got[1]
        out = rd.read_trace(self.data, name)
        if key is not None and out[0] == 200:
            with self._lock:
                self._views = {name: (key, out)}
        return out

    def plan(self) -> str | None:
        """The notes' line for the planned pieces (``state.pieces``); None with no notes, none
        given, or notes that are refused (the model says that)."""
        try:
            notes = rd.read_notes(self.notes)
        except md.NotesError:
            return None
        return ((notes or {}).get("state") or {}).get("pieces")

    def screen(self, name: str) -> tuple[int, Any]:
        """One screen's view at the server's clock (PR live screen): (200, the view); (404,
        words) for a name that is not a screen's folder; (422, words) for a record that cannot
        be read or is not a screen, unless an earlier read of it was good: then that read at
        the clock now, its ``kept`` saying why and when."""
        folder = rd.screen_folder(self.data, name)
        if folder is None:
            return 404, f"no screen named {name!r}"
        rec, why = rd.read_screen_record(folder)
        now, plan, progress = self.now(), self.plan(), rd.read_progress(folder)
        with self._screen_lock:
            if rec is None:
                kept = self._screens.get(name)
                if kept is None:
                    return 422, f"{name}: {why}"
                out = scv.view(name, kept[0], kept[1], now, plan, progress)
                out["kept"] = {"why": why, "at": now.isoformat()}
                return 200, out
            landings = rd.screen_landings(folder, rec, self._pairs)
            self._screens[name] = (rec, landings)
        return 200, scv.view(name, rec, landings, now, plan, progress)

    def explainer_page(self) -> str:
        if self.explainer is None:
            return NO_EXPLAINER
        try:
            body = Path(self.explainer).read_text(encoding="utf8")
        except OSError as e:
            return NO_EXPLAINER.replace(
                "No explainer file given: start the lab with <code>--explainer FILE</code>, the "
                "explainer's built file.",
                f"The explainer file could not be read ({e.strerror or e}).",
            )
        return EXPLAINER_HEAD + body + EXPLAINER_TAIL


def static_file(path: str) -> Path | None:
    """The page's file a ``/static/`` path names, or None: only a file inside the folder, of a
    type the page is made of."""
    name = unquote(path[len("/static/") :])
    if not name or "\\" in name or "\x00" in name:
        return None
    target = (STATIC / name).resolve()
    if STATIC not in target.parents or not target.is_file() or target.suffix not in TYPES:
        return None
    return target


def handler_for(lab: Lab) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SeasonSimLab"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _send(
            self, code: int, body: bytes, ctype: str, more: dict[str, str] | None = None
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (more or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _text(self, code: int, text: str) -> None:
            self._send(code, text.encode(), "text/plain; charset=utf-8")

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), TYPES[".html"])
            elif path.startswith("/static/"):
                f = static_file(path)
                if f is None:
                    self._text(404, "not found\n")
                else:
                    self._send(200, f.read_bytes(), TYPES[f.suffix])
            elif path == "/api/model":
                # A model that fails to build is a 500 with one line naming the error's kind,
                # never a dropped connection; the page says the model could not be built.
                try:
                    body = json.dumps(lab.model(), default=str, allow_nan=False).encode()
                except Exception as e:  # noqa: BLE001
                    self._text(500, f"the model could not be built: {type(e).__name__}\n")
                else:
                    self._send(200, body, "application/json; charset=utf-8")
            elif path == "/api/traces":
                try:
                    body = json.dumps(lab.model()["traces"], default=str, allow_nan=False)
                except Exception as e:  # noqa: BLE001
                    self._text(500, f"the traces could not be listed: {type(e).__name__}\n")
                else:
                    self._send(200, body.encode(), "application/json; charset=utf-8")
            elif path.startswith("/api/trace/"):
                try:
                    code, got = lab.trace(unquote(path[len("/api/trace/") :]))
                    body = (
                        json.dumps(got, default=str, allow_nan=False).encode()
                        if code == 200
                        else None
                    )
                except Exception as e:  # noqa: BLE001
                    self._text(500, f"the trace could not be read: {type(e).__name__}\n")
                else:
                    if body is None:
                        self._text(code, f"{got}\n")
                    else:
                        self._send(200, body, "application/json; charset=utf-8")
            elif path.startswith("/api/screen/"):
                try:
                    code, got = lab.screen(unquote(path[len("/api/screen/") :]))
                    body = (
                        json.dumps(got, default=str, allow_nan=False).encode()
                        if code == 200
                        else None
                    )
                except Exception as e:  # noqa: BLE001
                    self._text(500, f"the screen could not be read: {type(e).__name__}\n")
                else:
                    if body is None:
                        self._text(code, f"{got}\n")
                    else:
                        self._send(200, body, "application/json; charset=utf-8")
            elif path == "/explainer":
                self._send(200, lab.explainer_page().encode(), TYPES[".html"])
            elif path == "/healthz":
                self._text(200, "ok\n")
            else:
                self._text(404, "not found\n")

        def _refuse(self) -> None:
            self._send(405, b"GET only\n", "text/plain; charset=utf-8", {"Allow": "GET"})

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = (
            _refuse
        )

    return Handler


def server(lab: Lab, host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    """The lab's server, bound and not yet serving; ValueError on a refused host."""
    why = host_refused(host)
    if why is not None:
        raise ValueError(why)
    srv = ThreadingHTTPServer((host, port), handler_for(lab))
    srv.daemon_threads = True
    return srv


def check_lines(m: dict[str, Any]) -> list[str]:
    """``lab --check``: one line a section, counts only."""
    g = m["generated"]
    r = g["read"]
    other = ", ".join(f"{n} {k}" for k, n in sorted(r["other_runs"].items())) or "none"
    lines = [
        (
            f"read: {r['screens']} screen(s) with {r['screen_pairs']} pair record(s), "
            f"{r['tunes']} tune(s) with {r['tune_pairs']}, {r['replays']} written replay(s), "
            f"{r['ledger_lines']} ledger line(s); other runs not shown: {other}; "
            f"refused: {len(g['refused'])}"
        ),
    ]
    every = m["rulesets"]
    rs = [x for x in every if x["listed"]]
    lines.append(
        f"rulesets: {len(every)}, {len(rs)} listed"
        + "".join(
            f"; {x['key']} ({x['name']}, from the {x['named']}): {len(x['runs'])} run(s)"
            + ("" if x["listed"] else ", runs only, not listed")
            for x in every
        )
    )
    rows = m["knobs"]["rows"]
    played = [x for x in rows if x["played"]]
    lines.append(
        f"knobs: {len(rows)} row(s), {len(played)} played cell(s), "
        f"{sum(1 for x in played if x['did_nothing'])} did nothing, "
        f"{len(m['knobs']['shared'])} shared by two rulesets"
    )
    for x in rs:
        levels = [f["level"] for f in x["checks"]["flags"]]
        lines.append(
            f"checks {x['key']}: {x['checks']['luck']['tries']} tries; flags "
            + ", ".join(f"{levels.count(k)} {k}" for k in md.LEVELS)
            + f"; worst {x['checks']['level']}"
        )
    for x in rs:
        tags = ", ".join(f"{s['title']}: {s['tag']}" for s in x["stages"])
        lines.append(
            f"performance {x['key']}: baseline {'yes' if x['baseline'] else 'none'}; {tags}"
        )
    kinds = [run["kind"] for run in m["runs"]]
    lines.append(
        f"runs: {len(kinds)} ({kinds.count('screen')} screen, {kinds.count('tune')} tune, "
        f"{kinds.count('replay')} replay), {sum(len(run['pieces']) for run in m['runs'])} piece(s); "
        f"tunes in detail: {len(m['tunes'])}"
    )
    live = [
        r
        for r in m["runs"]
        if r["kind"] == "screen" and (r.get("live") or {}).get("state") in (md.IN_PLAY, md.PAUSED)
    ]
    lines.append(
        "live: "
        + (
            "; ".join(
                f"{r['name']} {r['live']['state']} ({r['live']['played']} played, "
                f"{r['live']['left']} left)"
                for r in live
            )
            or "no screen in play or paused"
        )
    )
    traces = m.get("traces") or []
    lines.append(
        f"traces: {len(traces)}"
        + (
            " ("
            + ", ".join(
                f"{sum(1 for t in traces if t['check']['level'] == k)} {k}" for k in md.LEVELS
            )
            + " by their check)"
            if traces
            else ""
        )
    )
    cards = (m.get("results") or {}).get("cards") or []
    lines.append(
        f"results: {len(cards)} card(s) ({sum(1 for c in cards if c['kind'] == 'screen')} screen, "
        f"{sum(1 for c in cards if c['kind'] == 'tune')} tune), "
        f"{sum(1 for c in cards if c['folded'])} folded shut, "
        f"{sum(1 for c in cards if c['reading'])} with the lead's reading"
    )
    caps = m.get("capabilities") or {}
    now = caps.get("current") or {}
    last = caps.get("latest") or {}
    played = sorted(
        {run["capability"]["replay_version"] for run in m["runs"] if run.get("capability")}
    )
    lines.append(
        f"capabilities: now version {now.get('replay_version')} ({now.get('title')}); last "
        f"update {last.get('date')} ({last.get('title')}); {len(caps.get('log') or [])} marks; "
        f"runs played on version(s) {', '.join(str(v) for v in played) or 'none recorded'}; "
        + (
            "behind live in " + ", ".join(e["issue"] for e in caps["behind"])
            if caps.get("behind")
            else (
                "nothing from live outstanding"
                if caps.get("engine")
                else "no live-engine change in the notes"
            )
        )
        + (
            f"; {len(caps['earlier'])} of {caps.get('of', 0)} run(s) with a version are of an "
            "engine live has left: " + ", ".join(caps["earlier"])
            if caps.get("earlier")
            else ""
        )
    )
    lines.append(
        f"seasons: {len(m['seasons'])} in the ledger ("
        + ", ".join(f"{s['words']} {s['role']} from the {s['from']}" for s in m["seasons"])
        + ")"
    )
    lines.append(f"notes: {g['notes']['state']}")
    lines.append(f"explainer: {'given' if g['explainer'] else 'none given'}")
    lines.append(f"not recorded: {len(g['lacks'])}" + "".join(f"; {x}" for x in g["lacks"]))
    return lines


__all__ = [
    "HOST",
    "PORT",
    "STATIC",
    "Lab",
    "check_lines",
    "handler_for",
    "host_refused",
    "server",
    "static_file",
]
