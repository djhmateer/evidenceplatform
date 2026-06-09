from typing import Optional, Dict
from pydantic import BaseModel
from extractors.models import StoriesFeed, CommentsConnection, MediaShortcode
from extractors.models_api_v1 import LikersApiV1
from extractors.models_graphql import ProfileTimelineGraphQL, FriendsListGraphQL, ReelsMediaConnection, \
    ClipsUserConnection, ProfileInfoUserGraphQL


def is_graphql_url(url: str) -> bool:
    """True if a request URL is an Instagram GraphQL endpoint whose response
    `extract_graphql_from_response` can parse. Instagram serves these from two
    paths: the web `…/graphql/query` endpoint and the `…/api/graphql` endpoint
    (which carries, among others, the PolarisProfilePageContentQuery `data.user`
    profile/biography response and the `xdt_api__v1__discover__chaining` friends
    list). Both must be scanned; matching only `graphql/query` silently drops
    everything that arrives via `/api/graphql`."""
    return "graphql/query" in url or "/api/graphql" in url


class GraphQLResponse(BaseModel):
    context: Optional[Dict] = None
    profile_timeline: Optional[ProfileTimelineGraphQL] = None
    friends_list: Optional[FriendsListGraphQL] = None
    reels_media: Optional[ReelsMediaConnection] = None
    clips_user_connection: Optional[ClipsUserConnection] = None
    stories_feed: Optional[StoriesFeed] = None
    comments_connection: Optional[CommentsConnection] = None
    likes: Optional[LikersApiV1] = None
    post_shortcode: Optional[MediaShortcode] = None
    profile_info: Optional[ProfileInfoUserGraphQL] = None


def extract_graphql_from_response(
    response_json: dict,
    context: Optional[Dict] = None,
) -> Optional[GraphQLResponse]:
    """
    Detects GraphQL query type by inspecting the response JSON structure.
    Does not require the X-FB-Friendly-Name request header, making it
    suitable for both HAR and WACZ/WARC archives.

    context: optional dict of POST params from the HAR request (used to
    populate structure.context for downstream comment/like/account URL
    construction). Pass None for WACZ where request params are unavailable.
    """
    data = response_json.get("data", {})
    if not data:
        return None

    res = GraphQLResponse(context=context or {})

    try:
        if "xdt_api__v1__feed__user_timeline_graphql_connection" in data:
            res.profile_timeline = ProfileTimelineGraphQL(
                **data["xdt_api__v1__feed__user_timeline_graphql_connection"]
            )
    except Exception as e:
        print(f"[graphql_response] Error parsing profile_timeline: {e}")

    try:
        if "xdt_api__v1__discover__chaining" in data:
            res.friends_list = FriendsListGraphQL(**data["xdt_api__v1__discover__chaining"])
    except Exception as e:
        print(f"[graphql_response] Error parsing friends_list: {e}")

    try:
        if "xdt_api__v1__feed__reels_media__connection" in data:
            res.reels_media = ReelsMediaConnection(**data["xdt_api__v1__feed__reels_media__connection"])
    except Exception as e:
        print(f"[graphql_response] Error parsing reels_media: {e}")

    try:
        if "xdt_api__v1__feed__reels_media" in data:
            res.stories_feed = StoriesFeed(**data["xdt_api__v1__feed__reels_media"])
    except Exception as e:
        print(f"[graphql_response] Error parsing stories_feed: {e}")

    try:
        if "xdt_api__v1__clips__user__connection_v2" in data:
            res.clips_user_connection = ClipsUserConnection(
                **data["xdt_api__v1__clips__user__connection_v2"]
            )
    except Exception as e:
        print(f"[graphql_response] Error parsing clips_user_connection: {e}")

    try:
        if "xdt_api__v1__media__media_id__comments__connection" in data:
            res.comments_connection = CommentsConnection(
                **data["xdt_api__v1__media__media_id__comments__connection"]
            )
    except Exception as e:
        print(f"[graphql_response] Error parsing comments_connection: {e}")

    try:
        if "xdt_api__v1__likes__media_id__likers" in data:
            res.likes = LikersApiV1(**data["xdt_api__v1__likes__media_id__likers"])
    except Exception as e:
        print(f"[graphql_response] Error parsing likes: {e}")

    try:
        if "xdt_api__v1__media__shortcode__web_info" in data:
            res.post_shortcode = MediaShortcode(**data["xdt_api__v1__media__shortcode__web_info"])
    except Exception as e:
        print(f"[graphql_response] Error parsing post_shortcode: {e}")

    try:
        # PolarisProfilePageContentQuery returns the viewed profile (with its
        # biography) directly under data.user. Detect on the biography key so
        # only profile-content responses match, not other data.user shapes.
        user_obj = data.get("user")
        if isinstance(user_obj, dict) and "biography" in user_obj:
            res.profile_info = ProfileInfoUserGraphQL(**user_obj)
    except Exception as e:
        print(f"[graphql_response] Error parsing profile_info: {e}")

    return res if any([
        res.profile_timeline,
        res.friends_list,
        res.reels_media,
        res.clips_user_connection,
        res.stories_feed,
        res.comments_connection,
        res.likes,
        res.post_shortcode,
        res.profile_info,
    ]) else None
