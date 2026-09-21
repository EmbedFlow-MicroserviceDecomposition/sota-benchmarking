import os
import sys
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

BASE_URL = os.environ.get("ROLLER_BASE_URL", "http://localhost:8080")
CONTAINER_NAME = "roller-roller-1"

USECASES = [
    "ViewHome",
    "ViewEntry",
    "ViewCategory",
    "SearchBlog",
    "ViewFeed",
    "ViewTags",
    "ViewLogin"
]

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

def make_request(method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml"
    }
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="ignore")
        return e.code, content
    except Exception as e:
        print(f"Request to {path} failed: {e}")
        return 0, str(e)

def run_usecase(name, **kwargs):
    print(f"--- Executing API calls for usecase: {name} ---")
    if name == "ViewHome":
        status, _ = make_request("GET", "/")
        print(f"GET / -> status {status}")
        status, _ = make_request("GET", "/yumyum/")
        print(f"GET /yumyum/ -> status {status}")

    elif name == "ViewEntry":
        status, _ = make_request("GET", "/yumyum/entry/first-article")
        print(f"GET /yumyum/entry/first-article -> status {status}")

    elif name == "ViewCategory":
        status, _ = make_request("GET", "/yumyum/category/General")
        print(f"GET /yumyum/category/General -> status {status}")
        status, _ = make_request("GET", "/yumyum/category/Technology")
        print(f"GET /yumyum/category/Technology -> status {status}")

    elif name == "SearchBlog":
        status, _ = make_request("GET", "/yumyum/search?q=test")
        print(f"GET /yumyum/search?q=test -> status {status}")

    elif name == "ViewFeed":
        status, _ = make_request("GET", "/yumyum/feed/entries/atom")
        print(f"GET /yumyum/feed/entries/atom -> status {status}")
        status, _ = make_request("GET", "/yumyum/feed/entries/rss")
        print(f"GET /yumyum/feed/entries/rss -> status {status}")

    elif name == "ViewTags":
        status, _ = make_request("GET", "/yumyum/tags/test")
        print(f"GET /yumyum/tags/test -> status {status}")

    elif name == "ViewLogin":
        status, _ = make_request("GET", "/roller-ui/login-redirect.rol")
        print(f"GET /roller-ui/login-redirect.rol -> status {status}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for Apache Roller")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
