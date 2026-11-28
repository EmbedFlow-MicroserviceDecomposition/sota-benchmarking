"""JForum 2.9 (Jakarta EE) functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Black-box scenarios over the forum, written from the FoSCI authors' JMeter plan (tools/fosci/FoSCI/testplan/jforum-testplan.jmx,
37 scenarios) and extended to the admin panel: the web installer, browsing, registration and login, topics and posts
(reply, quote, edit, delete, watch, lock, move, stick, poll, preview), bookmarks, private messages, the profile and avatar,
search, RSS, the moderation log and every admin module (config, categories, forums, groups, users, ranks, smilies,
ban list, spam block, attachments, statistics).

Notes: JForum guards state with OWASP CSRFGuard, whose JavaScript fills the token into forms and links; here every form is
read back from the page (`forms`) and every state-changing link gets the session's token. A new session's first page has no token,
so `Board.start` loads two pages. The installer runs only on a fresh database (the compose file leaves it empty); once the
board is installed the use cases share its Admin account (password `admin`).
"""

import os
import re
import struct
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, forms, unique  # noqa: E402

CTX = "/jforum"
suite = Suite("JForum", os.environ.get("JFORUM_BASE_URL", "http://localhost:8080") + CTX, ready_path="/install.jsp")
CONTAINER_NAME = "jforum-app"

ADMIN, ADMIN_PASSWORD = "Admin", "admin"
PASSWORD = "Pa55word"
LOG = {"log_type": 2, "log_description": "removed by the suite"}  # the moderation log entry a delete writes
PNG = None  # set below
INSTALL = {"dbhost": "mysql", "dbuser": "root", "dbpasswd": "root", "dbpasswd_confirm": "root", "dbencoding": "utf-8",
           "admin_pass1": ADMIN_PASSWORD, "admin_pass2": ADMIN_PASSWORD}


def make_png(width, height):
    """A valid grey PNG of the given size (the app decodes images to make thumbnails)."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


PNG = make_png(16, 16)


def local(url):
    """A link or form action as a path under the context: no host, context root or session id."""
    url = re.sub(r"^https?://[^/]+", "", url)
    url = re.sub(r";jsessionid=[^?#]*", "", url)
    return url[len(CTX):] if url.startswith(CTX + "/") else url


def text(resp):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp.text))


class Board:
    """One browser session on the forum."""

    def __init__(self, c):
        self.c = c
        self.token = ""

    def _remember(self, resp):
        m = re.search(r'name="OWASP_CSRFTOKEN" value="([^"]+)"', resp.text) or re.search(r"OWASP_CSRFTOKEN=([\w-]+)", resp.text)
        if m:
            self.token = m.group(1)
        return resp

    def get(self, path, **kw):
        return self._remember(self.c.get(path, **kw))

    def act(self, path, **kw):
        """A state-changing link: JForum's JavaScript would append the session token."""
        params = dict({"OWASP_CSRFTOKEN": self.token}, **kw.pop("params", {}))
        return self._remember(self.c.get(path, params=params, **kw))

    def start(self):
        self.get("/forums/list.page")
        return self.get("/forums/list.page")

    def form(self, path, form=None, params=None, expect=200, contains=(), absent=(), files=None, page=None, **fields):
        """Load `path` (or take `page`), fill the form (by id, else the one whose action is not search/login), submit it."""
        for attempt in range(4):  # a page can come back without its form while the traced app is busy: load it again
            page = page or self.get(path, params=params)
            found = forms(page)
            wanted = form if form is not None else next(
                (k for k, (_, f) in found.items() if f.get("module") not in ("search", "moderation") and k != "formlogin"
                 and "action" in f), None)
            if wanted in found or attempt == 3:
                break
            page = None
            time.sleep(2)
        form = wanted
        if form not in found:
            raise UsecaseFailed(f"{path}: no form {form!r} among {list(found)}")
        action, values = found[form]
        values = dict(values, **{k: v if isinstance(v, list) else str(v) for k, v in fields.items()})
        resp = self.c.request("POST", local(action), data=values, files=files, expect=expect, contains=contains, absent=absent)
        return self._remember(resp)

    def login(self, username=ADMIN, password=ADMIN_PASSWORD, **checks):
        page = self.start()
        _, values = forms(page)["formlogin"]
        return self._remember(self.c.post("/jforum.page", dict(values, username=username, password=password), **checks))

    def logged_in(self):
        return "user/logout.page" in self.get("/forums/list.page").text


def installed(c):
    resp = c.get("/forums/list.page", expect=None)
    return resp.status == 200 and "installation" not in resp.url and "formlogin" in resp.text or "logout.page" in resp.text


def install(c):
    """The web installer, as in the authors' plan: welcome page, check the information, install, finished."""
    b = Board(c)
    c.get("/install.jsp")
    b.get("/install/install.page", params={"module": "install", "action": "welcome"})
    welcome = b.get("/install/install.page", params={"module": "install", "action": "welcome"})
    _, values = forms(welcome)["install"]
    c.post("/install/install.page", dict(values, **dict(INSTALL, admin_pass2="different")), expect=(200, 302))  # passwords differ
    c.post("/install/install.page", dict(values, **dict(INSTALL, dbpasswd="wrong", dbpasswd_confirm="wrong")), expect=(200, 302))
    step2 = c.post("/install/install.page", dict(values, **INSTALL))
    _, values = forms(step2)["install"]
    c.post("/install/install.page", values, contains="Congratulations", timeout=300)
    c.get("/install/install.page", params={"module": "install", "action": "finished"}, expect=(200, 302))
    admin = Board(suite.client())
    admin.login()
    captcha_off(admin)


def ready_board(c, username=ADMIN, password=ADMIN_PASSWORD):
    """A logged-in Board on an installed forum (installing it first when the database is empty)."""
    if not installed(c):
        install(c)
    b = Board(c)
    b.login(username, password)
    if not b.logged_in():
        raise UsecaseFailed(f"could not log in as {username}")
    return b


def topic_id(resp):
    m = re.search(r"/posts/list/(?:\d+/)?(\d+)\.page", resp.url) or re.search(r"/posts/list/(?:\d+/)?(\d+)\.page", resp.text)
    if not m:
        raise UsecaseFailed(f"{resp.url}: no topic id")
    return int(m.group(1))


def post_shown(b, path, topic, marker, **fields):
    """Submit a post form and wait until the topic shows it: JForum's flood control (a delay between one user's posts, set
    to 0 by `captcha_off`) re-shows the form instead when a setting has not taken effect yet."""
    for _ in range(6):
        b.form(path, message=marker, **fields)
        if marker in b.get(f"/posts/list/{topic}.page").text:
            return
        time.sleep(3)
    raise UsecaseFailed(f"{path}: the post {marker!r} never appeared in topic {topic}")


def new_topic(b, subject=None, message="A first message", forum=1, **fields):
    subject = subject or unique("Topic")
    for _ in range(6):
        resp = b.form(f"/posts/insert/{forum}.page", subject=subject, message=message, **fields)
        if subject in resp.text:
            return topic_id(resp), subject
        time.sleep(3)  # flood control, see post_shown
    raise UsecaseFailed(f"the new topic {subject!r} is not shown")


def captcha_off(b):
    """Turn the registration and post captchas and the flood delay between posts off in the admin configuration."""
    b.get("/admBase/login.page")
    b.form("/adminConfig/list.page", **{"p_captcha.registration": "false", "p_captcha.posts": "false", "p_posts.new.delay": "0"})


@suite.usecase("Install")
def install_forum(c):
    c.get("/install.jsp", expect=(200, 301, 302))
    if not installed(c):
        install(c)
    b = ready_board(c)
    if not b.logged_in():
        raise UsecaseFailed("the Admin account does not work after the install")
    b.get("/install/install.page", params={"module": "install", "action": "welcome"}, expect=(200, 302))


@suite.usecase("Browse")
def browse(c):
    b = ready_board(c)
    for path in ("/forums/list.page", "/forums/show/1.page", "/forums/show/1/15.page", "/posts/list/1.page",
                 "/posts/list/0/1.page", "/recentTopics/list.page", "/hottestTopics/list.page", "/topDownloads/list.page",
                 "/user/list.page", "/user/list/30.page", "/user/profile/2.page", "/posts/listByUser/2.page",
                 "/search/filters.page", "/moderation/showActivityLog.page", "/forums/newMessages.page",
                 "/forums/moderation/1.page", "/js/list/moderation.page", "/ping_session.jsp", "/rss/forumTopics/1.page",
                 "/rss/topicPosts/1.page", "/rss/recentTopics.page", "/rss/hottestTopics.page", "/rss/forums.page"):
        b.get(path, expect=(200, 302))
    b.get("/user/profile/999999.page", expect=(200, 302, 404))
    b.get("/forums/show/999999.page", expect=(200, 302, 404))
    b.get("/posts/list/999999.page", expect=(200, 302, 404))
    b.act("/forums/readAll/1.page", expect=(200, 302))
    b.act("/forums/watchForum/1.page", expect=(200, 302))
    b.act("/forums/unwatchForum/1.page", expect=(200, 302))


@suite.usecase("LoginAndLogout")
def login_logout(c):
    ready_board(c)  # make sure the board exists
    b = Board(suite.client())
    page = b.login("nobody", "wrong")
    if "logout.page" in page.text:
        raise UsecaseFailed("a wrong password logged in")
    b = Board(suite.client())
    b.login(ADMIN, "wrong")
    if b.logged_in():
        raise UsecaseFailed("a wrong password logged Admin in")
    b = Board(suite.client())
    b.login(ADMIN, ADMIN_PASSWORD)
    if not b.logged_in():
        raise UsecaseFailed("Admin could not log in")
    b.get("/user/profile/2.page", contains="Admin")
    b.get("/user/logout.page")
    if b.logged_in():
        raise UsecaseFailed("logout kept the session")


def registration_form(b):
    """The sign-up form: the agreement page leads to it (a second GET of insert.page shows the agreement again)."""
    b.get("/user/insert.page")
    return b.get("/jforum.page", params={"module": "user", "action": "acceptAgreement"})


def post_ids(resp):
    return [int(x) for x in dict.fromkeys(re.findall(r"/posts/edit/\d+/(\d+)\.page", resp.text))]


def user_id(b, username):
    page = b.get("/user/list.page")
    m = re.search(r'/user/profile/(\d+)\.page"[^>]*>\s*' + re.escape(username), page.text)
    if not m:
        raise UsecaseFailed(f"user {username} is not in the member list")
    return int(m.group(1))


def member(c):
    """A freshly registered member's Board, plus the Admin's, on the same installed forum."""
    admin = ready_board(c)
    captcha_off(admin)
    other = suite.client()
    username = unique("member")
    ob = Board(other)
    ob.start()
    ob.form("", page=registration_form(ob), username=username, email=f"{username}@example.com", password=PASSWORD,
            password_confirm=PASSWORD, captchaResponse="x")
    ob = Board(suite.client())
    ob.login(username, PASSWORD)
    if not ob.logged_in():
        raise UsecaseFailed(f"the new member {username} cannot log in")
    return admin, ob, username


@suite.usecase("Register")
def registration(c):
    admin = ready_board(c)
    captcha_off(admin)
    anon = Board(suite.client())
    anon.start()
    form_page = registration_form(anon)
    username = unique("member")
    anon.get("/captcha/generate/1.page", expect=(200, 302))
    anon.get("/jforum.page", params={"module": "captcha", "action": "regenerate", "timestamp": "1"}, expect=(200, 302))
    anon.form("", page=form_page, username=username, email=f"{username}@example.com", password="a",
                      password_confirm="b", captchaResponse="x", expect=(200, 302))
    done = anon.form("", page=registration_form(anon), username=username, email=f"{username}@example.com", password=PASSWORD,
                     password_confirm=PASSWORD, captchaResponse="x")
    dup = Board(suite.client())
    dup.start()
    dup.form("", page=registration_form(dup), username=username, email=f"{username}@example.com", password=PASSWORD,
             password_confirm=PASSWORD, captchaResponse="x", expect=(200, 302))
    anon.get("/user/registrationComplete.page", expect=(200, 302))
    user = Board(suite.client())
    user.login(username, PASSWORD)
    if not user.logged_in():
        raise UsecaseFailed(f"{username} registered but cannot log in: {text(done)[-300:]}")
    user_id(admin, username)


@suite.usecase("Topics")
def topics(c):
    b = ready_board(c)
    captcha_off(b)
    topic, subject = new_topic(b, message="[b]Bold[/b] and [i]italic[/i] :) http://example.com")
    page = b.get(f"/posts/list/{topic}.page", contains=subject)
    first = post_ids(page)[0]
    post_shown(b, f"/posts/reply/0/{topic}.page", topic, "A reply")
    b.get(f"/posts/quote/0/{first}.page", contains="quote")
    post_shown(b, f"/posts/quote/0/{first}.page", topic, "Quoting the first message")
    page = b.get(f"/posts/list/{topic}.page")
    ids = post_ids(page)
    if len(ids) != 3:
        raise UsecaseFailed(f"the topic should hold 3 posts, found {ids}")
    b.get(f"/posts/edit/0/{ids[1]}.page", contains="A reply")
    b.get(f"/posts/review/0/{ids[1]}.page", expect=(200, 302))
    b.form(f"/posts/edit/0/{ids[1]}.page", message="An edited reply", contains="An edited reply")
    b.c.post("/jforum.page", {"module": "ajax", "action": "previewPost", "text": "[b]hi[/b]", "subject": "s", "html": "false",
                              "bbcode": "true", "smilies": "true", "OWASP_CSRFTOKEN": b.token}, expect=(200, 302))
    b.get(f"/posts/preList/{topic}/0.page", expect=(200, 302))
    b.get(f"/posts/list/{topic}/15.page")
    b.act(f"/posts/watch/0/{topic}.page", expect=(200, 302))
    b.act(f"/posts/unwatch/0/{topic}.page", expect=(200, 302))
    b.get("/posts/listByUser/2.page")
    b.act(f"/posts/delete/0/{ids[2]}.page", params=LOG, expect=(200, 302))
    if ids[2] in post_ids(b.get(f"/posts/list/{topic}.page")):
        raise UsecaseFailed("the deleted post is still listed")
    # a poll topic and an announcement
    b.form("/posts/insert/1.page", subject=unique("Poll"), message="Vote please", poll_label="Best colour?",
                  poll_option_1="Red", poll_option_2="Green", poll_option_count="2", poll_length="5")
    b.get("/search/filters.page")
    new_topic(b, topic_type="1")
    new_topic(b, topic_type="2")
    # an empty message is refused
    b.form("/posts/insert/1.page", subject="No body", message="", expect=(200, 302))
    b.act(f"/posts/delete/0/{first}.page", params=LOG, expect=(200, 302))


@suite.usecase("Moderation")
def moderation(c):
    b = ready_board(c)
    captcha_off(b)
    b.form("/adminForums/insert.page", forum_name=unique("Second forum"), description="Moved topics", categories_id=1)
    page = b.get("/adminForums/list.page")
    forum_ids = [int(x) for x in re.findall(r"/adminForums/edit/(\d+)\.page", page.text)]
    if len(forum_ids) < 2:
        raise UsecaseFailed("the second forum was not created")
    topic, _ = new_topic(b)
    back = f"/jforum/posts/list/0/{topic}.page"
    moderate = dict(action="doModeration", module="moderation", returnUrl=back, forum_id=1, topic_id=topic)

    def do(**extra):
        return b.c.post("/jforum.page", dict(moderate, OWASP_CSRFTOKEN=b.token, log_type=3, log_description="no", **extra))

    do(topicLock="1")
    b.get(f"/posts/list/{topic}.page", contains="locked")
    do(topicUnlock="1")
    b.c.post("/jforum.page", dict(moderate, OWASP_CSRFTOKEN=b.token, log_type=0, log_description="", topicMove="1"))
    for target in (forum_ids[-1], 1):
        b.c.post("/jforum.page", {"action": "moveTopic", "module": "moderation", "returnUrl": back, "topics": topic,
                                  "forum_id": 1 if target != 1 else forum_ids[-1], "log_type": 0, "log_description": "no",
                                  "to_forum": target, "submit": "Move", "OWASP_CSRFTOKEN": b.token}, expect=(200, 302))
    b.get("/moderation/showActivityLog.page", contains="Moderation")
    b.get("/js/list/moderation.page")
    b.get("/forums/moderation/1.page", expect=(200, 302))
    page = b.get(f"/posts/list/{topic}.page")
    first = post_ids(page)[0]
    for kind in ("1", "2", "0"):  # sticky, announcement, normal
        b.form(f"/posts/edit/0/{first}.page", topic_type=kind, message="Moderated")
    b.c.post("/jforum.page", dict(moderate, OWASP_CSRFTOKEN=b.token, log_type=3, log_description="no", topicDelete="1"), expect=(200, 302))


@suite.usecase("Bookmarks")
def bookmarks(c):
    b = ready_board(c)
    topic, subject = new_topic(b)
    b.form(f"/bookmarks/insert/2/{topic}.page", title=subject, description="", visible="1")
    page = b.get("/bookmarks/list/2.page", contains=subject)
    m = re.search(r'/posts/list/%d\.page".*?confirmDelete\((\d+)\)' % topic, page.text, re.S)
    if not m:
        raise UsecaseFailed("the bookmark is not listed")
    bid = m.group(1)
    b.form(f"/bookmarks/insert/2/{topic}.page", title=subject, description="Edited description", visible="1")  # opens the edit form
    b.get("/bookmarks/list/1.page", expect=(200, 302))
    b.get("/rss/userBookmarks/2.page", expect=(200, 302, 404))
    b.act(f"/bookmarks/delete/{bid}.page", expect=(200, 302))
    if bid in re.findall(r"confirmDelete\((\d+)\)", b.get("/bookmarks/list/2.page").text):
        raise UsecaseFailed("the bookmark is still listed")


@suite.usecase("PrivateMessages")
def private_messages(c):
    admin, member_b, username = member(c)
    uid = user_id(admin, username)
    subject = unique("Hello")
    admin.get(f"/pm/sendTo/{uid}.page")
    admin.get("/pm/send.page")
    admin.c.post("/jforum.page", {"module": "ajax", "action": "previewPost", "text": "hello", "subject": "hello", "html": "false",
                                  "bbcode": "true", "smilies": "true", "OWASP_CSRFTOKEN": admin.token}, expect=(200, 302))
    admin.form("/pm/send.page", toUsername=username, toUserId=uid, subject=subject, message="Private [b]hello[/b]", preview="1",
               expect=(200, 302))
    for _ in range(6):  # a private message counts for the flood control too
        admin.form("/pm/send.page", toUsername=username, toUserId=uid, subject=subject, message="Private [b]hello[/b]")
        if subject in member_b.get("/pm/inbox.page").text:
            break
        time.sleep(3)
    admin.form("/pm/send.page", toUsername="nobody-here", toUserId="", subject=subject, message="x", expect=(200, 302))
    inbox = member_b.get("/pm/inbox.page", contains=subject)
    ids = re.findall(r"/pm/read/(\d+)\.page", inbox.text)
    if not ids:
        raise UsecaseFailed("the message is not in the inbox")
    mid = ids[0]
    member_b.get(f"/pm/read/{mid}.page", contains="Private")
    member_b.get(f"/pm/quote/{mid}.page", expect=(200, 302))
    member_b.form(f"/pm/quote/{mid}.page", message="Replying", subject="Re: " + subject, expect=(200, 302))
    member_b.get("/pm/sentbox.page", expect=(200, 302))
    member_b.get("/pm/review/%s.page" % mid, expect=(200, 302))
    admin.get("/pm/inbox.page", contains="Re: " + subject)
    member_b.get(f"/pm/read/{mid}.page")
    member_b.c.post("/jforum.page", {"module": "pm", "action": "delete", "id": mid, "delete": "Delete this message",
                                     "OWASP_CSRFTOKEN": member_b.token}, expect=(200, 302))
    if mid in re.findall(r"/pm/read/(\d+)\.page", member_b.get("/pm/inbox.page").text):
        raise UsecaseFailed("the deleted message is still in the inbox")


@suite.usecase("Profile")
def profile(c):
    admin, b, username = member(c)
    uid = user_id(admin, username)
    b.get(f"/user/profile/{uid}.page", contains=username)
    b.get(f"/user/edit/{uid}.page", contains=username)
    b.form(f"/user/edit/{uid}.page", email=f"{username}@example.com", biography="About me", signature="-- sig", website="http://example.com",
           location="Colombo", occupation="Tester", interests="Forums")
    b.get(f"/user/editDone/{uid}.page", expect=(200, 302))
    new_password = PASSWORD + "2"
    b.form(f"/user/edit/{uid}.page", email=f"{username}@example.com", current_password=PASSWORD, new_password=new_password,
           password_confirm=new_password)
    b.form(f"/user/edit/{uid}.page", email=f"{username}@example.com", current_password="wrong", new_password=new_password,
           password_confirm=new_password, expect=(200, 302))
    b.form(f"/user/edit/{uid}.page", email="not-an-email", expect=(200, 302))
    b.form(f"/user/edit/{uid}.page", email=f"{username}@example.com", files={"avatar": ("me.png", PNG, "image/png")}, expect=(200, 302))
    b.get(f"/user/edit/{uid}.page", expect=(200, 302))
    b.get("/user/profile/2.page", expect=(200, 302))
    b.get("/user/edit/2.page", expect=(200, 302))  # someone else's profile
    again = Board(suite.client())
    again.login(username, new_password)
    if not again.logged_in():
        raise UsecaseFailed("the changed password does not work")


@suite.usecase("Search")
def search(c):
    b = ready_board(c)
    topic, subject = new_topic(b, message="zymurgy fermentation notes")
    b.get("/search/filters.page")
    for kw in ("zymurgy", "fermentation notes", "nothing-matches-this"):
        for match in ("all", "any"):
            b.get("/jforum.page", params={"module": "search", "action": "search", "search_keywords": kw, "match_type": match,
                                          "search_forum": "", "sort_by": "relevance", "sort_dir": "DESC"}, expect=(200, 302))
    b.get("/jforum.page", params={"module": "search", "action": "search", "search_keywords": "zymurgy", "match_type": "all",
                                  "search_forum": "1", "sort_by": "time", "sort_dir": "ASC"}, expect=(200, 302))
    b.get("/jforum.page", params={"module": "search", "action": "search", "search_author": "Admin", "match_type": "all"}, expect=(200, 302))
    b.get("/search/newMessages.page", expect=(200, 302))
    b.get("/jforum.page", params={"module": "search", "action": "searchByUser", "user_id": 2}, expect=(200, 302))


def admin_board(c):
    b = ready_board(c)
    b.get("/admBase/login.page")
    b.get("/admBase/menu.page")
    b.get("/admBase/main.page")
    return b


def admin_delete(b, module, field, item, **extra):
    """The delete form every admin list ends in: a checkbox per row."""
    resp = b.c.post("/jforum.page", dict({"action": "delete", "module": module, field: item, "OWASP_CSRFTOKEN": b.token}, **extra),
                    expect=(200, 302))
    return resp


def ids_in(b, path, pattern):
    return [int(x) for x in dict.fromkeys(re.findall(pattern, b.get(path).text))]


@suite.usecase("AdminConfig")
def admin_config(c):
    b = admin_board(c)
    b.form("/adminConfig/list.page", **{"p_forum.name": "Test Board", "p_topicsPerPage": "20", "p_postsPerPage": "15"})
    b.get("/adminConfig/list.page", contains="Test Board")
    b.form("/adminConfig/list.page", **{"p_forum.name": "My Forum", "p_topicsPerPage": "15"})
    b.get("/adminBoardStats/list.page")
    b.get("/adminBoardStats/showLast.page", expect=(200, 302))
    b.get("/adminCache/list.page")
    b.get("/adminCache/topics.page", expect=(200, 302))
    b.get("/adminCache/posts.page", expect=(200, 302))
    b.get("/adminModeration/list.page")
    b.get("/adminAnnouncement/list.page", expect=(200, 302))
    b.get("/adminSearchStats/list.page")
    b.form("/adminSearchStats/list.page", type="1", expect=(200, 302))  # reindex everything
    b.get("/adminBanner/list.page")
    b.get("/adminBanner/insert.page", expect=(200, 302))


@suite.usecase("AdminForums")
def admin_forums(c):
    b = admin_board(c)
    name = unique("Category")
    b.form("/adminCategories/insert.page", category_name=name, moderate="0", contains=name)
    cid = max(ids_in(b, "/adminCategories/list.page", r"/adminCategories/edit/(\d+)\.page"))
    b.form(f"/adminCategories/edit/{cid}.page", category_name=name + " renamed")
    b.get(f"/adminCategories/up/{cid}.page", expect=(200, 302))
    b.get(f"/adminCategories/down/{cid}.page", expect=(200, 302))
    forum_name = unique("Forum")
    b.form("/adminForums/insert.page", forum_name=forum_name, description="Created by the suite", categories_id=cid)
    fid = max(ids_in(b, "/adminForums/list.page", r"/adminForums/edit/(\d+)\.page"))
    b.form(f"/adminForums/edit/{fid}.page", forum_name=forum_name + " renamed", description="Edited")
    b.get(f"/adminForums/up/{fid}.page", expect=(200, 302))
    b.get(f"/adminForums/down/{fid}.page", expect=(200, 302))
    b.get(f"/forums/show/{fid}.page", contains="renamed")
    b.get(f"/forums/show/{fid}.page")
    b.get(f"/forums/moderation/{fid}.page", expect=(200, 302))
    admin_delete(b, "adminForums", "forum_id", fid)
    if fid in ids_in(b, "/adminForums/list.page", r"/adminForums/edit/(\d+)\.page"):
        raise UsecaseFailed("the forum was not deleted")
    admin_delete(b, "adminCategories", "categories_id", cid)
    if cid in ids_in(b, "/adminCategories/list.page", r"/adminCategories/edit/(\d+)\.page"):
        raise UsecaseFailed("the category was not deleted")


@suite.usecase("AdminGroupsAndUsers")
def admin_groups_users(c):
    admin, ob, username = member(c)
    b = admin
    b.get("/admBase/login.page")
    group = unique("Group")
    b.form("/adminGroups/insert.page", group_name=group, group_description="Suite group", parent_id="0")
    gid = max(ids_in(b, "/adminGroups/list.page", r"/adminGroups/edit/(\d+)\.page"))
    b.form(f"/adminGroups/edit/{gid}.page", group_name=group + " renamed")
    b.get(f"/adminGroups/permissions/{gid}.page")
    b.form(f"/adminGroups/permissions/{gid}.page", form="form1", expect=(200, 302))
    uid = user_id(b, username)
    b.get("/adminUsers/list.page")
    b.form("/adminUsers/list.page", form="formusersearch", username=username, contains=username)
    b.get("/adminUsers/search.page", expect=(200, 302))
    b.get(f"/adminUsers/edit/{uid}.page")
    b.form(f"/adminUsers/edit/{uid}.page", email=f"{username}@example.com", biography="Edited by an admin")
    b.get(f"/adminUsers/groups/{uid}.page")
    b.form(f"/adminUsers/groups/{uid}.page", groups="1")
    b.get("/adminUsers/pendingActivations.page")
    b.get("/adminUsers/search.page", params={"username": username}, expect=(200, 302))
    admin_delete(b, "adminGroups", "group_id", gid)
    lock = dict(comment="locked by the suite", start="0")
    admin_delete(b, "adminUsers", "user_id", uid, **lock)  # the admin "delete" only locks the account (it stays listed)
    b.get("/adminUsers/list.page", contains=username)
    admin_delete(b, "adminUsers", "user_id", uid, **lock)  # and the second one unlocks it
    b.get("/adminUsers/list.page", contains=username)


@suite.usecase("AdminCustomisation")
def admin_customisation(c):
    b = admin_board(c)
    title = unique("Rank")
    b.form("/adminRankings/insert.page", rank_title=title, rank_min="5000", contains=title)
    rid = max(ids_in(b, "/adminRankings/list.page", r"/adminRankings/edit/(\d+)\.page"))
    b.form(f"/adminRankings/edit/{rid}.page", rank_title=title + " edited")
    admin_delete(b, "adminRankings", "rank_id", rid)
    code = ":" + unique("sm")[:6] + ":"
    b.form("/adminSmilies/insert.page", code=code, files={"smilie_img": ("smile.png", PNG, "image/png")}, expect=(200, 302))
    b.get("/adminSmilies/list.page")
    sids = ids_in(b, "/adminSmilies/list.page", r"/adminSmilies/edit/(\d+)\.page")
    b.form(f"/adminSmilies/edit/{sids[-1]}.page", code=code, expect=(200, 302))
    admin_delete(b, "adminSmilies", "id", sids[-1])
    value = unique("ban") + "@example.com"
    b.form("/adminBanning/insert.page", value=value, type="email", contains=value)
    bids = ids_in(b, "/adminBanning/list.page", r'name="banlist_id" value="(\d+)"')
    admin_delete(b, "adminBanning", "banlist_id", bids[-1])
    def post(module, action, **fields):
        b.c.post("/jforum.page", dict(fields, module=module, action=action, OWASP_CSRFTOKEN=b.token), expect=(200, 302))

    pattern = unique("spam")
    post("adminSpamBlock", "insert", pattern=pattern)
    b.get("/adminSpamBlock/list.page", contains=pattern)
    post("adminSpamBlock", "delete", pattern=pattern)
    b.get("/adminSpamBlock/list.page", absent=pattern)
    # an entry in the registration e-mail list turns it into a whitelist, so it is removed again
    entry = unique("blocked") + "@example.com"
    post("adminRegEmail", "insertEmailOrDomain", email=entry, group="1")
    b.get("/adminRegEmail/list.page", contains=entry)
    post("adminRegEmail", "delete", email=entry)
    b.get("/adminRegEmail/list.page", absent=entry)


@suite.usecase("AdminAttachments")
def admin_attachments(c):
    b = admin_board(c)
    b.get("/adminAttachments/configurations.page")
    b.form("/adminAttachments/configurations.page", expect=(200, 302))
    group = unique("Group")
    b.form("/adminAttachments/extensionGroups.page", form="formAdd", name=group, download_mode="1", expect=(200, 302))
    b.get("/adminAttachments/extensionGroups.page", contains=group)
    ext = unique("x")[:6]
    b.form("/adminAttachments/extensions.page", form="formAdd", extension=ext, comment="a suite extension", expect=(200, 302))
    b.get("/adminAttachments/extensions.page", contains=ext)
    b.form("/adminAttachments/quotaLimit.page", form="form1", quota_description=unique("quota"), max_filesize="1024", type="1",
           expect=(200, 302))
    b.get("/adminAttachments/quotaLimit.page")
    b.form("/adminAttachments/quotaLimit.page", form="form2", expect=(200, 302))
    b.get("/topDownloads/list.page")


@suite.usecase("Attachments")
def attachments(c):
    admin, member_b, _ = member(c)
    # thumbnails are made for pictures above the size limit; a tiny limit keeps the app's per-pixel scaling short
    admin.form("/adminAttachments/configurations.page", **{"p_attachments.images.createthumb": "true",
                                                           "p_attachments.images.thumb.maxsize.w": "8",
                                                           "p_attachments.images.thumb.maxsize.h": "8"})
    subject = unique("Attached")
    resp = admin.form("/posts/insert/1.page", subject=subject, message="with a picture", total_files="1", comment_0="a picture",
                      files={"file_0": ("big.png", PNG, "image/png")})
    topic = topic_id(resp)
    ids = re.findall(r"downloadAttach/(\d+)", admin.get(f"/posts/list/{topic}.page").text)
    if not ids:
        raise UsecaseFailed("the attachment is not listed on the post")
    for who in (admin, member_b):
        who.get(f"/posts/downloadAttach/{ids[0]}.page", expect=(200, 302))
    admin.get("/topDownloads/list.page", contains="big.png")
    admin.form("/posts/insert/1.page", subject=unique("Text file"), message="a text attachment", total_files="1", comment_0="notes",
               files={"file_0": ("notes.txt", b"plain notes", "text/plain")}, expect=(200, 302))
    admin.form("/posts/insert/1.page", subject=unique("Bad extension"), message="not allowed", total_files="1", comment_0="x",
               files={"file_0": ("run.exe", b"MZ", "application/octet-stream")}, expect=(200, 302))
    post = post_ids(admin.get(f"/posts/list/{topic}.page"))[0]
    admin.form(f"/posts/edit/0/{post}.page", message="the picture is removed", delete_attach=ids[0], expect=(200, 302))
    admin.get("/posts/downloadAttach/999999.page", expect=(200, 302, 404))


@suite.usecase("Karma")
def karma(c):
    admin, member_b, _ = member(c)
    topic, _ = new_topic(admin, message="A post to rate")
    post = post_ids(admin.get(f"/posts/list/{topic}.page"))[0]
    for points in (4, 5, 1):
        member_b.get(f"/karma/insert/0/{post}/{points}.page", expect=(200, 302))
    admin.get(f"/karma/insert/0/{post}/3.page", expect=(200, 302))  # one's own post
    member_b.get(f"/posts/list/{topic}.page")
    admin.get("/karma/list.page", expect=(200, 302))
    admin.get("/karma/searchByPeriod/1/2.page", expect=(200, 302))
    admin.get("/karma/searchByMonth/1.page", expect=(200, 302))
    admin.get("/rss/userPosts/2.page")


@suite.usecase("Banners")
def banners(c):
    b = admin_board(c)
    name = unique("banner")
    page = b.form("/adminBanner/list.page")  # the "new banner" button posts action=insert and gets the form back
    b.form("", page=page, name=f'<a href="http://example.com">{name}</a>', description=name, url="http://example.com", weight="50",
           width="468", height="60", active="1", placement="1", type="1", comment=name)
    listing = b.get("/adminBanner/list.page", contains=name)
    bid = int(re.search(r"/adminBanner/edit/(\d+)\.page", listing.text).group(1))
    b.get(f"/adminBanner/edit/{bid}.page")
    b.form(f"/adminBanner/edit/{bid}.page", comment="edited")
    for place in ("/forums/list.page", "/forums/show/1.page", "/posts/list/1.page"):
        b.get(place)
    b.get("/banner/list.page", expect=(200, 302))
    b.get(f"/banner/redirect/{bid}.page", expect=(200, 302))
    b.get(f"/adminBanner/delete/{bid}.page", expect=(200, 302))


@suite.usecase("RestApi")
def rest_api(c):
    b = ready_board(c)
    # API keys are created in the database only, so the calls are refused: they still run the authentication
    b.get("/jforum.page", params={"module": "userApi", "action": "list", "api_key": "not-a-key"}, expect=(200, 302, 401, 403))
    b.get("/userApi/list/not-a-key.page", expect=(200, 302, 401, 403))
    b.c.post("/userApi/insert/not-a-key/rest-user/rest@example.com/secret.page", {}, expect=(200, 302, 401, 403))
    b.c.post("/postApi/insert/not-a-key/rest@example.com/1.page", {"subject": "s", "message": "m"}, expect=(200, 302, 401, 403))


@suite.usecase("ModeratedForum")
def moderated_forum(c):
    admin, member_b, _ = member(c)
    admin.get("/admBase/login.page")
    admin.form("/adminForums/edit/1.page", moderate="1")
    try:
        subject = unique("Pending")
        member_b.form("/posts/insert/1.page", subject=subject, message="Waits for a moderator")
        member_b.form("/posts/insert/1.page", subject=unique("Rejected"), message="A moderator will reject this")
        if subject in member_b.get("/forums/show/1.page").text:
            raise UsecaseFailed("a post in a moderated forum was published at once")
        admin.get("/adminModeration/list.page")
        page = admin.get("/adminModeration/view/1.page")
        pending = [int(x) for x in re.findall(r'name="status_(\d+)"', page.text)] or \
                  [int(x) for x in re.findall(r"status_(\d+)", str(forms(page)))]
        if len(pending) < 2:
            raise UsecaseFailed("the moderation queue does not hold the two posts")
        fields = {f"status_{pending[0]}": "approve", f"status_{pending[1]}": "reject", f"comment_{pending[1]}": "off topic"}
        for extra in pending[2:]:
            fields[f"status_{extra}"] = "defer"
        admin.form("/adminModeration/view/1.page", **fields)
        admin.get("/forums/show/1.page", contains=subject)
        admin.get("/moderation/showActivityLog.page")
    finally:
        admin.form("/adminForums/edit/1.page", moderate="0")


@suite.usecase("Polls")
def polls(c):
    b = ready_board(c)
    captcha_off(b)
    subject = unique("Poll")
    resp = b.form("/posts/insert/1.page", subject=subject, message="Vote please", poll_label="Best colour?", poll_option_1="Red",
                  poll_option_2="Green", poll_option_count="2", poll_length="5")
    topic = topic_id(resp)
    page = b.get(f"/posts/list/{topic}.page", contains="Best colour?")
    voting = next((f for _, f in forms(page).values() if f.get("action") == "vote"), None)
    if voting is None:
        raise UsecaseFailed("the poll has no vote form")
    for choice in ("1", "2", "1"):  # the second and third votes come from a user who already voted
        b.c.post("/jforum.page", dict(voting, poll_option=choice, OWASP_CSRFTOKEN=b.token), expect=(200, 302))
    first = post_ids(page)[0]
    b.form(f"/posts/edit/0/{first}.page", poll_label="Favourite colour?", poll_length="7")
    b.get(f"/posts/list/{topic}.page", contains="Favourite colour?")
    other = Board(suite.client())
    other.login()
    other.c.post("/jforum.page", dict(voting, poll_option="2", OWASP_CSRFTOKEN=other.token), expect=(200, 302))


@suite.usecase("Mail")
def mail(c):
    """Every kind of notification mail. No SMTP server listens in the compose file, so the sends fail in the app's mail thread;
    the use case still drives each notification path (and restores the settings that would block other registrations)."""
    admin, member_b, username = member(c)
    admin.form("/user/edit/2.page", email="admin@example.com")
    admin.get("/admBase/login.page")
    admin.form("/adminConfig/list.page", **{"p_mail.notify.answers": "true", "p_mail.smtp.auth": "false", "p_mail.smtp.host": "localhost"})
    try:
        topic, _ = new_topic(admin, message="Watched by e-mail")
        admin.act(f"/posts/watch/0/{topic}.page", expect=(200, 302))
        member_b.form(f"/posts/reply/0/{topic}.page", message="A reply that triggers a notification")  # TopicReplySpammer
        admin.act("/forums/watchForum/1.page", expect=(200, 302))
        new_topic(member_b)  # ForumNewTopicSpammer
        member_b.form("/pm/send.page", toUsername=ADMIN, toUserId=2, subject=unique("Mail"), message="A private message")  # PrivateMessageSpammer
        admin.c.post("/jforum.page", {"module": "ajax", "action": "sendTestMail", "sender": "a@example.com", "host": "localhost",
                                      "port": "25", "auth": "false", "ssl": "false", "username": "", "password": "", "to": "b@example.com",
                                      "additionalProperties": "", "OWASP_CSRFTOKEN": admin.token}, expect=(200, 302))
        # lost password: the mail's recovery link cannot be read back, so a wrong hash exercises the failure path
        anon = Board(suite.client())
        anon.start()
        anon.get("/user/lostPassword.page")
        anon.form("/user/lostPassword.page", username=username, email=f"{username}@example.com", expect=(200, 302))
        anon.form("/user/lostPassword.page", username="nobody-here", email="nobody@example.com", expect=(200, 302))
        anon.get("/user/recoverPassword/not-a-hash.page", expect=(200, 302))
        anon.c.post("/jforum.page", {"module": "user", "action": "recoverPasswordValidate", "recoverHash": "not-a-hash",
                                     "email": f"{username}@example.com", "newPassword": "x", "OWASP_CSRFTOKEN": anon.token},
                    expect=(200, 302))
        # e-mail activation: a new member gets an activation key (ActivationKeySpammer) and cannot sign in yet
        admin.form("/adminConfig/list.page", **{"p_mail.user.email.auth": "true"})
        pending = Board(suite.client())
        pending.start()
        name = unique("pending")
        pending.form("", page=registration_form(pending), username=name, email=f"{name}@example.com", password=PASSWORD,
                     password_confirm=PASSWORD, captchaResponse="x")
        late = Board(suite.client())
        late.login(name, PASSWORD)
        pending.get("/user/activateAccount/not-a-hash/1.page", expect=(200, 302))
        pending.get("/user/activateManual.page", expect=(200, 302))
        pending.form("/user/activateManual.page", username=name, expect=(200, 302))
        admin.get("/adminUsers/pendingActivations.page", expect=(200, 302))
    finally:
        admin.form("/adminConfig/list.page", **{"p_mail.notify.answers": "false", "p_mail.user.email.auth": "false"})
        admin.get("/forums/unwatchForum/1.page", expect=(200, 302))


@suite.usecase("AttachmentLimits")
def attachment_limits(c):
    """A denied extension and an upload over the group quota are both refused (the settings are put back afterwards)."""
    b = admin_board(c)
    captcha_off(b)
    b.form("/adminAttachments/extensionGroups.page", form="formAdd", name=unique("Blocked"), download_mode="1")
    b.form("/adminAttachments/extensions.page", form="formAdd", extension="exe", comment="never allowed")  # "allow" left unticked
    refused = b.form("/posts/insert/1.page", subject=unique("Bad extension"), message="an executable", total_files="1", comment_0="x",
                     files={"file_0": ("run.exe", b"MZ" + bytes(300), "application/octet-stream")}, expect=(200, 302))
    if "downloadAttach" in refused.text:
        raise UsecaseFailed("a denied extension was accepted")
    tiny = unique("tiny")
    b.form("/adminAttachments/quotaLimit.page", form="form1", quota_description=tiny, max_filesize="1", type="1")
    page = b.get("/adminAttachments/quotaLimit.page")
    quota = re.search(r'<option value="(\d+)"\s*>\s*%s' % tiny, re.search(r'<select name="limit_0">.*?</select>', page.text, re.S).group(0)).group(1)
    groups = {"group_0": "2", "group_1": "1"}
    try:
        b.form("/adminAttachments/quotaLimit.page", form="form2", limit_0=quota, limit_1=quota, **groups)
        for _ in range(5):  # the quota may take a moment to apply
            big = b.form("/posts/insert/1.page", subject=unique("Too big"), message="over the quota", total_files="1", comment_0="x",
                         files={"file_0": ("big.txt", b"x" * 4096, "text/plain")}, expect=(200, 302))
            if "downloadAttach" not in big.text:
                break
            time.sleep(2)
        else:
            raise UsecaseFailed("an upload over the quota was accepted")
        b.form("/posts/insert/1.page", subject=unique("Small"), message="under the quota", total_files="1", comment_0="x",
               files={"file_0": ("small.txt", b"hello", "text/plain")}, expect=(200, 302))
    finally:
        b.form("/adminAttachments/quotaLimit.page", form="form2", limit_0="", limit_1="", **groups)


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
