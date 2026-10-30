"""The ``--keychain`` mode of ``ops/mac/signin.sh`` (#238, #249): one site's sign-in, from a
Keychain item the user made by hand, into the droplet's sign-in browser over the DevTools
websocket on the ssh tunnel. Only the user's own command runs this, by hand, from the Mac; no
routine, timer or Claude session does.

From whatever page of the site is on screen it walks to the password field and fills it, then
stops: the user clicks Sign in. The item's account name (its ``acct`` attribute) goes into the
visible username field; on Yahoo it clicks Next, and when Yahoo answers with its passkey page it
clicks "Try signing in another way" and the option that names the password; on Basketball
Monster's front page it clicks the Login link. Every click is a mouse event on the centre of an
element found by its visible text, never a form submit, and nothing named Sign in is ever
clicked. The password is read in this process (``security find-generic-password -s <item> -w``)
only once the password field is on the page, sent to the browser as the text of one
``Input.insertText`` call after a click on the field, and goes nowhere else: not a shell
argument, not an environment variable, not a line of output; the account name is not printed
either. A page it does not know (a verification code, a captcha) is a clean stop with the
page's path, nothing more typed, and the user continues by hand in the DevTools window.

Arguments: the tunnel's local port, the site (``bbm`` or ``yahoo``) and the Keychain item's
service name. Exit 0 once the password field holds the text; 3 when the page is not one it
knows, did not change after a click, or the site has no tab (nothing more typed); 4 when the
Keychain item is missing, unreadable or without an account name; 5 when the browser did not
take a text."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

SITES = {"bbm": "basketballmonster.com", "yahoo": "yahoo.com"}
TIMEOUT = 15.0  # seconds, for each DevTools exchange and for a page to change after a click
POLL = 0.5  # seconds between looks while waiting for the page to change
SETTLE = 5.0  # seconds a page gets to show something known before it counts as unknown
MOST_STEPS = 8  # pages visited on one approach before giving up
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # the websocket handshake constant (RFC 6455)
NOT_FOUND = 44  # security's exit code for a missing item (errSecItemNotFound)

#: The page's elements the approach uses, each the first visible one of its kind: the password
#: field; the username field (a text or email input whose name, id, placeholder or autocomplete
#: names the user, login, email or account, not a search box, in the password field's form when
#: there is one); Yahoo's Next button, its "Try signing in another way" link and the option
#: that names the password (never a forgot/reset link); Basketball Monster's Login link. Called
#: with null it reports the path and which of them the page shows; called with a kind it scrolls
#: that element into view and returns the centre of its box in CSS pixels of the viewport, where
#: the click lands, or null.
PAGE_JS = (
    "(kind => {"
    " const visible = el => {"
    "   const r = el.getBoundingClientRect();"
    "   return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';"
    " };"
    " const text = el => ((el.innerText || el.textContent || el.value || '') + '')"
    "   .trim().replace(/\\s+/g, ' ');"
    " const clickables = Array.from(document.querySelectorAll("
    "   'a, button, [role=button], input[type=submit], input[type=button]')).filter(visible);"
    " const byText = test => clickables.find(el => test(text(el))) || null;"
    " const inputs = Array.from(document.querySelectorAll('input')).filter(visible);"
    " const password = inputs.find(el => el.type === 'password') || null;"
    " const names = el => [el.name, el.id, el.placeholder, el.getAttribute('autocomplete')]"
    "   .join(' ');"
    " const usernames = inputs.filter(el => (el.type === 'text' || el.type === 'email')"
    "   && /user|login|email|acct|account/i.test(names(el)) && !/search/i.test(names(el)));"
    " const found = {"
    "   password,"
    "   username: (password && usernames.find(el => el.form && el.form === password.form))"
    "     || usernames[0] || null,"
    "   next: byText(t => /^next$/i.test(t)),"
    "   another: byText(t => /another way/i.test(t)),"
    "   option: byText(t => /password/i.test(t) && !/forgot|reset|recover|retriev/i.test(t)),"
    "   login: byText(t => /^log ?in$/i.test(t)),"
    " };"
    " if (kind === null) {"
    "   const shows = {};"
    "   for (const k in found) shows[k] = found[k] !== null;"
    "   return {path: location.pathname, shows};"
    " }"
    " const el = found[kind];"
    " if (!el) return null;"
    " el.scrollIntoView({block: 'center', inline: 'nearest'});"
    " const r = el.getBoundingClientRect();"
    " return {x: r.left + r.width / 2, y: r.top + r.height / 2};"
    "})"
)
#: After the click on a field: the focused element is that kind of input, its text (a half-typed
#: attempt) selected so the insert replaces it. False when the click landed elsewhere.
FOCUS_JS = {
    "password": (
        "(() => {"
        " const el = document.activeElement;"
        " if (!el || el.tagName !== 'INPUT' || el.type !== 'password') return false;"
        " el.select();"
        " return true;"
        "})()"
    ),
    "username": (
        "(() => {"
        " const el = document.activeElement;"
        " if (!el || el.tagName !== 'INPUT' || (el.type !== 'text' && el.type !== 'email'))"
        "   return false;"
        " el.select();"
        " return true;"
        "})()"
    ),
}
#: What the approach says it did, by element, in the one line printed at the end.
SAID = {
    "login": "Login clicked",
    "username": "username in",
    "next": "Next clicked",
    "another": "passkey page passed",
    "option": "password option taken",
    "password": "the password field holds the Keychain item",
}


def page_expression(kind: str | None) -> str:
    """The script that looks at the page (``None``) or locates one kind of element on it."""
    return f"({PAGE_JS})({json.dumps(kind)})"


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


ACCOUNT_LINE = re.compile(r'^\s*"acct"<blob>=(?:"(.*)"|(0x[0-9A-Fa-f]*)\b.*|(<NULL>))$')


def keychain_account(service: str) -> tuple[str | None, str]:
    """The item's account name (the ``acct`` attribute, from the item's attributes: no ``-w``),
    or None and the line to print, which never carries the name."""
    try:
        done = subprocess.run(
            ["security", "find-generic-password", "-s", service],
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
        return None, f"Keychain did not give the item '{service}' (security exit {done.returncode})"
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        match = ACCOUNT_LINE.match(line)
        if not match:
            continue
        quoted, hexed, _null = match.groups()
        if quoted is not None:
            return quoted, ""
        if hexed:
            try:
                return bytes.fromhex(hexed[2:]).decode("utf-8"), ""
            except ValueError:
                break
        break
    return None, (
        f"the Keychain item '{service}' has no account name: make it again with"
        f"  security add-generic-password -s {service} -a <account> -w -U"
    )


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


def look(devtools: DevTools) -> dict[str, Any]:
    """The page's path and which elements it shows; an OSError while it is still loading."""
    page = devtools.evaluate(page_expression(None))
    if not isinstance(page, dict) or "shows" not in page:
        raise OSError("the page did not answer the look")
    return page


def settled(devtools: DevTools) -> dict[str, Any]:
    """The page once it shows something known, or as it is after SETTLE seconds: a page that
    is still drawing itself is not yet an unknown one."""
    end = time.monotonic() + SETTLE
    while True:
        try:
            page = look(devtools)
            if any(page["shows"].values()) or time.monotonic() >= end:
                return page
        except OSError:
            if time.monotonic() >= end:
                raise
        time.sleep(POLL)


def locate(devtools: DevTools, kind: str) -> dict[str, Any]:
    centre = devtools.evaluate(page_expression(kind))
    if not centre:
        raise OSError(f"the {kind} element left the page before the click")
    return centre


def click(devtools: DevTools, centre: dict[str, Any]) -> None:
    x, y = float(centre["x"]), float(centre["y"])
    devtools.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    for kind in ("mousePressed", "mouseReleased"):
        devtools.call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
        )


def insert(devtools: DevTools, kind: str, value: str) -> None:
    """Click the field of that kind and insert the text; an OSError when the field did not end
    up focused (after a second click) or did not take the whole text."""
    for attempt in (1, 2):
        click(devtools, locate(devtools, kind))
        if devtools.evaluate(FOCUS_JS[kind]):
            break
        if attempt == 2:
            raise OSError(f"the click did not land on the {kind} field")
    devtools.call("Input.insertText", {"text": value})
    if devtools.evaluate(LENGTH_JS) != len(value.encode("utf-16-le")) // 2:
        raise OSError(f"the {kind} field did not take the whole text")


def wait_for_change(devtools: DevTools, before: dict[str, Any]) -> bool:
    """Until the page's path or what it shows differs from ``before``, or TIMEOUT passes; a page
    half-way through loading does not answer and is looked at again."""
    end = time.monotonic() + TIMEOUT
    while time.monotonic() < end:
        time.sleep(POLL)
        try:
            page = look(devtools)
        except OSError:
            continue
        if page != before:
            return True
    return False


def approach(devtools: DevTools, site: str, service: str, said: list[str]) -> int:
    """From the page on screen to a filled password field: the exit code, with what was done in
    ``said``. Each step is decided from a fresh look; a click waits for the page to change."""
    username_done = False
    last = ""
    for _ in range(MOST_STEPS):
        page = settled(devtools)
        shows = page["shows"]
        if shows["password"]:
            if shows["username"] and not username_done:
                account, problem = keychain_account(service)
                if account is None:
                    print(problem, file=sys.stderr)
                    return 4
                insert(devtools, "username", account)
                said.append(SAID["username"])
            value, problem = keychain_password(service)
            if value is None:
                print(problem, file=sys.stderr)
                return 4
            insert(devtools, "password", value)
            said.append(f"{SAID['password']} '{service}'")
            return 0
        if shows["username"] and not username_done:
            account, problem = keychain_account(service)
            if account is None:
                print(problem, file=sys.stderr)
                return 4
            insert(devtools, "username", account)
            username_done = True
            said.append(SAID["username"])
            if not (site == "yahoo" and shows["next"]):
                continue  # without Next, look again (Basketball Monster shows both fields)
            step = "next"
        else:
            # Yahoo's passkey page first, then the option that names the password; a page
            # that still shows the link just clicked gets the other one.
            choices = []
            if site == "yahoo":
                choices += ["another"] * shows["another"] + ["option"] * shows["option"]
            elif site == "bbm" and shows["login"] and not shows["username"]:
                choices.append("login")
            if not choices:
                print(
                    f"{site}: a page this does not know, {page['path']}; nothing more typed:"
                    " continue by hand in the DevTools window, then Enter here again",
                    file=sys.stderr,
                )
                return 3
            step = next((c for c in choices if c != last), choices[0])
        click(devtools, locate(devtools, step))
        last = step
        said.append(SAID[step])
        if not wait_for_change(devtools, page):
            print(
                f"{site}: the page did not change within {TIMEOUT:.0f} s after {SAID[step]}"
                f" ({page['path']}); nothing more typed: continue by hand, then Enter again",
                file=sys.stderr,
            )
            return 3
    print(
        f"{site}: too many pages on the way to the password field; nothing more typed",
        file=sys.stderr,
    )
    return 3


def fill(port: int, site: str, service: str) -> int:
    """The site's first tab: the approach above, from the page it shows."""
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
    try:
        devtools = DevTools(port, pages[0])
    except OSError as exc:
        print(f"{site}: DevTools: {exc}", file=sys.stderr)
        return 5
    said: list[str] = []
    try:
        # A tab behind another is drawn late or not at all, and a page whose window is not the
        # one the OS has focused does not move focus into an input on a synthesized click (the
        # Mac test of 2026-10-30: activeElement stayed BODY); the protocol's remedy is to have
        # the session simulate a focused, active page.
        for method, params in (
            ("Page.bringToFront", {}),
            ("Emulation.setFocusEmulationEnabled", {"enabled": True}),
        ):
            try:
                devtools.call(method, params)
            except OSError:
                pass
        code = approach(devtools, site, service, said)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        done = f" after {', '.join(said)}" if said else ""
        print(f"{site}: {exc}{done}; continue by hand, then Enter here again", file=sys.stderr)
        return 5
    finally:
        devtools.close()
    if code == 0:
        print(f"{site}: {', '.join(said)}; click Sign in")
    elif said:
        print(f"{site}: done so far: {', '.join(said)}", file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in SITES or not argv[0].isdigit():
        print(
            "usage: keychain_fill.py <local port> <bbm|yahoo> <keychain service>", file=sys.stderr
        )
        return 2
    return fill(int(argv[0]), argv[1], argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
