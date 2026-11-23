"""SEASON SIM (#172, PR lab): what the lab reads, and only reads.

The records under ``data/sim/`` as the simulator writes them (``sim/readers.py``'s places):
each screen's folder (its record and its pairs), each tune's folder (its record, its values'
pairs and its confirmation's), the written runs of ``data/sim/runs/`` (a replay's; another
kind is counted and not shown) and the confirmation ledger; and the lead's notes file. A file
that is not JSON, or not a record, is refused by name and the rest is read. Nothing is
written, and nothing outside the data folder and the notes file is opened.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import readers as reader
from . import model as md


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
    try:
        looks = reader.read_looks(data)
    except reader.SimReadError as e:
        refused.append({"path": str(data / reader.LEDGER), "why": str(e)})
        looks = []
    return {
        "screens": screens,
        "tunes": tunes,
        "replays": replays,
        "looks": looks,
        "refused": refused,
        "read": {
            "screens": len(screens),
            "screen_pairs": pairs_read,
            "tunes": len(tunes),
            "tune_pairs": tune_pairs,
            "replays": len(replays),
            "other_runs": other,
            "ledger_lines": len(looks),
        },
    }


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
    roots = [data / reader.SCREENS_DIR, data / reader.TUNES_DIR, data / reader.RUNS_DIR]
    files = [p for r in roots if r.is_dir() for p in r.rglob("*.json")]
    files += [data / reader.LEDGER, *(p for p in more if p is not None)]
    for p in sorted(files):
        try:
            st = p.stat()
        except OSError:
            continue
        out.append((str(p), st.st_mtime_ns, st.st_size))
    return tuple(out)


__all__ = ["head_sha", "read_all", "read_notes", "stamp"]
