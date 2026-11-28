"""AutoCare Nepal functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Drives every endpoint of the used-vehicle marketplace back end: sign-up (incl. a duplicate username), OAuth2 tokens
(password, client-credentials and refresh-token grants, bad credentials), users (add, view, update, the SUPER_ADMIN-only
list and delete, the 401/403 guards), vehicles (add, page, update, search with every filter, delete, upload and delete an
image through S3, someone else's vehicle), comments (add, page per vehicle, update, delete, someone else's comment), the
system test endpoint and the Swagger docs.

Notes: sign-up copies `roles` from the request, so the suite signs up its own SUPER_ADMIN (a security hole of the app, kept
as is); `/system/exit` calls System.exit and is never requested; S3 is MinIO in the compose file.
"""

import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, unique  # noqa: E402

suite = Suite("AutoCare", os.environ.get("AUTOCARE_BASE_URL", "http://localhost:8080"), ready_path="/system/test")
CONTAINER_NAME = "autocare-app"

CLIENT = "Basic " + base64.b64encode(b"autocare:SR2wFdy$By&aj_?s").decode()  # AuthorizationServerConfiguration
PASSWORD = "Pa55word!"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def signup(c, roles=("USER",), password=PASSWORD):
    username = unique("user")
    user = c.request("POST", "/users/signup", json_body={
        "firstname": "Ram", "lastname": "Thapa", "username": username, "password": password, "roles": list(roles),
        "address": "Kathmandu", "email": f"{username}@example.com", "active": True,
        "organization": {"name": "AutoCare", "description": "Dealers"}}).json()
    if user.get("username") != username or user.get("password") == password:
        raise UsecaseFailed(f"sign-up returned {user}")
    return user


def token(c, username, password=PASSWORD, **checks):
    resp = c.post("/oauth/token", {"grant_type": "password", "username": username, "password": password,
                                    "scope": "all"}, headers={"Authorization": CLIENT}, **checks)
    return resp.json() if resp.status == 200 else resp


class Session:
    """A signed-in user: their record and Bearer-authenticated JSON calls."""

    def __init__(self, c, roles=("USER",)):
        self.c = c
        self.user = signup(c, roles)
        self.tokens = token(c, self.user["username"])
        self.auth = {"Authorization": f"Bearer {self.tokens['access_token']}"}

    def call(self, method, path, body=None, params=None, **checks):
        return self.c.request(method, path, params=params, json_body=body, headers=self.auth, **checks)


VEHICLE = {"brand": "Honda", "model": "Shine", "twoWheeler": True, "newVehicle": False, "distanceDriven": 12000.0,
           "price": 150000.0, "sold": False, "images": [], "description": "Well kept", "usedMonths": 18.0,
           "priceNegotiable": True, "mileage": 55.0, "tags": ["bike", "commuter"]}


def add_vehicle(s, **overrides):
    vehicle = s.call("POST", "/vehicles", dict(VEHICLE, **overrides)).json()
    if not vehicle.get("id"):
        raise UsecaseFailed(f"adding a vehicle returned {vehicle}")
    return vehicle


def page_items(resp):
    body = resp.json()
    items = next((v for v in body.values() if isinstance(v, list)), None)
    if items is None:
        raise UsecaseFailed(f"no list in paged response {body}")
    return items


@suite.usecase("SystemAndDocs")
def system_and_docs(c):
    c.get("/system/test", contains="System is up")
    c.get("/v2/api-docs", contains="swagger")
    c.get("/swagger-resources")
    c.get("/swagger-ui.html", expect=(200, 404))


@suite.usecase("CreateUser")
def create_user(c):
    user = signup(c)
    c.request("POST", "/users/signup", json_body={"username": user["username"], "password": "x", "roles": ["USER"]},
              expect=400)  # username already taken
    s = Session(c)
    added = s.call("POST", "/users", {"firstname": "Sita", "lastname": "Rai", "username": unique("staff"),
                                      "password": PASSWORD, "roles": ["USER"], "email": "sita@example.com"}).json()
    if not added.get("id"):
        raise UsecaseFailed(f"adding a user returned {added}")


@suite.usecase("Authenticate")
def authenticate(c):
    user = signup(c)
    tokens = token(c, user["username"])
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise UsecaseFailed(f"the password grant returned {tokens}")
    c.post("/oauth/token", {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
           headers={"Authorization": CLIENT}, contains="access_token")
    # The app's token enhancer casts the principal to a User, which a client-credentials grant does not have: HTTP 500.
    c.post("/oauth/token", {"grant_type": "client_credentials", "scope": "all"}, headers={"Authorization": CLIENT},
           expect=(200, 500))
    token(c, user["username"], "wrong", expect=400)
    token(c, "nobody", expect=(400, 401))
    c.post("/oauth/token", {"grant_type": "password", "username": user["username"], "password": PASSWORD},
           headers={"Authorization": "Basic " + base64.b64encode(b"autocare:wrong").decode()}, expect=401)


@suite.usecase("GetUser")
def get_user(c):
    s = Session(c)
    me = s.call("GET", f"/users/{s.user['id']}").json()
    if me["username"] != s.user["username"]:
        raise UsecaseFailed("user by id returned another user")
    s.call("GET", "/users/no-such-user", expect=(400, 404))
    c.get(f"/users/{s.user['id']}", expect=401)  # no token


@suite.usecase("UpdateUser")
def update_user(c):
    s = Session(c)
    updated = s.call("PUT", f"/users/{s.user['id']}", {"address": "Pokhara", "username": s.user["username"]}).json()
    if updated.get("address") != "Pokhara":
        raise UsecaseFailed("the user update was not stored")
    other = signup(c)
    s.call("PUT", f"/users/{s.user['id']}", {"username": other["username"]}, expect=400)  # taken by someone else


@suite.usecase("AdminUsers")
def admin_users(c):
    admin = Session(c, roles=("SUPER_ADMIN",))
    victim = signup(c)
    if not any(u["id"] == victim["id"] for u in admin.call("GET", "/users").json()):
        raise UsecaseFailed("a new user is not in the admin's user list")
    admin.call("DELETE", f"/users/{victim['id']}")
    admin.call("DELETE", "/users/no-such-user", expect=(400, 404))
    normal = Session(c)
    normal.call("GET", "/users", expect=403)
    normal.call("DELETE", f"/users/{admin.user['id']}", expect=403)


@suite.usecase("CreateVehicle")
def create_vehicle(c):
    s = Session(c)
    add_vehicle(s)
    add_vehicle(s, brand="Toyota", model="Corolla", twoWheeler=False, newVehicle=True, price=3500000.0, tags=["car"])


@suite.usecase("GetVehicles")
def get_vehicles(c):
    s = Session(c)
    for i in range(3):
        add_vehicle(s, model=f"Model {i}")
    if len(page_items(s.call("GET", "/vehicles", params={"page": 0, "size": 2}))) != 2:
        raise UsecaseFailed("a page of size 2 did not hold 2 vehicles")
    s.call("GET", "/vehicles", params={"page": 1, "size": 2})
    s.call("GET", "/vehicles", params={"page": 0}, expect=400)  # size is required


@suite.usecase("UpdateVehicle")
def update_vehicle(c):
    s = Session(c)
    vehicle = add_vehicle(s)
    if s.call("PUT", f"/vehicles/{vehicle['id']}", {"price": 140000.0, "sold": True}).json()["price"] != 140000.0:
        raise UsecaseFailed("the vehicle update was not stored")
    Session(c).call("PUT", f"/vehicles/{vehicle['id']}", {"price": 1.0}, expect=400)  # not the owner
    s.call("PUT", "/vehicles/no-such-vehicle", {"price": 1.0}, expect=(400, 404))


@suite.usecase("SearchVehicles")
def search_vehicles(c):
    s = Session(c)
    add_vehicle(s, brand="Yamaha", price=200000.0, location=[85.3, 27.7])
    add_vehicle(s, brand="Bajaj", price=120000.0, newVehicle=True)
    # SearchVehiclesDto: conditions are "New"/"Used"; locationDetails.location is [longitude, latitude], distance in km
    for search in ({}, {"brands": ["Yamaha", "Bajaj"]}, {"minPrice": 100000.0, "maxPrice": 250000.0},
                   {"minPrice": 150000.0}, {"maxPrice": 150000.0}, {"condition": ["New"]}, {"condition": ["Used"]},
                   {"condition": ["New", "Used"]}, {"locationDetails": {"location": [85.3, 27.7], "distance": 10.0}},
                   {"brands": ["Yamaha"], "minPrice": 150000.0, "condition": ["Used"]}):
        s.call("POST", "/vehicles/search", search, params={"page": 0, "size": 10})


@suite.usecase("VehicleImages")
def vehicle_images(c):
    s = Session(c)
    vehicle = add_vehicle(s)
    image = c.request("POST", f"/vehicles/{vehicle['id']}/images", files={"image": ("bike.png", PNG, "image/png")},
                      headers=s.auth).json()
    if not image.get("imageId") or "autocare" not in image.get("url", ""):
        raise UsecaseFailed(f"the image upload returned {image}")
    s.call("DELETE", f"/vehicles/{vehicle['id']}/images/{image['imageId']}")
    s.call("DELETE", f"/vehicles/{vehicle['id']}/images/no-such-image", expect=(200, 400, 404))


@suite.usecase("DeleteVehicle")
def delete_vehicle(c):
    s = Session(c)
    vehicle = add_vehicle(s)
    Session(c).call("DELETE", f"/vehicles/{vehicle['id']}", expect=400)  # not the owner
    s.call("DELETE", f"/vehicles/{vehicle['id']}", contains="true")
    s.call("DELETE", f"/vehicles/{vehicle['id']}", expect=(400, 404))  # already gone


@suite.usecase("CreateComment")
def create_comment(c):
    s = Session(c)
    vehicle = add_vehicle(s)
    comment = s.call("POST", "/comments", {"vehicleId": vehicle["id"], "body": "Is it still available?"}).json()
    if not comment.get("id"):
        raise UsecaseFailed(f"adding a comment returned {comment}")


@suite.usecase("GetComments")
def get_comments(c):
    s = Session(c)
    vehicle = add_vehicle(s)
    for i in range(3):
        s.call("POST", "/comments", {"vehicleId": vehicle["id"], "body": f"Question {i}"})
    if len(page_items(s.call("GET", "/comments", params={"vehicleId": vehicle["id"], "page": 0, "size": 10}))) != 3:
        raise UsecaseFailed("the vehicle does not list its three comments")


@suite.usecase("UpdateAndDeleteComment")
def update_and_delete_comment(c):
    s = Session(c)
    vehicle = add_vehicle(s)
    comment = s.call("POST", "/comments", {"vehicleId": vehicle["id"], "body": "First"}).json()
    if s.call("PUT", f"/comments/{comment['id']}", {"vehicleId": vehicle["id"], "body": "Edited"}).json()["body"] != "Edited":
        raise UsecaseFailed("the comment update was not stored")
    other = Session(c)
    other.call("PUT", f"/comments/{comment['id']}", {"vehicleId": vehicle["id"], "body": "Hijack"}, expect=400)
    other.call("DELETE", f"/comments/{comment['id']}", expect=400)
    s.call("DELETE", f"/comments/{comment['id']}", contains="true")


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
