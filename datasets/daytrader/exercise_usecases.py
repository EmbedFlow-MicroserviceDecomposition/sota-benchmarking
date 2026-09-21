import os
import sys
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

BASE_URL = os.environ.get("DAYTRADER_BASE_URL", "http://localhost:9082/daytrader")
CONTAINER_NAME = "daytrader-app"

USECASES = [
    "BuildDB",
    "ViewHome",
    "TradeConfig",
    "TradeScenario",
    "TradeApp",
    "PingServlet",
    "MarketSummary",
    "ViewQuotes"
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
    if name == "BuildDB":
        status, _ = make_request("GET", "/config?action=buildDB")
        print(f"GET /config?action=buildDB -> status {status}")

    elif name == "ViewHome":
        status, _ = make_request("GET", "/index.html")
        print(f"GET /index.html -> status {status}")
        status, _ = make_request("GET", "/header.html")
        print(f"GET /header.html -> status {status}")
        status, _ = make_request("GET", "/contentHome.html")
        print(f"GET /contentHome.html -> status {status}")

    elif name == "TradeConfig":
        status, _ = make_request("GET", "/config")
        print(f"GET /config -> status {status}")

    elif name == "TradeScenario":
        status, _ = make_request("GET", "/TradeScenarioServlet")
        print(f"GET /TradeScenarioServlet -> status {status}")

    elif name == "TradeApp":
        status, _ = make_request("GET", "/app")
        print(f"GET /app -> status {status}")

    elif name == "PingServlet":
        status, _ = make_request("GET", "/ping")
        print(f"GET /ping -> status {status}")

    elif name == "MarketSummary":
        status, _ = make_request("GET", "/app?action=marketSummary")
        print(f"GET /app?action=marketSummary -> status {status}")

    elif name == "ViewQuotes":
        status, _ = make_request("GET", "/app?action=quotes&symbols=s:0,s:1,s:2,s:3,s:4")
        print(f"GET /app?action=quotes -> status {status}")

def run_all():
    # Build database first before executing use cases
    make_request("GET", "/config?action=buildDB")
    time.sleep(2)
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for DayTrader")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
