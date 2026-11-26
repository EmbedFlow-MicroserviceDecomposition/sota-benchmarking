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
import http.cookiejar
import json
import re
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
                expect=200, contains=(), absent=()):
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
            with self.opener.open(req, timeout=self.timeout) as r:
                resp = Response(r.status, r.geturl(), r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            resp = Response(e.code, url, e.read().decode("utf-8", errors="replace"))
        return check(resp, f"{method} {path}", expect, contains, absent)

    def get(self, path, params=None, **kw):
        return self.request("GET", path, params=params, **kw)

    def post(self, path, data=None, **kw):
        return self.request("POST", path, data=data, **kw)


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
