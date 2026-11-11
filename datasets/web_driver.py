"""Minimal browser for the datasets' functional test suites (stdlib only): cookies, redirects, and form submission that
carries the hidden fields a real browser would send (CSRF tokens, Stripes `_sourcePage`/`__fp`)."""

import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


class Forms(HTMLParser):
    """Collects every <form>: its action and the name/value pairs a browser would submit."""

    def __init__(self):
        super().__init__()
        self.forms, self._form, self._select, self._area = [], None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = {"action": a.get("action", ""), "fields": {}, "submits": set()}
            self.forms.append(self._form)
        elif self._form is None:
            return
        elif tag == "input" and a.get("name"):
            kind = (a.get("type") or "text").lower()
            if kind == "submit":
                self._form["submits"].add(a["name"])
            elif kind in ("checkbox", "radio"):
                if "checked" in a:
                    self._form["fields"][a["name"]] = a.get("value", "on")
            else:
                self._form["fields"][a["name"]] = a.get("value") or ""
        elif tag == "select" and a.get("name"):
            self._select = a["name"]
            self._form["fields"].setdefault(self._select, "")
        elif tag == "option" and self._select:
            if "selected" in a or not self._form["fields"][self._select]:
                self._form["fields"][self._select] = a.get("value", "")
        elif tag == "textarea" and a.get("name"):
            self._area = a["name"]
            self._form["fields"][self._area] = ""

    def handle_data(self, data):
        if self._area and self._form is not None:
            self._form["fields"][self._area] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "select":
            self._select = None
        elif tag == "textarea":
            self._area = None


class Browser:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.page, self.url = "", ""

    def _open(self, req):
        req.add_header("User-Agent", "functional-tests")
        try:
            with self.opener.open(req, timeout=60) as r:
                self.page, self.url = r.read().decode("utf-8", "ignore"), r.geturl()
        except urllib.error.HTTPError as e:
            self.page, self.url = e.read().decode("utf-8", "ignore"), f"HTTP {e.code} {e.url}"
        return self.page

    def get(self, path):
        return self._open(urllib.request.Request(self.base + path))

    def forms(self):
        parser = Forms()
        parser.feed(self.page)
        return parser.forms

    def post(self, path, **data):
        """POST to `path`, adding the CSRF token of the current page if it has one."""
        token = next((f["fields"]["_csrf"] for f in self.forms() if "_csrf" in f["fields"]), None)
        if token and "_csrf" not in data:
            data["_csrf"] = token
        return self._open(urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode()))

    def submit(self, button=None, action=None, **override):
        """Submit the form on the current page that holds submit button `button`, or whose action contains `action`.
        `override` replaces fields (`a__b` means `a.b`); every other field keeps the value the page gave it."""
        forms = self.forms()
        if button is not None:
            form = next(f for f in forms if button in f["submits"])
        else:
            form = next(f for f in forms if action in f["action"])
        data = dict(form["fields"])
        data.update({k.replace("__", "."): v for k, v in override.items()})
        if button is not None:
            data[button] = "x"
        target = urllib.parse.urljoin(self.url, form["action"])
        return self._open(urllib.request.Request(target, data=urllib.parse.urlencode(data).encode()))


class Suite:
    """Collects PASS/FAIL checks; `finish()` prints the summary and returns the process exit code."""

    def __init__(self):
        self.failed = []

    def check(self, scenario, ok, detail):
        print(f"{'PASS' if ok else 'FAIL'}  {scenario}: {detail}")
        if not ok:
            self.failed.append(scenario)

    def finish(self):
        print(f"\n{len(self.failed)} failed scenario(s): {self.failed}" if self.failed else "\nall scenarios passed")
        return 1 if self.failed else 0
