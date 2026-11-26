"""DayTrader functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Covers both web UIs (the servlet UI at /app and the JSF UI at *.faces): registration, sign-in/out (good and bad), account
view and update, market summary, quotes, buy, portfolio, sell, the random-scenario servlet; the configuration page and every
implementation it switches between (Full EJB3 and Direct JDBC, synchronous / JMS two-phase / managed-thread orders, JSP and
JSP-Images, caching on and off), each run through a buy and a sell; the database build and reset; and every "primitive" ping
servlet. The app starts with an empty database, so BuildDB runs first (with a small user/quote count: the benchmark's
15000 x 10000 would put hundreds of thousands of calls into one trace). Use cases that change the configuration put the
defaults back before returning.

Known issues of the pinned app on this Liberty, kept as they are and expected by the suite: the /ejb3 primitives that inject
the trade EJB fail to load (CWNEN0074E, a 404); PingServlet2PDF, PingServlet2ServletRcv, PingJspEL.jsp and PingServlet2Jsp.jsp
are 500s; and the config servlet turns order alerts off when a
config update omits UseRemoteEJBInterface. In Full EJB3 mode the account page is intermittently a 500 (EclipseLink "value
holder with null session": a lazily loaded profile of a cached entity), depending on what the persistence cache holds, so the
suite accepts 200 or 500 for it there and stays strict in Direct mode.
"""

import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, jsf_click, jsf_post, unique  # noqa: E402

suite = Suite("DayTrader", os.environ.get("DAYTRADER_BASE_URL", "http://localhost:9082/daytrader"), ready_path="/app")
CONTAINER_NAME = "daytrader-app"

USER, PASSWORD = "uid:0", "xxx"  # TradeBuildDB creates uid:0..uid:N-1 with password xxx
MAX_USERS, MAX_QUOTES = 25, 80   # small database: see the module docstring

EJB3, DIRECT = 0, 1
SYNC, ASYNC_2PHASE, ASYNC_THREAD = 0, 1, 2
JSP, JSP_IMAGES = 0, 1
DISTRIBUTED_MAP, NO_CACHING = 0, 1
DEFAULTS = {"RunTimeMode": DIRECT, "OrderProcessingMode": SYNC, "WebInterface": JSP, "CachingType": DISTRIBUTED_MAP}

# primitives that work, and the ones that do not on this build (see the module docstring)
PINGS = """/servlet/ExplicitGC /servlet/PingJDBCRead /servlet/PingJDBCRead2JSP /servlet/PingJDBCWrite /servlet/PingJSONP
/servlet/PingManagedExecutor /servlet/PingManagedThread /servlet/PingReentryServlet /servlet/PingServlet /servlet/PingServlet2DB
/servlet/PingServlet2Include /servlet/PingServlet2IncludeRcv /servlet/PingServlet2JNDI /servlet/PingServlet2Jsp
/servlet/PingServlet2Servlet /servlet/PingServlet30Async /servlet/PingServlet31Async /servlet/PingServlet31AsyncRead
/servlet/PingServletCDI /servlet/PingServletCDIBeanManagerViaCDICurrent /servlet/PingServletCDIBeanManagerViaJNDI
/servlet/PingServletLargeContentLength /servlet/PingServletSetContentLength /servlet/PingServletWriter /servlet/PingSession1
/servlet/PingSession2 /servlet/PingSession3 /servlet/PingUpgradeServlet /ejb3/PingServlet2SessionLocal /TestServlet
/PingHtml.html /PingJsp.jsp /PingJsf.faces /PingCDIJSF.faces /web_prmtv.html /PingWebSocketJson.html""".split()
BROKEN_PINGS = {"/servlet/PingServlet2PDF": 500, "/servlet/PingServlet2ServletRcv": 500, "/PingJspEL.jsp": 500,
                "/PingServlet2Jsp.jsp": 500, "/ejb3/PingServlet2Entity": 404, "/ejb3/PingServlet2MDBQueue": 404,
                "/ejb3/PingServlet2MDBTopic": 404, "/ejb3/PingServlet2Session": 404,
                "/ejb3/PingServlet2Session2CMROne2Many": 404, "/ejb3/PingServlet2Session2CMROne2One": 404,
                "/ejb3/PingServlet2Session2Entity": 404, "/ejb3/PingServlet2Session2Entity2JSP": 404,
                "/ejb3/PingServlet2Session2EntityCollection": 404, "/ejb3/PingServlet2Session2JDBC": 404,
                "/ejb3/PingServlet2Session2JDBCCollection": 404, "/ejb3/PingServlet2TwoPhase": 404}


def text(page):
    return " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<!--.*?-->", "", page.text, flags=re.S)).split())


def configure(c, **params):
    """The config servlet's updateConfig action; unspecified settings keep their value."""
    form = {"action": "updateConfig", "UseRemoteEJBInterface": "false", "DisplayOrderAlerts": "true",
            "EnablePublishQuotePriceChange": "true"}
    form.update({k: str(v) for k, v in params.items()})
    return c.post("/config", form, contains="DayTrader Configuration Updated")


def restore_defaults(c):
    configure(c, **DEFAULTS)


def login(c, uid=USER, password=PASSWORD):
    return c.post("/app", {"action": "login", "uid": uid, "passwd": password}, contains=["Welcome", "Logoff"])


def new_user(c, uid=None, password="pw"):
    uid = uid or "ru:" + unique("")
    c.post("/app", {"action": "register", "user id": uid, "passwd": password, "confirm passwd": password,
                    "Full Name": "Test User", "Credit Card Number": "1111-2222-3333", "money": "50000",
                    "email": uid.replace(":", "") + "@example.com", "snail mail": "1 Market St"},
           contains=["Welcome", uid])
    return uid


def holdings(page):
    return re.findall(r"app\?action=sell&(?:amp;)?holdingID=(\d+)", page.text)


def account_page(c, ejb3=False):
    return c.get("/app", {"action": "account"}, expect=(200, 500) if ejb3 else 200)


def trade(c, symbol="s:3", quantity="5", ejb3=False):
    """Buy, look at the portfolio, sell the last holding, view the account; returns the buy and sell pages."""
    buy = c.post("/app", {"action": "buy", "symbol": symbol, "quantity": quantity}, contains=[symbol, "has been submitted"])
    portfolio = c.get("/app", {"action": "portfolio"}, contains="Portfolio")
    ids = holdings(portfolio)
    if not ids:
        raise UsecaseFailed("portfolio lists no holdings after a buy")
    sell = c.get("/app", {"action": "sell", "holdingID": ids[-1]}, contains="has been submitted")
    account_page(c, ejb3)
    return buy, sell


@suite.usecase("BuildDB")
def build_db(c):
    configure(c, MaxUsers=MAX_USERS, MaxQuotes=MAX_QUOTES, **DEFAULTS)
    c.get("/config", {"action": "buildDBTables"}, contains="TradeBuildDB", timeout=900)
    page = c.get("/config", {"action": "buildDB"}, contains=f"Creating {MAX_QUOTES} Quotes", timeout=1800)
    if "Exception" in page.text and "Trade" not in page.text:
        raise UsecaseFailed("database build reported an exception")
    login(c)  # uid:0 exists


@suite.usecase("ViewHome")
def view_home(c):
    c.get("/", expect=200)
    for path in ("/index.html", "/contentHome.html", "/leftMenu.html", "/header.html", "/footer.html", "/configure.html",
                 "/index.faces", "/welcome.faces", "/docs/glossary.html"):
        c.get(path, expect=(200, 404))
    c.get("/app", contains="Log in")
    c.get("/app", {"action": "home"}, contains="Log in")  # not signed in: back to the login page


@suite.usecase("Login")
def login_usecase(c):
    page = login(c)
    for needle in ("Account", "Market Summary", "Portfolio", "Quotes/Trade"):
        if needle not in page.text:
            raise UsecaseFailed(f"signed-in home lacks {needle}")
    c.get("/app", {"action": "home"}, contains="Welcome")
    c.get("/app", {"action": "logout"}, contains="Log in")
    c.get("/app", {"action": "portfolio"}, contains="Log in")  # signed out again


@suite.usecase("LoginFailure")
def login_failure(c):
    c.post("/app", {"action": "login", "uid": USER, "passwd": "wrong"}, contains="Log in", absent="Logoff")
    c.post("/app", {"action": "login", "uid": "uid:999999", "passwd": PASSWORD}, contains="Could not find account")
    c.get("/app", {"action": "no-such-action"}, contains="Log in")


@suite.usecase("Register")
def register_usecase(c):
    uid = new_user(c)
    c.get("/app", {"action": "logout"})
    login(c, uid, "pw")
    page = c.get("/app", {"action": "account"}, contains=[uid, "Account Information"])
    if "50000" not in page.text:
        raise UsecaseFailed("a new account does not hold its opening balance")
    c2 = suite.client()
    c2.post("/app", {"action": "register", "user id": "ru:" + unique(""), "passwd": "a", "confirm passwd": "b",
                     "Full Name": "X", "Credit Card Number": "1", "money": "1", "email": "x@x", "snail mail": "x"},
            contains="passwords did not match")
    c2.post("/app", {"action": "register", "user id": uid, "passwd": "pw", "confirm passwd": "pw", "Full Name": "Dup",
                     "Credit Card Number": "1", "money": "1", "email": "d@x", "snail mail": "x"}, expect=(200, 500))


@suite.usecase("Account")
def account(c):
    login(c)
    c.get("/app", {"action": "account"}, contains=["Account Information", USER])
    profile = {"action": "update_profile", "password": PASSWORD, "cpassword": PASSWORD, "fullname": "Ada Lovelace",
               "address": "1 Analytical Way", "creditcard": "4111-1111", "email": "ada@example.com"}
    c.post("/app", profile, contains="Account Information")
    c.post("/app", dict(profile, cpassword="different"), contains="passwords do not match")
    c.post("/app", dict(profile, address=""), contains="Account Information")  # a blank field is refused


@suite.usecase("MarketSummary")
def market_summary(c):
    login(c)
    c.get("/app", {"action": "mksummary"}, contains=["Market Summary", "Top Gainers"])


@suite.usecase("Quotes")
def quotes(c):
    login(c)
    page = c.get("/app", {"action": "quotes", "symbols": "s:1,s:2,s:3"}, contains=["s:1", "s:2", "s:3"])
    if 'name="quantity"' not in page.text:
        raise UsecaseFailed("the quotes page has no buy form")
    c.post("/app", {"action": "quotes", "symbols": "s:4"}, contains="s:4")
    c.get("/app", {"action": "quotes", "symbols": "s:99999"}, expect=(200, 500))


@suite.usecase("BuyAndSell")
def buy_and_sell(c):
    login(c, "uid:1")
    trade(c, "s:3", "5")
    trade(c, "s:7", "40")
    c.get("/app", {"action": "portfolioNoEdge"}, contains="Portfolio")
    c.post("/app", {"action": "buy", "symbol": "s:3", "quantity": "-5"}, expect=(200, 500))


@suite.usecase("NewUserTrades")
def new_user_trades(c):
    new_user(c)
    trade(c, "s:2", "10")


@suite.usecase("Portfolio")
def portfolio(c):
    login(c, "uid:2")
    c.post("/app", {"action": "buy", "symbol": "s:1", "quantity": "3"}, contains="has been submitted")
    page = c.get("/app", {"action": "portfolio"}, contains="Portfolio")
    if not holdings(page):
        raise UsecaseFailed("the portfolio lists no holdings after a buy")
    c.get("/app", {"action": "portfolio"}, contains="Portfolio")


@suite.usecase("TradeScenario")
def trade_scenario(c):
    """TradeScenarioServlet: one scripted step per action letter, as the benchmark's load driver issues them."""
    c.get("/scenario", {"action": "l"}, expect=200)
    for step in "hqapbsuhqbsor":
        c.get("/scenario", {"action": step}, expect=200)
    for _ in range(12):  # no action: a random operation weighted like the benchmark's mix
        c.get("/scenario", expect=200)


@suite.usecase("JsfPages")
def jsf_pages(c):
    for path in ("/index.faces", "/welcome.faces", "/config.faces", "/PingJsf.faces", "/PingCDIJSF.faces"):
        c.get(path)
    jsf_register(c)
    jsf_login(c)
    for page in ("account", "portfolio", "quote", "marketSummary", "order", "tradehome"):
        c.get(f"/{page}.faces", contains="Logoff")


def jsf_login(c, uid=USER, password=PASSWORD, **checks):
    welcome = c.get("/welcome.faces", contains="Log in")
    return jsf_post(c, welcome, "login", {"login:submit": "Log in"}, {"uid": uid, "password": password}, **checks)


def jsf_register(c):
    uid = "ru:" + unique("")
    page = c.get("/register.faces", contains="Register")
    fields = {"fullname": "Jsf User", "address": "2 Market St", "email": "jsf@example.com", "uid": uid, "password": "pw",
              "cpassword": "pw", "money": "20000", "ccn": "2222-3333-4444"}
    done = jsf_post(c, page, "register", {_submit(page, "register"): _submit_value(page, "register")}, fields)
    if "Welcome" not in done.text and uid not in done.text:
        raise UsecaseFailed("JSF registration did not sign the new user in")
    return uid


def _submit(page, form):
    m = re.search(rf'<input[^>]*type="submit"[^>]*name="({re.escape(form)}:[^"]*)"|<input[^>]*name="({re.escape(form)}:[^"]*)"[^>]*type="submit"',
                  page.text)
    if not m:
        raise UsecaseFailed(f"{page.url}: form {form!r} has no submit button")
    return m.group(1) or m.group(2)


def _submit_value(page, form):
    name = _submit(page, form)
    m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"|value="([^"]*)"[^>]*name="{re.escape(name)}"', page.text)
    return (m.group(1) or m.group(2)) if m else "submit"


@suite.usecase("JsfLogin")
def jsf_login_usecase(c):
    home = jsf_login(c, contains="Welcome")
    if USER not in home.text:
        raise UsecaseFailed("the JSF home does not greet the user")
    for path, needle in (("/tradehome.faces", "Welcome"), ("/account.faces", "Account Information"),
                         ("/marketSummary.faces", "Market Summary"), ("/portfolio.faces", "Portfolio"),
                         ("/quote.faces", "Quotes")):
        c.get(path, contains=needle)
    c.get("/welcome.faces")
    out = suite.client()
    jsf_login(out, USER, "wrong")  # a failed JSF login stays on the login form
    out.get("/portfolio.faces", contains="Log in")


@suite.usecase("JsfRegister")
def jsf_register_usecase(c):
    uid = jsf_register(c)
    c.get("/account.faces", contains=uid)


@suite.usecase("JsfAccount")
def jsf_account(c):
    jsf_login(c, "uid:3")
    page = c.get("/account.faces", contains="Account Information")
    form = {"fullname": "Grace Hopper", "password": PASSWORD, "cpassword": PASSWORD, "address": "3 Navy Yard",
            "ccn": "5555-6666", "email": "grace@example.com"}
    jsf_post(c, page, "updateProfile", {_submit(page, "updateProfile"): _submit_value(page, "updateProfile")}, form,
             contains="Account Information")
    jsf_post(c, page, "updateProfile", {_submit(page, "updateProfile"): _submit_value(page, "updateProfile")},
             dict(form, cpassword="zzz"))


@suite.usecase("JsfTrade")
def jsf_trade(c):
    jsf_login(c, "uid:4")
    quotes_page = c.get("/quote.faces", contains="Quotes")
    buy = jsf_post(c, quotes_page, "quotes", {"quotes:quotes:0:buy": "buy"}, {"quotes:quotes:0:quantity": "7"},
                   contains="Order")
    c.get("/order.faces", contains="Order")
    portfolio_page = c.get("/portfolio.faces", contains="Portfolio")
    jsf_click(c, portfolio_page, form="portfolio", text="sell", contains="Order")
    c.get("/marketSummary.faces", contains="Market Summary")
    jsf_click(c, c.get("/tradehome.faces"), text="Logoff")
    c.get("/portfolio.faces", contains="Log in")
    if "has been submitted" not in buy.text and "Order" not in buy.text:
        raise UsecaseFailed("the JSF buy produced no order page")


@suite.usecase("WebSockets")
def web_sockets(c):
    """The primitives' web-socket endpoints and the market-summary push, over a real WebSocket (harness: workload.WebSocket)."""
    for endpoint in ("/pingTextSync", "/pingTextAsync"):
        with c.websocket(endpoint) as ws:
            for _ in range(3):
                ws.send("ping")
                reply = ws.recv()
                if not (isinstance(reply, str) and reply.strip()):
                    raise UsecaseFailed(f"{endpoint} answered {reply!r}")
    with c.websocket("/pingBinary") as ws:
        ws.send(b"\x00\x01\x02\x03")
        if ws.recv() != b"\x00\x01\x02\x03":
            raise UsecaseFailed("/pingBinary did not echo the bytes")
    with c.websocket("/pingWebSocketJson") as ws:
        for _ in range(3):
            ws.send('{"key": "ping", "value": "1"}')
        seen = [ws.recv() for _ in range(3)]
        if not any(m and "receivedHitCount" in m for m in seen):
            raise UsecaseFailed(f"/pingWebSocketJson never reported its hit count: {seen}")
    with c.websocket("/marketsummary") as ws:
        ws.send('{"action": "update"}')
        summary = ws.recv()
        if not summary or "gainer1_stock" not in summary:
            raise UsecaseFailed(f"/marketsummary pushed {summary!r}")
        ws.send('{"action": "unknown"}')
        ws.send("not json")


@suite.usecase("ConfigPages")
def config_pages(c):
    c.get("/config", contains="Current DayTrader Configuration")
    page = c.get("/config.faces", contains="runtime")
    restore_defaults(c)
    jsf_post(c, page, "updateConfig", {_submit(page, "updateConfig"): _submit_value(page, "updateConfig")},
             {"runtimeMode": "Direct (JDBC)", "orderProcessingMode": "Sync", "webInterface": "JSP",
              "maxUsers": str(MAX_USERS), "maxQuotes": str(MAX_QUOTES)})
    for params in ({"MarketSummaryInterval": "5"}, {"PrimIterations": "2"}, {"PercentSentToWebsocket": "50"},
                   {"EnableActionTrace": "true", "EnableTrace": "true"}, {"EnableLongRun": "true"},
                   {"RunTimeMode": "99"}, {"MarketSummaryInterval": "20", "PrimIterations": "1",
                                          "PercentSentToWebsocket": "10"}):
        configure(c, **params)
    restore_defaults(c)


@suite.usecase("ConfigModes")
def config_modes(c):
    """Every (implementation, order mode) pair but EJB3 + managed thread, each through a buy and a sell."""
    try:
        for runtime in (EJB3, DIRECT):
            for order_mode in (SYNC, ASYNC_2PHASE, ASYNC_THREAD):
                if (runtime, order_mode) == (EJB3, ASYNC_THREAD):
                    continue  # its own use case, ConfigEjb3ManagedThread
                configure(c, RunTimeMode=runtime, OrderProcessingMode=order_mode)
                s = suite.client()
                login(s, "uid:5")
                trade(s, "s:5", "10", ejb3=runtime == EJB3)
                if order_mode != SYNC:
                    time.sleep(2)  # the order completes on a JMS message or a managed thread
                    account_page(s, runtime == EJB3)
                    s.get("/app", {"action": "portfolio"}, contains="Portfolio")
                    s.get("/app", {"action": "mksummary"}, contains="Market Summary")
    finally:
        restore_defaults(c)


@suite.usecase("ConfigWebInterface")
def config_web_interface(c):
    """JSP-Images renders the pages through the *Img.jsp variants."""
    try:
        for runtime in (EJB3, DIRECT):
            configure(c, WebInterface=JSP_IMAGES, RunTimeMode=runtime)
            s = suite.client()
            login(s, "uid:6")
            account_page(s, runtime == EJB3)
            s.get("/app", {"action": "mksummary"})
            s.get("/app", {"action": "quotes", "symbols": "s:1,s:2"})
            trade(s, "s:2", "3", ejb3=runtime == EJB3)
            s.get("/app", {"action": "logout"})
    finally:
        restore_defaults(c)


@suite.usecase("ConfigCaching")
def config_caching(c):
    try:
        for caching in (NO_CACHING, DISTRIBUTED_MAP):
            for runtime in (EJB3, DIRECT):
                configure(c, CachingType=caching, RunTimeMode=runtime)
                s = suite.client()
                login(s, "uid:7")
                s.get("/app", {"action": "quotes", "symbols": "s:1,s:2,s:3"})
                trade(s, "s:4", "2", ejb3=runtime == EJB3)
                s.get("/app", {"action": "mksummary"})
    finally:
        restore_defaults(c)


@suite.usecase("ConfigEjbRemoteInterface")
def config_ejb_remote(c):
    try:
        configure(c, RunTimeMode=EJB3, UseRemoteEJBInterface="true")
        s = suite.client()
        login(s, "uid:8")
        trade(s, "s:6", "4", ejb3=True)
    finally:
        restore_defaults(c)


@suite.usecase("PingServlets")
def ping_servlets(c):
    for path in PINGS:
        c.get(path, timeout=120)
    for path in ("/servlet/PingServlet2DB", "/servlet/PingJDBCRead", "/servlet/PingServlet2Include"):
        c.get(path, {"symbol": "s:1"})
    for path, status in BROKEN_PINGS.items():
        c.get(path, expect=status, timeout=120)


@suite.usecase("ConfigEjb3ManagedThread")
def config_ejb3_managed_thread(c):
    """The one (implementation, order mode) pair ConfigModes leaves out: the order runs on a managed thread without a
    persistence context, so reading it back through EJB3 is not reliable (see the module docstring)."""
    try:
        configure(c, RunTimeMode=EJB3, OrderProcessingMode=ASYNC_THREAD)
        s = suite.client()
        login(s, "uid:10")
        s.post("/app", {"action": "buy", "symbol": "s:5", "quantity": "10"}, contains="has been submitted")
        time.sleep(2)
        s.get("/app", {"action": "portfolio"}, contains="Portfolio")
        account_page(s, ejb3=True)
        s.get("/app", {"action": "mksummary"})
    finally:
        restore_defaults(c)


@suite.usecase("ResetTrade")
def reset_trade(c):
    """Deletes the users registered during the run and resets the holdings (the dummy `ru:` and `uid:` accounts)."""
    c.get("/config", {"action": "resetTrade"}, contains="DayTrader", timeout=900)
    login(c)


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
