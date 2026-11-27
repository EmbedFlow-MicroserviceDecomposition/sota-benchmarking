import base64
import hashlib
import importlib.util
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from workload import Client, Response, Suite, UsecaseFailed, WebSocket, forms, jsf_click, jsf_links, ws_frame

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/login"):
            self.send_response(302)
            self.send_header("Set-Cookie", "sid=abc; Path=/")
            self.send_header("Location", "/home")
            self.end_headers()
            return
        if self.path.startswith("/home"):
            body = b"signed in" if "sid=abc" in (self.headers.get("Cookie") or "") else b"anonymous"
            self.send_response(200)
        else:
            body = b"missing"
            self.send_response(404)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"echo " + data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_client_keeps_cookies_across_redirects(server):
    c = Client(server)
    assert c.get("/login", contains="signed in").status == 200
    assert "anonymous" in Client(server).get("/home").text


def test_client_checks_status_and_text(server):
    c = Client(server)
    with pytest.raises(UsecaseFailed, match="HTTP 404"):
        c.get("/nope")
    assert c.get("/nope", expect=404).text == "missing"
    with pytest.raises(UsecaseFailed, match="lacks"):
        c.get("/home", contains="signed in")
    with pytest.raises(UsecaseFailed, match="unexpectedly"):
        c.get("/home", absent="anon")
    assert c.post("/form", {"a": "1", "b": ["x", "y"]}).text == "echo a=1&b=x&b=y"


def test_suite_runs_every_usecase_and_reports_failures(server):
    suite = Suite("Demo", server, ready_path="/home")
    ran = []

    @suite.usecase("Good")
    def good(c):
        ran.append("Good")
        c.get("/home")

    @suite.usecase("Bad")
    def bad(c):
        c.get("/nope")

    @suite.usecase("AlsoGood")
    def also_good(c):
        ran.append("AlsoGood")

    suite.wait_ready(timeout=5)
    results = suite.run_all()
    assert list(results) == ["Good", "Bad", "AlsoGood"]
    assert results["Good"] is None and results["AlsoGood"] is None
    assert "HTTP 404" in results["Bad"]
    assert ran == ["Good", "AlsoGood"]
    with pytest.raises(ValueError):
        suite.usecase("Good")(lambda c: None)
    with pytest.raises(KeyError):
        suite.run("Unknown")


def test_wait_ready_times_out_while_the_app_is_not_deployed(server):
    with pytest.raises(TimeoutError):
        Suite("Demo", server, ready_path="/nope").wait_ready(timeout=0)


@pytest.mark.parametrize("dataset", ["jpetstore", "spring-blog", "plants", "daytrader", "acme-air"])
def test_suites_keep_mono2micro_contract(dataset):
    """record.py needs USECASES and run_usecase(name, **kwargs); the suite must match them."""
    path = ROOT / "datasets" / dataset / "exercise_usecases.py"
    spec = importlib.util.spec_from_file_location(f"suite_{dataset}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.USECASES == list(module.suite.usecases)
    assert len(module.USECASES) >= 10
    assert callable(module.run_usecase)


JSF_PAGE = """<form id="shop" name="shop" method="post" action="/app/shop.jsf">
<input type="hidden" name="shop_SUBMIT" value="1" /><input id="shop:qty" type="text" name="shop:qty" value="1" />
<input type="checkbox" name="shop:gift" value="true" /><input type="checkbox" name="shop:news" value="true" checked="checked" />
<select name="shop:size"><option value="S">S</option><option value="M" selected="selected">M</option></select>
<textarea name="shop:note">hi &amp; bye</textarea><input type="submit" name="shop:go" value="Go" />
<a href="#" onclick="return myfaces.oam.submitForm('shop','shop:j_id_1',null,[['itemID','T1']]);">Bonsai <b>Tree</b></a>
<a href="#" onclick="return myfaces.oam.submitForm('shop','shop:j_id_2');"><img src="x.gif" alt="Checkout Now" /></a>
<a href="#" onclick="jsf.util.chain(document.getElementById('shop:j_id_3'), event,'jsf.ajax.request(\\'shop:j_id_3\\',event,{execute:\\'@form \\',render:\\'shop:table \\',\\'javax.faces.behavior.event\\':\\'action\\'})'); return false;" id="shop:j_id_3"><img alt="Recalculate" /></a>
<input type="hidden" name="javax.faces.ViewState" value="VS1" /></form>"""


def test_forms_submit_what_a_browser_would():
    action, fields = forms(Response(200, "http://h/app/x.jsf", JSF_PAGE))["shop"]
    assert action == "/app/shop.jsf"
    assert fields == {"shop_SUBMIT": "1", "shop:qty": "1", "shop:news": "true", "shop:size": "M",
                      "shop:note": "hi & bye", "javax.faces.ViewState": "VS1"}


def test_jsf_links_find_text_images_params_and_ajax():
    links = jsf_links(Response(200, "http://h/app/x.jsf", JSF_PAGE))
    assert [(link_id, params, text, ajax) for _, link_id, params, text, ajax in links] == [
        ("shop:j_id_1", {"itemID": "T1"}, "Bonsai Tree", None),
        ("shop:j_id_2", {}, "Checkout Now", None),
        ("shop:j_id_3", {}, "Recalculate", ("@form", "shop:table"))]


def test_jsf_click_posts_the_form_like_myfaces(monkeypatch):
    page = Response(200, "http://h/app/x.jsf", JSF_PAGE)
    sent = []
    client = Client("http://h/app")
    monkeypatch.setattr(client, "post", lambda url, data, **kw: sent.append((url, data, kw)) or page)
    jsf_click(client, page, params={"itemID": "T1"}, fields={"qty": "3"})
    url, data, _ = sent[-1]
    assert url == "http://h/app/shop.jsf"
    assert data["shop:qty"] == "3" and data["itemID"] == "T1" and data["shop:_idcl"] == "shop:j_id_1"
    jsf_click(client, page, text="recalc")
    _, data, kw = sent[-1]
    assert data["javax.faces.source"] == "shop:j_id_3" and data["javax.faces.partial.execute"] == "shop"
    assert kw["headers"] == {"Faces-Request": "partial/ajax"}
    with pytest.raises(UsecaseFailed, match="no command link"):
        jsf_click(client, page, text="missing")


def _echo_server(listener):
    """A one-connection WebSocket server: completes the handshake, echoes data frames, pings once, then closes."""
    conn, _ = listener.accept()
    request = b""
    while b"\r\n\r\n" not in request:
        request += conn.recv(4096)
    key = next(line.split(b": ")[1] for line in request.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key")).decode()
    accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    conn.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode())
    conn.sendall(ws_frame(9, b"hi", mask=False))  # a ping the client must answer
    def read(n):
        data = b""
        while len(data) < n:
            data += conn.recv(n - len(data))
        return data

    for _ in range(4):  # text, the pong, binary, the big text
        head = read(2)
        opcode, n = head[0] & 0x0F, head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", read(8))[0]
        mask = read(4)
        body = read(n)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(body))
        if opcode == 10:
            assert payload == b"hi"  # the pong
        elif opcode in (1, 2):
            conn.sendall(ws_frame(opcode, payload, mask=False))
    conn.sendall(ws_frame(8, b"", mask=False))
    conn.close()


def test_websocket_client_handshakes_echoes_text_binary_and_big_frames_and_answers_pings():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    threading.Thread(target=_echo_server, args=(listener,), daemon=True).start()
    with WebSocket(f"ws://127.0.0.1:{listener.getsockname()[1]}/echo") as ws:
        ws.send("héllo")
        assert ws.recv() == "héllo"
        ws.send(b"\x00\x01\x02")
        assert ws.recv() == b"\x00\x01\x02"
        big = "x" * 70000  # 8-byte length form
        ws.send(big)
        assert ws.recv() == big
        assert ws.recv() is None  # the server's close frame
    listener.close()


def test_websocket_refuses_a_server_that_does_not_upgrade(server):
    with pytest.raises(UsecaseFailed, match="handshake refused"):
        WebSocket(server.replace("http", "ws") + "/home")
