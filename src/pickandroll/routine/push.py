"""The user's private push channel (#355): the ntfy topic ``ops/vm/alert.sh`` posts to, read from
the user's own file (``$PICKANDROLL_CONF/ntfy_topic``, ``~/.config/pickandroll`` by default) and
never written to a repository file, a report or a log. The pre-tip pass sends the private
league's suggestions here, never to a public issue: its drops name the league's roster."""

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .steps import Pusher, one_line

NTFY = "https://ntfy.sh"
TOPIC_FILE = "ntfy_topic"
#: ntfy's own message limit is 4096 bytes.
MAX_BYTES = 3800
TIMEOUT_S = 20.0


def ntfy_pusher(
    conf: Path,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = TIMEOUT_S,
) -> Pusher:
    """A push to the user's ntfy topic: ``(title, text)`` to (ok, detail). The detail never
    holds the topic."""

    def push(title: str, text: str) -> tuple[bool, str]:
        path = Path(conf) / TOPIC_FILE
        try:
            topic = "".join(path.read_text().split())
        except OSError:
            topic = ""
        if not topic:
            return False, f"no topic in {path}: nothing pushed"
        request = urllib.request.Request(
            f"{NTFY}/{quote(topic, safe='')}",
            # Cut on a character boundary: a body that is not UTF-8 is an attachment to ntfy.
            data=text.encode()[:MAX_BYTES].decode("utf-8", "ignore").encode(),
            headers={
                "Title": title.encode("ascii", "replace").decode(),
                "Tags": "basketball",
                "Markdown": "yes",
            },
            method="POST",
        )
        try:
            with opener(request, timeout=timeout) as answer:
                status = int(getattr(answer, "status", 0) or 0)
        except Exception as exc:  # noqa: BLE001 - the reason is reported, never raised
            return False, f"the push failed: {one_line(exc)}"
        if not 200 <= status < 300:
            return False, f"the push answered {status}"
        return True, f"pushed ({status})"

    return push
