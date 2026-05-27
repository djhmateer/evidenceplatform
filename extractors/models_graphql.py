from typing import Optional, List, Any

from pydantic import ConfigDict, BaseModel, Field

from extractors.models import InstagramPost, HighlightsReel, StoryUser, HighlightsReelPageInfo, VideoVersion, \
    InstagramImageVersions2, InstagramCarouselMedia, HighlightsReelUser


class ProfileTimelinePageInfo(BaseModel):
    end_cursor: Optional[str] = None
    has_next_page: bool
    has_previous_page: Optional[bool] = None
    start_cursor: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ProfileTimelineEdge(BaseModel):
    node: InstagramPost # Reusing InstagramPost as the structure matches
    cursor: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ProfileTimelineGraphQL(BaseModel):
    edges: List[ProfileTimelineEdge]
    page_info: Optional[ProfileTimelinePageInfo] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class FriendUser(BaseModel):
    friendship_status: Optional[Any] = None
    full_name: Optional[str] = None
    is_verified: Optional[bool] = None
    pk: Optional[str] = None
    profile_pic_url: Optional[str] = None
    username: Optional[str] = None
    is_private: Optional[bool] = None
    supervision_info: Optional[Any] = None
    social_context: Optional[str] = None
    live_broadcast_visibility: Optional[Any] = None
    live_broadcast_id: Optional[Any] = None
    hd_profile_pic_url_info: Optional[Any] = None
    is_unpublished: Optional[bool] = None # Assuming boolean if not null
    id: str

    model_config = ConfigDict(extra="allow")


class FriendsListGraphQL(BaseModel):
    users: List[FriendUser]

    model_config = ConfigDict(extra="allow")


class ReelsMediaCoverMediaCroppedImageVersion(BaseModel):
    url: str

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class ReelsMediaCoverMedia(BaseModel):
    cropped_image_version: Optional[ReelsMediaCoverMediaCroppedImageVersion] = None
    full_image_version: Optional[Any] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class ReelsMediaNode(BaseModel):
    id: str
    items: List[HighlightsReel]
    user: StoryUser
    seen: Optional[int] = None
    reel_type: str
    cover_media: Optional[ReelsMediaCoverMedia] = None
    title: Optional[str] = None
    latest_reel_media: Optional[int] = None
    muted: Optional[Any] = None
    typename: str = Field(alias="__typename")

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class ReelsMediaEdge(BaseModel):
    node: ReelsMediaNode
    cursor: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class ReelsMediaConnection(BaseModel):
    edges: List[ReelsMediaEdge]
    page_info: HighlightsReelPageInfo

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class GenericCursorInfo(BaseModel): # Placeholder
    end_cursor: Optional[str] = None
    has_next_page: bool
    has_previous_page: Optional[bool] = None
    start_cursor: Optional[str] = None
    model_config = ConfigDict(extra="allow", populate_by_name=True)



class ClipsUserMedia(BaseModel):
    pk: str
    id: str
    code: str
    media_overlay_info: Optional[Any] = None
    boosted_status: Optional[Any] = None
    boost_unavailable_identifier: Optional[Any] = None
    boost_unavailable_reason: Optional[Any] = None
    user: HighlightsReelUser # Reusing HighlightsReelUser
    product_type: str
    play_count: Optional[int] = None # Made optional as it might not always be present
    view_count: Optional[int] = None
    like_and_view_counts_disabled: Optional[bool] = None
    comment_count: int
    like_count: int
    audience: Optional[Any] = None
    clips_tab_pinned_user_ids: Optional[List[str]] = None
    has_views_fetching: Optional[bool] = None
    media_type: int
    carousel_media: Optional[List[InstagramCarouselMedia]] = None
    image_versions2: InstagramImageVersions2
    video_versions: Optional[List[VideoVersion]] = None
    preview: Optional[Any] = None
    original_height: int
    original_width: int

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class ClipsUserNode(BaseModel):
    media: ClipsUserMedia
    typename: str = Field(alias="__typename")

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class ClipsUserEdge(BaseModel):
    node: ClipsUserNode
    cursor: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")

class ClipsUserConnection(BaseModel):
    edges: List[ClipsUserEdge]
    page_info: GenericCursorInfo

    model_config = ConfigDict(populate_by_name=True, extra="allow")