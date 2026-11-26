"""Plants by WebSphere functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Drives the JSF storefront the way a browser does (MyFaces command links and f:ajax links via workload.jsf_click):
browsing the home specials and all four categories, every product page and image, the cart (add, AJAX recalculate,
remove by quantity 0), registration (valid and each validation failure), sign-in (good and bad), account update,
checkout (shipping same as billing or elsewhere, card validation, continue shopping from review), help and database
reset; the BASIC-auth admin pages (back orders, supplier configuration, populate); and the legacy AccountServlet.
Known issues of the pinned app, kept as they are and expected by the suite: back orders are never seeded (Util.readTokens
NPE), so the back-order actions run on an empty list; account update is a 500 (CustomerMgr.updateUser asks JPA for an
optimistic lock on an entity without a version column); AccountServlet and the admin populate forward to JSPs the app does
not ship (404/500); the mail resource is missing, so the order confirmation e-mail fails after the order is stored; the
database reset fails part-way once orders exist, so the two reset use cases run last.
"""

import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, forms, jsf_click, jsf_links, jsf_post, unique  # noqa: E402

suite = Suite("PlantsByWebSphere", os.environ.get("PLANTS_BASE_URL", "http://localhost:9080/PlantsByWebSphere"),
              ready_path="/promo.jsf")
CONTAINER_NAME = "plants-app"

CATEGORIES = {"0": "Flowers", "1": "Fruits", "2": "Trees", "3": "Accessories"}
ADMIN = {"Authorization": "Basic " + base64.b64encode(b"dev:dev").decode()}  # SampAdmin, see liberty/sota-overrides.xml
PASSWORD = "plants123"  # 6-10 characters

ACCOUNT = dict(fname="Ada", lname="Lovelace", addr1="1 Garden Way", addr2="Unit 2", city="Austin", state="TX",
               zip="78701", phone="555-123-4567")
SHIPPING = dict(sname="Grace Hopper", saddr1="2 Harbour St", saddr2="", scity="Arlington", sstate="VA", szip="22201",
                sphone="555-765-4321")
CARD = dict(ccardnum="4111 1111 1111 1111", ccholdername="Ada Lovelace", ccardname="VISA", ccardexpmonth="12",
            ccardexpyear="2029")


def home(c):
    return c.get("/promo.jsf", contains="Specials")


def item_ids(page):
    return sorted({p["itemID"] for _, _, p, _, _ in jsf_links(page) if "itemID" in p})


def category(c, page, cat):
    return jsf_click(c, page, form="bannerform", params={"category": cat}, contains=CATEGORIES[cat])


def add_to_cart(c, page, item_id, quantity=1):
    """From any page listing `item_id`: open the product, add `quantity`; returns the cart page."""
    product = jsf_click(c, page, params={"itemID": item_id}, contains="Add to Cart")
    return jsf_click(c, product, form="product", text="Add to Cart", fields={"quantity": str(quantity)},
                     contains="Shopping Cart")


def cart_total(page):
    return float(page.find(r"Current total is ([0-9]+(?:\.[0-9]+)?)", "cart total"))


def messages(page):
    return " ".join(re.sub(r"<[^>]+>", " ", page.text).split())


def register(c, page, email=None, expect=200, **overrides):
    """Register from any page (via LOGIN); returns (email, response)."""
    email = email or unique("user") + "@example.com"
    login = jsf_click(c, page, form="bannerform", text="LOGIN", contains="E-mail address")
    form = jsf_click(c, login, text="register for your own account", contains="Registration")
    fields = dict(ACCOUNT, email=email, password=PASSWORD, checkPassword=PASSWORD)
    fields.update(overrides)
    return email, jsf_click(c, form, form="register", text="Register", fields=fields, expect=expect)


def new_customer():
    """A registered customer in a session of its own; returns their e-mail."""
    c = suite.client()
    email, page = register(c, home(c))
    if "Specials" not in page.text:
        raise UsecaseFailed("registration did not return to the home page")
    return email


def sign_in(c, page, email, password=PASSWORD, **checks):
    login = jsf_click(c, page, form="bannerform", text="LOGIN", contains="E-mail address")
    return jsf_click(c, login, form="login", text="Sign in", fields={"email": email, "password": password}, **checks)


def checkout(c, cart, ship_elsewhere=False):
    """From the cart of a signed-in customer to the order confirmation; returns the order number."""
    info = jsf_click(c, cart, form="cart", text="Checkout Now", contains="Billing Address")
    fields = dict(CARD, **(SHIPPING if ship_elsewhere else same_as_billing(info)))
    shipping_method = next(k for k in _form_fields(info, "orderinfo") if k.startswith("orderinfo:j_id"))
    fields[shipping_method] = "Next Day Air" if ship_elsewhere else "Standard Ground"
    review = jsf_click(c, info, form="orderinfo", text="Continue", fields=fields, contains='id="checkout_final"')
    done = jsf_click(c, review, form="checkout_final", text="Checkout Now", contains=['id="orderdone"', "Thank you for making your"])
    return done.find(r"Order number\s*(?:<[^>]+>\s*)*(\d+)", "order number")


def same_as_billing(info):
    """What the "shipping same as billing" checkbox's useBill() script fills in: the server needs the fields."""
    billing = _form_fields(info, "orderinfo")
    shipping = {f"s{k}": billing[f"orderinfo:b{k}"] for k in ("addr1", "addr2", "city", "state", "zip", "phone")}
    return dict(shipping, sname=billing["orderinfo:bname"], **{"orderinfo:shipisbill": "true"})


def _form_fields(page, form_id):
    return forms(page)[form_id][1]


@suite.usecase("ViewHome")
def view_home(c):
    c.get("/index.html")
    page = home(c)
    specials = item_ids(page)
    if not specials:
        raise UsecaseFailed("home page lists no specials")
    for item in specials:
        jsf_click(c, home(c), form="promo", params={"itemID": item}, contains=["Add to Cart", item])


@suite.usecase("ViewShopping")
def view_shopping(c):
    for cat in CATEGORIES:
        page = category(c, home(c), cat)
        if not item_ids(page):
            raise UsecaseFailed(f"category {CATEGORIES[cat]} lists no items")


@suite.usecase("ViewProduct")
def view_product(c):
    for cat in CATEGORIES:
        listing = category(c, home(c), cat)
        for item in item_ids(listing):
            jsf_click(c, listing, form="shopping", params={"itemID": item}, contains=["Add to Cart", item])


@suite.usecase("ViewImage")
def view_image(c):
    listing = category(c, home(c), "2")
    for item in item_ids(listing)[:6]:
        c.get("/servlet/ImageServlet", {"action": "getimage", "inventoryID": item})
    c.get("/servlet/ImageServlet", {"action": "getimage", "inventoryID": "NO-SUCH-ITEM"}, expect=None)
    c.get("/javax.faces.resource/pbw.jpg.jsf", {"ln": "images"})


@suite.usecase("AddToCart")
def add_items_to_cart(c):
    listing = category(c, home(c), "0")
    items = item_ids(listing)
    cart = add_to_cart(c, listing, items[0], 2)
    cart = add_to_cart(c, category(c, cart, "3"), item_ids(category(c, cart, "3"))[0], 1)
    if "contains 2 items" not in cart.text:
        raise UsecaseFailed("cart does not hold the two added items")


@suite.usecase("ViewCart")
def view_cart(c):
    empty = jsf_click(c, home(c), form="bannerform", text="SHOPPING CART", contains="Shopping Cart")
    if "currently empty" not in empty.text:
        raise UsecaseFailed("a new session's cart is not empty")
    cart = add_to_cart(c, home(c), item_ids(home(c))[0])
    jsf_click(c, cart, form="cart", text="Continue Shopping")
    jsf_click(c, home(c), form="bannerform", text="SHOPPING CART", contains="contains 1 items")


@suite.usecase("RecalculateCart")
def recalculate_cart(c):
    listing = category(c, home(c), "1")
    first, second = item_ids(listing)[:2]
    add_to_cart(c, listing, first, 1)
    cart = add_to_cart(c, category(c, home(c), "1"), second, 1)
    before = cart_total(cart)
    quantity_fields = sorted(k for k in _form_fields(cart, "cart") if k.endswith(":quantity"))
    jsf_click(c, cart, form="cart", text="Recalculate", fields={quantity_fields[0]: "4"}, contains="partial-response")
    cart = jsf_click(c, home(c), form="bannerform", text="SHOPPING CART")
    if cart_total(cart) <= before:
        raise UsecaseFailed("raising a quantity did not raise the total")
    jsf_click(c, cart, form="cart", text="Recalculate", fields={quantity_fields[1]: "0"}, contains="partial-response")
    if "contains 1 items" not in jsf_click(c, home(c), form="bannerform", text="SHOPPING CART").text:
        raise UsecaseFailed("quantity 0 did not remove the item")


@suite.usecase("CheckoutRequiresLogin")
def checkout_requires_login(c):
    cart = add_to_cart(c, home(c), item_ids(home(c))[0])
    jsf_click(c, cart, form="cart", text="Checkout Now", contains="You must log in first")


@suite.usecase("RegisterValidation")
def register_validation(c):
    for overrides, message in (({"phone": "5551234"}, "Phone number does not match"),
                               ({"password": "abc", "checkPassword": "abc"}, "Password must be between 6 and 10"),
                               ({"zip": "7"}, "Zip"),
                               ({"fname": ""}, "fname")):
        _, page = register(c, home(c), **overrides)
        if "Registration" not in page.text or message.lower() not in messages(page).lower():
            raise UsecaseFailed(f"registration with {overrides} did not fail with {message!r}")


@suite.usecase("RegisterAccount")
def register_account(c):
    email, page = register(c, home(c))
    if "Specials" not in page.text:
        raise UsecaseFailed("registration did not return to the home page")
    jsf_click(c, page, text="My Account", contains=["Account Update", ACCOUNT["addr1"]])
    other = suite.client()
    register(other, home(other), email=email, expect=500)  # the duplicate key reaches the database: a 500


@suite.usecase("Login")
def login(c):
    page = sign_in(c, home(c), new_customer(), contains="Specials")
    jsf_click(c, page, text="My Account", contains="Account Update")


@suite.usecase("LoginFailure")
def login_failure(c):
    page = sign_in(c, home(c), new_customer(), "wrongpass1", contains="E-mail address")
    if "Specials" in page.text:
        raise UsecaseFailed("a wrong password signed in")
    sign_in(c, home(c), "nobody@example.com", PASSWORD, contains="E-mail address")


@suite.usecase("ViewAccount")
def view_account(c):
    _, page = register(c, home(c))
    account = jsf_click(c, page, text="My Account", contains=["Account Update", ACCOUNT["addr1"]])
    # CustomerMgr.updateUser requests an optimistic lock on an entity without a version column: always a 500
    jsf_click(c, account, form="account", text="Update", fields={"city": "Dallas", "addr1": "9 Elm St"}, expect=500)


@suite.usecase("PlaceOrder")
def place_order(c):
    _, page = register(c, home(c))
    listing = category(c, page, "2")
    add_to_cart(c, listing, item_ids(listing)[0], 2)
    cart = add_to_cart(c, category(c, home(c), "0"), item_ids(category(c, home(c), "0"))[1], 3)
    checkout(c, cart)
    if "currently empty" not in jsf_click(c, home(c), form="bannerform", text="SHOPPING CART").text:
        raise UsecaseFailed("the cart was not emptied by the order")


@suite.usecase("PlaceOrderShipElsewhere")
def place_order_ship_elsewhere(c):
    _, page = register(c, home(c))
    cart = add_to_cart(c, category(c, page, "1"), item_ids(category(c, home(c), "1"))[2], 1)
    info = jsf_click(c, cart, form="cart", text="Checkout Now", contains="Billing Address")
    bad = jsf_click(c, info, form="orderinfo", text="Continue", fields=dict(CARD, ccardnum="4111111111111111", **SHIPPING),
                    contains="Credit card numbers must be entered")
    review = jsf_click(c, bad, form="orderinfo", text="Continue", fields=dict(CARD, **SHIPPING), contains='id="checkout_final"')
    jsf_click(c, review, form="checkout_final", text="Continue Shopping")  # back to the store, order kept open
    checkout(c, jsf_click(c, home(c), form="bannerform", text="SHOPPING CART"), ship_elsewhere=True)


@suite.usecase("ViewHelp")
def view_help(c):
    page = jsf_click(c, home(c), form="bannerform", text="HELP", contains="Reset database")
    jsf_click(c, page, form="help", text="Home", fields={"help:logging1": "true"}, contains="Specials")


@suite.usecase("ViewAdmin")
def view_admin(c):
    for path in ("/admin.html", "/adminbanner.html", "/adminactions.html", "/servlet/AdminServlet"):
        c.get(path, headers=ADMIN)
    anonymous = suite.client()  # `c` now holds the admin's LTPA cookie
    for path in ("/servlet/AdminServlet", "/backorderadmin.jsp", "/supplierconfig.jsp"):
        anonymous.get(path, expect=401)  # web.xml's SampAdmin constraint (the .html admin pages are served regardless)


@suite.usecase("AdminBackOrders")
def admin_back_orders(c):
    servlet = "/servlet/AdminServlet"
    c.get(servlet, {"admintype": "backorder"}, headers=ADMIN, contains="Back Order Items")
    c.get("/backorderadmin.jsp", headers=ADMIN)
    for action, extra in (("getbackorders", {}), ("orderstock", {"selectedObjectIds": "1"}),
                          ("updatestock", {"selectedObjectIds": ["1", "2"]}), ("orderstatus", {}),
                          ("updatequantity", {"backOrderID": "1", "itemqty": "7"}),
                          ("cancel", {"selectedObjectIds": "1"})):
        c.post(servlet, dict({"admintype": "backorder", "action": action}, **extra), headers=ADMIN)


@suite.usecase("AdminSupplierConfig")
def admin_supplier_config(c):
    servlet = "/servlet/AdminServlet"
    page = c.get(servlet, {"admintype": "supplierconfig", "action": "getsupplier"}, headers=ADMIN, contains="supplierid")
    supplier_id = page.find(r'name="supplierid" value="([^"]*)"', "supplier id")
    name = unique("Garden Supply ")
    c.post(servlet, {"admintype": "supplierconfig", "action": "updatesupplier", "supplierid": supplier_id,
                     "name": name, "street": "5 Seed Rd", "city": "Fresno", "state": "CA", "zip": "93650",
                     "phone": "555-000-1111", "location_url": "http://example.com"}, headers=ADMIN)
    c.get("/supplierconfig.jsp", headers=ADMIN)
    c.get(servlet, {"admintype": "supplierconfig"}, headers=ADMIN)


@suite.usecase("AccountServlet")
def account_servlet(c):
    """The pre-JSF account servlet: its handlers run, then forward to JSPs this version does not ship."""
    servlet = "/servlet/AccountServlet"
    email = unique("svc") + "@example.com"
    c.post(servlet, {"action": "register", "userid": email, "passwd": PASSWORD, "vpasswd": PASSWORD,
                     "fname": "Alan", "lname": "Turing", "addr1": "3 Bletchley", "addr2": "", "city": "Austin",
                     "state": "TX", "zip": "78701", "phone": "555-222-3333"}, expect=(200, 404, 500))
    c.post(servlet, {"action": "login", "userid": email, "passwd": PASSWORD, "updating": "false"}, expect=(200, 404, 500))
    c.post(servlet, {"action": "login", "userid": email, "passwd": "wrong", "updating": "false"}, expect=(200, 404, 500))
    c.post(servlet, {"action": "account"}, expect=(200, 404, 500))
    c.post(servlet, {"action": "accountUpdate", "fname": "Alan", "lname": "Turing", "addr1": "4 Bletchley",
                     "city": "Austin", "state": "TX", "zip": "78701", "phone": "555-222-3333"}, expect=(200, 404, 500))
    c.post(servlet, {"action": "SetLogging", "logging": "debug"}, expect=(200, 404, 500))


# The database reset fails part-way once orders exist (see the docstring), so it runs last.
@suite.usecase("PopulateDB")
def populate_db(c):
    page = jsf_click(c, home(c), form="bannerform", text="HELP", contains="Reset database")
    jsf_post(c, page, "help", {"help:resetdb": "Reset database"})
    if not item_ids(category(c, home(c), "0")):
        raise UsecaseFailed("the catalogue is empty after the database reset")


@suite.usecase("AdminPopulate")
def admin_populate(c):
    # war.Populate's delete fails on the orders' foreign keys and leaves the catalogue empty; it then redirects to
    # help.jsp, which the app does not ship
    c.get("/servlet/AdminServlet", {"admintype": "populate"}, headers=ADMIN, expect=404)


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
