"""SEASON SIM (#172, PR lab): what the lab reads, and only reads.

The records under ``data/sim/`` as the simulator writes them (``sim/readers.py``'s places):
each screen's folder (its record and its pairs), each tune's folder (its record, its values'
pairs and its confirmation's), the written runs of ``data/sim/runs/`` (a replay's; another
kind is counted and not shown), the traces of ``data/sim/traces/`` (PR viewer: each one's line
for the list, and one whole for the Season tab) and the confirmation ledger; and the lead's
notes file. For the Screen tab (PR live screen), one screen's record and, of each played pair's
record beside it, only when it started and landed (:func:`screen_landings`). A file
that is not JSON, or not a record, is refused by name and the rest is read. Nothing is
written, and nothing outside the data folder and the notes file is opened.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import readers as reader
from . import model as md
from . import screen_view as scv
from . import trace_view as tv

#: A trace's name as the ``trace`` command makes it safe (``readers.trace_path``): the only
#: names ``/api/trace/<name>`` reads.
TRACE_NAME = re.compile(r"[A-Za-z0-9_-]{1,80}")
#: A screen's folder name as the screen command makes it safe (``readers.screen_dir``): the
#: only names ``/api/screen/<name>`` reads (PR live screen).
SCREEN_NAME = re.compile(r"[A-Za-z0-9_-]{1,60}")


def _json(path: Path, refused: list[dict[str, str]]) -> dict[str, Any] | None:
    try:
        got = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        refused.append({"path": str(path), "why": f"not JSON: {e}"})
        return None
    if not isinstance(got, dict):
        refused.append({"path": str(path), "why": "not a record (no object)"})
        return None
    return got


def _folders(root: Path, record: str) -> Iterator[Path]:
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / record).is_file():
                yield d


def read_all(data: Path) -> dict[str, Any]:
    """Every record the lab reads, as :func:`model.build` takes them, with what was refused and
    how much was read."""
    refused: list[dict[str, str]] = []
    screens, tunes, replays = [], [], []
    pairs_read = 0
    for d in _folders(data / reader.SCREENS_DIR, reader.SCREEN_FILE):
        rec = _json(d / reader.SCREEN_FILE, refused)
        if rec is None:
            continue
        pairs = {}
        for f in sorted(d.glob("*.json")):
            if f.name == reader.SCREEN_FILE:
                continue
            got = _json(f, refused)
            if got is not None:
                pairs[f.name] = got
        pairs_read += len(pairs)
        screens.append({"folder": d.name, "record": rec, "pairs": pairs})
    tune_pairs = 0
    for d in _folders(data / reader.TUNES_DIR, reader.TUNE_FILE):
        rec = _json(d / reader.TUNE_FILE, refused)
        if rec is None:
            continue
        pairs = {}
        for f in sorted(d.glob("*.json")):
            if f.name == reader.TUNE_FILE:
                continue
            got = _json(f, refused)
            if got is not None:
                pairs[f.name] = got
        tune_pairs += len(pairs)
        tunes.append({"folder": d.name, "record": rec, "pairs": pairs})
    other: dict[str, int] = {}
    runs_dir = data / reader.RUNS_DIR
    for f in sorted(runs_dir.glob("*.json")) if runs_dir.is_dir() else []:
        rec = _json(f, refused)
        if rec is None:
            continue
        kind = str(rec.get("kind"))
        if kind == "replay":
            replays.append({"file": f.name, "record": rec})
        else:
            other[kind] = other.get(kind, 0) + 1
    traces = []
    traces_dir = data / reader.TRACES_DIR
    for f in sorted(traces_dir.glob("*.json")) if traces_dir.is_dir() else []:
        rec = _json(f, refused)
        if rec is None:
            continue
        why = not_a_trace(rec)
        if why is not None:
            refused.append({"path": str(f), "why": why})
            continue
        traces.append(tv.summary(f.stem, rec))
    try:
        looks = reader.read_looks(data)
    except reader.SimReadError as e:
        refused.append({"path": str(data / reader.LEDGER), "why": str(e)})
        looks = []
    return {
        "screens": screens,
        "tunes": tunes,
        "replays": replays,
        "traces": traces,
        "looks": looks,
        "refused": refused,
        "read": {
            "screens": len(screens),
            "screen_pairs": pairs_read,
            "tunes": len(tunes),
            "tune_pairs": tune_pairs,
            "replays": len(replays),
            "other_runs": other,
            "traces": len(traces),
            "ledger_lines": len(looks),
        },
    }


#: The trace versions the Season tab plays: 1, and 2 since PR capabilities (the same record
#: with the replay version it was played under).
TRACE_READS = (1, tv.tr.TRACE_VERSION)


def not_a_trace(rec: Any) -> str | None:
    """Why a record is not a trace the Season tab plays; None when it is one."""
    if not isinstance(rec, dict) or rec.get("kind") != "trace":
        return "not a trace (its kind is not trace)"
    if rec.get("trace_version") not in TRACE_READS:
        return (
            f"a trace of version {rec.get('trace_version')!r}: the lab reads versions "
            + " and ".join(str(v) for v in TRACE_READS)
        )
    if not isinstance((rec.get("arms") or {}).get("a"), dict) or not isinstance(
        (rec.get("arms") or {}).get("b"), dict
    ):
        return "not a trace (no two arms)"
    return None


def read_trace(data: Path, name: str) -> tuple[int, Any]:
    """One trace by its name, as the Season tab plays it: (200, the view); (404, words) for a
    name that is not a file of ``data/sim/traces/``; (422, words) for a file that is not JSON
    or not a trace, said by name."""
    if not TRACE_NAME.fullmatch(name):
        return 404, f"no trace named {name!r}"
    folder = (data / reader.TRACES_DIR).resolve()
    f = (folder / f"{name}.json").resolve()
    if f.parent != folder or not f.is_file():
        return 404, f"no trace named {name!r}"
    try:
        rec = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        return 422, f"{name}: not JSON ({e})"
    why = not_a_trace(rec)
    if why is not None:
        return 422, f"{name}: {why}"
    return 200, tv.view(name, rec)


def screen_folder(data: Path, name: str) -> Path | None:
    """The folder of the screen ``name`` under ``data/sim/screens/``: None when the name is not
    a screen folder's shape, would lead outside that folder, or names no folder with a record."""
    if not SCREEN_NAME.fullmatch(name):
        return None
    root = (data / reader.SCREENS_DIR).resolve()
    folder = (root / name).resolve()
    if folder.parent != root or not (folder / reader.SCREEN_FILE).is_file():
        return None
    return folder


def read_screen_record(folder: Path) -> tuple[dict[str, Any] | None, str | None]:
    """A screen's record from its folder, read whole: ``(record, None)``, or ``(None, why)`` for
    a file that cannot be read, is not JSON or is not a screen the Screen tab reads
    (``screen_view.not_a_screen``), said by name."""
    f = folder / reader.SCREEN_FILE
    try:
        rec = json.loads(f.read_text())
    except OSError as e:
        return None, f"its record could not be read ({e.strerror or e})"
    except ValueError as e:
        return None, f"its record is not JSON ({e})"
    why = scv.not_a_screen(rec)
    if why is not None:
        return None, why
    return rec, None


def screen_landings(
    folder: Path, record: dict[str, Any], kept: dict[str, tuple[int, int, dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """When each played pair of ``record`` started and landed, by its key: its own record's
    ``started_at`` and ``finished_at``, and its paths' differences on the screen's measure
    (``screen_view.paths_of``, None when the record keeps no ``by_path``), from the file the row
    names (``file``, else
    ``readers.pair_file``) in the screen's folder. A pair's record is written once, so each file
    is read once: ``kept`` holds what was read by its path, with its modification time and
    size. A file that is missing, outside the folder or not JSON is left out (its landing is not
    known)."""
    out: dict[str, dict[str, Any]] = {}
    root = folder.resolve()
    measure = str(record.get("measure") or "matchup_wins")
    for row in record.get("rows") or []:
        if not isinstance(row, dict) or not row.get("result"):
            continue
        key = str(row.get("key"))
        f = (root / str(row.get("file") or reader.pair_file(key))).resolve()
        if f.parent != root:
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        got = kept.get(str(f))
        if got is not None and got[:2] == (st.st_mtime_ns, st.st_size):
            out[key] = got[2]
            continue
        try:
            pair = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(pair, dict):
            continue
        times = {
            "started_at": pair.get("started_at"),
            "finished_at": pair.get("finished_at"),
            "paths": scv.paths_of(pair, measure),
        }
        kept[str(f)] = (st.st_mtime_ns, st.st_size, times)
        out[key] = times
    return out


def read_progress(folder: Path) -> dict[str, Any] | None:
    """The run's progress file in a screen's folder (``readers.PROGRESS_FILE``, PR live screen):
    the pair in play's paths so far. None when there is none, it is a link, or it cannot be read
    or is not one (``screen_view.progress_ok``): the view then falls back to the estimate."""
    f = folder / reader.PROGRESS_FILE
    try:
        if f.is_symlink() or not f.is_file():
            return None
        got = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    return got if scv.progress_ok(got) is None else None


def read_notes(path: Path | None) -> dict[str, Any] | None:
    """The notes file, checked (``model.notes_of``); None when none is given. A file that cannot
    be read, is not JSON or is not the schema raises ``model.NotesError`` by name."""
    if path is None:
        return None
    try:
        text = Path(path).read_text()
    except OSError as e:
        raise md.NotesError(f"notes: {path}: {e.strerror or e}") from None
    try:
        got = json.loads(text)
    except ValueError as e:
        raise md.NotesError(f"notes: {path} is not JSON: {e}") from None
    return md.notes_of(got)


def head_sha(root: Path) -> str | None:
    """The checkout's commit, read from its ``.git`` (a worktree's pointer file, a branch's ref
    or the packed refs) without starting a process; None when it cannot be read."""
    git = Path(root) / ".git"
    try:
        if git.is_file():
            text = git.read_text().strip()
            if not text.startswith("gitdir:"):
                return None
            gitdir = (Path(root) / text[len("gitdir:") :].strip()).resolve()
        else:
            gitdir = git
        head = (gitdir / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head[len("ref:") :].strip()
        common = gitdir
        if (gitdir / "commondir").is_file():
            common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
        for base in (gitdir, common):
            if (base / ref).is_file():
                return (base / ref).read_text().strip() or None
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text().splitlines():
                if line.endswith(" " + ref):
                    return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


def stamp(data: Path, *more: Path | None) -> tuple[tuple[str, int, int], ...]:
    """What the records and the given files are now, by path, modification time and size: the
    model is built again when this changes."""
    out = []
    roots = [
        data / reader.SCREENS_DIR,
        data / reader.TUNES_DIR,
        data / reader.RUNS_DIR,
        data / reader.TRACES_DIR,
    ]
    files = [p for r in roots if r.is_dir() for p in r.rglob("*.json")]
    files += [data / reader.LEDGER, *(p for p in more if p is not None)]
    for p in sorted(files):
        try:
            st = p.stat()
        except OSError:
            continue
        out.append((str(p), st.st_mtime_ns, st.st_size))
    return tuple(out)


__all__ = [
    "SCREEN_NAME",
    "TRACE_NAME",
    "head_sha",
    "not_a_trace",
    "read_all",
    "read_notes",
    "read_progress",
    "read_screen_record",
    "read_trace",
    "screen_folder",
    "screen_landings",
    "stamp",
]
