import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error

BASE_URL = os.environ.get("PETCLINIC_BASE_URL", "http://localhost:8080")
CONTAINER_NAME = "spring-petclinic-app"

USECASES = [
    "Add_Owner",
    "Find_Owner",
    "Add_Pet",
    "Add_Visit",
    "Add_Vet"
]

def make_request(method, path, data=None, is_form=True):
    url = f"{BASE_URL}{path}"
    headers = {}
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
    if name == "Add_Owner":
        owner_data = {
            "firstName": "George",
            "lastName": "Franklin",
            "address": "110 W. Liberty St.",
            "city": "Madison",
            "telephone": "6085551023"
        }
        status, _ = make_request("POST", "/owners/new", owner_data)
        print(f"POST /owners/new -> status {status}")

    elif name == "Find_Owner":
        status, _ = make_request("GET", "/owners?lastName=Franklin")
        print(f"GET /owners?lastName=Franklin -> status {status}")
        status, _ = make_request("GET", "/owners/1")
        print(f"GET /owners/1 -> status {status}")

    elif name == "Add_Pet":
        pet_data = {
            "id": "",
            "name": "Leo",
            "birthDate": "2020-09-07",
            "type": "cat"
        }
        status, _ = make_request("POST", "/owners/1/pets/new", pet_data)
        print(f"POST /owners/1/pets/new -> status {status}")

    elif name == "Add_Visit":
        visit_data = {
            "date": "2023-01-01",
            "description": "rabies shot"
        }
        status, _ = make_request("POST", "/owners/1/pets/1/visits/new", visit_data)
        print(f"POST /owners/1/pets/1/visits/new -> status {status}")

    elif name == "Add_Vet":
        status, _ = make_request("GET", "/vets.json")
        print(f"GET /vets.json -> status {status}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for Spring PetClinic")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
