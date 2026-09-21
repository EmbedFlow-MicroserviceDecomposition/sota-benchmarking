import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

BASE_URL = os.environ.get("JPETSTORE_BASE_URL", "http://localhost:8080/jpetstore")
CONTAINER_NAME = "jpetstore-app"

USECASES = [
    "ViewMain",
    "ViewCategory",
    "ViewProduct",
    "ViewItem",
    "SearchProducts",
    "AddToCart",
    "ViewCart",
    "Signon",
    "ListOrders"
]

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

def make_request(method, path, data=None, is_form=True):
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    body = None
    if data is not None:
        if is_form:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

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
    if name == "ViewMain":
        status, _ = make_request("GET", "/actions/Catalog.action")
        print(f"GET /actions/Catalog.action -> status {status}")

    elif name == "ViewCategory":
        status, _ = make_request("GET", "/actions/Catalog.action?viewCategory=&categoryId=FISH")
        print(f"GET /actions/Catalog.action?viewCategory=FISH -> status {status}")

    elif name == "ViewProduct":
        status, _ = make_request("GET", "/actions/Catalog.action?viewProduct=&productId=FI-SW-01")
        print(f"GET /actions/Catalog.action?viewProduct=FI-SW-01 -> status {status}")

    elif name == "ViewItem":
        status, _ = make_request("GET", "/actions/Catalog.action?viewItem=&itemId=EST-1")
        print(f"GET /actions/Catalog.action?viewItem=EST-1 -> status {status}")

    elif name == "SearchProducts":
        status, _ = make_request("GET", "/actions/Catalog.action?searchProducts=&keyword=fish")
        print(f"GET /actions/Catalog.action?searchProducts=fish -> status {status}")

    elif name == "AddToCart":
        status, _ = make_request("GET", "/actions/Cart.action?addItemToCart=&workingItemId=EST-1")
        print(f"GET /actions/Cart.action?addItemToCart=EST-1 -> status {status}")

    elif name == "ViewCart":
        status, _ = make_request("GET", "/actions/Cart.action?viewCart=")
        print(f"GET /actions/Cart.action?viewCart= -> status {status}")

    elif name == "Signon":
        status, _ = make_request("GET", "/actions/Account.action?signonForm=")
        print(f"GET /actions/Account.action?signonForm= -> status {status}")
        signon_data = {
            "signon": "",
            "username": "j2ee",
            "password": "your_password"
        }
        status, _ = make_request("POST", "/actions/Account.action", signon_data)
        print(f"POST /actions/Account.action?signon -> status {status}")

    elif name == "ListOrders":
        status, _ = make_request("GET", "/actions/Order.action?listOrders=")
        print(f"GET /actions/Order.action?listOrders= -> status {status}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for JPetStore")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
