import os
import sys
import time
import requests
import argparse

BASE_URL = os.environ.get("ACMEAIR_BASE_URL", "http://localhost:9080/acmeair-webapp")
CONTAINER_NAME = "acme-air-acmeair-liberty-1"

USECASES = [
    "LoadDB",
    "Login",
    "ViewAccount",
    "UpdateProfile",
    "BrowseFlights",
    "BookFlight",
    "ViewBookings",
    "CancelBooking",
    "Logout"
]

session = requests.Session()
state = {}

def run_usecase(name, **kwargs):
    print(f"--- Executing API calls for usecase: {name} ---")
    try:
        if name == "LoadDB":
            res = session.get(f"{BASE_URL}/rest/info/loader/query", timeout=15)
            print(f"Loader query -> {res.status_code}")
            res2 = session.get(f"{BASE_URL}/rest/info/loader/load?numCustomers=5", timeout=90)
            print(f"LoadDB -> {res2.status_code}")

        elif name == "Login":
            res = session.post(f"{BASE_URL}/rest/api/login", data={"login": "uid0@email.com", "password": "password"}, timeout=15)
            print(f"Login -> {res.status_code}")

        elif name == "ViewAccount":
            res = session.get(f"{BASE_URL}/rest/api/customer/byid/uid0@email.com", timeout=15)
            print(f"ViewAccount -> {res.status_code}")

        elif name == "UpdateProfile":
            cust_res = session.get(f"{BASE_URL}/rest/api/customer/byid/uid0@email.com", timeout=15)
            if cust_res.status_code == 200:
                cust_data = cust_res.json()
                cust_data["password"] = "password"
                cust_data["phoneNumber"] = "555-123-4567"
                res = session.post(f"{BASE_URL}/rest/api/customer/byid/uid0@email.com", json=cust_data, timeout=15)
                print(f"UpdateProfile -> {res.status_code}")

        elif name == "BrowseFlights":
            res = session.post(f"{BASE_URL}/rest/api/flights/browseflights", data={
                "fromAirport": "AMS",
                "toAirport": "FRA",
                "oneWay": "true"
            }, timeout=15)
            print(f"BrowseFlights -> {res.status_code}")
            if res.status_code == 200:
                data = res.json()
                flights = data.get("tripFlights", [{}])[0].get("flightsOptions", [])
                if flights:
                    state["flightId"] = flights[0]["_id"]
                    state["flightSegId"] = flights[0]["flightSegmentId"]

        elif name == "BookFlight":
            if "flightId" in state:
                res = session.post(f"{BASE_URL}/rest/api/bookings/bookflights", data={
                    "userid": "uid0@email.com",
                    "toFlightId": state["flightId"],
                    "toFlightSegId": state["flightSegId"],
                    "oneWayFlight": "true"
                }, timeout=15)
                print(f"BookFlight -> {res.status_code}")
                if res.status_code == 200:
                    data = res.json()
                    state["bookingId"] = data.get("oneWayBookingId") or data.get("departBookingId")

        elif name == "ViewBookings":
            res = session.get(f"{BASE_URL}/rest/api/bookings/byuser/uid0@email.com", timeout=15)
            print(f"ViewBookings -> {res.status_code}")

        elif name == "CancelBooking":
            if "bookingId" in state and state["bookingId"]:
                res = session.post(f"{BASE_URL}/rest/api/bookings/cancelbooking", data={
                    "number": state["bookingId"],
                    "userid": "uid0@email.com"
                }, timeout=15)
                print(f"CancelBooking -> {res.status_code}")

        elif name == "Logout":
            res = session.get(f"{BASE_URL}/rest/api/login/logout", params={"login": "uid0@email.com"}, timeout=15)
            print(f"Logout -> {res.status_code}")
    except Exception as e:
        print(f"Exception during {name}: {e}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for Acme Air")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
