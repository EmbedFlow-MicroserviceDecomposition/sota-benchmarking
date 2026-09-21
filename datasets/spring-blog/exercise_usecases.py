import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

BASE_URL = os.environ.get("SPRING_BLOG_BASE_URL", "http://localhost:8080")
CONTAINER_NAME = "spring-blog-app"

USECASES = [
    "ViewHome",
    "ViewAbout",
    "ViewPostsArchive",
    "ViewTags",
    "UserLogin",
    "AdminViewPosts",
    "AdminCreatePost",
    "AdminViewUsers",
    "AdminViewSettings"
]

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

def make_request(method, path, data=None, is_form=True):
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    body = None
    if data is not None:
        if is_form:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="ignore")
        return e.code, content
    except Exception as e:
        print(f"Request failed: {e}")
        return 0, str(e)

def run_usecase(name, **kwargs):
    print(f"--- Executing API calls for usecase: {name} ---")
    if name == "ViewHome":
        status, _ = make_request("GET", "/")
        print(f"GET / -> status {status}")

    elif name == "ViewAbout":
        status, _ = make_request("GET", "/about")
        print(f"GET /about -> status {status}")

    elif name == "ViewPostsArchive":
        status, _ = make_request("GET", "/posts/archive")
        print(f"GET /posts/archive -> status {status}")

    elif name == "ViewTags":
        status, _ = make_request("GET", "/tags")
        print(f"GET /tags -> status {status}")

    elif name == "UserLogin":
        status, _ = make_request("GET", "/login")
        print(f"GET /login -> status {status}")
        login_data = {
            "email": "admin@example.com",
            "password": "admin"
        }
        status, _ = make_request("POST", "/authenticate", login_data)
        print(f"POST /authenticate -> status {status}")

    elif name == "AdminViewPosts":
        status, _ = make_request("GET", "/admin/posts")
        print(f"GET /admin/posts -> status {status}")

    elif name == "AdminCreatePost":
        post_data = {
            "title": "Test Blog Post",
            "content": "This is test content for Mono2Micro dynamic tracing.",
            "postType": "POST",
            "postStatus": "PUBLISHED",
            "postFormat": "MARKDOWN",
            "tags": "java,mono2micro"
        }
        status, _ = make_request("POST", "/admin/posts", post_data)
        print(f"POST /admin/posts -> status {status}")

    elif name == "AdminViewUsers":
        status, _ = make_request("GET", "/admin/users")
        print(f"GET /admin/users -> status {status}")

    elif name == "AdminViewSettings":
        status, _ = make_request("GET", "/admin/settings")
        print(f"GET /admin/settings -> status {status}")

def run_all():
    for uc in USECASES:
        run_usecase(uc)
        time.sleep(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for SpringBlog")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase)
    else:
        run_all()
