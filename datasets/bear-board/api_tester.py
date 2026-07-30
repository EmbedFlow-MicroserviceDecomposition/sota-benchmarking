import urllib.request
import urllib.error
import json
import time

BASE_URL = "http://localhost:8080"
STATE = {}
HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

def make_request(method, path, payload=None):
    url = f"{BASE_URL}{path}"
    headers = HEADERS.copy()
    data = None
    if payload:
        data = json.dumps(payload).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            body = response.read().decode('utf-8')
            return status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            parsed = json.loads(body)
        except:
            parsed = body
        return e.code, parsed
    except Exception as e:
        return 0, str(e)

def prompt_to_continue(use_case_name):
    print(f"\n=======================================================")
    print(f"READY FOR USE CASE: '{use_case_name}'")
    print(f"1. Switch to your Mono2Micro usecase terminal")
    print(f"2. Start recording by typing: {use_case_name}")
    print(f"3. Press ENTER here to fire the API calls")
    input("\nPress ENTER when Mono2Micro is recording...")

def run_usecase(name, func):
    prompt_to_continue(name)
    try:
        func()
    except Exception as e:
        print(f"Error during {name}: {e}")
    print(f"\nFinished '{name}'.")
    print("--> Stop recording in Mono2Micro now (press Enter there).")

# ================= API FUNCTIONS =================

def create_user():
    print("Executing POST /users...")
    email = f"user_{int(time.time())}@example.com"
    payload = {
        "emailAddress": email,
        "password": "password123",
        "firstName": "John",
        "lastName": "Doe",
        "role": "USER"
    }
    status, data = make_request("POST", "/users", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))
    
    if isinstance(data, dict) and 'id' in data:
        STATE['user_id'] = data['id']

def get_all_users():
    print("Executing GET /users...")
    status, data = make_request("GET", "/users")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def get_user():
    user_id = STATE.get('user_id')
    if not user_id:
        print("No user ID in state, skipping.")
        return
    print(f"Executing GET /users/{user_id}...")
    status, data = make_request("GET", f"/users/{user_id}")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def create_event():
    print("Executing POST /events...")
    payload = {
        "title": "Baylor Tech Conference",
        "coordinator": "Alice Smith",
        "description": "Annual technology conference at Baylor University",
        "images": ["http://example.com/image1.jpg"],
        "videos": []
    }
    status, data = make_request("POST", "/events", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))
    
    if isinstance(data, dict) and 'id' in data:
        STATE['event_id'] = data['id']

def get_events():
    print("Executing GET /events?page=0&size=10...")
    status, data = make_request("GET", "/events?page=0&size=10")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def get_event():
    event_id = STATE.get('event_id')
    if not event_id:
        print("No event ID in state, skipping.")
        return
    print(f"Executing GET /events/{event_id}...")
    status, data = make_request("GET", f"/events/{event_id}")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def create_award():
    print("Executing POST /awards...")
    payload = {
        "title": "Outstanding Developer Award",
        "description": "Recognizing excellence in software engineering",
        "date": "2026-11-01"
    }
    status, data = make_request("POST", "/awards", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))
    
    if isinstance(data, dict) and 'id' in data:
        STATE['award_id'] = data['id']

def get_awards():
    print("Executing GET /awards?page=0&size=10...")
    status, data = make_request("GET", "/awards?page=0&size=10")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def get_award():
    award_id = STATE.get('award_id')
    if not award_id:
        print("No award ID in state, skipping.")
        return
    print(f"Executing GET /awards/{award_id}...")
    status, data = make_request("GET", f"/awards/{award_id}")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def create_whitelist_user():
    print("Executing POST /whitelist-users...")
    payload = {
        "user": f"baylor_user_{int(time.time())}"
    }
    status, data = make_request("POST", "/whitelist-users", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))
    
    if isinstance(data, dict) and 'id' in data:
        STATE['whitelist_id'] = data['id']

def get_whitelist_users():
    print("Executing GET /whitelist-users...")
    status, data = make_request("GET", "/whitelist-users")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def get_tweets():
    print("Executing GET /tweets?page=0&size=10...")
    status, data = make_request("GET", "/tweets?page=0&size=10")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def main():
    print("=======================================================")
    print("      Bear Board API Tester for Mono2Micro Tracing")
    print("=======================================================")
    
    run_usecase("CreateUser", create_user)
    run_usecase("GetAllUsers", get_all_users)
    run_usecase("GetUser", get_user)
    run_usecase("CreateEvent", create_event)
    run_usecase("GetEvents", get_events)
    run_usecase("GetEvent", get_event)
    run_usecase("CreateAward", create_award)
    run_usecase("GetAwards", get_awards)
    run_usecase("GetAward", get_award)
    run_usecase("CreateWhitelistUser", create_whitelist_user)
    run_usecase("GetWhitelistUsers", get_whitelist_users)
    run_usecase("GetTweets", get_tweets)
    
    print("\nAll API sequences completed successfully!")

if __name__ == "__main__":
    main()
