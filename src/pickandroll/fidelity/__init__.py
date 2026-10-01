"""Fidelity of a pickandroll session to a live Yahoo draft room: the event log, the scorecard
and the Tier 1 replay (``docs/YAHOO_SYNC.md``)."""

from pathlib import Path

from .recorder import FidelityLog, last_attach, now_iso, read_events, to_iso, to_ms
from .scorecard import analyze, guardrail_pass, markdown, status

#: Where the API writes logs by default: ``data/fidelity/`` (gitignored with the rest of data/).
FIDELITY_DIR = Path(__file__).resolve().parents[3] / "data" / "fidelity"

__all__ = [
    "FIDELITY_DIR",
    "FidelityLog",
    "analyze",
    "guardrail_pass",
    "last_attach",
    "markdown",
    "now_iso",
    "read_events",
    "status",
    "to_iso",
    "to_ms",
]
