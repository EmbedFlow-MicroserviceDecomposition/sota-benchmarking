"""JPetStore functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Covers the FoSCI authors' 14 JPetStore scenarios (tools/fosci/FoSCI/testscenario/jpetstore-ts.txt) plus the failure paths:
catalogue browsing over the whole seed catalogue, search, sign-on/off (good and bad credentials), registration, account
editing, the cart (add, update quantities, remove), checkout with and without a separate shipping address, order history,
and viewing someone else's order. Catalogue ids are read from the app's own seed data, so the suite tracks the checkout.
"""

import functools
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, unique  # noqa: E402

suite = Suite("JPetStore", os.environ.get("JPETSTORE_BASE_URL", "http://localhost:8080/jpetstore"),
              ready_path="/actions/Catalog.action")
CONTAINER_NAME = "jpetstore-app"

SEED = os.path.join(HERE, "jpetstore-6/src/main/resources/database/jpetstore-hsqldb-dataload.sql")


@functools.lru_cache(maxsize=None)
def seed():
    """([category], [(product, category)], [(item, product)]) from the seed SQL, read on first use so the suite
    imports (and lists its use cases) without the submodule checked out."""
    if not os.path.exists(SEED):
        raise UsecaseFailed(f"seed data not found at {SEED}: run `git submodule update --init datasets/jpetstore/jpetstore-6`")
    sql = open(SEED, encoding="utf-8").read()
    categories = re.findall(r"INSERT INTO category VALUES \('([^']+)'", sql)
    products = re.findall(r"INSERT INTO product VALUES \('([^']+)','([^']+)'", sql)
    items = re.findall(r"INSERT INTO\s+item \([^)]*\) VALUES\('([^']+)','([^']+)'", sql)
    return categories, products, items

CATALOG = "/actions/Catalog.action"
ACCOUNT = "/actions/Account.action"
CART = "/actions/Cart.action"
ORDER = "/actions/Order.action"
USER, PASSWORD = "j2ee", "j2ee"
OTHER_USER, OTHER_PASSWORD = "ACID", "ACID"

ACCOUNT_FIELDS = {
    "account.firstName": "Ada", "account.lastName": "Lovelace", "account.email": "ada@example.com",
    "account.phone": "555-0100", "account.address1": "1 Analytical Way", "account.address2": "Suite 2",
    "account.city": "London", "account.state": "LN", "account.zip": "10001", "account.country": "UK",
    "account.languagePreference": "english", "account.favouriteCategoryId": "DOGS",
    "account.listOption": "true", "account.bannerOption": "true",
}

BILLING = {
    "order.cardType": "Visa", "order.creditCard": "999 9999 9999 9999", "order.expiryDate": "12/03",
    "order.billToFirstName": "ABC", "order.billToLastName": "XYX", "order.billAddress1": "901 San Antonio Road",
    "order.billAddress2": "MS UCUP02-206", "order.billCity": "Palo Alto", "order.billState": "CA",
    "order.billZip": "94303", "order.billCountry": "USA",
}

SHIPPING = {
    "order.shipToFirstName": "Grace", "order.shipToLastName": "Hopper", "order.shipAddress1": "2 Harbour St",
    "order.shipAddress2": "", "order.shipCity": "Arlington", "order.shipState": "VA", "order.shipZip": "22201",
    "order.shipCountry": "USA",
}


def signon(c, username=USER, password=PASSWORD):
    c.get(ACCOUNT, {"signonForm": ""}, contains="Username")
    return c.post(ACCOUNT, {"signon": "", "username": username, "password": password}, contains="Sign Out")


def add_to_cart(c, item_id):
    return c.get(CART, {"addItemToCart": "", "workingItemId": item_id}, contains=item_id)


def place_order(c, items, ship_elsewhere=False):
    """Checkout of `items` by the signed-on client; returns the new order id."""
    for item_id in items:
        add_to_cart(c, item_id)
    c.get(ORDER, {"newOrderForm": ""}, contains="Payment Details")
    form = dict(BILLING, newOrder="Continue")
    if ship_elsewhere:
        form["shippingAddressRequired"] = "true"
        c.post(ORDER, form, contains="Shipping Address")
        c.post(ORDER, dict(SHIPPING, newOrder="Continue"), contains="Confirm")
    else:
        c.post(ORDER, form, contains="Confirm")
    done = c.get(ORDER, {"newOrder": "", "confirmed": "true"}, contains="Thank you, your order has been submitted.")
    return done.find(r"Order #(\d+)", "order id")


@suite.usecase("ViewMain")
def view_main(c):
    categories = seed()[0]
    c.get("/", expect=200)
    main = c.get(CATALOG, contains=["Sign In"])
    for category in categories:
        if f"categoryId={category}" not in main.text:
            raise UsecaseFailed(f"main menu lacks a link to category {category}")
    c.get("/help.html", contains="JPetStore")


@suite.usecase("ViewCategory")
def view_category(c):
    categories, products, _ = seed()
    for category in categories:
        page = c.get(CATALOG, {"viewCategory": "", "categoryId": category})
        for product, cat in products:
            if cat == category and product not in page.text:
                raise UsecaseFailed(f"category {category} page lacks product {product}")


@suite.usecase("ViewProduct")
def view_product(c):
    _, products, items = seed()
    for product, _ in products:
        page = c.get(CATALOG, {"viewProduct": "", "productId": product})
        for item, prod in items:
            if prod == product and item not in page.text:
                raise UsecaseFailed(f"product {product} page lacks item {item}")


@suite.usecase("ViewItem")
def view_item(c):
    items = seed()[2]
    for item, _ in items:
        c.get(CATALOG, {"viewItem": "", "itemId": item}, contains=[item, "Add to Cart"])


@suite.usecase("SearchProducts")
def search_products(c):
    for keyword in ("fish", "Dog", "snake", "parrot", "persian", "retriever"):
        page = c.post(CATALOG, {"searchProducts": "", "keyword": keyword})
        if not re.search(r"productId=\w", page.text):
            raise UsecaseFailed(f"search for {keyword!r} found no products")
    c.post(CATALOG, {"searchProducts": "", "keyword": "zzz-no-such-pet"}, absent="productId=")
    c.post(CATALOG, {"searchProducts": "", "keyword": ""}, contains="Please enter a keyword")


@suite.usecase("Signon")
def signon_usecase(c):
    page = signon(c)
    if "My Account" not in page.text:
        raise UsecaseFailed("signed-on page lacks My Account")
    c.get(ACCOUNT, {"signoff": ""}, contains="Sign In", absent="Sign Out")


@suite.usecase("SignonFailure")
def signon_failure(c):
    c.post(ACCOUNT, {"signon": "", "username": USER, "password": "wrong"}, contains="Invalid username or password")
    c.post(ACCOUNT, {"signon": "", "username": "no-such-user", "password": "x"}, contains="Invalid username or password")


@suite.usecase("RegisterAccount")
def register_account(c):
    username = unique("user")
    c.get(ACCOUNT, {"signonForm": ""})
    c.get(ACCOUNT, {"newAccountForm": ""}, contains="User Information")
    form = dict(ACCOUNT_FIELDS, newAccount="Save Account Information", username=username,
                password="secret", repeatedPassword="secret")
    # newAccount redirects to the catalogue but, unlike signon, does not put the account into the session
    c.post(ACCOUNT, form, contains="Saltwater")
    signon(c, username, "secret")
    c.get(ACCOUNT, {"signoff": ""}, contains="Sign In")
    c.post(ACCOUNT, {"signon": "", "username": username, "password": "wrong"}, contains="Invalid username or password")


@suite.usecase("EditAccount")
def edit_account(c):
    username = unique("edit")
    c.post(ACCOUNT, dict(ACCOUNT_FIELDS, newAccount="", username=username, password="old", repeatedPassword="old"),
           contains="Saltwater")
    signon(c, username, "old")
    c.get(ACCOUNT, {"editAccountForm": ""}, contains=[username, "1 Analytical Way"])
    changed = dict(ACCOUNT_FIELDS, editAccount="Save Account Information", username=username, password="new",
                   repeatedPassword="new")
    changed.update({"account.address1": "42 Babbage Rd", "account.city": "Cambridge", "account.zip": "02139",
                    "account.favouriteCategoryId": "CATS", "account.languagePreference": "japanese"})
    c.post(ACCOUNT, changed, contains="Sign Out")
    c.get(ACCOUNT, {"editAccountForm": ""}, contains=["42 Babbage Rd", "Cambridge"])
    c.get(ACCOUNT, {"signoff": ""})
    c.post(ACCOUNT, {"signon": "", "username": username, "password": "old"}, contains="Invalid username or password")
    signon(c, username, "new")


@suite.usecase("AddToCart")
def add_items_to_cart(c):
    items = seed()[2]
    c.get(CART, {"viewCart": ""}, contains="Your cart is empty.")
    for item, _ in items[::4]:
        add_to_cart(c, item)
    add_to_cart(c, items[0][0])  # same item again: quantity 2
    page = c.get(CART, {"viewCart": ""}, contains="Sub Total")
    if not re.search(rf'name="{items[0][0]}"[^>]*value="2"', page.text):
        raise UsecaseFailed("adding the same item twice did not raise its quantity to 2")


@suite.usecase("ViewCart")
def view_cart(c):
    c.get(CART, {"viewCart": ""}, contains="Your cart is empty.")
    add_to_cart(c, "EST-1")
    c.get(CART, {"viewCart": ""}, contains=["EST-1", "Sub Total", "Proceed to Checkout"])
    c.get(CART, {"checkOut": ""}, contains=["Checkout Summary", "EST-1"])  # handler no page links to


@suite.usecase("UpdateCartQuantities")
def update_cart_quantities(c):
    for item in ("EST-1", "EST-2", "EST-3"):
        add_to_cart(c, item)
    page = c.post(CART, {"updateCartQuantities": "", "EST-1": "5", "EST-2": "0", "EST-3": "abc"}, contains="Sub Total")
    if not re.search(r'name="EST-1"[^>]*value="5"', page.text):
        raise UsecaseFailed("EST-1 quantity was not updated to 5")
    if 'name="EST-2"' in page.text:
        raise UsecaseFailed("quantity 0 did not remove EST-2")


@suite.usecase("RemoveFromCart")
def remove_from_cart(c):
    add_to_cart(c, "EST-4")
    add_to_cart(c, "EST-5")
    c.get(CART, {"removeItemFromCart": "", "workingItemId": "EST-4"}, absent='name="EST-4"', contains="EST-5")
    c.get(CART, {"removeItemFromCart": "", "workingItemId": "EST-5"}, contains="Your cart is empty.")


@suite.usecase("CheckoutRequiresSignon")
def checkout_requires_signon(c):
    add_to_cart(c, "EST-6")
    c.get(ORDER, {"newOrderForm": ""}, contains="You must sign on before attempting to check out")


@suite.usecase("PlaceOrder")
def place_order_usecase(c):
    signon(c)
    order_id = place_order(c, ["EST-6", "EST-7", "EST-7"])
    c.get(CART, {"viewCart": ""}, contains="Your cart is empty.")
    c.get(ORDER, {"viewOrder": "", "orderId": order_id}, contains=[f"Order #{order_id}", "EST-6", "EST-7"])


@suite.usecase("PlaceOrderShipElsewhere")
def place_order_ship_elsewhere(c):
    signon(c, OTHER_USER, OTHER_PASSWORD)
    order_id = place_order(c, ["EST-18"], ship_elsewhere=True)
    c.get(ORDER, {"viewOrder": "", "orderId": order_id}, contains=["Grace", "2 Harbour St"])


@suite.usecase("ListOrders")
def list_orders(c):
    signon(c)
    page = c.get(ORDER, {"listOrders": ""}, contains="Order ID")
    order_ids = page.find_all(r"orderId=(\d+)")
    if not order_ids:
        order_ids = [place_order(c, ["EST-10"])]
        c.get(ORDER, {"listOrders": ""}, contains=order_ids[0])
    for order_id in order_ids[:5]:
        c.get(ORDER, {"viewOrder": "", "orderId": order_id}, contains=f"Order #{order_id}")


@suite.usecase("ViewOtherUsersOrder")
def view_other_users_order(c):
    signon(c)
    order_id = place_order(c, ["EST-11"])
    other = suite.client()
    signon(other, OTHER_USER, OTHER_PASSWORD)
    other.get(ORDER, {"viewOrder": "", "orderId": order_id}, contains="You may only view your own orders.")


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
