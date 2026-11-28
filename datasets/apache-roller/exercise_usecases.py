"""Apache Roller 6.1 functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Black-box scenarios over the blog server, written from the FoSCI authors' 78 scenarios
(tools/fosci/FoSCI/testscenario/roller-ts.txt): the auto-installer, registration and login, weblogs and their settings,
entries (draft, publish, edit, delete, tags, categories), the public site (home, entry, archives, search, feeds), comments,
categories, the blogroll (folders, bookmarks, OPML import), media files, themes and templates, members and pings, and the
site administration (global config, users, cache, ping targets, planet groups and subscriptions).

Notes: Roller's Struts2 forms carry a `salt` token and name their buttons `action:<action>!<method>`, so every form is read
back from the page (`forms`) and submitted with the button a browser would send. The first user to register becomes the global
admin: the suite registers `admin` / `admin123` on a fresh database and signs in as that user afterwards.
"""

import base64
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, forms, unique  # noqa: E402

suite = Suite("Roller", os.environ.get("ROLLER_BASE_URL", "http://localhost:8080"), ready_path="/")
CONTAINER_NAME = "roller-app"

ADMIN, ADMIN_PASSWORD = "admin", "admin123"
PASSWORD = "Pa55word1"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
AUTHORING = "/roller-ui/authoring"


def text(resp):
    return re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", resp.text, flags=re.S))


class Roller:
    """One browser session on the site."""

    def __init__(self, c):
        self.c = c

    def get(self, path, **kw):
        return self.c.get(path, **kw)

    def form(self, path, form=None, button=None, params=None, page=None, files=None, expect=200, contains=(), absent=(), **fields):
        """Load `path` (or take `page`), fill the form (by id; else the first one with a salt that is not a list-row remover),
        press `button` (a Struts `<action>!<method>`) and submit."""
        page = page or self.get(path, params=params)
        found = forms(page)
        if form is None:
            form = next((k for k, (_, f) in found.items() if "salt" in f and not str(k).startswith(("entryRemove", "searchForm"))), None)
        if form not in found:
            raise UsecaseFailed(f"{path}: no form {form!r} among {list(found)}")
        action, values = found[form]
        values = dict(values, **{k: v if isinstance(v, list) else str(v) for k, v in fields.items()})
        if button:
            values["action:" + button] = "go"
        return self.c.request("POST", action, data=values, files=files, expect=expect, contains=contains, absent=absent)

    def login(self, username=ADMIN, password=ADMIN_PASSWORD, **checks):
        action, values = forms(self.get("/roller-ui/login.rol"))["loginForm"]
        return self.c.post(action, dict(values, j_username=username, j_password=password), **dict({"expect": None}, **checks))

    def logged_in(self):
        return "/roller-ui/logout.rol" in self.get("/roller-ui/menu.rol", expect=None).text


def install(c):
    """The auto-installer: create the tables, then bootstrap."""
    page = c.get("/")
    action, values = forms(page)["install"]
    c.post(action, values, contains="Tables created", timeout=300)
    c.get("/roller-ui/install/install!bootstrap.rol", timeout=300)


def register_form(c):
    """The sign-up form (action, fields). Registration is switched on in the global config, which takes a moment to show."""
    for _ in range(20):
        found = forms(c.get("/roller-ui/register.rol"))
        if "register" in found:
            return found["register"]
        time.sleep(2)
    raise UsecaseFailed("the registration form never appeared: registration is disabled")


def register(c, username, password=PASSWORD, **checks):
    action, values = register_form(c)
    values = dict(values, **{"bean.userName": username, "bean.screenName": username.title(), "bean.fullName": f"{username} Tester",
                             "bean.emailAddress": f"{username}@example.com", "bean.passwordText": password,
                             "bean.passwordConfirm": password})
    return c.post(action, values, **checks)


def ready(c):
    """A signed-in admin session on an installed site (installing and registering the admin when the site is new)."""
    c.timeout = 180  # planet subscriptions fetch feeds, the traced app is slow
    if "Auto-Installer" in c.get("/").text:
        install(c)
    r = Roller(c)
    r.login()
    if not r.logged_in():
        c.get("/roller-ui/logout.rol", expect=None)
        register(c, ADMIN, ADMIN_PASSWORD, contains="has been created")
        r.login()
    if not r.logged_in():
        raise UsecaseFailed("cannot sign in as the admin")
    # The global config page cannot be saved while no weblog exists (its front-page weblog list is empty): make one first.
    if "site.frontpage.weblog.handle" not in forms(r.get("/roller-ui/admin/globalConfig.rol"))["globalConfig"][1]:
        add_weblog(r, "frontpage")
    # registration is off once the first user exists: switch it on (and weblog creation, no e-mail activation, media uploads)
    r.form("/roller-ui/admin/globalConfig.rol", **{"users.registration.enabled": "true", "site.allowUserWeblogCreation": "true",
                                                  "user.account.email.activation": "false", "uploads.enabled": "true",
                                                  "webservices.enableAtomPub": "true", "webservices.enableXmlRpc": "true",
                                                  "webservices.atomPubAuth": "basic"})  # the page shows "basic " with a space: send it clean
    register_form(suite.client())
    return r


def new_member(c):
    """An admin session plus a signed-in session of a freshly registered ordinary user."""
    admin = ready(c)
    username = unique("user").lower()
    other = suite.client()
    register(other, username, contains="has been created")
    member = Roller(other)
    member.login(username, PASSWORD)
    if not member.logged_in():
        raise UsecaseFailed(f"the new user {username} cannot sign in")
    return admin, member, username


def add_weblog(r, handle=None, theme="basic", **fields):
    handle = (handle or unique("blog")).lower()
    r.form("/roller-ui/createWeblog.rol", **{"bean.name": f"Blog {handle}", "bean.handle": handle, "bean.theme": theme}, **fields,
           contains=handle)
    return handle


def add_entry(r, handle, title=None, body="An entry body", publish=True, **fields):
    """Post (or save as a draft) an entry; returns (entry id, public anchor)."""
    title = title or unique("Entry")
    resp = r.form(f"{AUTHORING}/entryAdd.rol", params={"weblog": handle}, button="entryAdd!publish" if publish else "entryAdd!saveDraft",
                  **{"bean.title": title, "bean.text": body}, **fields)
    entry_id = re.search(r"bean\.id=([\w-]+)", resp.url) or re.search(r'name="bean\.id" value="([\w-]+)"', resp.text)
    if not entry_id:
        raise UsecaseFailed(f"adding the entry {title!r} did not lead to its edit page: {text(resp)[-300:]}")
    anchor = re.search(r"/%s/entry/([\w.-]+)" % re.escape(handle), resp.text)
    return entry_id.group(1), anchor.group(1) if anchor else None


@suite.usecase("Install")
def install_site(c):
    if "Auto-Installer" in c.get("/").text:
        install(c)
    c.get("/roller-ui/install/install.rol", expect=(200, 302, 404))
    c.get("/")
    r = ready(c)
    r.get("/roller-ui/menu.rol", contains="Your Profile")


@suite.usecase("Registration")
def registration(c):
    ready(c)
    anon = suite.client()
    username = unique("user").lower()
    action, values = register_form(anon)
    base = dict(values, **{"bean.userName": username, "bean.screenName": username, "bean.fullName": "A User",
                           "bean.emailAddress": f"{username}@example.com", "bean.passwordText": PASSWORD, "bean.passwordConfirm": PASSWORD})
    anon.post(action, dict(base, **{"bean.passwordConfirm": "different"}), expect=(200, 302))  # passwords differ
    anon.post(action, dict(base, **{"bean.emailAddress": "not-an-email"}), expect=(200, 302))
    anon.post(action, dict(base, **{"bean.userName": ""}), expect=(200, 302))
    anon.post(action, base, contains="has been created")
    anon.post(action, base, expect=(200, 302))  # the user name is taken
    anon.get("/roller-ui/register!activate.rol", params={"activationCode": "no-such-code"}, expect=(200, 302, 404))
    member = Roller(anon)
    member.login(username, PASSWORD)
    if not member.logged_in():
        raise UsecaseFailed("the registered user cannot sign in")


@suite.usecase("LoginAndProfile")
def login_and_profile(c):
    ready(c)
    anon = suite.client()
    username = unique("user").lower()
    register(anon, username, contains="has been created")
    bad = Roller(suite.client())
    bad.login(username, "wrong")
    if bad.logged_in():
        raise UsecaseFailed("a wrong password signed in")
    bad.login("nobody-here", PASSWORD)
    me = Roller(anon)
    me.login(username, PASSWORD)
    if not me.logged_in():
        raise UsecaseFailed("sign-in failed")
    me.get("/roller-ui/menu.rol", contains="Your Profile")
    me.form("/roller-ui/profile.rol", **{"bean.fullName": "Renamed Person", "bean.screenName": "Renamed"})
    me.get("/roller-ui/profile.rol", contains="Renamed Person")
    new = PASSWORD + "9"
    me.form("/roller-ui/profile.rol", **{"bean.passwordText": new, "bean.passwordConfirm": new})
    me.form("/roller-ui/profile.rol", **{"bean.passwordText": "x", "bean.passwordConfirm": "y"}, expect=(200, 302))
    me.get("/roller-ui/logout.rol")
    if me.logged_in():
        raise UsecaseFailed("logout kept the session")
    again = Roller(suite.client())
    again.login(username, new)
    if not again.logged_in():
        raise UsecaseFailed("the changed password does not work")
    suite.client().get("/roller-ui/authoring/entryAdd.rol", params={"weblog": "blog1"}, expect=(200, 302, 403))  # anonymous


@suite.usecase("Weblogs")
def weblogs(c):
    admin, member, username = new_member(c)
    handle = add_weblog(member)
    member.get("/roller-ui/menu.rol", contains=handle)
    member.form("/roller-ui/createWeblog.rol", **{"bean.name": "Again", "bean.handle": handle, "bean.theme": "basic"}, expect=(200, 302))
    member.form("/roller-ui/createWeblog.rol", **{"bean.name": "", "bean.handle": "bad handle!", "bean.theme": "basic"}, expect=(200, 302))
    member.form(f"{AUTHORING}/weblogConfig.rol", params={"weblog": handle}, **{"bean.name": "Renamed blog", "bean.tagline": "A tagline",
                "bean.about": "About this blog", "bean.entryDisplayCount": "7", "__checkbox_bean.enableMultiLang": "true"})
    member.get(f"/{handle}/", contains="Renamed blog")
    member.get(f"{AUTHORING}/members.rol", params={"weblog": handle})
    member.get(f"{AUTHORING}/pings.rol", params={"weblog": handle})
    for button in ("maintenance!flushCache", "maintenance!index"):
        member.form(f"{AUTHORING}/maintenance.rol", params={"weblog": handle}, button=button)
    member.get(f"{AUTHORING}/weblogRemove.rol", params={"weblog": handle})
    other = Roller(suite.client())
    other.login()
    other.get(f"{AUTHORING}/weblogConfig.rol", params={"weblog": handle}, expect=(200, 302, 403))
    member.form(f"{AUTHORING}/weblogRemove.rol", form="weblogRemove", params={"weblog": handle}, button=None, expect=(200, 302))
    member.get(f"/{handle}/", expect=(200, 404))


@suite.usecase("Entries")
def entries(c):
    r = ready(c)
    handle = add_weblog(r)
    draft_id, _ = add_entry(r, handle, publish=False, body="A draft")
    entry_id, anchor = add_entry(r, handle, title="Hello Entries", body="Published body with <b>markup</b>", **{"bean.tagsAsString": "alpha beta"})
    r.get(f"{AUTHORING}/entries.rol", params={"weblog": handle}, contains="Hello Entries")
    r.form(f"{AUTHORING}/entries.rol", params={"weblog": handle}, form="entries", **{"bean.text": "Hello", "bean.status": "PUBLISHED"},
           button=None, expect=(200, 302))
    r.get(f"{AUTHORING}/entries!query.rol", params={"weblog": handle, "bean.text": "Hello", "bean.tagsAsString": "alpha"}, expect=(200, 302, 404))
    r.get(f"{AUTHORING}/entryEdit.rol", params={"weblog": handle, "bean.id": entry_id}, contains="Hello Entries")
    r.form(f"{AUTHORING}/entryEdit.rol", params={"weblog": handle, "bean.id": entry_id}, form="entry", button="entryEdit!publish",
           **{"bean.title": "Hello Entries edited", "bean.text": "Edited body", "bean.pinnedToMain": "true"})
    r.form(f"{AUTHORING}/entryEdit.rol", params={"weblog": handle, "bean.id": draft_id}, form="entry", button="entryEdit!publish",
           **{"bean.title": "Draft now published"})
    r.form(f"{AUTHORING}/entryEdit.rol", params={"weblog": handle, "bean.id": entry_id}, form="entry", button="entryEdit!saveDraft")
    r.form(f"{AUTHORING}/entryEdit.rol", params={"weblog": handle, "bean.id": entry_id}, form="entry", button="entryEdit!publish")
    r.form(f"{AUTHORING}/entryAdd.rol", params={"weblog": handle}, button="entryAdd!publish", **{"bean.title": "", "bean.text": "no title"},
           expect=(200, 302))
    r.form(f"{AUTHORING}/entryAdd.rol", params={"weblog": handle}, button="entryAdd!publish",
           **{"bean.title": unique("Scheduled"), "bean.text": "later", "bean.dateString": "12/31/2030", "bean.hours": "9"})
    r.get(f"{AUTHORING}/entryAddWithMediaFile.rol", params={"weblog": handle})
    r.get(f"{AUTHORING}/entryEdit.rol", params={"weblog": handle, "bean.id": "no-such-entry"}, expect=(200, 302, 404, 500))
    r.form(f"{AUTHORING}/entries.rol", params={"weblog": handle}, form="entryRemoveViaList", removeId=draft_id, expect=(200, 302))
    r.get(f"{AUTHORING}/entries.rol", params={"weblog": handle}, absent="Draft now published")


@suite.usecase("PublicSite")
def public_site(c):
    r = ready(c)
    handle = add_weblog(r)
    _, anchor = add_entry(r, handle, title="Public Entry", body="Searchable platypus text", **{"bean.tagsAsString": "marsupial"})
    anon = suite.client()
    for path in ("/", f"/{handle}/", f"/{handle}/entry/{anchor}", f"/{handle}/entry/{anchor}#comments", f"/{handle}/date/{time.strftime('%Y')}",
                 f"/{handle}/date/{time.strftime('%Y%m')}", f"/{handle}/date/{time.strftime('%Y%m%d')}", f"/{handle}/category/General",
                 f"/{handle}/?tags=marsupial", f"/{handle}/?page=2", f"/{handle}/?cat=General", f"/{handle}/?locale=en"):
        anon.get(path, expect=(200, 404))
    anon.get(f"/{handle}/search", params={"q": "platypus"}, contains="Public Entry")
    anon.get(f"/{handle}/search", params={"q": "zzzznothing"})
    anon.get(f"/{handle}/search", params={"q": "platypus", "cat": "General"}, expect=(200, 404))
    for kind in ("entries", "comments"):
        for fmt in ("atom", "rss"):
            anon.get(f"/{handle}/feed/{kind}/{fmt}", contains="<")
    anon.get(f"/{handle}/feed/entries/atom", params={"cat": "General"})
    anon.get(f"/{handle}/feed/entries/atom", params={"tags": "marsupial"})
    anon.get(f"/{handle}/feed/entries/atom", params={"excerpts": "true"})
    anon.get(f"/{handle}/feed/entries/rss", params={"page": 1})
    anon.get("/roller-ui/rendering/feed/%s/entries/atom" % handle)
    anon.get("/roller-ui/rendering/planet.do", expect=(200, 404))
    anon.get("/planet.do", expect=(200, 404))
    anon.get("/roller-ui/rendering/blogs.do", expect=(200, 404))
    anon.get("/roller-ui/rendering/search/%s" % handle, params={"q": "platypus"}, expect=(200, 404))
    anon.get(f"/{handle}/page/nosuchpage", expect=(200, 404))
    anon.get("/no-such-weblog-here/", expect=(200, 404))
    anon.get(f"/{handle}/mediaresource/none.png", expect=(200, 404))
    anon.get("/robots.txt", expect=(200, 404))
    anon.get("/favicon.svg", expect=(200, 404))


def comment(anon, handle, anchor, content, method="post", name="Visitor", answer=None, expect=200, **fields):
    """Post (or preview) a public comment, answering the site's math question."""
    url = f"/{handle}/entry/{anchor}"
    anon.get(url)
    if answer is None:
        question = anon.get("/CommentAuthenticatorServlet", params={"weblog": handle}).text
        m = re.search(r"(\d+) \+ (\d+)", question)
        answer = str(int(m.group(1)) + int(m.group(2))) if m else "0"
    return anon.post(url, dict({"method": method, "name": name, "email": f"{name.lower()}@example.com", "url": "http://example.com",
                               "content": content, "answer": answer}, **fields), expect=expect)


@suite.usecase("Comments")
def comments(c):
    r = ready(c)
    handle = add_weblog(r)
    _, anchor = add_entry(r, handle, title="Comment target")
    visitor = suite.client()
    comment(visitor, handle, anchor, "A previewed comment", method="preview", contains="A previewed comment")
    comment(visitor, handle, anchor, "A real comment", contains="has been accepted")
    comment(visitor, handle, anchor, "Buy cheap pills", name="Spammer")
    comment(visitor, handle, anchor, "Wrong answer", answer="999", contains="not correct")
    comment(visitor, handle, anchor, "", expect=(200, 302))
    visitor.get(f"/{handle}/entry/{anchor}", contains="A real comment")
    visitor.get(f"/{handle}/feed/comments/atom", contains="A real comment")
    page = r.get(f"{AUTHORING}/comments.rol", params={"weblog": handle}, contains="A real comment")
    ids = re.findall(r'name="bean\.ids" value="([^"]+)"', page.text)[0].split(",")  # one hidden field, comma separated
    if len(ids) < 2:
        raise UsecaseFailed(f"the comment list holds {ids}")
    r.form(f"{AUTHORING}/comments.rol", params={"weblog": handle}, form="commentsQuery", **{"bean.searchString": "real"},
           page=None, expect=200)
    for query in ({"bean.searchString": "Spammer"}, {"bean.approvedString": "APPROVED"}, {"bean.approvedString": "PENDING"},
                  {"bean.approvedString": "SPAM"}, {"bean.startDateString": "01/01/2020", "bean.endDateString": "12/31/2030"}):
        r.form(f"{AUTHORING}/comments.rol", params={"weblog": handle}, form="commentsQuery", button=None, **query)
    page = r.get(f"{AUTHORING}/comments.rol", params={"weblog": handle})
    action, values = forms(page)["comments"]
    base = dict(values, **{"bean.ids": ids})
    r.c.post(action, dict(base, **{"bean.spamComments": ids[:1]}))  # mark the first comment as spam
    r.c.post(action, dict(base, **{"bean.approvedComments": ids[:1]}))  # and approve it again
    r.c.post(action, dict(base, **{"bean.deleteComments": ids[-1:]}))
    r.get("/roller-ui/admin/globalCommentManagement.rol")
    r.form("/roller-ui/admin/globalCommentManagement.rol", form="commentsQuery", **{"bean.searchString": "real"}, button=None, expect=(200, 302))


@suite.usecase("Categories")
def categories(c):
    r = ready(c)
    handle = add_weblog(r)
    page_path = f"{AUTHORING}/categories.rol"
    r.form(page_path, params={"weblog": handle}, form="categoryEditForm", button="categoryEdit!save",
           **{"bean.name": "News", "bean.description": "All the news"})
    r.form(page_path, params={"weblog": handle}, form="categoryEditForm", button="categoryEdit!save", **{"bean.name": "News"},
           expect=(200, 302))  # duplicate name
    r.form(page_path, params={"weblog": handle}, form="categoryEditForm", button="categoryEdit!save", **{"bean.name": ""}, expect=(200, 302))
    r.form(page_path, params={"weblog": handle}, form="categoryEditForm", button="categoryEdit!save", **{"bean.name": "Misc"})
    page = r.get(page_path, params={"weblog": handle}, contains="News")
    ids = dict((name, cid) for cid, name in re.findall(r"showCategoryEditModal\(\s*'([\w-]+)',\s*'([^']*)'", page.text))
    r.form(page_path, params={"weblog": handle}, form="categoryEditForm", button="categoryEdit!save",
           **{"bean.id": ids["News"], "bean.name": "Headlines", "bean.description": "Renamed"})
    _, anchor = add_entry(r, handle, title="Categorised", **{"bean.categoryId": ids["Misc"]})
    r.get(f"/{handle}/category/Misc", contains="Categorised")
    r.get(f"/{handle}/feed/entries/atom", params={"cat": "Misc"})
    r.form(page_path, params={"weblog": handle}, form="categories", categoryId=ids["Misc"], button=None, expect=(200, 302))  # move view
    r.form(page_path, params={"weblog": handle}, form="categoryRemove", removeId=ids["Misc"], targetCategoryId=ids["News"])
    r.get(page_path, params={"weblog": handle}, absent="Misc")
    r.get(f"/{handle}/category/Headlines", contains="Categorised")


@suite.usecase("Bookmarks")
def bookmarks(c):
    r = ready(c)
    handle = add_weblog(r)
    path = f"{AUTHORING}/bookmarks.rol"
    r.form(path, params={"weblog": handle}, form="folderEditForm", button="folderEdit!save", **{"bean.name": "Friends"})
    for name, url in (("Apache", "http://apache.org"), ("Example", "http://example.com")):
        r.form(path, params={"weblog": handle}, form="bookmarkEdit", button="bookmarkEdit!save",
               **{"bean.name": name, "bean.url": url, "bean.feedUrl": url + "/feed", "bean.description": "A site"})
    r.form(path, params={"weblog": handle}, form="bookmarkEdit", button="bookmarkEdit!save", **{"bean.name": "", "bean.url": "x"},
           expect=(200, 302))
    page = r.get(path, params={"weblog": handle}, contains="Apache")
    ids = re.findall(r'name="selectedBookmarks"[^>]*value="([^"]+)"', page.text)
    if len(ids) < 2:
        raise UsecaseFailed(f"the blogroll holds {ids}")
    target = ids[-1] if "Apache" in page.text else ids[0]
    r.form(path, params={"weblog": handle}, form="bookmarkEdit", button="bookmarkEdit!save",
           **{"bean.id": target, "bean.name": "Apache edited", "bean.url": "http://apache.org"})
    r.get(path, params={"weblog": handle}, contains="Apache edited")
    r.get(f"/{handle}/", contains="Apache edited")
    opml = ('<?xml version="1.0"?><opml version="1.0"><head><title>Links</title></head><body>'
            '<outline text="Imported site" title="Imported site" type="link" xmlUrl="http://example.org/feed" htmlUrl="http://example.org"/>'
            '</body></opml>').encode()
    r.form(f"{AUTHORING}/bookmarksImport.rol", params={"weblog": handle}, files={"opmlFile": ("links.opml", opml, "text/xml")})
    page = r.get(path, params={"weblog": handle})
    imported = re.search(r'<option value="([^"]+)"[^>]*>\s*imported-', page.text)
    if not imported:
        raise UsecaseFailed("the OPML import created no blogroll folder")
    r.get(path, params={"weblog": handle, "folderId": imported.group(1)}, contains="Imported site")
    page = r.get(path, params={"weblog": handle})  # two forms share the id "bookmarks": post the delete action by hand
    _, form = forms(page)["folderEditForm"]
    folder = re.search(r'name="folderId" value="([^"]+)"', page.text).group(1)
    r.c.post(f"{AUTHORING}/bookmarks!delete.rol", {"salt": form["salt"], "weblog": handle, "folderId": folder, "selectedBookmarks": [target]})
    r.get(path, params={"weblog": handle}, absent="Apache edited")
    page = r.get(path, params={"weblog": handle})
    folder = re.search(r'name="folderId" value="([^"]+)"', page.text).group(1)
    r.form(path, params={"weblog": handle}, form="boomarks_delete_folder", folderId=folder, expect=(200, 302))
    r.get(f"/{handle}/feed/entries/atom")


@suite.usecase("MediaFiles")
def media_files(c):
    r = ready(c)
    handle = add_weblog(r)
    view = f"{AUTHORING}/mediaFileView.rol"
    r.get(view, params={"weblog": handle})
    r.form(view, params={"weblog": handle}, form="mediaFileViewForm", newDirectoryName="photos", button=None, expect=(200, 302))
    r.get(f"{AUTHORING}/mediaFileAdd.rol", params={"weblog": handle})
    name = unique("pic")
    r.form(f"{AUTHORING}/mediaFileAdd.rol", params={"weblog": handle}, button="mediaFileAdd!save",
           **{"bean.name": name, "bean.description": "A tiny picture", "bean.copyrightText": "me", "bean.tagsAsString": "tiny pic"},
           files={"uploadedFiles": ("tiny.png", PNG, "image/png")}, expect=(200, 302))
    page = r.get(view, params={"weblog": handle}, contains="tiny.png")
    ids = re.findall(r"mediaFileId=([\w-]+)", page.text) or re.findall(r'name="selectedMediaFiles"[^>]*value="([\w-]+)"', page.text)
    r.form(view, params={"weblog": handle}, form="mediaFileSearchForm", **{"bean.name": "tiny"}, button=None, expect=(200, 302))
    r.form(view, params={"weblog": handle}, form="mediaFileSearchForm", **{"bean.type": "image", "bean.sizeFilterType": "GT", "bean.size": "0"},
           button=None, expect=(200, 302))
    if ids:
        r.form(f"{AUTHORING}/mediaFileEdit.rol", params={"weblog": handle, "mediaFileId": ids[0]},
               **{"bean.name": name + " edited", "bean.description": "Edited"}, expect=(200, 302))
        r.get(f"/{handle}/mediaresource/{ids[0]}", expect=(200, 404))
    r.form(f"{AUTHORING}/entryAddWithMediaFile.rol", params={"weblog": handle}, form="entry", button="entryAdd!publish",
           **{"bean.title": unique("With media"), "bean.text": "see the picture"}, expect=(200, 302))
    r.get(f"{AUTHORING}/mediaFileAdd.rol", params={"weblog": handle, "directoryName": "default"})


@suite.usecase("Design")
def design(c):
    r = ready(c)
    handle = add_weblog(r)
    r.get(f"{AUTHORING}/themeEdit.rol", params={"weblog": handle})
    themes = re.findall(r'name="selectedThemeId"[^>]*value="([^"]+)"', r.get(f"{AUTHORING}/themeEdit.rol", params={"weblog": handle}).text)
    for theme in (themes[:3] or ["basic"]):
        r.form(f"{AUTHORING}/themeEdit.rol", params={"weblog": handle}, themeType="shared", selectedThemeId=theme, expect=(200, 302))
        r.get(f"/{handle}/")
    r.form(f"{AUTHORING}/themeEdit.rol", params={"weblog": handle}, themeType="custom", importTheme="true", expect=(200, 302))
    r.get(f"{AUTHORING}/stylesheetEdit.rol", params={"weblog": handle}, expect=(200, 302))
    r.form(f"{AUTHORING}/stylesheetEdit.rol", params={"weblog": handle}, form="stylesheetEdit", button=None, expect=(200, 302))
    r.get(f"/{handle}/", expect=(200, 404))
    page = r.get(f"{AUTHORING}/templates.rol", params={"weblog": handle})
    name = unique("page").lower()
    r.form(f"{AUTHORING}/templates.rol", params={"weblog": handle}, form="templateAdd", newTmplName=name, newTmplAction="CUSTOM", expect=(200, 302))
    page = r.get(f"{AUTHORING}/templates.rol", params={"weblog": handle}, contains=name)
    edit = re.search(r'href="([^"]*templateEdit[^"]*%s[^"]*|[^"]*templateEdit[^"]*)"' % name, page.text)
    template = re.findall(r'(?:bean\.id|templateId|removeId)[=:"\s]+([\w-]{20,})', page.text)
    if edit:
        link = edit.group(1).replace("&amp;", "&")
        r.get(link)
        r.form(link, button="templateEdit!save", **{"bean.contents": "<html><body>Hello template</body></html>", "bean.name": name},
               expect=(200, 302))
        r.get(f"/{handle}/page/{name}", expect=(200, 404))
    r.get(f"/{handle}/?theme=preview", expect=(200, 404))
    if template:
        r.form(f"{AUTHORING}/templates.rol", params={"weblog": handle}, form="templates", removeId=template[-1], expect=(200, 302))


@suite.usecase("MembersAndPings")
def members_and_pings(c):
    admin, member, username = new_member(c)
    handle = add_weblog(admin)
    r = admin
    r.get(f"{AUTHORING}/members.rol", params={"weblog": handle})
    r.form(f"{AUTHORING}/members.rol", params={"weblog": handle}, form="members", expect=(200, 302))
    member.get("/roller-ui/menu.rol")
    member.get(f"{AUTHORING}/memberResign.rol", params={"weblog": handle}, expect=(200, 302, 403))
    r.get(f"{AUTHORING}/pings.rol", params={"weblog": handle})
    page = r.get(f"{AUTHORING}/pings.rol", params={"weblog": handle})
    for link in sorted(set(re.findall(r'href="(/roller-ui/authoring/pings[^"]*)"', page.text)))[:6]:
        r.get(link.replace("&amp;", "&"), expect=(200, 302))
    r.get(f"{AUTHORING}/pingSetup.rol", params={"weblog": handle}, expect=(200, 302, 404))


ADMIN_UI = "/roller-ui/admin"


@suite.usecase("AdminSite")
def admin_site(c):
    r = ready(c)
    r.get(f"{ADMIN_UI}/globalConfig.rol")
    r.form(f"{ADMIN_UI}/globalConfig.rol", **{"site.name": "Test Roller", "site.shortName": "Roller", "site.description": "A test site",
                                              "site.pages.maxEntries": "12", "site.newsfeeds.defaultEntries": "10", "uploads.file.maxsize": "3.00",
                                              "spam.bannedwordslist": "casino\npills", "users.registration.enabled": "true",
                                              "site.allowUserWeblogCreation": "true", "uploads.enabled": "true",
                                              "users.comments.enabled": "true", "users.trackbacks.enabled": "true"})
    r.get("/")
    r.get("/roller-ui/menu.rol", contains="Test Roller")
    r.form(f"{ADMIN_UI}/globalConfig.rol", **{"site.name": "Roller", "users.editor.pages": "editor-text.jsp,editor-xml.jsp"}, expect=(200, 302))
    handle = add_weblog(r)
    r.form(f"{ADMIN_UI}/globalConfig.rol", **{"site.frontpage.weblog.handle": handle, "site.frontpage.weblog.aggregated": "true"})
    r.get("/")
    r.form(f"{ADMIN_UI}/globalConfig.rol", **{"site.frontpage.weblog.handle": "", "site.frontpage.weblog.aggregated": "false"}, expect=(200, 302))
    for kind in ("weblog", "memory"):  # the cache page lists one form per cache
        page = r.get(f"{ADMIN_UI}/cacheInfo.rol")
        caches = re.findall(r'name="cache" value="([^"]+)"', page.text)
        for cache in caches[:3]:
            r.c.post(f"{ADMIN_UI}/cacheInfo!clear.rol", {"salt": forms(page)["cacheInfo"][1]["salt"], "cache": cache}, expect=(200, 302))
        break
    name = unique("made").lower()
    r.form(f"{ADMIN_UI}/createUser.rol", button="createUser!save", **{"bean.userName": name, "bean.screenName": name.title(),
           "bean.fullName": "Made By Admin", "bean.password": PASSWORD, "bean.emailAddress": f"{name}@example.com", "bean.enabled": "true"})
    r.form(f"{ADMIN_UI}/createUser.rol", button="createUser!save", **{"bean.userName": name, "bean.screenName": "x", "bean.fullName": "Dup",
           "bean.password": PASSWORD, "bean.emailAddress": "dup@example.com"}, expect=(200, 302))
    r.form(f"{ADMIN_UI}/createUser.rol", button="createUser!save", **{"bean.userName": "", "bean.password": ""}, expect=(200, 302))
    r.form(f"{ADMIN_UI}/createUser.rol", button="createUser!cancel", expect=(200, 302))
    edit = r.form(f"{ADMIN_UI}/userAdmin.rol", **{"bean.userName": name})
    r.form("", page=edit, form="modifyUser", **{"bean.fullName": "Edited By Admin", "bean.administrator": "true", "bean.enabled": "true"})
    r.form(f"{ADMIN_UI}/userAdmin.rol", **{"bean.userName": name})
    page = r.form(f"{ADMIN_UI}/userAdmin.rol", **{"bean.userName": name})
    r.form("", page=page, form="modifyUser", **{"bean.enabled": "false", "__checkbox_bean.enabled": "true"}, expect=(200, 302))
    gone = Roller(suite.client())
    gone.login(name, PASSWORD)
    r.form(f"{ADMIN_UI}/userAdmin.rol", **{"bean.userName": "no-such-user-anywhere"}, expect=(200, 302, 500))
    outsider = suite.client()
    outsider.get(f"{ADMIN_UI}/globalConfig.rol", expect=(200, 302, 403))


@suite.usecase("AdminPingsAndPlanet")
def admin_pings_and_planet(c):
    r = ready(c)
    handle = add_weblog(r)
    add_entry(r, handle, title="Planet feed entry")
    target = unique("Ping")
    # the page's modal posts the form (by AJAX) to commonPingTargetAdd.rol or commonPingTargetEdit.rol
    form_page = r.get(f"{ADMIN_UI}/commonPingTargets.rol")
    _, ping_form = forms(form_page)["pingTargetEditForm"]
    r.c.post(f"{ADMIN_UI}/commonPingTargetAdd.rol", dict(ping_form, actionName="commonPingTargetAdd",
                                                                  **{"bean.name": target, "bean.pingUrl": "http://localhost:8080/ping/RPC2"}))
    page = r.get(f"{ADMIN_UI}/commonPingTargets.rol", contains=target)
    ids = dict((name, tid) for tid, name in re.findall(r"showAddEditModal\(\s*'([\w-]+)',\s*'([^']*)'", page.text))
    for link in sorted(set(re.findall(r'href="(/roller-ui/admin/commonPingTargets[^"]*)"', page.text)))[:8]:
        r.get(link.replace("&amp;", "&"), expect=(200, 302))
    r.c.post(f"{ADMIN_UI}/commonPingTargetEdit.rol", dict(ping_form, actionName="commonPingTargetEdit",
                                                                       **{"bean.id": ids[target], "bean.name": target + " edited",
                                                                       "bean.pingUrl": "http://localhost:8080/ping/RPC2"}))
    r.get(f"{ADMIN_UI}/commonPingTargets.rol", contains=target + " edited")
    r.get(f"{AUTHORING}/pings.rol", params={"weblog": handle})
    for link in sorted(set(re.findall(r'href="(/roller-ui/authoring/pings[^"]*)"', r.get(f"{AUTHORING}/pings.rol", params={"weblog": handle}).text)))[:8]:
        r.get(link.replace("&amp;", "&"), expect=(200, 302))
    r.form(f"{ADMIN_UI}/commonPingTargets.rol", form="commonPingTargets", pingTargetId=ids[target], button="commonPingTargets!delete")
    r.get(f"{ADMIN_UI}/commonPingTargets.rol", absent=target + " edited")
    r.form(f"{ADMIN_UI}/planetConfig.rol", **{"planet.site.name": "Test Planet", "planet.site.description": "Aggregated blogs",
                                              "planet.site.adminname": "Admin", "planet.site.adminemail": "admin@example.com",
                                              "planet.site.absoluteurl": "http://localhost:8080"})
    r.get(f"{ADMIN_UI}/planetGroups.rol")
    group = unique("grp").lower()
    r.form(f"{ADMIN_UI}/planetGroupSubs.rol", params={"createNew": "true"}, **{"group.title": "A group", "group.handle": group})
    feed = f"http://localhost:8080/{handle}/feed/entries/atom"
    r.form(f"{ADMIN_UI}/planetGroupSubs.rol", params={"group.handle": group}, subUrl=feed, expect=(200, 302))
    r.get(f"{ADMIN_UI}/planetGroupSubs.rol", params={"group.handle": group})
    r.get(f"{ADMIN_UI}/planetGroupSubs.rol", params={"group.handle": "all"})
    r.form(f"{ADMIN_UI}/planetGroupSubs.rol", params={"group.handle": "all"}, subUrl=feed, expect=(200, 302))
    page = r.get(f"{ADMIN_UI}/planetGroupSubs.rol", params={"group.handle": group})
    for link in sorted(set(re.findall(r'href="(/roller-ui/admin/planetGroupSubs[^"]*)"', page.text)))[:5]:
        r.get(link.replace("&amp;", "&"), expect=(200, 302))
    suite.client().get("/roller-ui/planet.do", expect=(200, 404))


@suite.usecase("WebServices")
def web_services(c):
    r = ready(c)
    handle = add_weblog(r)
    auth = {"Authorization": "Basic " + base64.b64encode(f"{ADMIN}:{ADMIN_PASSWORD}".encode()).decode()}
    anon = suite.client()
    # Roller 6.1.5's BASIC check compares the password with a field that is still null (RollerAtomHandler.authenticateBASIC swallows
    # the NullPointerException), so no credentials are ever accepted: every call is answered 401 after running the authentication.
    anon.get("/roller-services/app", expect=401)
    anon.get("/roller-services/app", headers=auth, expect=(200, 401))
    anon.get(f"/roller-services/app/{handle}/entries", headers=auth, expect=(200, 401))
    anon.get(f"/roller-services/app/{handle}/entries/0", headers=auth, expect=(200, 401, 404))
    anon.get(f"/roller-services/app/{handle}/resources", headers=auth, expect=(200, 401, 404))
    atom = (b'<?xml version="1.0"?><entry xmlns="http://www.w3.org/2005/Atom"><title>%s</title>'
            b'<content type="html">Posted by APP</content></entry>')
    headers = dict(auth, **{"Content-Type": "application/atom+xml;type=entry"})
    for method, path, body in (("POST", f"/roller-services/app/{handle}/entries", atom % b"From AtomPub"),
                               ("PUT", f"/roller-services/app/{handle}/entry/none", atom % b"Edited"),
                               ("DELETE", f"/roller-services/app/{handle}/entry/none", b""),
                               ("POST", f"/roller-services/app/{handle}/entries", b"not xml")):
        apprequest(anon, method, path, body, headers, expect=(200, 201, 204, 400, 401, 404, 405, 500))
    apprequest(anon, "POST", f"/roller-services/app/{handle}/resources", PNG, dict(auth, **{"Content-Type": "image/png", "Slug": "app.png"}),
               expect=(200, 201, 400, 401, 404, 415, 500))
    def call(method, *params):
        return ('<?xml version="1.0"?><methodCall><methodName>%s</methodName><params>%s</params></methodCall>'
                % (method, "".join("<param><value>%s</value></param>" % p for p in params)))

    def string(value):
        return f"<string>{value}</string>"

    post = "<struct><member><name>title</name><value>%s</value></member><member><name>description</name><value>Over XML-RPC</value></member></struct>"
    for body in (call("blogger.getUsersBlogs", string("key"), string(ADMIN), string(ADMIN_PASSWORD)),
                 call("metaWeblog.getCategories", string(handle), string(ADMIN), string(ADMIN_PASSWORD)),
                 call("metaWeblog.getRecentPosts", string(handle), string(ADMIN), string(ADMIN_PASSWORD), "<int>5</int>"),
                 call("metaWeblog.newPost", string(handle), string(ADMIN), string(ADMIN_PASSWORD), post % unique("rpc"), "<boolean>1</boolean>"),
                 call("blogger.getUserInfo", string("key"), string(ADMIN), string(ADMIN_PASSWORD)),
                 call("metaWeblog.getRecentPosts", string(handle), string(ADMIN), string("wrong-password"), "<int>5</int>")):
        xmlrpc(anon, body)
    anon.get(f"/roller-services/opensearch/{handle}", expect=(200, 404))
    anon.get("/roller-services/rsd/%s" % handle, expect=(200, 404))
    anon.get("/roller-services/oembed", params={"url": f"http://localhost:8080/{handle}/"}, expect=(200, 400, 404, 501))


def apprequest(client, method, path, body, headers, expect=(200,)):
    """A raw request (the harness posts forms or JSON; AtomPub bodies are XML or binary); returns the response text."""
    req = urllib.request.Request(client.base_url + path, data=body or None, method=method, headers=headers)
    try:
        with client.opener.open(req, timeout=client.timeout) as resp:
            status, text = resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", errors="replace")
    if status not in expect:
        raise UsecaseFailed(f"{method} {path}: HTTP {status}, expected {expect}\n{text[:300]}")
    return text


def xmlrpc(client, body):
    req = urllib.request.Request(client.base_url + "/roller-services/xmlrpc", data=body.encode(), method="POST",
                                 headers={"Content-Type": "text/xml"})
    try:
        with client.opener.open(req, timeout=60) as resp:
            return resp.status
    except Exception as e:  # an XML-RPC fault or error status still ran the service
        return getattr(e, "code", 0)


@suite.usecase("Servlets")
def servlets(c):
    """The remaining servlets: Ajax data, OAuth, theme preview, trackback, RSD, planet feed, mobile rendering, tag data."""
    r = ready(c)
    handle = add_weblog(r)
    _, anchor = add_entry(r, handle, title="Servlet target", **{"bean.tagsAsString": "alpha alpine"})
    anon = suite.client()
    for path in (f"{AUTHORING}/userdata?startsWith=a", f"{AUTHORING}/userdata?startsWith=zzz",
                 f"{AUTHORING}/themedata/basic", f"{AUTHORING}/themedata/nonesuch", f"{AUTHORING}/commentdata/{handle}",
                 f"{AUTHORING}/preview/{handle}/", f"{AUTHORING}/preview/{handle}/entry/{anchor}",
                 f"{AUTHORING}/preview/{handle}/?theme=basic", f"{AUTHORING}/previewresource/{handle}/none.css"):
        r.get(path, expect=(200, 400, 404, 500))
    for path in ("/roller-services/tagdata/?prefix=al", "/roller-services/tagdata/?prefix=zz", "/roller-services/tagdata/"):
        anon.get(path, expect=(200, 400))
    for path in ("/roller-services/oauth/requestToken", "/roller-services/oauth/authorize", "/roller-services/oauth/accessToken"):
        anon.get(path, expect=(200, 400, 401, 500))
        anon.post(path, {"oauth_consumer_key": "none"}, expect=(200, 400, 401, 500))
    anon.post(f"/roller-ui/rendering/trackback/{handle}", {"url": "http://localhost:8080/", "title": "t", "excerpt": "e", "blog_name": "b"},
              params={"anchor": anchor}, expect=(200, 400))
    anon.get(f"/roller-ui/rendering/rsd/{handle}", contains="rsd")
    anon.get("/planetrss/", expect=(200, 404))
    anon.get("/planetrss/all", expect=(200, 404))
    anon.get(f"/roller-ui/rendering/page/{handle}/", expect=(200, 404))
    anon.get(f"/roller-ui/rendering/resources/{handle}/none.css", expect=(200, 404))
    anon.get("/roller-ui/rendering/media-resources/nonesuch", expect=(200, 404))
    anon.get(f"/roller-ui/rendering/comment/{handle}", params={"entry": anchor}, expect=(200, 404))
    anon.get(f"/roller-services/opensearch/{handle}", expect=(200, 404))
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    for path in (f"/{handle}/", f"/{handle}/entry/{anchor}", f"/{handle}/?theme=mobile"):
        anon.get(path, headers={"User-Agent": iphone}, expect=(200, 404))
        anon.get(path, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 11) Mobile Safari/537.36"}, expect=(200, 404))
    r.get(f"/{handle}/?tags=alpha")
    r.get(f"/{handle}/tags/alpha", expect=(200, 404))
    r.get(f"/{handle}/entry/{anchor}/tags/alpha", expect=(200, 404))
    r.get(f"/{handle}/feed/entries/atom", params={"tags": "alpha"})
    r.get("/roller-ui/rendering/search/%s" % handle, params={"q": "servlet", "page": 1}, expect=(200, 404))
    r.get(f"/{handle}/search", params={"q": "servlet", "cat": "General", "page": 2}, expect=(200, 404))
    r.get(f"{AUTHORING}/entryAdd.rol", params={"weblog": handle})


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
