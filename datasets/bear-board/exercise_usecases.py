"""Bear Board functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Drives every REST endpoint of the kiosk back end: users (register, duplicate and empty password, sign-in good and bad,
list, view, update, delete), events and awards (create, page, slide list, view, update, delete), the tweet whitelist,
the tweet board (list by status, view, moderate, delete all, re-open the Twitter stream) and the STOMP news push over
the SockJS endpoint's raw WebSocket. Tweets only arrive from the live Twitter API, which needs real credentials (the
compose file passes dummy ones), so the board is exercised empty and the stream fails in the background.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, unique  # noqa: E402

suite = Suite("BearBoard", os.environ.get("BEARBOARD_BASE_URL", "http://localhost:8080"), ready_path="/events")
CONTAINER_NAME = "bear-board-app"

ORIGIN = "http://localhost:3000"  # one of WebSocketConfig's allowed origins


def post_json(c, path, body, **checks):
    return c.request("POST", path, json_body=body, **checks)


def put_json(c, path, body, **checks):
    return c.request("PUT", path, json_body=body, **checks)


def register(c, password="Secret123!"):
    email = unique("bear") + "@baylor.edu"
    user = post_json(c, "/users", {"emailAddress": email, "password": password, "firstName": "Bear",
                                   "lastName": "Board"}).json()
    if user.get("emailAddress") != email or user.get("password") == password:
        raise UsecaseFailed(f"registration returned {user}")
    return user, password


def page_items(resp):
    body = resp.json()
    items = next((v for v in body.values() if isinstance(v, list)), None)
    if items is None:
        raise UsecaseFailed(f"no list in paged response {body}")
    return items


@suite.usecase("CreateUser")
def create_user(c):
    user, password = register(c)
    post_json(c, "/users", {"emailAddress": user["emailAddress"], "password": "x", "firstName": "Dup",
                            "lastName": "User"}, expect=400)  # already registered
    post_json(c, "/users", {"emailAddress": unique("e") + "@baylor.edu", "password": "", "firstName": "No",
                            "lastName": "Password"}, expect=400)


@suite.usecase("Login")
def login(c):
    user, password = register(c)
    me = post_json(c, "/users/login", {"emailAddress": user["emailAddress"], "password": password}).json()
    if me.get("id") != user["id"]:
        raise UsecaseFailed("signing in returned another user")
    post_json(c, "/users/login", {"emailAddress": user["emailAddress"], "password": "wrong"}, expect=400)
    post_json(c, "/users/login", {"emailAddress": "nobody@baylor.edu", "password": password}, expect=400)


@suite.usecase("GetAllUsers")
def get_all_users(c):
    user, _ = register(c)
    if not any(u["id"] == user["id"] for u in c.get("/users").json()):
        raise UsecaseFailed("a new user is not listed")


@suite.usecase("GetUser")
def get_user(c):
    user, _ = register(c)
    if c.get(f"/users/{user['id']}").json()["emailAddress"] != user["emailAddress"]:
        raise UsecaseFailed("user by id returned another user")


@suite.usecase("UpdateAndDeleteUser")
def update_and_delete_user(c):
    user, _ = register(c)
    updated = put_json(c, f"/users/{user['id']}", {"firstName": "Updated"}).json()
    if updated["firstName"] != "Updated" or updated["lastName"] != "Board":
        raise UsecaseFailed("updating one field did not keep the others")
    c.request("DELETE", f"/users/{user['id']}")
    if any(u["id"] == user["id"] for u in c.get("/users").json()):
        raise UsecaseFailed("a deleted user is still listed")


def create(c, collection, body):
    item = post_json(c, f"/{collection}", body).json()
    if not item.get("id"):
        raise UsecaseFailed(f"creating in /{collection} returned {item}")
    return item


@suite.usecase("CreateEvent")
def create_event(c):
    create(c, "events", {"title": unique("Homecoming "), "coordinator": "Student Life", "description": "Parade",
                         "date": "2026-12-05T18:00:00.000+0000", "images": ["a.png"], "videos": []})


@suite.usecase("GetEvents")
def get_events(c):
    for i in range(3):
        create(c, "events", {"title": unique(f"Event {i} "), "coordinator": "ECS", "description": "Talk",
                             "date": "2026-12-10T10:00:00.000+0000", "images": [], "videos": ["v.mp4"]})
    if len(page_items(c.get("/events", {"page": 0, "size": 2}))) != 2:
        raise UsecaseFailed("a page of size 2 did not hold 2 events")
    c.get("/events", {"page": 1, "size": 2})
    c.get("/events")
    page_items(c.get("/events/slide", {"page": 0, "size": 5}))


@suite.usecase("GetEvent")
def get_event(c):
    event = create(c, "events", {"title": unique("Finals "), "coordinator": "Registrar", "description": "Week",
                                 "date": "2026-12-14T08:00:00.000+0000", "images": [], "videos": []})
    if c.get(f"/events/{event['id']}").json()["title"] != event["title"]:
        raise UsecaseFailed("event by id returned another event")


@suite.usecase("UpdateAndDeleteEvent")
def update_and_delete_event(c):
    event = create(c, "events", {"title": unique("Draft "), "coordinator": "ECS", "description": "Old",
                                 "date": "2026-12-20T08:00:00.000+0000", "images": [], "videos": []})
    if put_json(c, f"/events/{event['id']}", {"description": "New"}).json()["description"] != "New":
        raise UsecaseFailed("event update was not stored")
    c.request("DELETE", f"/events/{event['id']}")


@suite.usecase("CreateAward")
def create_award(c):
    create(c, "awards", {"title": unique("Best Paper "), "description": "ICSE", "date": "2026-11-01"})


@suite.usecase("GetAwards")
def get_awards(c):
    for i in range(2):
        create(c, "awards", {"title": unique(f"Award {i} "), "description": "Dean's list", "date": "2026-10-01"})
    if not page_items(c.get("/awards", {"page": 0, "size": 10})):
        raise UsecaseFailed("no awards listed")
    c.get("/awards", {"page": 3, "size": 1})


@suite.usecase("GetAward")
def get_award(c):
    award = create(c, "awards", {"title": unique("Teaching "), "description": "Outstanding", "date": "2026-09-01"})
    if c.get(f"/awards/{award['id']}").json()["title"] != award["title"]:
        raise UsecaseFailed("award by id returned another award")


@suite.usecase("UpdateAndDeleteAward")
def update_and_delete_award(c):
    award = create(c, "awards", {"title": unique("Draft award "), "description": "Old", "date": "2026-08-01"})
    if put_json(c, f"/awards/{award['id']}", {"description": "New"}).json()["description"] != "New":
        raise UsecaseFailed("award update was not stored")
    c.request("DELETE", f"/awards/{award['id']}")


@suite.usecase("CreateWhitelistUser")
def create_whitelist_user(c):
    create(c, "whitelist-users", {"user": unique("baylor_")})


@suite.usecase("GetWhitelistUsers")
def get_whitelist_users(c):
    entry = create(c, "whitelist-users", {"user": unique("bu_")})
    if not any(w["id"] == entry["id"] for w in c.get("/whitelist-users").json()):
        raise UsecaseFailed("a whitelisted user is not listed")
    c.request("DELETE", f"/whitelist-users/{entry['id']}")
    if any(w["id"] == entry["id"] for w in c.get("/whitelist-users").json()):
        raise UsecaseFailed("a removed whitelisted user is still listed")


@suite.usecase("GetTweets")
def get_tweets(c):
    page_items(c.get("/tweets"))
    for status in ("PENDING", "ACCEPTED", "REJECTED"):
        c.get("/tweets", {"status": status, "page": 0, "size": 10})
    c.get("/tweets", {"status": "NOT_A_STATUS"}, expect=400)


@suite.usecase("ModerateTweets")
def moderate_tweets(c):
    c.get("/tweets/fetch")  # re-opens the Twitter stream (fails in the background without real credentials)
    c.request("PUT", "/tweets/no-such-tweet/status?status=ACCEPTED", expect=(400, 404, 500))
    c.get("/tweets/no-such-tweet", expect=(200, 404, 500))
    c.request("DELETE", "/tweets", contains="Deleted all tweets")


@suite.usecase("NewsPush")
def news_push(c):
    """STOMP over the SockJS endpoint's raw WebSocket: subscribe to /topic/user, then trigger /res and send a message."""
    with c.websocket("/websocket-chat/websocket", headers={"Origin": ORIGIN}) as ws:
        ws.send("CONNECT\naccept-version:1.2\nhost:localhost\nheart-beat:0,0\n\n\x00")
        if not (ws.recv() or "").startswith("CONNECTED"):
            raise UsecaseFailed("the STOMP broker did not accept the connection")
        ws.send("SUBSCRIBE\nid:sub-0\ndestination:/topic/user\n\n\x00")
        c.get("/res")
        pushed = ws.recv() or ""
        if "MESSAGE" not in pushed or "boo" not in pushed:
            raise UsecaseFailed(f"/res pushed {pushed!r}")
        body = json.dumps({"name": "kiosk", "message": "hello"})
        ws.send(f"SEND\ndestination:/app/user-all\ncontent-type:application/json\n\n{body}\x00")
        echoed = ws.recv() or ""
        if "hello" not in echoed:
            raise UsecaseFailed(f"/app/user-all echoed {echoed!r}")
        ws.send(f"SEND\ndestination:/app/user\ncontent-type:application/json\n\n{body}\x00")
        ws.recv()
        ws.send("DISCONNECT\n\n\x00")


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
