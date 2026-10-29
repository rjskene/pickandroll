"""The one way a routine reaches the API: ``Call(method, path, body, timeout)`` answering the
status, the JSON body and the headers (lower-cased). ``http`` is the real one; tests inject
their own."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol

Answer = tuple[int, Any, dict[str, str]]


class Unreachable(RuntimeError):
    """The API did not answer at all."""


class Call(Protocol):
    def __call__(
        self, method: str, path: str, body: Any = None, timeout: float = 60.0
    ) -> Answer: ...


def http(base: str) -> Call:
    """A ``Call`` over HTTP against ``base`` (no trailing slash)."""
    base = base.rstrip("/")

    def call(method: str, path: str, body: Any = None, timeout: float = 60.0) -> Answer:
        data = None
        headers = {}
        if method == "POST":
            data = json.dumps(body).encode() if body is not None else b""
            if body is not None:
                headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, _json(r.read()), _headers(r.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, _json(exc.read()), _headers(exc.headers)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise Unreachable(f"{base}: {exc}") from exc

    return call


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw or b"null")
    except ValueError:
        return {"detail": raw.decode("utf-8", errors="replace")}


def _headers(h: Mapping[str, str] | Any) -> dict[str, str]:
    try:
        return {str(k).lower(): str(v) for k, v in h.items()}
    except AttributeError:
        return {}
