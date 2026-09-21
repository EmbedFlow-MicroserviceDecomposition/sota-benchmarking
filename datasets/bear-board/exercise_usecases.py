import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.error

BASE_URL = os.environ.get("BEAR_BOARD_BASE_URL", "http://localhost:8080")
CONTAINER_NAME = "bear-board-app"

USECASES = [
    "CreateUser",
    "GetAllUsers",
    "GetUser",
    "CreateEvent",
    "GetEvents",
    "GetEvent",
    "CreateAward",
    "GetAwards",
    "GetAward",
    "CreateWhitelistUser",
    "GetWhitelistUsers",
    "GetTweets"
]

HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json'}
STATE = {}

def make_request(method, path, payload=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            body = response.read().decode('utf-8')
            return response.getcode(), (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            parsed = json.loads(body)
        except:
            parsed = body
        return e.code, parsed
    except Exception as e:
        return 0, str(e)

def run_usecase(name, **kwargs):
    print(f"--- Executing API calls for usecase: {name} ---")
    if name == "CreateUser":
        email = f"user_{int(time.time())}@example.com"
        payload = {"emailAddress": email, "password": "password123", "firstName": "John", "lastName": "Doe", "role": "USER"}
        status, data = make_request("POST", "/users", payload)
        if isinstance(data, dict) and 'id' in data:
            STATE['user_id'] = data['id']
        print(f"POST /users -> status {status}")

    elif name == "GetAllUsers":
        status, _ = make_request("GET", "/users")
        print(f"GET /users -> status {status}")

    elif name == "GetUser":
        uid = STATE.get('user_id', '1')
        status, _ = make_request("GET", f"/users/{uid}")
        print(f"GET /users/{uid} -> status {status}")

    elif name == "CreateEvent":
        payload = {"title": "Baylor Tech Conference", "coordinator": "Alice Smith", "description": "Annual tech conference", "images": [], "videos": []}
        status, data = make_request("POST", "/events", payload)
        if isinstance(data, dict) and 'id' in data:
            STATE['event_id'] = data['id']
        print(f"POST /events -> status {status}")

    elif name == "GetEvents":
        status, _ = make_request("GET", "/events?page=0&size=10")
        print(f"GET /events -> status {status}")

    elif name == "GetEvent":
        eid = STATE.get('event_id', '1')
        status, _ = make_request("GET", f"/events/{eid}")
        print(f"GET /events/{eid} -> status {status}")

    elif name == "CreateAward":
        payload = {"title": "Outstanding Developer", "description": "Engineering excellence", "date": "2026-11-01"}
        status, data = make_request("POST", "/awards", payload)
        if isinstance(data, dict) and 'id' in data:
            STATE['award_id'] = data['id']
        print(f"POST /awards -> status {status}")

    elif name == "GetAwards":
        status, _ = make_request("GET", "/awards?page=0&size=10")
        print(f"GET /awards -> status {status}")

    elif name == "GetAward":
        aid = STATE.get('award_id', '1')
        status, _ = make_request("GET", f"/awards/{aid}")
        print(f"GET /awards/{aid} -> status {status}")

    elif name == "CreateWhitelistUser":
        payload = {"user": f"baylor_user_{int(time.time())}"}
        status, data = make_request("POST", "/whitelist-users", payload)
        if isinstance(data, dict) and 'id' in data:
            STATE['whitelist_id'] = data['id']
        print(f"POST /whitelist-users -> status {status}")

    elif name == "GetWhitelistUsers":
        status, _ = make_request("GET", "/whitelist-users")
        print(f"GET /whitelist-users -> status {status}")

    elif name == "GetTweets":
        status, _ = make_request("GET", "/tweets?page=0&size=10")
        print(f"GET /tweets -> status {status}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for Bear Board")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
