import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error

BASE_URL = os.environ.get("PHARMACY_BASE_URL", "http://localhost:8080/pharmacy")
CONTAINER_NAME = "pharmacy-app"

USECASES = [
    "GetCategories",
    "CreateCategory",
    "GetDosageForms",
    "CreateDosageForm",
    "GetDrugs",
    "GetOrders",
    "GetUsers"
]

def make_request(method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
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
    if name == "GetCategories":
        status, _ = make_request("GET", "/categories")
        print(f"GET /categories -> status {status}")

    elif name == "CreateCategory":
        cat_data = {
            "name": "Antibiotics",
            "description": "Antibiotic drugs and medications"
        }
        status, _ = make_request("POST", "/categories", cat_data)
        print(f"POST /categories -> status {status}")

    elif name == "GetDosageForms":
        status, _ = make_request("GET", "/dosage-forms")
        print(f"GET /dosage-forms -> status {status}")

    elif name == "CreateDosageForm":
        dosage_data = {
            "name": "Tablet",
            "description": "Oral solid dosage form"
        }
        status, _ = make_request("POST", "/dosage-forms", dosage_data)
        print(f"POST /dosage-forms -> status {status}")

    elif name == "GetDrugs":
        status, _ = make_request("GET", "/drugs")
        print(f"GET /drugs -> status {status}")

    elif name == "GetOrders":
        status, _ = make_request("GET", "/orders")
        print(f"GET /orders -> status {status}")

    elif name == "GetUsers":
        status, _ = make_request("GET", "/users")
        print(f"GET /users -> status {status}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for Pharmacy")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
