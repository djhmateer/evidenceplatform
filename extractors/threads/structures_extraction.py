"""Threads per-entry structure detection (host-routed by the generic dispatcher).

Threads (Meta codename "Barcelona") differs from Instagram in a way that dictates
this module's approach: its GraphQL content responses do **not** use Instagram's
``xdt_api__v1__*`` root-key convention. The same post object arrives under generic
roots via three different routes —

  * bare at ``data.data`` (BarcelonaLightboxDialogRootQuery / PostColumnPageQuery),
  * thread-wrapped at ``data.data.edges[].node.thread_items[].post`` (PostPageQuery),
  * HTML-embedded in a ``<script type="application/json">`` Relay bootstrap blob
    (``...result.data.mediaData.edges[].node.thread_items[].post``, ProfileThreadsTab).

So detection is **structural**, not key-based: we recursively walk any Threads
JSON (GraphQL body or each HTML script blob) and pick out every post object and
every user object by shape. This is route-agnostic — whichever way the user
reached the content, the same walk finds it — and robust to Meta renaming the
``Barcelona*`` queries.
"""
import json
from typing import Iterator, List, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

from extractors.models_har import HarRequest
from extractors.threads.models import ThreadsPost, ThreadsUser


class ThreadsResponse(BaseModel):
    """Container for the Threads posts/users recovered from one HAR entry."""
    model_config = ConfigDict(extra="allow")
    context: Optional[dict] = None
    posts: List[ThreadsPost] = []
    users: List[ThreadsUser] = []


THREADS_HOSTS = ("threads.com", "threads.net")


def is_threads_host(host: Optional[str]) -> bool:
    if not host:
        return False
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in THREADS_HOSTS)


def _is_graphql_url(url: str) -> bool:
    # Same endpoint paths Instagram uses; host routing (not this check) is what
    # separates the two platforms.
    return "graphql/query" in url or "/api/graphql" in url


def _iter_dicts(obj) -> Iterator[dict]:
    """Yield every dict nested anywhere within obj (depth-first, iterative)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _looks_like_post(d: dict) -> bool:
    # A Threads post (XDTTextPostApp media object) always carries a shortcode and
    # the Threads-specific text_post_app_info block. Carousel children lack
    # text_post_app_info, so they are not mistaken for standalone posts.
    return bool(d.get("code")) and ("text_post_app_info" in d)


def _looks_like_user(d: dict) -> bool:
    if not d.get("username") or not (d.get("pk") or d.get("id")):
        return False
    return any(k in d for k in (
        "biography", "follower_count", "friendship_status", "has_onboarded_to_text_post_app",
    ))


def _collect_from_json(data) -> ThreadsResponse:
    raw_posts: list[dict] = []
    raw_users: list[dict] = []
    seen_posts: set = set()
    seen_users: set = set()
    for d in _iter_dicts(data):
        if _looks_like_post(d):
            key = d.get("id") or d.get("pk") or id(d)
            if key not in seen_posts:
                seen_posts.add(key)
                raw_posts.append(d)
        elif _looks_like_user(d):
            key = d.get("pk") or d.get("id") or id(d)
            if key not in seen_users:
                seen_users.add(key)
                raw_users.append(d)
    posts: list[ThreadsPost] = []
    for p in raw_posts:
        try:
            posts.append(ThreadsPost(**p))
        except Exception as e:
            print(f"[threads] failed to parse post: {e}")
    users: list[ThreadsUser] = []
    for u in raw_users:
        try:
            users.append(ThreadsUser(**u))
        except Exception as e:
            print(f"[threads] failed to parse user: {e}")
    return ThreadsResponse(posts=posts, users=users)


def _merge(into: ThreadsResponse, other: ThreadsResponse) -> None:
    into.posts.extend(other.posts)
    into.users.extend(other.users)


def extract_structure_from_entry(entry: dict) -> Optional[ThreadsResponse]:
    """Detect and parse Threads content from a single HAR/WARC entry.

    GraphQL JSON bodies are walked directly; HTML pages have their
    ``<script type="application/json">`` Relay blobs walked individually. Returns
    None when no Threads post/user is found.
    """
    url: str = entry["request"]["url"]
    content: dict = entry["response"]["content"]
    mime: str = content.get("mimeType", "")
    body: Optional[str] = content.get("text")
    if not body:
        return None

    context = None
    try:
        req = HarRequest(**entry["request"])
        if req.postData and req.postData.params:
            context = {p["name"]: p["value"] for p in req.postData.params}
    except Exception:
        context = None

    result: Optional[ThreadsResponse] = None
    try:
        if _is_graphql_url(url) and not mime.startswith("text/html"):
            result = _collect_from_json(json.loads(body))
        elif mime.startswith("text/html"):
            soup = BeautifulSoup(body, "html.parser")
            agg = ThreadsResponse()
            for script in soup.find_all("script", {"type": "application/json"}):
                if not script.string:
                    continue
                try:
                    _merge(agg, _collect_from_json(json.loads(script.string)))
                except Exception:
                    continue
            result = agg
    except Exception as e:
        print(f"[threads] failed to extract structure: {e}")
        return None

    if not result or (not result.posts and not result.users):
        return None
    result.context = context
    return result
