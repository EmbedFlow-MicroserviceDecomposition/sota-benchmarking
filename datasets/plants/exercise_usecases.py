import os
import sys
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

BASE_URL = os.environ.get("PLANTS_BASE_URL", "http://localhost:9080/PlantsByWebSphere")
CONTAINER_NAME = "plants-app"

USECASES = [
    "ViewHome",
    "PopulateDB",
    "ViewShopping",
    "ViewCart",
    "ViewAccount",
    "ViewAdmin",
    "ViewImage"
]

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

def make_request(method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="ignore")
        return e.code, content
    except Exception as e:
        print(f"Request failed: {e}")
        return 0, str(e)

def run_usecase(name, **kwargs):
    print(f"--- Executing API calls for usecase: {name} ---")
    if name == "ViewHome":
        status, _ = make_request("GET", "/index.html")
        print(f"GET /index.html -> status {status}")
        status, _ = make_request("GET", "/promo.jsf")
        print(f"GET /promo.jsf -> status {status}")

    elif name == "PopulateDB":
        status, _ = make_request("GET", "/servlet/Populate")
        print(f"GET /servlet/Populate -> status {status}")

    elif name == "ViewShopping":
        status, _ = make_request("GET", "/shopping.jsf")
        print(f"GET /shopping.jsf -> status {status}")

    elif name == "ViewCart":
        status, _ = make_request("GET", "/cart.jsf")
        print(f"GET /cart.jsf -> status {status}")

    elif name == "ViewAccount":
        status, _ = make_request("GET", "/account.jsf")
        print(f"GET /account.jsf -> status {status}")

    elif name == "ViewAdmin":
        status, _ = make_request("GET", "/admin.jsf")
        print(f"GET /admin.jsf -> status {status}")

    elif name == "ViewImage":
        status, _ = make_request("GET", "/servlet/ImageServlet?icon=1")
        print(f"GET /servlet/ImageServlet?icon=1 -> status {status}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for PlantsByWebSphere")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
