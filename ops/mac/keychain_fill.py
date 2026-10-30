"""The ``--keychain`` mode of ``ops/mac/signin.sh`` (#238): the password of one site, from a
Keychain item the user made by hand, into the password field of the droplet's sign-in browser
over the DevTools websocket on the ssh tunnel. Only the user's own command runs this, by hand,
from the Mac; no routine, timer or Claude session does.

The password is read in this process (``security find-generic-password -s <item> -w``), sent
to the browser as the text of one ``Input.insertText`` call after a click on the first visible
password field, and goes nowhere else: not a shell argument, not an environment variable, not a
line of output. Arguments: the tunnel's local port, the site (``bbm`` or ``yahoo``) and the
Keychain item's service name. Exit 0 once the field holds the text; 3 when no page of the site
has a password field yet (nothing typed; Yahoo shows it on its second page); 4 when the Keychain
item is missing or unreadable (nothing typed); 5 when the browser did not take the text."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
from typing import Any

SITES = {"bbm": "basketballmonster.com", "yahoo": "yahoo.com"}
TIMEOUT = 15.0  # seconds, for each DevTools exchange
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # the websocket handshake constant (RFC 6455)
NOT_FOUND = 44  # security's exit code for a missing item (errSecItemNotFound)

#: The first password field on the page that is visible, scrolled into view: the centre of its
#: box in CSS pixels of the viewport (where the click lands), or null when there is none.
FIND_JS = (
    "(() => {"
    " const fields = Array.from(document.querySelectorAll('input[type=password]')).filter(el => {"
    "   const r = el.getBoundingClientRect();"
    "   return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';"
    " });"
    " if (!fields.length) return null;"
    " const el = fields[0];"
    " el.scrollIntoView({block: 'center', inline: 'nearest'});"
    " const r = el.getBoundingClientRect();"
    " return {x: r.left + r.width / 2, y: r.top + r.height / 2};"
    "})()"
)
#: After the click: the focused element is a password field, its text (a half-typed attempt)
#: selected so the insert replaces it. False when the click landed elsewhere.
FOCUS_JS = (
    "(() => {"
    " const el = document.activeElement;"
    " if (!el || el.tagName !== 'INPUT' || el.type !== 'password') return false;"
    " el.select();"
    " return true;"
    "})()"
)
#: After the insert: the length of the focused field's text, compared and never printed.
LENGTH_JS = "((document.activeElement && document.activeElement.value) || '').length"


def send_frame(sock: socket.socket, opcode: int, payload: bytes, mask: bool = True) -> None:
    """One websocket frame; a client masks its frames (RFC 6455 §5.3), a server does not."""
    head = bytearray([0x80 | opcode])
    flag = 0x80 if mask else 0
    if len(payload) < 126:
        head.append(flag | len(payload))
    elif len(payload) < 65536:
        head.append(flag | 126)
        head += struct.pack("!H", len(payload))
    else:
        head.append(flag | 127)
        head += struct.pack("!Q", len(payload))
    if mask:
        key = os.urandom(4)
        head += key
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(head) + payload)


class Reader:
    """Websocket frames off a socket, with whatever the handshake read past its own end."""

    def __init__(self, sock: socket.socket, leftover: bytes = b"", mask: bool = True) -> None:
        self.sock = sock
        self.buffer = leftover
        self.mask = mask  # how this side's own frames (the pongs) are sent

    def exact(self, n: int) -> bytes:
        while len(self.buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("the browser closed the DevTools connection")
            self.buffer += chunk
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def frame(self) -> tuple[bool, int, bytes]:
        first, second = self.exact(2)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.exact(8))[0]
        key = self.exact(4) if second & 0x80 else b""
        data = self.exact(length)
        if key:
            data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
        return bool(first & 0x80), first & 0x0F, data

    def message(self) -> str:
        """The next complete text message; pings answered, a close frame raised."""
        parts: list[bytes] = []
        while True:
            fin, opcode, data = self.frame()
            if opcode == 0x9:
                send_frame(self.sock, 0xA, data, mask=self.mask)
                continue
            if opcode == 0x8:
                raise OSError("the browser closed the DevTools connection")
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8")


class DevTools:
    """One DevTools websocket on a page target, through the tunnel's local port: the page's
    ``webSocketDebuggerUrl`` names the browser's own port, so only its path is used."""

    def __init__(self, port: int, ws_url: str) -> None:
        path = urllib.parse.urlsplit(ws_url).path
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("the browser closed the DevTools connection in the handshake")
            head += chunk
        head, _, leftover = head.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in status:
            raise OSError(f"DevTools refused the websocket: {status}")
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        accepted = [
            line.split(":", 1)[1].strip()
            for line in head.decode("latin-1").split("\r\n")[1:]
            if line.lower().startswith("sec-websocket-accept:")
        ]
        if accepted != [expected]:
            raise OSError("DevTools answered the websocket handshake with a wrong accept key")
        self.reader = Reader(self.sock, leftover)
        self.last_id = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_id += 1
        request = {"id": self.last_id, "method": method, "params": params or {}}
        send_frame(self.sock, 0x1, json.dumps(request).encode("utf-8"))
        while True:
            message = json.loads(self.reader.message())
            if message.get("id") == self.last_id:
                break  # events (no id) and other clients' traffic pass
        if "error" in message:
            detail = message["error"].get("message") or "error"
            raise OSError(f"{method}: {detail}")
        return message.get("result") or {}

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if result.get("exceptionDetails"):
            raise OSError("the page threw on the script that looks for the password field")
        return (result.get("result") or {}).get("value")

    def close(self) -> None:
        try:
            send_frame(self.sock, 0x8, b"")
        except OSError:
            pass
        self.sock.close()


def keychain_password(service: str) -> tuple[str | None, str]:
    """The item's password read in this process, or None and the line to print. Nothing of the
    value or of security's own output is in that line."""
    try:
        done = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return None, "no `security` command here: --keychain runs on the Mac"
    if done.returncode == NOT_FOUND:
        return None, (
            f"no Keychain item '{service}': create it with"
            f"  security add-generic-password -s {service} -a <account> -w"
            "  (<account> is your sign-in name on the site; it asks for the password twice)"
        )
    if done.returncode != 0:
        return None, (
            f"Keychain did not give the item '{service}' (security exit {done.returncode};"
            " a denied prompt, or the keychain is locked)"
        )
    value = done.stdout[:-1] if done.stdout.endswith(b"\n") else done.stdout
    if not value:
        return None, f"the Keychain item '{service}' holds an empty password"
    try:
        return value.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, f"the Keychain item '{service}' is not text (hex or binary data)"


def site_pages(port: int, site: str) -> list[str]:
    """The websocket URLs of the browser's pages on the site, from its /json/list."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=TIMEOUT) as resp:
        targets = json.load(resp)
    domain = SITES[site]
    out = []
    for target in targets:
        host = urllib.parse.urlsplit(target.get("url") or "").hostname or ""
        ws_url = target.get("webSocketDebuggerUrl") or ""
        if target.get("type") != "page" or not ws_url:
            continue
        if host == domain or host.endswith("." + domain):
            out.append(ws_url)
    return out


def insert(devtools: DevTools, centre: dict[str, Any], value: str) -> None:
    """Click the password field at its centre and insert the text; an OSError when the field
    did not end up focused or did not take the whole text."""
    x, y = float(centre["x"]), float(centre["y"])
    devtools.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    for kind in ("mousePressed", "mouseReleased"):
        devtools.call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
        )
    if not devtools.evaluate(FOCUS_JS):
        raise OSError("the click did not land on the password field")
    devtools.call("Input.insertText", {"text": value})
    if devtools.evaluate(LENGTH_JS) != len(value):
        raise OSError("the password field did not take the whole text")


def fill(port: int, site: str, service: str) -> int:
    """The site's pages in turn: the first with a visible password field gets the Keychain
    item's password, read only once that field is there."""
    try:
        pages = site_pages(port, site)
    except (OSError, ValueError) as exc:
        print(
            f"the browser's DevTools list on 127.0.0.1:{port} did not answer: {exc}",
            file=sys.stderr,
        )
        return 5
    if not pages:
        print(f"{site}: no {SITES[site]} tab in the droplet's browser", file=sys.stderr)
        return 3
    for ws_url in pages:
        try:
            devtools = DevTools(port, ws_url)
        except OSError as exc:
            print(f"{site}: DevTools: {exc}", file=sys.stderr)
            return 5
        try:
            centre = devtools.evaluate(FIND_JS)
            if not centre:
                continue
            value, problem = keychain_password(service)
            if value is None:
                print(problem, file=sys.stderr)
                return 4
            insert(devtools, centre, value)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(
                f"{site}: {exc}; click the field in the DevTools window and try again",
                file=sys.stderr,
            )
            return 5
        finally:
            devtools.close()
        print(f"{site}: the password field holds the Keychain item '{service}'; click Sign in")
        return 0
    hint = " (Yahoo shows it on its second page)" if site == "yahoo" else ""
    print(
        f"{site}: no password field on the {SITES[site]} page yet{hint}; nothing typed",
        file=sys.stderr,
    )
    return 3


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in SITES or not argv[0].isdigit():
        print(
            "usage: keychain_fill.py <local port> <bbm|yahoo> <keychain service>", file=sys.stderr
        )
        return 2
    return fill(int(argv[0]), argv[1], argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
