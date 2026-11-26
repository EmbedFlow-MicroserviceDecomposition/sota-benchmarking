import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from workload import Client, Response, Suite, UsecaseFailed, forms, jsf_click, jsf_links

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


@pytest.mark.parametrize("dataset", ["jpetstore", "spring-blog", "plants"])
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
