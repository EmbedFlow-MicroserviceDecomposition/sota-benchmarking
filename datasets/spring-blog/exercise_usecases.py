"""SpringBlog functional test suite (shared by Mono2Micro and FoSCI; see datasets/workload.py).

Covers every controller endpoint of the pinned SpringBlog: the public blog (home with paging, posts by permalink and by id,
pages such as /about, archive, tags, 404s), sign-in/out (good and bad credentials, remember-me), and the admin area (dashboard,
post list with paging, creating Markdown/HTML posts, drafts and pages, editing, deleting, invalid forms, settings, profile and
password change). The FoSCI authors' SpringBlog scenarios (tools/fosci/FoSCI/testscenario/springblog-ts.txt) describe a later
version; the ones this version has (login, post, browse, archive, tags, delete, settings, profile, logout) are all here.
Every admin form carries Spring Security's CSRF token, read from the page that renders it.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from workload import Suite, UsecaseFailed, unique  # noqa: E402

suite = Suite("SpringBlog", os.environ.get("SPRING_BLOG_BASE_URL", "http://localhost:8080"), ready_path="/login")
CONTAINER_NAME = "spring-blog-app"

ADMIN, ADMIN_PASSWORD = "admin", "admin"  # Constants.DEFAULT_ADMIN_*, created on startup

MARKDOWN = """# Heading

Some *emphasis*, a [link](https://example.com), ~~struck~~ text and an autolink https://spring.io.

| col a | col b |
|-------|-------|
| 1     | 2     |

```java
class Hello {}
```
"""


def csrf(resp):
    m = (re.search(r"""name=["']_csrf["'][^>]*value=["']([^"']+)""", resp.text)
         or re.search(r"""value=["']([^"']+)["'][^>]*name=["']_csrf["']""", resp.text))
    if not m:
        raise UsecaseFailed(f"{resp.url}: no CSRF token on the page")
    return m.group(1)


def login(c, username=ADMIN, password=ADMIN_PASSWORD, remember=False):
    form = {"username": username, "password": password, "_csrf": csrf(c.get("/login", contains='name="username"'))}
    if remember:
        # the login page's checkbox is named rememberMe, which Spring Security ignores (it reads remember-me): an app
        # bug that makes the checkbox a no-op, so send the name the configured remember-me service actually reads
        form["remember-me"] = "on"
    return c.post("/authenticate", form)


def admin(c):
    login(c)
    c.get("/admin", contains="Posts")
    return c


def create_post(c, title=None, post_type="POST", post_format="MARKDOWN", status="PUBLISHED", tags="java,spring",
                content=MARKDOWN, permalink=None):
    """Create a post through the admin form; returns (id, permalink, title)."""
    title = title or unique("Post ")
    permalink = permalink if permalink is not None else unique("post-")
    form = {"_csrf": csrf(c.get("/admin/posts/new", contains='name="title"')), "title": title, "content": content,
            "summary": f"Summary of {title}", "postType": post_type, "postFormat": post_format, "postStatus": status,
            "permalink": permalink, "postTags": tags}
    listing = c.post("/admin/posts", form, contains=title)
    return listing.find(rf"<td>(\d+)</td>\s*<td>{re.escape(title)}</td>", "post id"), permalink, title


def delete_post(c, post_id):
    listing = c.get("/admin/posts")
    c.post(f"/admin/posts/{post_id}/delete", {"_csrf": csrf(listing)}, absent=f"<td>{post_id}</td>")


@suite.usecase("ViewHome")
def view_home(c):
    a = admin(suite.client())
    titles = [create_post(a, tags="home")[2] for _ in range(3)]
    c.get("/", contains=[titles[-1], "/posts/"])
    for page in ("1", "2", "0", "99"):
        c.get("/", {"page": page})


@suite.usecase("ViewAbout")
def view_about(c):
    resp = c.get("/about", expect=(200, 404))
    if resp.status == 404:
        create_post(admin(suite.client()), title="About this blog", post_type="PAGE", permalink="about", tags="")
    c.get("/about", contains="About this blog")
    c.get("/posts/about", expect=404)  # a PAGE is not served as a post


@suite.usecase("ViewPost")
def view_post(c):
    a = admin(suite.client())
    post_id, permalink, title = create_post(a, tags="java,markdown")
    c.get(f"/posts/{permalink}", contains=[title, "<table>", "<del>struck</del>"])
    c.get(f"/posts/{post_id}", contains=title)  # by id
    c.get(f"/posts/{permalink}", contains=title)  # view counter again


@suite.usecase("ViewHtmlPost")
def view_html_post(c):
    a = admin(suite.client())
    _, permalink, title = create_post(a, post_format="HTML", content="<p>Plain <b>HTML</b> body</p>", tags="html")
    c.get(f"/posts/{permalink}", contains=[title, "<b>HTML</b>"])


@suite.usecase("ViewPostNotFound")
def view_post_not_found(c):
    c.get("/posts/no-such-post", expect=404)
    c.get("/posts/987654321", expect=404)
    c.get("/no-such-page", expect=404)
    c.get("/tags/no-such-tag", expect=404)


@suite.usecase("ViewPostsArchive")
def view_posts_archive(c):
    _, _, title = create_post(admin(suite.client()), tags="archive")
    c.get("/posts/archive", contains=title)


@suite.usecase("ViewTags")
def view_tags(c):
    tag = unique("tag")
    _, _, title = create_post(admin(suite.client()), tags=f"{tag},java")
    c.get("/tags", contains=tag)
    # TagController renders "tags/show", which the pinned checkout does not ship: the page is a 500 after the
    # controller and services have run (an app bug, kept as is)
    c.get(f"/tags/{tag}", expect=500)
    c.get(f"/tags/{tag}", {"page": "2"}, expect=500)


@suite.usecase("UserLogin")
def user_login(c):
    login(c)
    c.get("/admin", contains="Posts")
    c.get("/admin/users/profile", contains='name="newPassword"')


@suite.usecase("LoginFailure")
def login_failure(c):
    resp = login(c, ADMIN, "wrong-password")
    if "error" not in resp.url:
        raise UsecaseFailed(f"bad credentials did not land on the error page ({resp.url})")
    login(c, "nobody", "x")
    c.get("/admin", expect=200, contains='name="username"')  # still bounced to the login form


@suite.usecase("RememberMeLogin")
def remember_me_login(c):
    login(c, remember=True)
    remember = next((k for k in c.cookies if k.name == "remember-me"), None)
    if remember is None:
        raise UsecaseFailed("no remember-me cookie after signing in with rememberMe")
    fresh = suite.client()
    fresh.cookies.set_cookie(remember)
    fresh.get("/admin", contains="Posts")  # authenticated by the cookie alone


@suite.usecase("Logout")
def logout(c):
    admin(c)
    resp = c.post("/logout", {"_csrf": csrf(c.get("/admin"))})
    if "logout" not in resp.url:
        raise UsecaseFailed(f"logout did not redirect to /login?logout ({resp.url})")
    c.get("/admin/posts", contains='name="username"')


@suite.usecase("AdminRequiresLogin")
def admin_requires_login(c):
    for path in ("/admin", "/admin/posts", "/admin/posts/new", "/admin/settings", "/admin/users/profile"):
        resp = c.get(path)
        if "/login" not in resp.url:
            raise UsecaseFailed(f"anonymous {path} was not redirected to /login ({resp.url})")


@suite.usecase("AdminViewPosts")
def admin_view_posts(c):
    admin(c)
    for _ in range(2):
        create_post(c, tags="list")
    c.get("/admin/posts", contains=["Operations", "/admin/posts/"])
    c.get("/admin/posts", {"page": "1"})


@suite.usecase("AdminCreatePost")
def admin_create_post(c):
    admin(c)
    post_id, permalink, title = create_post(c, tags="spring,boot,java")
    c.get(f"/admin/posts/{post_id}/edit", contains=[title, "spring"])
    suite.client().get(f"/posts/{permalink}", contains=title)


@suite.usecase("AdminCreatePostInvalid")
def admin_create_post_invalid(c):
    admin(c)
    form = {"_csrf": csrf(c.get("/admin/posts/new")), "title": "", "content": "", "postType": "POST",
            "postFormat": "MARKDOWN", "postStatus": "PUBLISHED", "permalink": "", "postTags": ""}
    c.post("/admin/posts", form, contains='name="title"')  # the form again, nothing created


@suite.usecase("AdminCreateDraft")
def admin_create_draft(c):
    admin(c)
    post_id, permalink, title = create_post(c, status="DRAFT", tags="draft")
    anon = suite.client()
    if title in anon.get("/").text or title in anon.get("/posts/archive").text:
        raise UsecaseFailed("a draft is listed publicly")
    anon.get(f"/posts/{permalink}", expect=404)
    anon.get(f"/posts/{post_id}", contains=title)  # preview by id


@suite.usecase("AdminEditPost")
def admin_edit_post(c):
    admin(c)
    post_id, permalink, _ = create_post(c, tags="before")
    edit = c.get(f"/admin/posts/{post_id}/edit", contains='name="title"')
    new_title = unique("Edited ")
    form = {"_csrf": csrf(edit), "title": new_title, "content": "Updated **body**", "summary": "updated",
            "postType": "POST", "postFormat": "MARKDOWN", "postStatus": "PUBLISHED", "permalink": permalink,
            "postTags": "after,java"}
    c.post(f"/admin/posts/{post_id}", form, contains=new_title)
    c.get(f"/admin/posts/{post_id}/edit", contains='value="after,java"')  # the post page does not show tags
    suite.client().get(f"/posts/{permalink}", contains=[new_title, "<strong>body</strong>"])


@suite.usecase("AdminDeletePost")
def admin_delete_post(c):
    admin(c)
    post_id, permalink, _ = create_post(c, tags="doomed")
    delete_post(c, post_id)
    suite.client().get(f"/posts/{permalink}", expect=404)


@suite.usecase("AdminViewUsers")
def admin_view_users(c):
    admin(c)
    c.get("/admin/users/profile", contains=["admin", 'name="password"'])


@suite.usecase("AdminChangePassword")
def admin_change_password(c):
    admin(c)
    profile = c.get("/admin/users/profile")
    user_id = profile.find(r'action="/admin/users/(\d+)"', "user id")
    action = f"/admin/users/{user_id}"
    c.post(action, {"_csrf": csrf(profile), "password": "wrong", "newPassword": "x"}, contains="Change password failed")
    c.post(action, {"_csrf": csrf(c.get("/admin/users/profile")), "password": ADMIN_PASSWORD, "newPassword": "temp-pass"},
           contains="Change password successfully")
    try:
        login(suite.client(), ADMIN, "temp-pass")
        c.get("/admin", contains="Posts")
    finally:  # put the shared admin password back
        c.post(action, {"_csrf": csrf(c.get("/admin/users/profile")), "password": "temp-pass",
                        "newPassword": ADMIN_PASSWORD}, contains="Change password successfully")
    c.post(action, {"_csrf": csrf(c.get("/admin/users/profile")), "password": ADMIN_PASSWORD, "newPassword": ""})
    c.post("/admin/users/987654321", {"_csrf": csrf(c.get("/admin/users/profile")), "password": "a",
                                      "newPassword": "b"}, expect=404)


@suite.usecase("AdminViewSettings")
def admin_view_settings(c):
    admin(c)
    c.get("/admin/settings", contains=['name="siteName"', 'name="pageSize"'])


@suite.usecase("AdminUpdateSettings")
def admin_update_settings(c):
    admin(c)
    page = c.get("/admin/settings")
    original = {f: page.find(rf'name="{f}"[^>]*value="([^"]*)"', f) for f in ("siteName", "siteSlogan", "pageSize")}
    site = unique("Site ")
    c.post("/admin/settings", {"_csrf": csrf(page), "siteName": site, "siteSlogan": "Functional tests",
                               "pageSize": "2", "intro": "Intro", "pictureUrl": ""},
           contains="Update settings successfully")
    suite.client().get("/", contains=site)
    suite.client().get("/", {"page": "2"})
    c.post("/admin/settings", dict(original, _csrf=csrf(c.get("/admin/settings")), intro="", pictureUrl=""),
           contains="Update settings successfully")


USECASES = list(suite.usecases)


def run_usecase(name, **_):
    """Mono2Micro's record.py entry point (it also passes agent/log arguments this suite does not need)."""
    suite.run(name)


if __name__ == "__main__":
    suite.main()
