"""Shared harness for the per-dataset functional test suites (`datasets/<dataset>/exercise_usecases.py`).

A suite registers use cases with `@suite.usecase("Name")`. Each use case is a black-box functional test against a running
instance: it gets its own cookie session, so it can run alone, and every request checks its response (status, expected
text), raising UsecaseFailed otherwise. The same suite drives both dynamic-analysis tools:

- Mono2Micro (`tools/mono2micro/record.py`) runs the use cases one by one through the module's USECASES / run_usecase.
- FoSCI (`tools/fosci/record_trace.py`) runs them all with the tracer agent attached to produce `fosci_trace.csv.gz`.

Run a suite by hand with `python3 datasets/<dataset>/exercise_usecases.py [--usecase NAME] [--list] [--base-url URL]`.
Standard library only: record.py imports the suites into whatever interpreter runs Mono2Micro.
"""

import argparse
import base64
import hashlib
import html
import http.cookiejar
import json
import os
import re
import socket
import struct
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict


class UsecaseFailed(AssertionError):
    pass


class Response:
    def __init__(self, status, url, text):
        self.status = status
        self.url = url
        self.text = text

    def json(self):
        return json.loads(self.text)

    def find(self, pattern, what="value"):
        """First group of `pattern` in the body; fails the use case when absent."""
        m = re.search(pattern, self.text)
        if not m:
            raise UsecaseFailed(f"{self.url}: no {what} matching {pattern!r} in the response")
        return m.group(1)

    def find_all(self, pattern):
        return re.findall(pattern, self.text)


def check(resp, what, expect=200, contains=(), absent=()):
    allowed = expect if isinstance(expect, (tuple, list, set, frozenset)) else (expect,)
    if expect is not None and resp.status not in allowed:
        raise UsecaseFailed(f"{what}: HTTP {resp.status}, expected {expect}\n{resp.text[:500]}")
    for text in (contains,) if isinstance(contains, str) else contains:
        if text not in resp.text:
            raise UsecaseFailed(f"{what}: response lacks {text!r}")
    for text in (absent,) if isinstance(absent, str) else absent:
        if text in resp.text:
            raise UsecaseFailed(f"{what}: response unexpectedly contains {text!r}")
    return resp


class Client:
    """A browser-like session: cookies, redirects followed, every response checked."""

    def __init__(self, base_url, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, method, path, params=None, data=None, json_body=None, headers=None,
                expect=200, contains=(), absent=(), timeout=None):
        url = path if path.startswith("http") else self.base_url + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        hdrs = {"User-Agent": "Mozilla/5.0 (sota-benchmarking functional suite)"}
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        hdrs.update(headers or {})
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as r:
                resp = Response(r.status, r.geturl(), r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            resp = Response(e.code, url, e.read().decode("utf-8", errors="replace"))
        return check(resp, f"{method} {path}", expect, contains, absent)

    def websocket(self, path, **kw):
        """Open a WebSocket on `path` of the same server, with this session's cookies."""
        url = "ws" + self.base_url[4:] + path
        cookie = "; ".join(f"{c.name}={c.value}" for c in self.cookies)
        return WebSocket(url, headers={"Cookie": cookie} if cookie else None, **kw)

    def get(self, path, params=None, **kw):
        return self.request("GET", path, params=params, **kw)

    def post(self, path, data=None, **kw):
        return self.request("POST", path, data=data, **kw)


_FORM = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.S | re.I)
_ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_INPUT = re.compile(r"<input\b([^>]*)>", re.I)
_SELECT = re.compile(r"<select\b([^>]*)>(.*?)</select>", re.S | re.I)
_TEXTAREA = re.compile(r"<textarea\b([^>]*)>(.*?)</textarea>", re.S | re.I)
_MYFACES_LINK = re.compile(r"""<a\b[^>]*onclick="return myfaces\.oam\.submitForm\('([^']+)','([^']+)'(?:,null,\[(.*?)\])?\);"[^>]*>(.*?)</a>""",
                           re.S)
# h:commandLink with f:ajax: jsf.ajax.request('<id>',event,{execute:'...',render:'...',...})
_AJAX_LINK = re.compile(r"""<a\b[^>]*onclick="[^"]*jsf\.ajax\.request\(\\'([^\\]+)\\',event,\{execute:\\'([^\\]*)\\',"""
                        r"""render:\\'([^\\]*)\\'[^"]*"[^>]*>(.*?)</a>""", re.S)


def _attrs(text):
    return {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3)) for m in _ATTR.finditer(text)}


def forms(resp):
    """{form id or name: (action, {field: value})} with the values a browser would submit (no submit buttons)."""
    found = {}
    for m in _FORM.finditer(resp.text):
        attrs, body = _attrs(m.group(1)), m.group(2)
        fields = {}
        for i in _INPUT.finditer(body):
            a = _attrs(i.group(1))
            kind = a.get("type", "text").lower()
            if "name" not in a or kind in ("submit", "image", "button", "reset", "file"):
                continue
            if kind in ("checkbox", "radio") and "checked" not in a:
                continue
            fields[a["name"]] = a.get("value", "on" if kind == "checkbox" else "")
        for s in _SELECT.finditer(body):
            a = _attrs(s.group(1))
            options = re.findall(r"<option\b([^>]*)>", s.group(2), re.I)
            chosen = next((o for o in options if "selected" in _attrs(o)), options[0] if options else None)
            if "name" in a and chosen is not None:
                fields[a["name"]] = _attrs(chosen).get("value", "")
        for t in _TEXTAREA.finditer(body):
            a = _attrs(t.group(1))
            if "name" in a:
                fields[a["name"]] = html.unescape(t.group(2))
        found[attrs.get("id") or attrs.get("name")] = (attrs.get("action", resp.url), fields)
    return found


def _link_text(inner):
    alt = " ".join(re.findall(r"""alt="([^"]*)\"""", inner))
    return " ".join((html.unescape(re.sub(r"<[^>]+>", " ", inner)) + " " + alt).split())


def jsf_links(resp):
    """Command links: [(form id, link id, {param: value}, visible text, ajax)], ajax = None or (execute, render)."""
    links = []
    for form_id, link_id, params, inner in _MYFACES_LINK.findall(resp.text):
        links.append((form_id, link_id, dict(re.findall(r"\['([^']*)','([^']*)'\]", params or "")), _link_text(inner), None))
    for link_id, execute, render, inner in _AJAX_LINK.findall(resp.text):
        links.append((link_id.split(":")[0], link_id, {}, _link_text(inner), (execute.strip(), render.strip())))
    return links


def jsf_click(client, resp, text=None, params=None, fields=None, form=None, **checks):
    """Follow an h:commandLink as the browser would: MyFaces' submitForm() posts the form's fields plus `<form>:_idcl`
    and the link's f:params; an f:ajax link sends the JSF partial request instead (the response is partial XML).
    Picks the first link whose text (or image alt) contains `text` and whose params include `params`; `fields`
    overrides form inputs (keys may omit the `<form>:` prefix)."""
    for form_id, link_id, link_params, link_text, ajax in jsf_links(resp):
        if form and form_id != form:
            continue
        if text is not None and text.lower() not in link_text.lower():
            continue
        if params and any(link_params.get(k) != str(v) for k, v in params.items()):
            continue
        if ajax:
            execute, render = ajax
            extra = {"javax.faces.source": link_id, "javax.faces.partial.event": "click",
                     "javax.faces.partial.execute": " ".join(form_id if t == "@form" else t for t in execute.split()),
                     "javax.faces.partial.render": render, "javax.faces.behavior.event": "action",
                     "javax.faces.partial.ajax": "true"}
            return jsf_post(client, resp, form_id, extra, fields, headers={"Faces-Request": "partial/ajax"}, **checks)
        return jsf_post(client, resp, form_id, dict(link_params, **{f"{form_id}:_idcl": link_id}), fields, **checks)
    raise UsecaseFailed(f"{resp.url}: no command link text={text!r} params={params!r} form={form!r}; "
                        f"links: {[(t, p) for _, _, p, t, _ in jsf_links(resp)][:40]}")


def jsf_post(client, resp, form_id, extra=None, fields=None, **checks):
    """Submit JSF form `form_id` of `resp` with `extra` parameters (e.g. a command button's name) and overridden fields."""
    page_forms = forms(resp)
    if form_id not in page_forms:
        raise UsecaseFailed(f"{resp.url}: no form {form_id!r}; forms: {list(page_forms)}")
    action, data = page_forms[form_id]
    for name, value in (fields or {}).items():
        key = name if name in data or ":" in name else f"{form_id}:{name}"
        data[key] = value
    data.update(extra or {})
    return client.post(urllib.parse.urljoin(resp.url, action), data, **checks)


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_frame(opcode, payload, mask=True):
    """One unfragmented RFC 6455 frame (clients must mask)."""
    head = bytes([0x80 | opcode])
    n = len(payload)
    mask_bit = 0x80 if mask else 0
    head += bytes([mask_bit | n]) if n < 126 else bytes([mask_bit | 126]) + struct.pack(">H", n) if n < 65536 \
        else bytes([mask_bit | 127]) + struct.pack(">Q", n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


class WebSocket:
    """Minimal RFC 6455 client: text and binary messages, answers pings; enough to drive a server endpoint."""

    def __init__(self, url, timeout=30, headers=None):
        parts = urllib.parse.urlparse(url)
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        self.sock = socket.create_connection((parts.hostname, port), timeout)
        self.timeout = timeout
        key = base64.b64encode(os.urandom(16)).decode()
        path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                           f"{extra}\r\n").encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise UsecaseFailed(f"{url}: connection closed during the WebSocket handshake")
            reply += chunk
        head, _, self._buffer = reply.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        if " 101 " not in status or accept not in head.decode("latin-1"):
            raise UsecaseFailed(f"{url}: WebSocket handshake refused: {status}")

    def _read(self, n):
        while len(self._buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise UsecaseFailed("WebSocket closed by the server")
            self._buffer += chunk
        data, self._buffer = self._buffer[:n], self._buffer[n:]
        return data

    def send(self, message):
        """A str goes as a text frame, bytes as a binary frame."""
        if isinstance(message, str):
            self.sock.sendall(ws_frame(1, message.encode("utf-8")))
        else:
            self.sock.sendall(ws_frame(2, bytes(message)))

    def recv(self):
        """The next text (str) or binary (bytes) message; None when the server closes."""
        while True:
            first, second = self._read(2)
            opcode, n = first & 0x0F, second & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)  # servers do not mask
            if opcode == 9:
                self.sock.sendall(ws_frame(10, payload))
            elif opcode == 8:
                return None
            elif opcode == 1:
                return payload.decode("utf-8")
            elif opcode == 2:
                return payload

    def close(self):
        try:
            self.sock.sendall(ws_frame(8, b""))
        except OSError:
            pass
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def unique(prefix):
    """A name that does not collide across repeated runs against the same database."""
    return f"{prefix}{int(time.time() * 1000) % 10**9}"


class Suite:
    def __init__(self, name, base_url, ready_path=""):
        self.name = name
        self.base_url = base_url
        self.ready_path = ready_path
        self.usecases = OrderedDict()

    def usecase(self, name):
        def register(fn):
            if name in self.usecases:
                raise ValueError(f"duplicate use case {name}")
            self.usecases[name] = fn
            return fn
        return register

    def client(self):
        return Client(self.base_url)

    def run(self, name):
        if name not in self.usecases:
            raise KeyError(f"{self.name}: unknown use case {name!r}; known: {', '.join(self.usecases)}")
        self.usecases[name](self.client())

    def wait_ready(self, timeout=600):
        """Block until the app answers `ready_path` successfully (a container answers 404 until the app is deployed)."""
        deadline = time.time() + timeout
        url = self.base_url.rstrip("/") + self.ready_path
        while True:
            try:
                with urllib.request.urlopen(url, timeout=10):
                    return
            except OSError:  # includes HTTPError
                pass
            if time.time() > deadline:
                raise TimeoutError(f"{self.name} did not answer {url} within {timeout}s")
            time.sleep(3)

    def run_all(self, names=None, on_start=None, on_end=None):
        """Run use cases in order; returns {name: None | error text}. Hooks get the use case name."""
        results = OrderedDict()
        for name in names or self.usecases:
            if on_start:
                on_start(name)
            started = time.time()
            try:
                self.run(name)
                results[name] = None
                print(f"PASS {name} ({time.time() - started:.1f}s)", flush=True)
            except Exception as e:  # report every failing use case, not just the first
                results[name] = f"{type(e).__name__}: {e}"
                print(f"FAIL {name}: {results[name]}", flush=True)
                if not isinstance(e, UsecaseFailed):
                    traceback.print_exc()
            if on_end:
                on_end(name)
        failed = [n for n, err in results.items() if err]
        print(f"{self.name}: {len(results) - len(failed)}/{len(results)} use cases passed", flush=True)
        return results

    def main(self, argv=None):
        parser = argparse.ArgumentParser(description=f"{self.name} functional test suite")
        parser.add_argument("--usecase", action="append", help="run only this use case (repeatable)")
        parser.add_argument("--list", action="store_true", help="list the use cases")
        parser.add_argument("--base-url", help=f"default {self.base_url}")
        parser.add_argument("--wait", action="store_true", help="wait for the app to come up first")
        args = parser.parse_args(argv)
        if args.list:
            print("\n".join(self.usecases))
            return
        if args.base_url:
            self.base_url = args.base_url
        if args.wait:
            self.wait_ready()
        results = self.run_all(args.usecase)
        sys.exit(1 if any(results.values()) else 0)
