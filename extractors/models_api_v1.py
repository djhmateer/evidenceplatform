from typing import List, Optional, Any, Union

from pydantic import BaseModel, Field

from extractors.models import VideoVersion, InstagramImageVersions2


class FriendshipUserApiV1(BaseModel):
    pk: str
    pk_id: str
    id: str
    full_name: str
    is_private: bool
    fbid_v2: Optional[str] = None
    third_party_downloads_enabled: Optional[int] = None
    strong_id__: Optional[str] = Field(None, alias="strong_id__") # Using alias for field with double underscore
    profile_pic_id: Optional[str] = None
    profile_pic_url: str
    is_verified: bool
    username: str
    has_anonymous_profile_picture: Optional[bool] = None
    account_badges: Optional[List[Any]] = Field(default_factory=list)
    latest_reel_media: Optional[int] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class FriendshipsApiV1(BaseModel):
    users: List[FriendshipUserApiV1]
    big_list: Optional[bool] = None
    page_size: Optional[int] = None
    has_more: Optional[bool] = None
    should_limit_list_of_followers: Optional[bool] = None
    use_clickable_see_more: Optional[bool] = None
    show_spam_follow_request_tab: Optional[bool] = None
    follow_ranking_token: Optional[str] = None
    status: str

    class Config:
        extra = "allow"

class FriendshipStatusApiV1(BaseModel):
    is_muting_reel: Optional[bool] = None
    is_blocking_reel: Optional[bool] = None
    is_muting_notes: Optional[bool] = None
    following: Optional[bool] = None
    is_bestie: Optional[bool] = None
    is_feed_favorite: Optional[bool] = None
    is_private: Optional[bool] = None
    is_restricted: Optional[bool] = None
    incoming_request: Optional[bool] = None
    outgoing_request: Optional[bool] = None
    followed_by: Optional[bool] = None
    muting: Optional[bool] = None
    blocking: Optional[bool] = None
    is_eligible_to_subscribe: Optional[bool] = None
    subscribed: Optional[bool] = None

    class Config:
        populate_by_name = True
        extra = "allow"


class LikerUserApiV1(BaseModel):
    pk: str
    pk_id: Optional[str] = None
    full_name: str
    is_private: Optional[bool] = None
    strong_id__: Optional[str] = Field(None, alias="strong_id__")
    id: str
    username: str
    is_verified: bool
    profile_pic_id: Optional[str] = None
    profile_pic_url: str
    account_badges: Optional[List[Any]] = Field(default_factory=list)
    friendship_status: Optional[FriendshipStatusApiV1] = None
    latest_reel_media: Optional[int] = None
    social_context: Optional[Any] = None
    supervision_info: Optional[Any] = None
    live_broadcast_visibility: Optional[Any] = None
    live_broadcast_id: Optional[Any] = None
    hd_profile_pic_url_info: Optional[Any] = None
    is_unpublished: Optional[Any] = None

    class Config:
        populate_by_name = True
        extra = "allow"


class LikersApiV1(BaseModel):
    users: List[LikerUserApiV1]
    user_count: Optional[int] = None
    follow_ranking_token: Optional[str] = None
    status: Optional[str] = None

    class Config:
        extra = "allow"

class CommentUserApiV1(BaseModel):
    pk: Union[str, int]
    pk_id: Union[str, int]
    id: Union[str, int]
    full_name: str
    is_private: bool
    is_unpublished: Optional[bool] = None
    strong_id__: str = Field(alias="strong_id__")
    fbid_v2: Optional[str] = None
    username: str
    is_verified: bool
    profile_pic_id: Optional[str] = None
    profile_pic_url: str
    is_mentionable: Optional[bool] = None # Specific to user in comment items

    class Config:
        populate_by_name = True
        extra = "allow"

class CommentCaptionApiV1(BaseModel):
    pk: Union[str, int]
    user_id: Union[str, int]
    type: int
    did_report_as_spam: bool
    created_at: int
    created_at_utc: int
    created_at_for_fb_app: Optional[int] = None # Assuming this is an epoch timestamp
    content_type: str
    status: str
    bit_flags: int
    share_enabled: bool
    is_ranked_comment: bool
    media_id: str
    is_created_by_media_owner: Optional[bool] = None
    strong_id__: str = Field(alias="strong_id__")
    text: str
    is_covered: bool
    liked_by_media_coauthors: Optional[List[Any]] = Field(default_factory=list)
    private_reply_status: int
    has_translation: Optional[bool] = None
    user: CommentUserApiV1

    class Config:
        populate_by_name = True
        extra = "allow"

class CommentItemApiV1(BaseModel):
    pk: Union[str, int]
    user_id: Union[str, int]
    type: int
    did_report_as_spam: bool
    created_at: int
    created_at_utc: int
    created_at_for_fb_app: int # Assuming this is an epoch timestamp
    content_type: str
    status: str
    bit_flags: int
    share_enabled: bool
    is_ranked_comment: bool
    media_id: str
    comment_index: Optional[int] = None
    strong_id__: str = Field(alias="strong_id__")
    text: str
    is_covered: bool
    liked_by_media_coauthors: Optional[List[Any]] = Field(default_factory=list)
    inline_composer_display_condition: Optional[str] = None
    has_liked_comment: bool
    has_disliked_comment: Optional[bool] = None # Assuming this can be absent
    comment_like_count: int
    private_reply_status: int
    has_translation: Optional[bool] = None
    preview_child_comments: Optional[List[Any]] = Field(default_factory=list)
    child_comment_count: int
    other_preview_users: Optional[List[Any]] = Field(default_factory=list)
    user: CommentUserApiV1

    class Config:
        populate_by_name = True
        extra = "allow"

class QuickResponseEmojiApiV1(BaseModel):
    unicode: str

    class Config:
        populate_by_name = True
        extra = "allow"

class CommentsApiV1(BaseModel):
    can_view_more_preview_comments: Optional[bool] = None
    caption: Optional[CommentCaptionApiV1] = None
    caption_is_edited: Optional[bool] = None
    comment_count: Optional[int] = None
    comment_cover_pos: Optional[str] = None
    comment_filter_param: Optional[str] = None
    comment_likes_enabled: Optional[bool] = None
    comments: List[CommentItemApiV1] = Field(default_factory=list)
    has_more_comments: Optional[bool] = None
    has_more_headload_comments: Optional[bool] = None
    initiate_at_top: Optional[bool] = None
    insert_new_comment_to_top: Optional[bool] = None
    is_ranked: Optional[bool] = None
    liked_by_media_owner_badge_enabled: Optional[bool] = None
    media_header_display: Optional[str] = None
    next_min_id: Optional[str] = None
    quick_response_emojis: Optional[List[QuickResponseEmojiApiV1]] = Field(default_factory=list)
    scroll_behavior: Optional[int] = None
    sort_order: Optional[str] = None
    threading_enabled: Optional[bool] = None
    should_render_upsell: Optional[bool] = None
    status: str

    class Config:
        populate_by_name = True
        extra = "allow"


class TaggedUserInTagApiV1(BaseModel):
    pk: str
    pk_id: str
    id: str
    full_name: str
    is_private: bool
    strong_id__: str = Field(alias="strong_id__")
    username: str
    is_verified: bool
    profile_pic_id: Optional[str] = None
    profile_pic_url: str

    class Config:
        populate_by_name = True
        extra = "allow"

class UserTagInApiV1(BaseModel):
    position: Optional[List[float]] = None # Expecting [0, 0] as [float, float]
    user: Optional[TaggedUserInTagApiV1] = None

    class Config:
        extra = "allow"

class UserTagsApiV1(BaseModel):
    in_field: Optional[List[UserTagInApiV1]] = Field(default_factory=list, alias="in")

    class Config:
        populate_by_name = True
        extra = "allow"

class SharingFrictionInfoApiV1(BaseModel):
    bloks_app_url: Optional[str] = None
    should_have_sharing_friction: bool
    sharing_friction_payload: Optional[Any] = None # Assuming it can be any type or null

    class Config:
        extra = "allow"

class HdProfilePicUrlInfoApiV1(BaseModel):
    height: int
    url: str
    width: int

    class Config:
        extra = "allow"

class ProfilePicVersionApiV1(BaseModel):
    height: int
    url: str
    width: int

    class Config:
        extra = "allow"

class MediaUserApiV1(BaseModel):
    fbid_v2: Optional[str] = None
    feed_post_reshare_disabled: Optional[bool] = None
    full_name: str
    id: str
    is_private: bool
    is_unpublished: Optional[bool] = None
    pk: str
    pk_id: str
    show_account_transparency_details: Optional[bool] = None
    strong_id__: str = Field(alias="strong_id__")
    third_party_downloads_enabled: Optional[int] = None
    can_see_quiet_post_attribution: Optional[bool] = None
    text_post_app_is_private: Optional[bool] = None
    is_active_on_text_post_app: Optional[bool] = None
    account_type: Optional[int] = None
    account_badges: Optional[List[Any]] = Field(default_factory=list)
    fan_club_info: Optional[dict] = Field(default_factory=dict)
    friendship_status: Optional[FriendshipStatusApiV1] = None # Reusing FriendshipStatusApiV1
    has_anonymous_profile_picture: Optional[bool] = None
    hd_profile_pic_url_info: Optional[HdProfilePicUrlInfoApiV1] = None
    hd_profile_pic_versions: Optional[List[ProfilePicVersionApiV1]] = Field(default_factory=list)
    is_favorite: Optional[bool] = None
    is_verified: bool
    profile_pic_id: Optional[str] = None
    profile_pic_url: str
    transparency_product_enabled: Optional[bool] = None
    username: str
    is_embeds_disabled: Optional[bool] = None
    latest_reel_media: Optional[int] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class FbDownstreamUseXpostMetadataApiV1(BaseModel):
    downstream_use_xpost_deny_reason: Optional[str] = None

    class Config:
        extra = "allow"

class CrosspostMetadataApiV1(BaseModel):
    fb_downstream_use_xpost_metadata: Optional[FbDownstreamUseXpostMetadataApiV1] = None

    class Config:
        extra = "allow"

class GenAIDetectionMethodApiV1(BaseModel):
    detection_method: str

    class Config:
        extra = "allow"

class ReportInfoApiV1(BaseModel):
    has_viewer_submitted_report: Optional[bool] = None

    class Config:
        extra = "allow"

class MediaItemApiV1(BaseModel):
    pk: str
    id: str
    fbid: Optional[str] = None
    device_timestamp: Optional[int] = None # Can be float or int
    caption_is_edited: bool
    strong_id__: str = Field(alias="strong_id__")
    deleted_reason: Optional[int] = None
    has_shared_to_fb: Optional[int] = None # 0 or 1, can be bool
    has_delayed_metadata: Optional[bool] = None
    mezql_token: Optional[str] = None
    share_count_disabled: Optional[bool] = None
    should_request_ads: Optional[bool] = None
    is_reshare_of_text_post_app_media_in_ig: Optional[bool] = None
    integrity_review_decision: Optional[str] = None
    client_cache_key: Optional[str] = None
    filter_type: Optional[int] = None
    is_visual_reply_commenter_notice_enabled: Optional[bool] = None
    comment_threading_enabled: Optional[bool] = None
    like_and_view_counts_disabled: Optional[bool] = None
    has_privately_liked: Optional[bool] = None
    is_unified_video: Optional[bool] = None
    is_post_live_clips_media: Optional[bool] = None
    commerciality_status: Optional[str] = None
    is_quiet_post: Optional[bool] = None
    subtype_name_for_rest__: Optional[str] = Field(None, alias="subtype_name_for_REST__")
    taken_at: int
    has_tagged_users: Optional[bool] = None
    usertags: Optional[UserTagsApiV1] = None
    photo_of_you: Optional[bool] = None
    can_see_insights_as_brand: Optional[bool] = None
    media_type: int
    code: str
    caption: Optional[CommentCaptionApiV1] = None
    sharing_friction_info: Optional[SharingFrictionInfoApiV1] = None
    timeline_pinned_user_ids: Optional[Union[List[str], List[int]]] = None
    play_count: Optional[int] = None
    has_views_fetching: Optional[bool] = None
    ig_play_count: Optional[int] = None
    creator_viewer_insights: Optional[List[Any]] = None
    fb_user_tags: Optional[UserTagsApiV1] = None
    coauthor_producers: Optional[List[Any]] = None
    coauthor_producer_can_see_organic_insights: Optional[bool] = None
    invited_coauthor_producers: Optional[List[Any]] = None
    is_in_profile_grid: Optional[bool] = None
    profile_grid_control_enabled: Optional[bool] = None
    media_cropping_info: Optional[Any] = None # Structure unknown
    user: MediaUserApiV1
    owner: MediaUserApiV1 # Structure is identical to user in the example
    image_versions2: Optional[InstagramImageVersions2] = None
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    is_artist_pick: Optional[bool] = None
    media_notes: Optional[dict] = None
    media_reposter_bottomsheet_enabled: Optional[bool] = None
    enable_media_notes_production: Optional[bool] = None
    product_type: str
    is_paid_partnership: Optional[bool] = None
    music_metadata: Optional[Any] = None # Structure unknown
    social_context: Optional[List[Any]] = None
    organic_tracking_token: Optional[str] = None
    is_third_party_downloads_eligible: Optional[bool] = None
    ig_media_sharing_disabled: Optional[bool] = None
    are_remixes_crosspostable: Optional[bool] = None
    crosspost_metadata: Optional[CrosspostMetadataApiV1] = None
    boost_unavailable_identifier: Optional[Any] = None
    boost_unavailable_reason: Optional[Any] = None
    boost_unavailable_reason_v2: Optional[Any] = None
    subscribe_cta_visible: Optional[bool] = None
    is_cutout_sticker_allowed: Optional[bool] = None
    cutout_sticker_info: Optional[List[Any]] = None
    gen_ai_detection_method: Optional[GenAIDetectionMethodApiV1] = None
    community_notes_info: Optional[dict] = None
    report_info: Optional[ReportInfoApiV1] = None
    fb_aggregated_like_count: Optional[int] = None
    fb_aggregated_comment_count: Optional[int] = None
    has_high_risk_gen_ai_inform_treatment: Optional[bool] = None
    open_carousel_show_follow_button: Optional[bool] = None
    is_tagged_media_shared_to_viewer_profile_grid: Optional[bool] = None
    should_show_author_pog_for_tagged_media_shared_to_profile_grid: Optional[bool] = None
    is_eligible_for_media_note_recs_nux: Optional[bool] = None
    is_social_ufi_disabled: Optional[bool] = None
    is_eligible_for_meta_ai_share: Optional[bool] = None
    meta_ai_suggested_prompts: Optional[List[Any]] = None
    can_reply: Optional[bool] = None
    floating_context_items: Optional[List[Any]] = None
    is_eligible_content_for_post_roll_ad: Optional[bool] = None
    related_ads_pivots_media_info: Optional[str] = None
    is_open_to_public_submission: Optional[bool] = None
    hidden_likes_string_variant: Optional[int] = None
    can_view_more_preview_comments: Optional[bool] = None
    preview_comments: Optional[List[Any]] = None
    comment_count: Optional[int] = None
    hide_view_all_comment_entrypoint: Optional[bool] = None
    inline_composer_display_condition: Optional[str] = None
    is_comments_gif_composer_enabled: Optional[bool] = None
    comment_inform_treatment: Optional[dict] = None
    has_more_comments: Optional[bool] = None
    max_num_visible_preview_comments: Optional[int] = None
    explore_hide_comments: Optional[bool] = None
    has_liked: Optional[bool] = None
    like_count: Optional[int] = None
    facepile_top_likers: Optional[List[Any]] = None
    top_likers: Optional[List[Any]] = None
    video_sticker_locales: Optional[List[Any]] = None
    is_dash_eligible: Optional[int] = None # 0 or 1, can be bool
    video_dash_manifest: Optional[str] = None
    number_of_qualities: Optional[int] = None
    video_versions: Optional[List[VideoVersion]] = None
    video_duration: Optional[float] = None
    has_audio: Optional[bool] = None
    clips_tab_pinned_user_ids: Optional[List[Any]] = None
    clips_metadata: Optional[dict] = None

    class Config:
        populate_by_name = True
        extra = "allow"

class MediaInfoApiV1(BaseModel):
    num_results: int
    more_available: bool
    items: List[MediaItemApiV1]
    auto_load_more_enabled: Optional[bool] = None
    status: str

    class Config:
        extra = "allow"