import urllib.request
import urllib.parse
import urllib.error
import json
import time

BASE_URL = "http://localhost:8080"
STATE = {}
HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

def make_request(method, path, payload=None, is_form=False, custom_headers=None):
    url = f"{BASE_URL}{path}"
    headers = HEADERS.copy()
    if custom_headers:
        headers.update(custom_headers)
        
    data = None
    if payload:
        if is_form:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            data = urllib.parse.urlencode(payload).encode('utf-8')
        else:
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
    print("Executing POST /users/signup...")
    username = f"user_{int(time.time())}"
    password = "password123"
    payload = {
        "active": True,
        "address": "123 Kathmandu",
        "email": f"test_{int(time.time())}@autocare.com",
        "firstname": "John",
        "lastname": "Doe",
        "organization": {
            "description": "Auto Care Co",
            "name": "AutoCare"
        },
        "password": password,
        "roles": ["USER"],
        "username": username
    }
    status, data = make_request("POST", "/users/signup", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))
    
    if isinstance(data, dict) and 'id' in data:
        STATE['user_id'] = data['id']
        STATE['username'] = username
        STATE['password'] = password

def authenticate_user():
    print("Executing POST /oauth/token (Fetching Bearer Token)...")
    username = STATE.get('username')
    password = STATE.get('password')
    if not username:
        print("No user created, skipping auth.")
        return
        
    payload = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "client_id": "autocare",
        "client_secret": "SR2wFdy$By&aj_?s"
    }
    
    import base64
    auth_header = "Basic " + base64.b64encode(b"autocare:SR2wFdy$By&aj_?s").decode('utf-8')
    status, data = make_request("POST", "/oauth/token", payload, is_form=True, custom_headers={'Authorization': auth_header})
    print(f"Status: {status}")
    
    if isinstance(data, dict) and 'access_token' in data:
        token = data['access_token']
        HEADERS['Authorization'] = f"Bearer {token}"
        print(f"Successfully obtained OAuth2 token! (Length: {len(token)})")
    else:
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

def create_vehicle():
    print("Executing POST /vehicles...")
    payload = {
        "brand": "Toyota",
        "description": "A very reliable car",
        "distanceDriven": 15000.5,
        "images": [],
        "location": [85.3240, 27.7172],
        "mileage": 14.5,
        "model": "Corolla",
        "newVehicle": False,
        "price": 25000.00,
        "priceNegotiable": True,
        "sold": False,
        "tags": ["sedan", "used", "toyota"],
        "twoWheeler": False,
        "usedMonths": 36
    }
    status, data = make_request("POST", "/vehicles", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))
    
    if isinstance(data, dict) and 'id' in data:
        STATE['vehicle_id'] = data['id']

def get_vehicles():
    print("Executing GET /vehicles?page=0&size=10...")
    status, data = make_request("GET", "/vehicles?page=0&size=10")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def search_vehicles():
    print("Executing POST /vehicles/search?page=0&size=10...")
    payload = {
        "brands": ["Toyota", "Honda"],
        "condition": [],
        "locationDetails": {
            "distance": 50.0,
            "location": [85.3, 27.7]
        },
        "maxPrice": 50000.0,
        "minPrice": 5000.0
    }
    status, data = make_request("POST", "/vehicles/search?page=0&size=10", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def create_comment():
    vehicle_id = STATE.get('vehicle_id')
    if not vehicle_id:
        print("No vehicle ID in state, skipping.")
        return
    print("Executing POST /comments...")
    payload = {
        "body": "Is the price negotiable?",
        "vehicleId": vehicle_id
    }
    status, data = make_request("POST", "/comments", payload)
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def get_comments():
    vehicle_id = STATE.get('vehicle_id')
    if not vehicle_id:
        print("No vehicle ID in state, skipping.")
        return
    print(f"Executing GET /comments?vehicleId={vehicle_id}&page=0&size=10...")
    status, data = make_request("GET", f"/comments?vehicleId={vehicle_id}&page=0&size=10")
    print(f"Status: {status}")
    print(json.dumps(data, indent=2))

def main():
    print("=======================================================")
    print("      Autocare API Tester for Mono2Micro Tracing")
    print("=======================================================")
    
    run_usecase("CreateUser", create_user)
    run_usecase("Authenticate", authenticate_user)
    run_usecase("GetUser", get_user)
    run_usecase("CreateVehicle", create_vehicle)
    run_usecase("GetVehicles", get_vehicles)
    run_usecase("SearchVehicles", search_vehicles)
    run_usecase("CreateComment", create_comment)
    run_usecase("GetComments", get_comments)
    
    print("\nAll API sequences completed successfully!")

if __name__ == "__main__":
    main()
