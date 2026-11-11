# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Black-box functional test suite for a running Spring Blog: the scenarios of the FoSCI authors' list
(tools/fosci/FoSCI/testscenario/springblog-ts.txt) that the pinned build implements, driven over HTTP like a browser.

Covered: 3 login, 2/10 initialise and update the blog settings, 4 write posts (published/draft, markdown/HTML, page), 5 browse the
blog, 8 draft list, 12 archive, 14/15 tags, edit a post, 18 delete a post, 23 update the account (password), 24 logout.
Not in the pinned build, so not testable: register, comments, attachments, skins, search, subscribe, categories, extra users,
like/dislike, projects. Known defects of the pinned build it works around: `/tags/<name>` has no view template (500), and deleting
a post fails while another post shares one of its tags.

Run it against an instance started with the tracer agent to record FoSCI's execution trace (see tools/fosci/README.md):
    uv run functional_tests.py [--base-url http://localhost:8080]
Exits 1 if any scenario's check fails, so a trace is only kept from a suite that really passed. It leaves its posts and settings in the blog
(use a fresh database per recording); the admin password is restored.
"""

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from web_driver import Browser, Suite  # noqa: E402

ADMIN, PASSWORD = "admin", "admin"   # the blog creates this account on first start


def login(b, password):
    b.get("/login")
    b.submit(action="/authenticate", username=ADMIN, password=password)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:8080")
    base = ap.parse_args().base_url
    b, suite = Browser(base), Suite()
    check = suite.check
    stamp = str(int(time.time()))

    # 5) browse the blog anonymously; the admin area is closed
    b.get("/")
    check("5 home", "SpringBlog" in b.page, "public home page")
    b.get("/admin/posts")
    check("3 admin needs login", b.url.endswith("/login"), f"anonymous /admin/posts goes to {b.url}")

    # 3) login: a wrong password is refused, the right one opens the admin area
    login(b, "wrong-password")
    check("3 bad login", "error" in b.url, f"wrong password -> {b.url}")
    login(b, PASSWORD)
    b.get("/admin")
    check("3 login", "Admin Dashboard" in b.page, "signed in as admin")

    # 2, 10) initialise / update the blog settings
    b.get("/admin/settings")
    b.submit(action="/admin/settings", siteName=f"Functional Blog {stamp}", siteSlogan="tested end to end", pageSize="5",
             intro="Written by the functional test suite")
    b.get("/")
    check("10 settings", f"Functional Blog {stamp}" in b.page, "new site name shown on the home page")

    # 4) write posts: published markdown, published HTML, a draft, a page, and a scratch post with a tag of its own
    posts = [
        ("published markdown", f"ft-md-{stamp}", "# Heading\n\nBody **text** with `code`.", "MARKDOWN", "PUBLISHED", "POST", "functest,markdown"),
        ("published html", f"ft-html-{stamp}", "<p>Plain <b>html</b> body</p>", "HTML", "PUBLISHED", "POST", "functest,html"),
        ("draft", f"ft-draft-{stamp}", "Not for the public yet", "MARKDOWN", "DRAFT", "POST", "functest"),
        ("page", f"ft-page-{stamp}", "A standalone page", "MARKDOWN", "PUBLISHED", "PAGE", "functest"),
        ("scratch", f"ft-del-{stamp}", "To be deleted", "MARKDOWN", "PUBLISHED", "POST", f"del{stamp}"),
    ]
    for kind, permalink, content, fmt, status, ptype, tags in posts:
        b.get("/admin/posts/new")
        b.submit(action="/admin/posts", title=f"Title {permalink}", content=content, summary=f"Summary {permalink}",
                 permalink=permalink, postFormat=fmt, postStatus=status, postType=ptype, postTags=tags)
        check(f"4 create {kind}", b.url.endswith("/admin/posts"), f"saved, back at {b.url}")

    # 8) the draft list: every post, with its status, in the admin list
    b.get("/admin/posts")
    rows = re.findall(r"<tr>(.*?)</tr>", b.page, re.S)
    listed = {}
    for row in rows:
        m = re.search(r"/admin/posts/(\d+)/edit", row)
        link = re.search(r"Title (ft-[a-z]+-" + stamp + ")", row)
        if m and link:
            listed[link.group(1)] = (m.group(1), "Draft" in row or "DRAFT" in row)
    check("8 draft list", len(listed) == 5 and listed[f"ft-draft-{stamp}"][1] and not listed[f"ft-md-{stamp}"][1],
          f"5 new posts listed, only the draft marked: {listed}")

    # 5) browse: published post and page are public, the draft is not
    b.get("/")
    check("5 home lists published", f"Title ft-md-{stamp}" in b.page and f"Title ft-draft-{stamp}" not in b.page,
          "published post on the home page, draft hidden")
    b.get(f"/posts/ft-md-{stamp}")
    check("5 view post", "Body" in b.page and "Heading" in b.page, "markdown rendered")
    b.get(f"/posts/ft-html-{stamp}")
    check("5 view html post", "html" in b.page, "html post rendered")
    b.get(f"/ft-page-{stamp}")
    check("5 view page", "standalone page" in b.page, "page served at its permalink")

    # 12) archive; 14, 15) tags
    b.get("/posts/archive")
    check("12 archive", f"Title ft-md-{stamp}" in b.page, "archive lists the post")
    b.get("/tags")
    check("14 tags", "functest" in b.page and "markdown" in b.page, "tag list shows the new tags")
    b.get("/tags/markdown")
    # the pinned build has no tags/show.html, so the page is a 500 once the controller has queried the tag and its posts
    ok = (f"Title ft-md-{stamp}" in b.page and f"Title ft-html-{stamp}" not in b.page) or b.url.startswith("HTTP 500")
    check("15 posts by tag", ok, f"tag page reached ({b.url}); known upstream defect: the view template is missing")

    # edit a post (admin), then 18) delete one
    pid = listed[f"ft-html-{stamp}"][0]
    b.get(f"/admin/posts/{pid}/edit")
    b.submit(action=f"/admin/posts/{pid}", title=f"Edited {stamp}")
    b.get(f"/posts/ft-html-{stamp}")
    check("edit post", f"Edited {stamp}" in b.page, "edited title shown")
    # deleting a post fails (foreign key) while any of its tags is shared with another post, so delete the one with its own tag
    b.get("/admin/posts")
    b.submit(action=f"/admin/posts/{listed[f'ft-del-{stamp}'][0]}/delete")   # the row's own delete form, as the trash button's script does
    b.get("/admin/posts")
    check("18 delete post", f"ft-del-{stamp}" not in b.page and f"ft-md-{stamp}" in b.page, "scratch post gone, the others kept")
    b.get(f"/posts/ft-del-{stamp}")
    check("18 deleted post is gone", "To be deleted" not in b.page, "permalink no longer serves the post")

    # 23) update the account: change the password, sign in with it, change it back
    b.get("/admin/users/profile")
    b.submit(action="/admin/users/", password=PASSWORD, newPassword="changed-" + stamp)
    # 24) logout
    b.get("/admin")
    b.post("/logout")
    check("24 logout", "logout" in b.url, f"logged out -> {b.url}")
    b.get("/admin/posts")
    check("24 admin closed after logout", b.url.endswith("/login"), "admin area needs login again")
    login(b, PASSWORD)
    check("23 old password refused", "error" in b.url, "old password no longer works")
    login(b, "changed-" + stamp)
    b.get("/admin")
    check("23 new password works", "Admin Dashboard" in b.page, "signed in with the new password")
    b.get("/admin/users/profile")
    b.submit(action="/admin/users/", password="changed-" + stamp, newPassword=PASSWORD)
    b.post("/logout")
    login(b, PASSWORD)
    b.get("/admin")
    check("23 password restored", "Admin Dashboard" in b.page, "original password back")
    b.post("/logout")

    return suite.finish()


if __name__ == "__main__":
    sys.exit(main())
