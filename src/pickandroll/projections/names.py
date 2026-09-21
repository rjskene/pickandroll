"""Name normalization shared by projection sources and matching."""

from __future__ import annotations

import re
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str) -> str:
    """Lowercase ASCII with punctuation and generational suffixes removed."""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = re.sub(r"[.'’\-]", "", text.lower())
    tokens = [t for t in re.split(r"\s+", text.strip()) if t and t not in SUFFIXES]
    return " ".join(tokens)


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return cleaned or "unknown"
