"""Pharmacy (Upachar) functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Drives every endpoint of the online-pharmacy back end: users (sign-up with its validation errors, admin sign-up, validate,
page, view, update, delete), OAuth2 tokens (password with the phone number as username, refresh-token and client-credentials
grants, bad credentials), dosage forms, categories and sub-categories (multipart JSON + image), drugs (add with an image,
every listing, search, update with and without an image, delete), orders (with and without prescriptions, status changes,
re-order, delete) and the CSV bulk load.

Notes: the resource server permits every request, so no use case needs a token; `@RequestPart` DTOs are sent as
`application/json` parts; image folders under /opt/pharmacy/images/ are created by the compose command.
"""

import base64
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, unique  # noqa: E402

suite = Suite("Pharmacy", os.environ.get("PHARMACY_BASE_URL", "http://localhost:8080/pharmacy"), ready_path="/categories")
CONTAINER_NAME = "pharmacy-app"

CLIENT = "Basic " + base64.b64encode(b"upachar-pharmacy:upachar123").decode()  # AuthorizationServerConfiguration
PASSWORD = "Pa55word!"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
# a CSV row per DrugDetailsDto: position 0 and 9 are unused
CSV_ROW = '1,{brand},{generic},{rx},{form},Acme Pharma,12.5,"Take one daily rnWith water",{sub},x,10\n'


def phone():
    return str(random.randrange(10 ** 9, 10 ** 10))


def part(dto):
    """A multipart JSON part for a @RequestPart DTO."""
    return ("dto.json", json.dumps(dto).encode(), "application/json")


def signup(c, **overrides):
    body = dict({"firstName": "Sita", "lastName": "Rai", "email": f"{unique('user')}@example.com", "password": PASSWORD,
                 "phone": phone(), "address": "Kathmandu"}, **overrides)
    user = c.request("POST", "/users/signup", json_body=body).json()
    if user.get("phone") != body["phone"] or "password" in user:
        raise UsecaseFailed(f"sign-up returned {user}")
    return user


def add_category(c, name=None):
    name = name or unique("category")
    category = c.request("POST", "/categories", data=None, files={"categoryDto": part({"name": name}),
                                                                  "image": ("c.png", PNG, "image/png")}).json()
    if not category.get("id"):
        raise UsecaseFailed(f"adding a category returned {category}")
    return category


def add_sub_category(c, category_id, name=None):
    sub = c.request("POST", f"/categories/{category_id}/subcategories", json_body={"name": name or unique("sub")}).json()
    if not sub.get("id"):
        raise UsecaseFailed(f"adding a sub-category returned {sub}")
    return sub


def dosage_form(c, form="Tablet"):
    for existing in c.get("/dosage-forms").json():
        if existing["form"] == form:
            return existing
    return c.request("POST", "/dosage-forms", json_body={"form": form}).json()


def add_drug(c, sub_id=None, form_id=None, **overrides):
    dto = dict({"productId": random.randrange(1, 10 ** 6), "brandName": unique("Brand"), "genericName": unique("generic"),
                "manufacturer": "Acme Pharma", "details": "Take one a day", "inStock": True, "price": 25.5, "packSize": 10,
                "prescriptionRequired": False, "trending": False, "specialOffer": False,
                "subCategoryId": sub_id or add_sub_category(c, add_category(c)["id"])["id"],
                "dosageFormId": form_id or dosage_form(c)["id"]}, **overrides)
    drug = c.request("POST", "/drugs", files={"drugDto": part(dto), "image": ("d.png", PNG, "image/png")}).json()
    if not drug.get("id"):
        raise UsecaseFailed(f"adding a drug returned {drug}")
    return drug


def add_order(c, user, drugs, prescriptions=(), **checks):
    dto = {"drugQuantities": {str(d["id"]): 2 for d in drugs}, "totalPrice": 51.0, "userId": user["id"]}
    files = {"orderDto": part(dto)}
    if prescriptions:
        files["prescriptions"] = [(name, PNG, "image/png") for name in prescriptions]
    resp = c.request("POST", "/orders", files=files, **checks)
    return resp.json() if resp.status == 200 else resp


@suite.usecase("SystemAndDocs")
def system_and_docs(c):
    c.get("/v2/api-docs", contains="swagger")
    c.get("/swagger-resources")
    c.get("/swagger-ui.html", expect=(200, 404))


@suite.usecase("Signup")
def signup_user(c):
    user = signup(c)
    c.request("POST", "/users/signup", json_body={"email": user["email"], "password": PASSWORD, "phone": phone()},
              expect=400, contains="Email already registered")
    c.request("POST", "/users/signup", json_body={"email": "new@example.com", "password": PASSWORD, "phone": user["phone"]},
              expect=400, contains="Phone number already registered")
    c.request("POST", "/users/signup", json_body={"email": "not-an-email", "password": PASSWORD, "phone": phone()},
              expect=400, contains="Email format incorrect")
    c.request("POST", "/users/signup", json_body={"email": "short@example.com", "password": PASSWORD, "phone": "123"},
              expect=400, contains="Validation failed")
    admin = c.request("POST", "/users/admin/signup", json_body={"firstName": "Root", "lastName": "Admin", "password": PASSWORD,
                                                                 "phone": phone(), "email": f"{unique('admin')}@example.com"}).json()
    if admin["roles"][0]["role"] != "ADMIN":
        raise UsecaseFailed(f"admin sign-up returned {admin}")


@suite.usecase("ValidateUser")
def validate_user(c):
    user = signup(c)
    c.request("POST", "/users/validate", json_body={"email": "free@example.com", "phone": phone()}, contains="true")
    c.request("POST", "/users/validate", json_body={"email": user["email"], "phone": phone()}, expect=400)
    c.request("POST", "/users/validate", json_body={"email": "free@example.com", "phone": user["phone"]}, expect=400)
    c.request("POST", "/users/validate", json_body={"email": "bad", "phone": phone()}, expect=400)
    c.request("POST", "/users/validate", json_body={"email": "free@example.com", "phone": "12"}, expect=400)


@suite.usecase("Authenticate")
def authenticate(c):
    user = signup(c)
    login = {"grant_type": "password", "username": user["phone"], "password": PASSWORD, "scope": "all"}
    tokens = c.post("/oauth/token", login, headers={"Authorization": CLIENT}, contains="access_token").json()
    if tokens.get("userId") != user["id"]:
        raise UsecaseFailed(f"the token does not carry the user id: {tokens}")
    c.post("/oauth/token", {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
           headers={"Authorization": CLIENT}, contains="access_token")
    # The token enhancer casts the principal to a User, which a client-credentials grant does not have: HTTP 500.
    c.post("/oauth/token", {"grant_type": "client_credentials", "scope": "all"}, headers={"Authorization": CLIENT},
           expect=(200, 500))
    c.post("/oauth/token", dict(login, password="wrong"), headers={"Authorization": CLIENT}, expect=400)
    c.post("/oauth/token", dict(login, username="0000000000"), headers={"Authorization": CLIENT}, expect=(400, 401))
    c.post("/oauth/token", login, headers={"Authorization": "Basic " + base64.b64encode(b"upachar-pharmacy:wrong").decode()},
           expect=401)


@suite.usecase("UsersCrud")
def users_crud(c):
    user = signup(c)
    other = signup(c)
    if c.get(f"/users/{user['id']}").json()["phone"] != user["phone"]:
        raise UsecaseFailed("user by id returned another user")
    c.get("/users/999999", expect=400, contains="User not found")
    page = c.get("/users", params={"page": 0, "size": 5}).json()
    if not page["content"] or page["pageElementCount"] < 1:
        raise UsecaseFailed(f"user page is empty: {page}")
    new_phone = phone()
    updated = c.request("PUT", f"/users/{user['id']}", json_body={"firstName": "Gita", "lastName": "Rai", "address": "Pokhara",
                                                                   "email": user["email"], "phone": new_phone}).json()
    if updated["firstName"] != "Gita" or updated["phone"] != new_phone:
        raise UsecaseFailed(f"update was not stored: {updated}")
    c.request("PUT", f"/users/{user['id']}", json_body={"email": other["email"], "phone": new_phone}, expect=400)
    c.request("PUT", f"/users/{user['id']}", json_body={"email": user["email"], "phone": other["phone"]}, expect=400)
    c.request("PUT", f"/users/{user['id']}", json_body={"email": "bad", "phone": new_phone}, expect=400)
    c.request("PUT", f"/users/{user['id']}", json_body={"email": "", "phone": new_phone})  # clears the email
    c.request("PUT", "/users/999999", json_body={"email": "x@example.com", "phone": phone()}, expect=400)
    c.request("DELETE", f"/users/{other['id']}")
    c.get(f"/users/{other['id']}", expect=400)


@suite.usecase("DosageForms")
def dosage_forms(c):
    form = unique("Form")
    created = c.request("POST", "/dosage-forms", json_body={"form": form}, contains=form).json()
    c.request("POST", "/dosage-forms", json_body={"form": form}, expect=400, contains="already exists")
    c.request("POST", "/dosage-forms", json_body={}, expect=400, contains="Validation failed")
    if created["id"] not in [f["id"] for f in c.get("/dosage-forms").json()]:
        raise UsecaseFailed("the new dosage form is not listed")


@suite.usecase("Categories")
def categories(c):
    category = add_category(c)
    c.request("POST", "/categories", files={"categoryDto": part({"name": category["name"]}), "image": ("c.png", PNG, "image/png")},
              expect=400, contains="already exists")
    c.request("POST", "/categories", files={"categoryDto": part({"name": unique("noimage")})}, expect=400)
    if category["id"] not in [x["id"] for x in c.get("/categories").json()]:
        raise UsecaseFailed("the new category is not listed")
    renamed = c.request("PUT", f"/categories/{category['id']}", files={"categoryDto": part({"name": unique("renamed")})}).json()
    if renamed["name"] == category["name"]:
        raise UsecaseFailed("the rename was not stored")
    c.request("PUT", f"/categories/{category['id']}", files={"categoryDto": part({"name": unique("again")}),
                                                              "image": ("c2.png", PNG, "image/png")})
    c.request("PUT", "/categories/999999", files={"categoryDto": part({"name": "x"})}, expect=400, contains="Category not found")
    sub = add_sub_category(c, category["id"])
    add_drug(c, sub_id=sub["id"])
    c.request("DELETE", f"/categories/{category['id']}")  # also removes its sub-categories and their drugs
    c.request("DELETE", f"/categories/{category['id']}", expect=400)


@suite.usecase("SubCategories")
def sub_categories(c):
    category = add_category(c)
    sub = add_sub_category(c, category["id"])
    add_sub_category(c, category["id"])
    c.request("POST", "/categories/999999/subcategories", json_body={"name": "x"}, expect=400, contains="Category not found")
    if len(c.get(f"/categories/{category['id']}/subcategories").json()) != 2:
        raise UsecaseFailed("the category does not list its two sub-categories")
    renamed = c.request("PUT", f"/categories/{category['id']}/subcategories/{sub['id']}", json_body={"name": "Renamed"}).json()
    if renamed["name"] != "Renamed":
        raise UsecaseFailed("the sub-category rename was not stored")
    c.request("PUT", f"/categories/{category['id']}/subcategories/999999", json_body={"name": "x"}, expect=400)
    c.request("DELETE", f"/categories/{category['id']}/subcategories/{sub['id']}")


@suite.usecase("Drugs")
def drugs(c):
    sub = add_sub_category(c, add_category(c)["id"])
    form = dosage_form(c)
    drug = add_drug(c, sub["id"], form["id"], brandName="Zorbex", genericName="zorbexin", trending=True, specialOffer=True)
    add_drug(c, sub["id"], form["id"], price=0.0)  # a free drug is only on the raw listing
    c.request("POST", "/drugs", files={"drugDto": part({"brandName": "X", "subCategoryId": 999999}),
                                       "image": ("d.png", PNG, "image/png")}, expect=400, contains="Subcategory not found")
    c.request("POST", "/drugs", files={"drugDto": part({"brandName": "X", "subCategoryId": sub["id"], "dosageFormId": 999999}),
                                       "image": ("d.png", PNG, "image/png")}, expect=400, contains="Dosage form does not exist")
    c.request("POST", "/drugs", files={"drugDto": part({"brandName": "X", "subCategoryId": sub["id"]})}, expect=400)
    if c.get(f"/drugs/{drug['id']}").json()["brandName"] != "Zorbex":
        raise UsecaseFailed("drug by id returned another drug")
    c.get("/drugs/999999", expect=400, contains="Drug not found")
    paged = c.get("/drugs", params={"page": 0, "size": 50}).json()
    raw = c.get("/drugs/raw", params={"page": 0, "size": 50}).json()
    if raw["totalElements"] <= paged["totalElements"]:
        raise UsecaseFailed("the raw listing should also hold the free drug")
    c.get("/drugs", params={"page": 0}, expect=400)
    if drug["id"] not in [d["id"] for d in c.get(f"/drugs/sub-categories/{sub['id']}").json()]:
        raise UsecaseFailed("the sub-category does not list its drug")
    c.get("/drugs/names", contains="zorbexin")
    c.get("/drugs/special-offer", contains="Zorbex")
    c.get("/drugs/trending", contains="Zorbex")
    c.get("/drugs/latest", contains="Zorbex")
    c.get("/drugs/search", params={"search": "orbe"}, contains="Zorbex")
    c.get("/drugs/search", params={"search": "no-such-drug-anywhere"}, contains="[]")
    c.get("/drugs/search", expect=400)
    c.request("PUT", f"/drugs/{drug['id']}", files={"drugDto": part({"price": 30.0, "trending": False, "inStock": False})})
    c.request("PUT", f"/drugs/{drug['id']}", files={"drugDto": part({"details": "New leaflet", "dosageFormId": form["id"],
                                                                      "subCategoryId": sub["id"]}),
                                                     "image": ("d2.png", PNG, "image/png")})
    c.request("PUT", "/drugs/999999", files={"drugDto": part({"price": 1.0})}, expect=400)
    c.request("PUT", f"/drugs/{drug['id']}", files={"drugDto": part({"subCategoryId": 999999})}, expect=400)
    c.request("PUT", f"/drugs/{drug['id']}", files={"drugDto": part({"dosageFormId": 999999})}, expect=400)
    c.request("DELETE", f"/drugs/{drug['id']}")
    c.request("DELETE", f"/drugs/{drug['id']}", expect=400)


@suite.usecase("Orders")
def orders(c):
    user = signup(c)
    plain, rx = add_drug(c), None
    rx = add_drug(c, prescriptionRequired=True)
    order = add_order(c, user, [plain])
    if order["orderStatus"] != "PENDING" or order["deliveryPhone"] != user["phone"]:
        raise UsecaseFailed(f"new order looks wrong: {order}")
    add_order(c, user, [rx], expect=400, contains="requires a prescription")
    with_rx = add_order(c, user, [plain, rx], prescriptions=("rx.png", "rx2.png"))
    if len(with_rx["orderPrescriptions"]) != 2:
        raise UsecaseFailed(f"the order lost its prescriptions: {with_rx}")
    c.request("POST", "/orders", files={"orderDto": part({"drugQuantities": {"999999": 1}, "userId": user["id"]})},
              expect=400, contains="Drug not found")
    c.request("POST", "/orders", files={"orderDto": part({"drugQuantities": {str(plain["id"]): 1}, "userId": 999999})},
              expect=400, contains="User not found")
    only_rx = c.request("POST", "/orders/prescriptions", files={"orderDto": part({"totalPrice": 0.0, "userId": user["id"]}),
                                                                 "prescriptions": ("p.png", PNG, "image/png")}).json()
    c.request("POST", "/orders/prescriptions", files={"orderDto": part({"userId": 999999}),
                                                       "prescriptions": ("p.png", PNG, "image/png")}, expect=400)
    if c.get(f"/orders/{order['id']}").json()["id"] != order["id"]:
        raise UsecaseFailed("order by id returned another order")
    c.get("/orders/999999", expect=400, contains="Order not found")
    if len(c.get(f"/orders/users/{user['id']}").json()) != 3:
        raise UsecaseFailed("the user does not list their three orders")
    if c.get("/orders", params={"page": 0, "size": 50}).json()["totalElements"] < 3:
        raise UsecaseFailed("the order page is missing orders")
    edited = c.request("PUT", f"/orders/{order['id']}", json_body={"deliveryAddress": "Lalitpur", "deliveryPhone": "9800000000"}).json()
    if edited["deliveryAddress"] != "Lalitpur":
        raise UsecaseFailed("the delivery address was not stored")
    c.request("PUT", "/orders/999999", json_body={"deliveryAddress": "x"}, expect=400)
    for status in ("PROCESSED", "DELIVERED", "PENDING"):
        if c.request("PATCH", f"/orders/{order['id']}/status", json_body={"orderStatus": status}).json()["orderStatus"] != status:
            raise UsecaseFailed(f"status {status} was not stored")
    c.request("PATCH", "/orders/999999/status", json_body={"orderStatus": "PROCESSED"}, expect=400)
    c.request("PATCH", f"/orders/{order['id']}/status", json_body={"orderStatus": "SHIPPED"}, expect=400)
    again = c.request("POST", f"/orders/{with_rx['id']}/reorder", json_body={"userId": user["id"]}).json()
    if again["id"] == with_rx["id"] or len(again["drugQuantities"]) != 2:
        raise UsecaseFailed(f"the re-order looks wrong: {again}")
    c.request("POST", "/orders/999999/reorder", json_body={"userId": user["id"]}, expect=400)
    c.request("DELETE", f"/orders/{only_rx['id']}")
    c.request("DELETE", f"/drugs/{plain['id']}")  # deletes the orders holding it
    c.request("DELETE", f"/users/{user['id']}")   # and then the user's remaining orders


@suite.usecase("LoadData")
def load_data(c):
    sub = unique("Sub")
    rows = (CSV_ROW.format(brand=unique("Csv"), generic="gx", rx="yes", form="Tablet 10mg", sub=sub)
            + CSV_ROW.format(brand=unique("Csv"), generic="gy", rx="no", form="Syrup", sub=sub)
            + CSV_ROW.format(brand="", generic="gz", rx="no", form="Syrup", sub=sub))  # no brand name: skipped
    for form in ("Tablet", "Syrup"):
        dosage_form(c, form)
    c.request("POST", "/data", files={"file": ("drugs.csv", rows.encode(), "text/csv")}, contains="Successfully loaded")
    c.get("/drugs/raw", params={"page": 0, "size": 5}, contains="Csv")
    bad = CSV_ROW.format(brand=unique("Csv"), generic="gx", rx="no", form="Powder", sub=sub)
    c.request("POST", "/data", files={"file": ("bad.csv", bad.encode(), "text/csv")}, expect=500, contains="not found")


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
