# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Black-box functional test suite for a running JPetStore: the 14 scenarios of the FoSCI authors' test scenario list
(tools/fosci/FoSCI/testscenario/jpetstore-ts.txt), driven over HTTP like a browser (cookies, live form tokens).

Run it against an instance started with the tracer agent to record FoSCI's execution trace (see tools/fosci/README.md):
    uv run functional_tests.py [--base-url http://localhost:8080/jpetstore]
Exits 1 if any scenario's check fails, so a trace is only kept from a suite that really passed.
"""

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from web_driver import Browser, Suite  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:8080/jpetstore")
    b = Browser(ap.parse_args().base_url)
    suite = Suite()
    check = suite.check
    user, pw = f"ft{int(time.time())}", "Passw0rd!"

    b.get("/actions/Catalog.action")
    check("home", "Welcome to JPetStore" in b.page or "Catalog" in b.page, "main catalog page")

    # 1) register a new user
    b.get("/actions/Account.action?newAccountForm=")
    b.submit("newAccount", username=user, password=pw, repeatedPassword=pw, account__firstName="Func", account__lastName="Test",
             account__email="ft@example.org", account__phone="555", account__address1="1 Main St", account__address2="Apt 2",
             account__city="Colombo", account__state="WP", account__zip="10100", account__country="LK",
             account__languagePreference="english", account__favouriteCategoryId="DOGS", account__listOption="true",
             account__bannerOption="true")
    check("1 register", "Sign In" in b.page and "Invalid" not in b.page, f"account {user} created")

    # 2) sign in
    b.get("/actions/Account.action?signonForm=")
    b.submit("signon", username=user, password=pw)
    check("2 sign in", "Sign Out" in b.page, "signed in")

    # 4) modify account info (name, e-mail and password)
    b.get("/actions/Account.action?editAccountForm=")
    # the action bean validates `username` and `password` as required on editAccount, though the form only shows them
    b.submit("editAccount", username=user, password="Passw0rd2!", repeatedPassword="Passw0rd2!",
             account__firstName="Changed", account__lastName="Name", account__email="ft2@example.org")
    check("4 edit account", b.url.endswith("/Catalog.action"), f"edit accepted, redirected to {b.url}")

    # 5, 6) view category and product
    b.get("/actions/Catalog.action?viewCategory=&categoryId=FISH")
    check("5 view category", "FI-SW-01" in b.page, "FISH category lists its products")
    b.get("/actions/Catalog.action?viewProduct=&productId=FI-SW-01")
    check("6 view product", "EST-1" in b.page, "product lists its items")
    b.get("/actions/Catalog.action?viewItem=&itemId=EST-1")
    check("6 view item", "Add to Cart" in b.page, "item detail")

    # 7) add items to the cart; 8) delete one; 9) change quantity and re-price
    b.get("/actions/Cart.action?addItemToCart=&workingItemId=EST-1")
    check("7 add to cart", "EST-1" in b.page, "EST-1 in cart")
    b.get("/actions/Cart.action?addItemToCart=&workingItemId=EST-2")
    b.get("/actions/Cart.action?removeItemFromCart=&cartItem=EST-2")
    check("8 remove from cart", "EST-2" not in b.page and "EST-1" in b.page, "EST-2 removed, EST-1 kept")
    b.submit("updateCartQuantities", **{"EST-1": "3"})
    check("9 update quantity", 'value="3"' in b.page, "quantity 3 re-priced")

    # 10) new order, 11) place order
    b.get("/actions/Order.action?newOrderForm=")
    b.submit("newOrder", order__cardType="Visa", order__creditCard="999 9999 9999 9999", order__expiryDate="12/30",
             order__billToFirstName="Func", order__billToLastName="Test", order__billAddress1="1 Main St",
             order__billAddress2="Apt 2", order__billCity="Colombo", order__billState="WP", order__billZip="10100",
             order__billCountry="LK")
    check("10 new order", "confirmed=true" in b.page, "order confirmation page")
    b.get("/actions/Order.action?newOrder=&confirmed=true")
    check("11 place order", "Thank you" in b.page, "order placed")

    # 12) view old orders
    b.get("/actions/Order.action?listOrders=")
    ids = re.findall(r"orderId=(\d+)", b.page)
    check("12 list orders", bool(ids), f"orders {ids}")
    if ids:
        b.get(f"/actions/Order.action?viewOrder=&orderId={ids[0]}")
        check("12 view order", "Order #" in b.page, f"order {ids[0]}")

    # 13) search products
    b.get("/actions/Catalog.action")
    b.submit("searchProducts", keyword="dog")
    check("13 search", "K9-BD-01" in b.page, "search 'dog' finds a dog product")

    # 14) modify the account's address and location information
    b.get("/actions/Account.action?editAccountForm=")
    b.submit("editAccount", username=user, password="Passw0rd2!", repeatedPassword="Passw0rd2!",
             account__address1="9 Lake Rd", account__city="Kandy", account__zip="20000", account__country="LK")
    check("14 edit address", b.url.endswith("/Catalog.action"), f"edit accepted, redirected to {b.url}")

    # 3) sign out
    b.get("/actions/Account.action?signoff=")
    check("3 sign out", "Sign In" in b.page, "signed out")

    # scenario 4/14 edits persisted: sign in again (with the new password) and read the profile back
    b.get("/actions/Account.action?signonForm=")
    b.submit("signon", username=user, password="Passw0rd2!")
    check("4 new password works", "Sign Out" in b.page, "signed in with the changed password")
    b.get("/actions/Account.action?editAccountForm=")
    saved = dict(re.findall(r'<input name="account\.(firstName|city)" type="text" value="([^"]*)"', b.page))
    check("4 edit persisted", saved == {"firstName": "Changed", "city": "Kandy"}, f"profile shows {saved}")
    b.get("/actions/Account.action?signoff=")

    return suite.finish()


if __name__ == "__main__":
    sys.exit(main())
