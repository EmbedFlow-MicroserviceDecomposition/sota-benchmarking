"""Acme Air functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Drives every REST endpoint of the monolith as its web pages do: the database loader, the configuration/count endpoints,
sign-in/out (good and bad credentials, the session-cookie guard), the customer profile (view, update, wrong password,
someone else's profile), flight search (round trip, one way, browse, routes with no flights), booking (one way and round
trip), bookings by user and by number, and cancellation. The app starts with an empty MongoDB, so LoadDB runs first.

Out of reach of any request, so not covered: the `wxs` data service (WebSphere eXtreme Scale; its proprietary objectgrid
dependency is not published, and the server is configured for `morphia`) and `acmeair-reporter` (a command-line JMeter log
parser, not part of the web app).
"""

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed  # noqa: E402

suite = Suite("AcmeAir", os.environ.get("ACMEAIR_BASE_URL", "http://localhost:9080/acmeair-webapp"),
              ready_path="/rest/info/config/runtime")
CONTAINER_NAME = "acme-air-acmeair-liberty-1"

NUM_CUSTOMERS = 20  # the loader creates uid0@email.com .. uid19@email.com, password "password"
PASSWORD = "password"
API = "/rest/api"
INFO = "/rest/info"


def user(n=0):
    return f"uid{n}@email.com"


def day(offset=0):
    """A date as the flights page's Dojo date box sends it; the loader schedules flights from today on."""
    return (datetime.date.today() + datetime.timedelta(days=offset)).strftime("%a %b %d %Y")


def login(c, n=0, password=PASSWORD):
    return c.post(f"{API}/login", {"login": user(n), "password": password}, contains="logged in")


def query(c, origin="CDG", dest="JFK", one_way=False, offset=1):
    resp = c.post(f"{API}/flights/queryflights", {"fromAirport": origin, "toAirport": dest, "fromDate": day(offset),
                                                    "returnDate": day(offset + 1), "oneWay": str(one_way).lower()})
    return resp.json()


def first_option(trip, leg=0):
    options = trip["tripFlights"][leg]["flightsOptions"]
    if not options:
        raise UsecaseFailed(f"no flights on leg {leg}")
    return options[0]


def book(c, n, one_way=True, origin="CDG", dest="JFK"):
    trip = query(c, origin, dest, one_way)
    out = first_option(trip, 0)
    form = {"userid": user(n), "toFlightId": out["_id"], "toFlightSegId": out["flightSegmentId"],
            "oneWayFlight": str(one_way).lower()}
    if not one_way:
        back = first_option(trip, 1)
        form.update(retFlightId=back["_id"], retFlightSegId=back["flightSegmentId"])
    receipt = c.post(f"{API}/bookings/bookflights", form).json()
    if not receipt.get("departBookingId") or (not one_way and not receipt.get("returnBookingId")):
        raise UsecaseFailed(f"booking returned {receipt}")
    return receipt


def bookings(c, n):
    return c.get(f"{API}/bookings/byuser/{user(n)}").json()


@suite.usecase("LoadDB")
def load_db(c):
    c.get(f"{INFO}/loader/query", contains="")
    c.get(f"{INFO}/loader/load", {"numCustomers": NUM_CUSTOMERS}, contains="Loaded", timeout=600)
    if int(c.get(f"{INFO}/config/countCustomers").text) < NUM_CUSTOMERS:
        raise UsecaseFailed("the loader did not create the customers")


@suite.usecase("ViewPages")
def view_pages(c):
    for page in ("/", "/index.html", "/flights.html", "/checkin.html", "/customerprofile.html", "/loader.html",
                 "/config.html", "/js/acmeair-common.js"):
        c.get(page)


@suite.usecase("ViewConfig")
def view_config(c):
    if "morphia" not in c.get(f"{INFO}/config/activeDataService").text:
        raise UsecaseFailed("the active data service is not morphia")
    c.get(f"{INFO}/config/dataServices", contains="morphia")
    c.get(f"{INFO}/config/runtime", contains="Java")
    for count in ("countBookings", "countCustomers", "countSessions", "countFlights", "countFlightSegments",
                  "countAirports"):
        if not c.get(f"{INFO}/config/{count}").text.strip().isdigit():
            raise UsecaseFailed(f"{count} is not a number")


@suite.usecase("Login")
def login_usecase(c):
    login(c, 0)
    c.get(f"{API}/customer/byid/{user(0)}", contains=user(0))
    if not any(k.name == "sessionid" for k in c.cookies):
        raise UsecaseFailed("signing in set no sessionid cookie")


@suite.usecase("LoginFailure")
def login_failure(c):
    c.post(f"{API}/login", {"login": user(1), "password": "wrong"}, expect=403)
    c.post(f"{API}/login", {"login": "nobody@email.com", "password": PASSWORD}, expect=403)
    c.get(f"{API}/customer/byid/{user(1)}", expect=403)  # the session filter refuses a request without a session


@suite.usecase("ViewAccount")
def view_account(c):
    login(c, 2)
    profile = c.get(f"{API}/customer/byid/{user(2)}").json()
    if profile.get("username") != user(2) or "address" not in profile:
        raise UsecaseFailed(f"profile of {user(2)} is {profile}")
    c.get(f"{API}/customer/byid/{user(3)}", expect=403)  # someone else's profile


@suite.usecase("UpdateProfile")
def update_profile(c):
    login(c, 4)
    profile = c.get(f"{API}/customer/byid/{user(4)}").json()
    profile.update(password=PASSWORD, phoneNumber="919-555-0100", phoneNumberType="MOBILE")
    profile["address"].update(streetAddress1="42 Runway Rd", city="Raleigh")
    c.request("POST", f"{API}/customer/byid/{user(4)}", json_body=profile)
    stored = c.get(f"{API}/customer/byid/{user(4)}").json()
    if stored["phoneNumber"] != "919-555-0100" or stored["address"]["city"] != "Raleigh":
        raise UsecaseFailed(f"the profile update was not stored: {stored}")
    c.request("POST", f"{API}/customer/byid/{user(4)}", json_body=dict(profile, password="wrong"), expect=403)
    c.request("POST", f"{API}/customer/byid/{user(5)}", json_body=dict(profile, username=user(5)), expect=403)


@suite.usecase("QueryFlights")
def query_flights(c):
    login(c, 6)
    round_trip = query(c, "CDG", "JFK", one_way=False)
    if round_trip["tripLegs"] != 2 or not round_trip["tripFlights"][1]["flightsOptions"]:
        raise UsecaseFailed("a round trip did not return two legs with flights")
    if query(c, "JFK", "LHR", one_way=True)["tripLegs"] != 1:
        raise UsecaseFailed("a one-way query did not return one leg")
    for origin, dest in (("SIN", "HKG"), ("FRA", "AMS"), ("BOM", "DEL")):
        query(c, origin, dest, one_way=False, offset=2)
    empty = query(c, "JFK", "XXX", one_way=True)
    if empty["tripFlights"][0]["flightsOptions"]:
        raise UsecaseFailed("a route to an unknown airport returned flights")


@suite.usecase("BrowseFlights")
def browse_flights(c):
    login(c, 7)
    for origin, dest, one_way in (("CDG", "JFK", "false"), ("LHR", "JFK", "true"), ("JFK", "XXX", "true")):
        c.post(f"{API}/flights/browseflights", {"fromAirport": origin, "toAirport": dest, "oneWay": one_way})


@suite.usecase("BookFlight")
def book_flight(c):
    login(c, 8)
    before = len(bookings(c, 8))
    book(c, 8, one_way=True)
    book(c, 8, one_way=False, origin="LHR", dest="JFK")
    if len(bookings(c, 8)) != before + 3:
        raise UsecaseFailed("a one-way and a round trip did not add three bookings")


@suite.usecase("ViewBookings")
def view_bookings(c):
    login(c, 9)
    receipt = book(c, 9, one_way=True)
    listed = bookings(c, 9)
    if not any(b["bookingId"] == receipt["departBookingId"] for b in listed):
        raise UsecaseFailed("the new booking is not listed")
    one = c.get(f"{API}/bookings/bybookingnumber/{user(9)}/{receipt['departBookingId']}").json()
    if one.get("bookingId") != receipt["departBookingId"]:
        raise UsecaseFailed(f"booking by number returned {one}")
    c.get(f"{INFO}/config/countBookings")


@suite.usecase("CancelBooking")
def cancel_booking(c):
    login(c, 10)
    receipt = book(c, 10, one_way=False, origin="CDG", dest="JFK")
    for number in (receipt["departBookingId"], receipt["returnBookingId"]):
        c.post(f"{API}/bookings/cancelbooking", {"number": number, "userid": user(10)})
    remaining = {b["bookingId"] for b in bookings(c, 10)}
    if receipt["departBookingId"] in remaining or receipt["returnBookingId"] in remaining:
        raise UsecaseFailed("cancelled bookings are still listed")


@suite.usecase("Logout")
def logout(c):
    login(c, 11)
    c.get(f"{API}/customer/byid/{user(11)}")
    c.get(f"{API}/login/logout", {"login": user(11)}, contains="logged out")
    c.get(f"{API}/customer/byid/{user(11)}", expect=403)  # the session is gone


@suite.usecase("FullTrip")
def full_trip(c):
    """A whole visit as the web pages make it: sign in, profile, search, book a round trip, check in, cancel, sign out."""
    login(c, 12)
    c.get(f"{API}/customer/byid/{user(12)}")
    receipt = book(c, 12, one_way=False, origin="SIN", dest="HKG")
    bookings(c, 12)
    c.post(f"{API}/bookings/cancelbooking", {"number": receipt["returnBookingId"], "userid": user(12)})
    c.get(f"{API}/login/logout", {"login": user(12)})
    if json.loads(c.get(f"{INFO}/config/countSessions").text) < 0:
        raise UsecaseFailed("negative session count")


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
