"""What a run says about itself: its steps, the alerts worth a push, the written summary, the
JSON run log and the daily marker the freshness light reads (``season/status.py``)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

OK, FAILED, SKIPPED = "ok", "failed", "skipped"
#: The daily marker's step keys, the routine's own (``season/status.py``).
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
#: The exports' kinds (``season.status.EXPORTS``).
EXPORT_KINDS = ("ros", "week_this", "week_next", "actual_7d", "actual_14d")


@dataclass
class Step:
    name: str
    status: str
    detail: str
    started: str | None = None
    finished: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.started:
            out["started"] = self.started
        if self.finished:
            out["finished"] = self.finished
        if self.data:
            out["data"] = self.data
        return out


@dataclass
class Report:
    routine: str
    started: datetime
    finished: datetime | None = None
    steps: list[Step] = field(default_factory=list)
    #: Lines that want a human: what the Desktop routines sent the master session.
    alerts: list[str] = field(default_factory=list)
    #: The exports saved this run, by kind (the browser steps fill it).
    exports: dict[str, str] = field(default_factory=dict)
    refused: str | None = None
    stopped: bool = False
    #: The API never answered (connection refused, DNS, timeout): exit code 2.
    unreachable: bool = False

    def add(self, name: str, status: str, detail: str, **data: Any) -> Step:
        step = Step(name, status, detail, data=data)
        self.steps.append(step)
        return step

    def ok(self, name: str, detail: str, **data: Any) -> Step:
        return self.add(name, OK, detail, **data)

    def failed(self, name: str, detail: str, **data: Any) -> Step:
        return self.add(name, FAILED, detail, **data)

    def skipped(self, name: str, detail: str, **data: Any) -> Step:
        return self.add(name, SKIPPED, detail, **data)

    def alert(self, line: str) -> None:
        self.alerts.append(line)

    def find(self, name: str) -> Step | None:
        return next((s for s in self.steps if s.name == name), None)

    @property
    def any_failed(self) -> bool:
        return any(s.status == FAILED for s in self.steps)

    def summary(self) -> str:
        """The short written summary every routine ends with."""
        lines = [f"{self.routine}: {self.started:%a %Y-%m-%d %H:%M %Z}"]
        if self.refused:
            lines.append(f"refused: {self.refused}")
        if self.stopped:
            lines.append("STOP is set: nothing done")
        for s in self.steps:
            lines.append(f"- {s.name}: {s.status}, {s.detail}")
        if self.exports:
            lines.append("- exports saved: " + ", ".join(f"{k} {v}" for k, v in self.exports.items()))
        for a in self.alerts:
            lines.append(f"! {a}")
        if self.finished:
            lines.append(f"finished {self.finished:%H:%M:%S}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "routine": self.routine,
            "started_at": self.started.isoformat(),
            "finished_at": self.finished.isoformat() if self.finished else None,
            "refused": self.refused,
            "stopped": self.stopped,
            "steps": [s.to_dict() for s in self.steps],
            "alerts": list(self.alerts),
            "exports": dict(self.exports),
            "failed": self.any_failed,
        }


def marker(report: Report) -> dict[str, Any]:
    """The daily marker: the eight step keys, each ``{"status", "detail"}``, the exports by kind
    (a kind not made left out), the run's times with their offset."""
    steps: dict[str, Any] = {}
    for key in MARKER_STEPS:
        step = report.find(key)
        if step is None:
            steps[key] = {"status": SKIPPED, "detail": "not run"}
        else:
            steps[key] = {"status": step.status, "detail": step.detail}
    exports = {k: report.exports[k] for k in EXPORT_KINDS if k in report.exports}
    return {
        "started_at": report.started.isoformat(),
        "finished_at": (report.finished or report.started).isoformat(),
        "steps": steps,
        "exports": exports,
    }


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return path
