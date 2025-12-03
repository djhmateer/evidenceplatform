from typing import Literal

from pydantic import BaseModel

supported_page_types = Literal["highlight", "story", "reel", "post", "profile"]
import json
from bs4 import BeautifulSoup
from typing import List, Optional

from extractors.models import HighlightsReelConnection, CommentsConnection, \
    ProfileTimeline, MediaShortcode, StoriesFeed
from extractors.models_graphql import ReelsMediaConnection
from extractors.models_har import HarRequest



def find_json_by_keyword(data: dict, keyword: str) -> List[dict]:
    matches = []

    def search(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if keyword in k and isinstance(v, dict):
                    matches.append(v)
                search(v)
        elif isinstance(obj, list):
            for item in obj:
                search(item)

    search(data)
    return matches


def infer_post_type_from_url(url: str) -> Optional[supported_page_types]:
    if "instagram.com" not in url:
        return None
    if "/stories/highlights/" in url:
        return "highlight"
    elif "/stories/" in url:
        return "story"
    elif "/reel/" in url:
        return "reel"
    elif "/p/" in url:
        return "post"
    return "profile"


class PageResponse(BaseModel):
    posts: Optional[MediaShortcode]
    comments: Optional[CommentsConnection]
    timelines: Optional[ProfileTimeline]
    highlight_reels: Optional[HighlightsReelConnection]
    stories: Optional[ReelsMediaConnection]
    stories_direct: Optional[StoriesFeed]


def extract_data_from_html_response(soup: BeautifulSoup) -> Optional[PageResponse]:
    post = None
    comments = None
    timeline = None
    highlight_reels = None
    stories = None
    stories_direct = None

    for script in soup.find_all("script", {"type": "application/json"}):
        if not script.string:
            continue
        try:
            json_data = json.loads(script.string)

            post_blobs = find_json_by_keyword(json_data, "xdt_api__v1__media__shortcode__web_info")
            timeline_blobs = find_json_by_keyword(json_data, "xdt_api__v1__profile_timeline")
            highlight_reels_blobs = find_json_by_keyword(json_data, "xdt_api__v1__feed__reels_media__connection")
            story_feeds = find_json_by_keyword(json_data, "xdt_api__v1__feed__reels_media")
            comment_blobs = find_json_by_keyword(json_data, "xdt_api__v1__media__media_id__comments__connection")

            for post_data in post_blobs:
                post = MediaShortcode(**post_data)

            for comment_data in comment_blobs:
                comments =CommentsConnection(**comment_data)

            for timeline_data in timeline_blobs:
                timeline = ProfileTimeline(**timeline_data)

            for reel_data in highlight_reels_blobs:
                highlight_reels = HighlightsReelConnection(**reel_data)

            for story_data in story_feeds:
                if story_data.get("edges"):
                    stories = ReelsMediaConnection(**story_data)
                elif story_data.get("reels_media"):
                    stories_direct = StoriesFeed(**story_data)

        except Exception as e:
            print("Failed to parse post from HTML:", e)
            continue
    if not post and not comments and not timeline and not highlight_reels and not stories and not stories_direct:
        res = None
    else:
        res = PageResponse(
            posts=post,
            comments=comments,
            timelines=timeline,
            highlight_reels=highlight_reels,
            stories=stories,
            stories_direct=stories_direct
        )
    return res


def extract_data_from_html_entry(html_data: str, req: HarRequest) -> Optional[PageResponse]:
    soup = BeautifulSoup(html_data, "html.parser")
    #html_type = infer_post_type_from_url(req.url)
    data = extract_data_from_html_response(soup)
    return data
