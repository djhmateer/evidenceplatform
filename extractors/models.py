from typing import List, Optional, Any

from pydantic import BaseModel, Field


class InstagramCaption(BaseModel):
    created_at: int
    has_translation: Optional[bool] = None
    pk: str
    text: str

    class Config:
        populate_by_name = True
        extra = "allow"

class InstagramImageCandidate(BaseModel):
    height: int
    url: str
    width: int

    class Config:
        populate_by_name = True
        extra = "allow"

class ScrubberSpritesheetDefault(BaseModel):
    file_size_kb: int
    max_thumbnails_per_sprite: int
    rendered_width: int
    sprite_height: int
    sprite_urls: List[str]
    sprite_width: int
    thumbnail_duration: float
    thumbnail_height: int
    thumbnail_width: int
    thumbnails_per_row: int
    total_thumbnail_num_per_sprite: int
    video_length: float

    class Config:
        extra = "allow"

class ScrubberSpritesheetInfoCandidates(BaseModel):
    default: Optional[ScrubberSpritesheetDefault] = None

    class Config:
        extra = "allow"

class AdditionalCandidates(BaseModel):
    first_frame: Optional[InstagramImageCandidate] = None
    igtv_first_frame: Optional[InstagramImageCandidate] = None
    smart_frame: Optional[InstagramImageCandidate] = None # Assuming same structure or Any

    class Config:
        extra = "allow"

class InstagramImageVersions2(BaseModel):
    candidates: Optional[List[InstagramImageCandidate]] = Field(default_factory=list)
    additional_candidates: Optional[AdditionalCandidates] = None
    scrubber_spritesheet_info_candidates: Optional[ScrubberSpritesheetInfoCandidates] = None

    class Config:
        extra = "allow"

class VideoVersion(BaseModel):
    id: Optional[str] = None
    url: str
    type: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    bandwidth: Optional[int] = None # Made optional as not always present for all types

    class Config:
        extra = "allow"

class InstagramSharingFrictionInfo(BaseModel):
    bloks_app_url: Optional[str] = None
    should_have_sharing_friction: bool

    class Config:
        populate_by_name = True
        extra = "allow"

class InstagramUserTagUser(BaseModel):
    full_name: str
    id: str
    is_verified: bool
    pk: str
    profile_pic_url: str
    username: str

    class Config:
        populate_by_name = True
        extra = "allow"

class InstagramUserTag(BaseModel):
    position: List[float]
    user: InstagramUserTagUser

    class Config:
        populate_by_name = True
        extra = "allow"

class InstagramUserTags(BaseModel):
    in_field: Optional[List[InstagramUserTag]] = Field(None, alias="in")

    class Config:
        populate_by_name = True
        extra = "allow"


class InstagramCarouselMedia(BaseModel):
    accessibility_caption: Optional[str] = None
    carousel_parent_id: Optional[str] = None
    display_uri: Optional[str] = None
    has_liked: Optional[bool] = None
    id: Optional[str] = None
    image_versions2: Optional[InstagramImageVersions2] = None
    inventory_source: Optional[Any] = None
    is_dash_eligible: Optional[Any] = None
    like_count: Optional[int] = None
    link: Optional[Any] = None
    logging_info_token: Optional[Any] = None
    media_overlay_info: Optional[Any] = None
    media_type: Optional[int] = None
    number_of_qualities: Optional[Any] = None
    organic_tracking_token: Optional[Any] = None
    original_height: Optional[int] = None
    original_width: Optional[int] = None
    owner: Optional[Any] = None # Could be a more specific User model if structure is known
    pk: Optional[str] = None
    preview: Optional[str] = None
    previous_submitter: Optional[Any] = None
    sharing_friction_info: Optional[InstagramSharingFrictionInfo] = None
    story_cta: Optional[Any] = None
    taken_at: Optional[int] = None
    user: Optional[Any] = None # Could be a more specific User model if structure is known
    usertags: Optional[InstagramUserTags] = None
    video_dash_manifest: Optional[Any] = None
    video_versions: Optional[List[VideoVersion]] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class InstagramLocation(BaseModel):
    typename: Optional[str] = Field(None, alias="__typename")
    lat: Optional[float] = None
    lng: Optional[float] = None
    name: Optional[str] = None
    pk: Optional[int] = None
    profile_pic_url: Optional[str] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class InstagramFriendshipStatus(BaseModel):
    following: Optional[bool] = None
    blocking: Optional[Any] = None
    followed_by: Optional[Any] = None
    incoming_request: Optional[Any] = None
    is_feed_favorite: Optional[bool] = None
    is_private: Optional[bool] = None
    is_restricted: Optional[bool] = None
    is_viewer_unconnected: Optional[Any] = None
    muting: Optional[Any] = None
    outgoing_request: Optional[Any] = None
    subscribed: Optional[Any] = None

    class Config:
        populate_by_name = True
        extra = "allow"


class InstagramHdProfilePicUrlInfo(BaseModel):
    url: str

    class Config:
        populate_by_name = True
        extra = "allow"

class InstagramUser(BaseModel):
    typename: Optional[str] = Field(None, alias="__typename")
    ai_agent_owner_username: Optional[Any] = None
    friendship_status: Optional[InstagramFriendshipStatus] = None
    id: Optional[str] = None
    is_private: Optional[bool] = None
    is_unpublished: Optional[bool] = None
    is_verified: Optional[bool] = None
    pk: Optional[str] = None
    profile_pic_url: Optional[str] = None
    show_account_transparency_details: Optional[bool] = None
    transparency_label: Optional[Any] = None
    transparency_product: Optional[Any] = None
    transparency_product_enabled: Optional[bool] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    hd_profile_pic_url_info: Optional[InstagramHdProfilePicUrlInfo] = None
    is_embeds_disabled: Optional[bool] = None
    latest_reel_media: Optional[int] = None
    live_broadcast_id: Optional[Any] = None
    live_broadcast_visibility: Optional[Any] = None

    class Config:
        populate_by_name = True
        extra = "allow"


class InstagramPost(BaseModel):
    accessibility_caption: Optional[str] = None
    ad_id: Optional[Any] = None
    affiliate_info: Optional[Any] = None
    all_previous_submitters: Optional[List[Any]] = None
    boost_unavailable_identifier: Optional[Any] = None
    boost_unavailable_reason: Optional[Any] = None
    boosted_status: Optional[Any] = None
    can_reshare: Optional[Any] = None
    can_see_insights_as_brand: Optional[bool] = None
    can_viewer_reshare: Optional[bool] = None
    caption: Optional[InstagramCaption] = None
    caption_is_edited: Optional[bool] = None
    carousel_media: Optional[List[InstagramCarouselMedia]] = None
    carousel_media_count: Optional[int] = None
    carousel_parent_id: Optional[str] = None
    clips_attribution_info: Optional[Any] = None
    clips_metadata: Optional[Any] = None
    coauthor_producers: Optional[List[Any]] = None
    code: Optional[str] = None
    comment_count: Optional[int] = None
    commenting_disabled_for_viewer: Optional[Any] = None
    comments_disabled: Optional[Any] = None
    display_uri: Optional[str] = None # This seems to be None in the example, but often present
    facepile_top_likers: Optional[List[Any]] = None
    fb_like_count: Optional[Any] = None
    feed_demotion_control: Optional[Any] = None
    feed_recs_demotion_control: Optional[Any] = None
    follow_hashtag_info: Optional[Any] = None
    group: Optional[Any] = None
    has_audio: Optional[Any] = None
    has_liked: Optional[bool] = None
    has_viewer_saved: Optional[Any] = None
    id: Optional[str] = None
    ig_media_sharing_disabled: Optional[bool] = None
    image_versions2: Optional[InstagramImageVersions2] = None
    inventory_source: Optional[Any] = None
    invited_coauthor_producers: Optional[List[Any]] = None
    is_dash_eligible: Optional[Any] = None
    is_paid_partnership: Optional[bool] = None
    like_and_view_counts_disabled: Optional[bool] = None
    like_count: Optional[int] = None
    link: Optional[Any] = None
    location: Optional[InstagramLocation] = None
    logging_info_token: Optional[Any] = None
    main_feed_carousel_starting_media_id: Optional[Any] = None
    media_level_comment_controls: Optional[Any] = None
    media_overlay_info: Optional[Any] = None
    media_type: Optional[int] = None
    number_of_qualities: Optional[Any] = None
    open_carousel_submission_state: Optional[str] = None
    organic_tracking_token: Optional[str] = None
    original_height: Optional[int] = None
    original_width: Optional[int] = None
    owner: InstagramUser
    pk: str
    preview: Optional[Any] = None
    preview_comments: Optional[List[Any]] = None # Could be List[InstagramCommentPreview] if structure known
    previous_submitter: Optional[Any] = None
    product_type: Optional[str] = None
    saved_collection_ids: Optional[Any] = None
    sharing_friction_info: InstagramSharingFrictionInfo
    social_context: Optional[List[Any]] = None
    sponsor_tags: Optional[Any] = None
    story_cta: Optional[Any] = None
    taken_at: Optional[int] = None
    top_likers: Optional[List[Any]] = None
    user: InstagramUser # This seems to be the same structure as owner in the example
    usertags: Optional[InstagramUserTags] = None
    video_dash_manifest: Optional[Any] = None
    video_versions: Optional[List[VideoVersion]] = None # Could be List[InstagramVideoVersion] if structure known
    view_count: Optional[Any] = None
    wearable_attribution_info: Optional[Any] = None

    class Config:
        populate_by_name = True
        extra = "allow"


class MediaShortcode(BaseModel):
    items: List[InstagramPost]

    class Config:
        populate_by_name = True
        extra = "allow"


class PostCommentUser(BaseModel):
    fbid_v2: Optional[str] = None
    id: str
    is_unpublished: Optional[Any] = None
    is_verified: Optional[bool] = None
    pk: str
    profile_pic_url: Optional[str] = None
    username: str

    class Config:
        populate_by_name = True
        extra = "allow"


class PostComment(BaseModel):
    typename: Optional[str] = Field(None, alias="__typename")
    child_comment_count: Optional[int] = None
    comment_like_count: Optional[int] = None
    created_at: int
    giphy_media_info: Optional[Any] = None
    has_liked_comment: Optional[bool] = None
    has_translation: Optional[bool] = None
    is_covered: Optional[bool] = None
    parent_comment_id: Optional[str] = None # refers to the parent comment's pk value if it's a reply
    pk: str
    restricted_status: Optional[Any] = None
    text: str
    user: PostCommentUser

    class Config:
        populate_by_name = True
        extra = "allow"


class PostCommentNode(BaseModel):
    node: PostComment

    class Config:
        populate_by_name = True
        extra = "allow"

class CommentsConnection(BaseModel):
    count: Optional[int] = None
    page_info: Optional[Any] = None # Could be a more specific PageInfo model if structure is known
    edges: List[PostCommentNode] = Field(default_factory=list)

    class Config:
        populate_by_name = True
        extra = "allow"


# Re-using existing models if their structure matches
# from .existing_models import InstagramImageVersions2, InstagramSharingFrictionInfo
# Assuming InstagramImageVersions2 and InstagramSharingFrictionInfo are defined as in the previous conversation history
class IGMention(BaseModel):
    username: str
    full_name: Optional[str] = None

    class Config:
        populate_by_name = True

class BlokStickerData(BaseModel):
    ig_mention: IGMention

    class Config:
        populate_by_name = True
        extra = "allow"

class BlokStickerInner(BaseModel):
    sticker_data: BlokStickerData

    class Config:
        populate_by_name = True
        extra = "allow"

class StoryBlokSticker(BaseModel):
    bloks_sticker: BlokStickerInner

class HighlightsReelUser(BaseModel):
    pk: str
    id: str
    interop_messaging_user_fbid: Optional[Any] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class HighlightsReel(BaseModel):
    pk: str
    id: str
    has_audio: Optional[bool] = None
    story_music_stickers: Optional[Any] = None
    user: HighlightsReelUser
    inventory_source: Optional[Any] = None
    boosted_status: Optional[Any] = None
    boost_unavailable_identifier: Optional[Any] = None
    boost_unavailable_reason: Optional[Any] = None
    product_type: str
    carousel_media_count: Optional[Any] = None
    carousel_media: Optional[List[InstagramCarouselMedia]] = None # Could be List[InstagramCarouselMedia] if structure is known
    media_overlay_info: Optional[Any] = None
    caption: Optional[InstagramCaption] = None # Could be InstagramCaption if structure is known
    accessibility_caption: Optional[str] = None
    image_versions2: InstagramImageVersions2
    organic_tracking_token: Optional[str] = None
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    taken_at: int
    is_dash_eligible: Optional[int] = None # Or bool, example shows int
    number_of_qualities: Optional[int] = None
    video_dash_manifest: Optional[str] = None
    video_versions: Optional[List[VideoVersion]] = None
    media_type: int
    visual_comment_reply_sticker_info: Optional[Any] = None
    story_bloks_stickers: Optional[List[StoryBlokSticker]] = None
    story_link_stickers: Optional[Any] = None
    story_hashtags: Optional[Any] = None # Could be List[StoryHashtag]
    story_locations: Optional[Any] = None # Could be List[StoryLocation]
    story_feed_media: Optional[Any] = None
    text_post_share_to_ig_story_stickers: Optional[Any] = None
    story_countdowns: Optional[Any] = None
    story_questions: Optional[Any] = None
    story_sliders: Optional[Any] = None
    story_cta: Optional[Any] = None
    link: Optional[Any] = None
    reel_media_background: Optional[Any] = None
    video_duration: Optional[float] = None
    preview: Optional[Any] = None
    expiring_at: Optional[Any] = None # Typically an int timestamp or datetime
    is_paid_partnership: Optional[bool] = None
    sponsor_tags: Optional[Any] = None
    wearable_attribution_info: Optional[Any] = None
    reshared_story_media_author: Optional[Any] = None
    story_app_attribution: Optional[Any] = None
    has_translation: Optional[bool] = None
    can_see_insights_as_brand: Optional[bool] = None
    audience: Optional[Any] = None
    has_liked: Optional[bool] = None
    viewer_count: Optional[Any] = None # Typically int
    viewers: Optional[Any] = None # Could be List[User]
    sharing_friction_info: InstagramSharingFrictionInfo
    can_viewer_reshare: Optional[Any] = None # Typically bool
    ig_media_sharing_disabled: Optional[bool] = None
    can_reply: Optional[bool] = None
    can_reshare: Optional[bool] = None
    typename: Optional[str] = Field(None, alias="__typename")

    class Config:
        populate_by_name = True
        extra = "allow"

class HighlightsReelPageInfo(BaseModel):
    end_cursor: str
    has_next_page: bool
    has_previous_page: bool
    start_cursor: str

    class Config:
        populate_by_name = True
        extra = "allow"

class HighlightsReelUploader(BaseModel):
    pk: str
    id: str
    interop_messaging_user_fbid: Optional[str] = None
    username: str
    user_id: Optional[str] = None
    profile_pic_url: Optional[str] = None
    is_verified: bool = False
    transparency_label: Optional[Any] = None
    transparency_product: Optional[Any] = None
    transparency_product_enabled: bool = False
    is_private: bool = False
    class Config:
        populate_by_name = True
        extra = "allow"


class HighlightsReelWrap(BaseModel):
    id: str
    title: Optional[str] = None
    items: list[HighlightsReel]
    user: HighlightsReelUploader


class HighlightsReelNode(BaseModel):
    node: HighlightsReelWrap

    class Config:
        populate_by_name = True
        extra = "allow"

class HighlightsReelConnection(BaseModel):
    id: Optional[str] = None
    edges: List[HighlightsReelNode]
    page_info: HighlightsReelPageInfo

    class Config:
        populate_by_name = True
        extra = "allow"


class TimelineItemSquareCrop(BaseModel):
    crop_bottom: int
    crop_left: int
    crop_right: int
    crop_top: int

    class Config:
        populate_by_name = True
        extra = "allow"

class TimelineItemMediaCroppingInfo(BaseModel):
    square_crop: Optional[TimelineItemSquareCrop] = None
    four_by_three_crop: Optional[Any] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class TimelineItemUser(BaseModel):
    pk: str
    username: str
    id: str

    class Config:
        populate_by_name = True
        extra = "allow"

class TimelineItem(BaseModel):
    pk: str
    accessibility_caption: Optional[str] = None
    caption: Optional[Any] = None # Could be InstagramCaption if structure is known
    audience: Optional[Any] = None
    carousel_media_count: Optional[int] = None
    display_uri: Optional[str] = None
    media_type: int
    carousel_media: Optional[List[InstagramCarouselMedia]] = None # Could be List[InstagramCarouselMedia] if structure is known
    image_versions2: InstagramImageVersions2
    video_versions: Optional[List[VideoVersion]] = None
    code: Optional[str] = None
    media_cropping_info: Optional[TimelineItemMediaCroppingInfo] = None
    profile_grid_thumbnail_fitting_style: Optional[str] = None
    media_overlay_info: Optional[Any] = None
    preview: Optional[Any] = None
    product_type: Optional[str] = None
    thumbnails: Optional[Any] = None
    timeline_pinned_user_ids: Optional[List[str]] = None # Assuming list of user ID strings
    upcoming_event: Optional[Any] = None
    user: TimelineItemUser
    like_count: int
    like_and_view_counts_disabled: bool
    boosted_status: Optional[Any] = None
    boost_unavailable_identifier: Optional[Any] = None
    boost_unavailable_reason: Optional[Any] = None
    comment_count: int
    comments_disabled: Optional[Any] = None
    view_count: Optional[int] = None
    id: str

    class Config:
        populate_by_name = True
        extra = "allow"

class ProfileTimeline(BaseModel):
    num_results: int
    items: List[TimelineItem]

    class Config:
        populate_by_name = True
        extra = "allow"

class StoryFeedMediaItem(BaseModel):
    x: float
    y: float
    width: float
    height: float
    rotation: float
    media_code: Optional[str] = None
    id: Optional[str] = None
    product_type: str

    class Config:
        populate_by_name = True
        extra = "allow"

class BloksStickerDataIgMention(BaseModel):
    full_name: str
    username: str

    class Config:
        populate_by_name = True
        extra = "allow"


class BloksStickerData(BaseModel):
    ig_mention: BloksStickerDataIgMention

    class Config:
        populate_by_name = True
        extra = "allow"


class BloksSticker(BaseModel):
    sticker_data: BloksStickerData
    id: str # e.g., "bloks_sticker_id"

    class Config:
        populate_by_name = True
        extra = "allow"


class StoryBloksStickerItem(BaseModel):
    x: float
    y: float
    width: float
    height: float
    rotation: float
    bloks_sticker: BloksSticker
    id: Optional[str] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class StoryItem(BaseModel):
    id: str
    original_height: int
    original_width: int
    image_versions2: InstagramImageVersions2
    media_type: int
    pk: str
    has_audio: Optional[bool] = None
    story_music_stickers: Optional[Any] = None
    user: HighlightsReelUser # Reusing HighlightsReelUser as structure matches
    inventory_source: Optional[Any] = None
    boosted_status: Optional[Any] = None
    boost_unavailable_identifier: Optional[Any] = None
    boost_unavailable_reason: Optional[Any] = None
    product_type: str
    carousel_media_count: Optional[int] = None
    carousel_media: Optional[List[InstagramCarouselMedia]] = None
    media_overlay_info: Optional[Any] = None
    caption: Optional[InstagramCaption] = None
    accessibility_caption: Optional[str] = None
    organic_tracking_token: Optional[str] = None
    taken_at: Optional[int] = None
    is_dash_eligible: Optional[int] = None
    number_of_qualities: Optional[int] = None
    video_dash_manifest: Optional[str] = None
    video_versions: Optional[List[VideoVersion]] = None # Reusing
    visual_comment_reply_sticker_info: Optional[Any] = None
    story_bloks_stickers: Optional[list[StoryBloksStickerItem]] = None
    story_link_stickers: Optional[Any] = None
    story_hashtags: Optional[Any] = None
    story_locations: Optional[Any] = None
    story_feed_media: Optional[List[StoryFeedMediaItem]] = None
    text_post_share_to_ig_story_stickers: Optional[Any] = None
    story_countdowns: Optional[Any] = None
    story_questions: Optional[Any] = None
    story_sliders: Optional[Any] = None
    story_cta: Optional[Any] = None
    link: Optional[Any] = None
    reel_media_background: Optional[Any] = None
    video_duration: Optional[float] = None # Example shows 15, could be int or float
    preview: Optional[Any] = None
    expiring_at: Optional[int] = None
    is_paid_partnership: Optional[bool] = False
    sponsor_tags: Optional[Any] = None
    wearable_attribution_info: Optional[Any] = None
    reshared_story_media_author: Optional[Any] = None
    story_app_attribution: Optional[Any] = None
    has_translation: Optional[bool] = False
    can_see_insights_as_brand: Optional[bool] = False
    audience: Optional[Any] = None
    has_liked: Optional[bool] = False
    viewer_count: Optional[int] = None
    viewers: Optional[Any] = None
    sharing_friction_info: InstagramSharingFrictionInfo # Reusing
    can_viewer_reshare: Optional[bool] = None
    ig_media_sharing_disabled: Optional[bool] = False
    can_reply: Optional[bool] = False
    can_reshare: Optional[bool] = False
    typename: Optional[str] = Field(None, alias="__typename")

    class Config:
        populate_by_name = True
        extra = "allow"

class StoryUserFriendshipStatus(BaseModel):
    following: bool

    class Config:
        populate_by_name = True
        extra = "allow"

class StoryUser(BaseModel):
    pk: str
    id: str
    username: str
    typename: Optional[str] = Field(None, alias="__typename")
    friendship_status: Optional[StoryUserFriendshipStatus] = None
    interop_messaging_user_fbid: Optional[str] = None
    user_id: Optional[str] = None # Assuming string if not null
    profile_pic_url: str
    is_verified: bool
    transparency_label: Optional[Any] = None
    transparency_product: Optional[Any] = None
    transparency_product_enabled: Optional[bool] = None
    is_private: bool

    class Config:
        populate_by_name = True
        extra = "allow"

class StoriesReelMedia(BaseModel):
    id: str
    reel_type: str
    items: List[StoryItem]
    user: StoryUser
    seen: Optional[int] = None
    cover_media: Optional[Any] = None
    title: Optional[Any] = None
    latest_reel_media: Optional[int] = None
    muted: Optional[Any] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class StoriesFeed(BaseModel):
    reels_media: List[StoriesReelMedia]

    class Config:
        populate_by_name = True
        extra = "allow"

