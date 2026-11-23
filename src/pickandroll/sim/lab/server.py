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
