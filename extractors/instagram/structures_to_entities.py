"""Instagram structures -> abstract entities mappers.

Moved out of the generic ``extractors.structures_to_entities`` orchestration
module so Instagram-specific mapping lives beside the rest of the Instagram
code. The generic orchestration module imports ``graphql_to_entities`` /
``api_v1_to_entities`` / ``page_to_entities`` from here and dispatches to them
by structure type.
"""
import json
from datetime import datetime, timezone
from typing import Any, Optional

from extractors.entity_types import Post, Account, Media, \
    ExtractedEntitiesFlattened, Comment, Like, AccountRelation, TaggedAccount
from extractors.extraction_helpers import _is_video, _asset_url_from_item, \
    canonical_cdn_url, extend_flattened_entities
from extractors.instagram.models import MediaShortcode, HighlightsReelConnection, StoriesFeed, CommentsConnection, ProfileTimeline
from extractors.instagram.models_api_v1 import MediaInfoApiV1, CommentsApiV1, LikersApiV1, FriendshipsApiV1
from extractors.instagram.models_graphql import ProfileTimelineGraphQL, ReelsMediaConnection, FriendsListGraphQL, ClipsUserConnection, ProfileInfoUserGraphQL
from extractors.instagram.structures_extraction_api_v1 import ApiV1Response, ApiV1Context
from extractors.instagram.structures_extraction_graphql import GraphQLResponse
from extractors.instagram.structures_extraction_html import PageResponse


def account_url_suffix(username: Optional[str]) -> Optional[str]:
    """Build an Account/relation url_suffix from a username, or None when absent.

    A missing username must never be formatted into the literal string "None/"
    (which normalize_url_suffix stores as "None"): distinct usernameless accounts
    would otherwise collide on that shared sentinel and merge into one canonical.
    Returning None (NULL) is safe - matching and deduplication never join on a
    null-like value, so id-only accounts stay distinct via id_on_platform, and
    reconciliation consistently prefers a real username over a missing one.
    """
    return f"{username}/" if username else None


def media_id_to_shortcode(media_id: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    shortcode = ''
    while media_id > 0:
        media_id, remainder = divmod(media_id, 64)
        shortcode = alphabet[remainder] + shortcode
    return shortcode


def graphql_to_entities(structure: GraphQLResponse) -> ExtractedEntitiesFlattened:
    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], account_relations=[], tagged_accounts=[]
    )
    if structure.reels_media:
        try:
            extend_flattened_entities(entities, graphql_reels_media_to_entities(structure.reels_media))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing reels_media: {e}")
    if structure.stories_feed:
        try:
            extend_flattened_entities(entities, page_stories_to_entities(structure.stories_feed))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing stories_feed: {e}")
    if structure.profile_timeline:
        try:
            extend_flattened_entities(entities, graphql_profile_timeline_to_entities(structure.profile_timeline))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing profile_timeline: {e}")
    if structure.clips_user_connection:
        try:
            extend_flattened_entities(entities, graphql_clips_to_entities(structure.clips_user_connection))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing clips_user_connection: {e}")
    if structure.comments_connection:
        try:
            extend_flattened_entities(
                entities,
                graphql_comments_to_entities(structure.comments_connection, structure.context)
            )
        except Exception as e:
            print(f"[graphql_to_entities] Error processing comments_connection: {e}")
    if structure.likes:
        try:
            extend_flattened_entities(entities, graphql_likes_to_entities(structure.likes, structure.context))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing likes: {e}")
    if structure.friends_list:
        try:
            extend_flattened_entities(entities,
                                      graphql_suggested_accounts_to_entities(structure.friends_list, structure.context))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing friends_list: {e}")
    if structure.post_shortcode:
        try:
            extend_flattened_entities(entities, page_posts_to_entities(structure.post_shortcode))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing post_shortcode: {e}")
    if structure.profile_info:
        try:
            extend_flattened_entities(entities, graphql_profile_info_to_entities(structure.profile_info))
        except Exception as e:
            print(f"[graphql_to_entities] Error processing profile_info: {e}")
    return entities


def graphql_profile_info_to_entities(user: ProfileInfoUserGraphQL) -> ExtractedEntitiesFlattened:
    """Emit a single Account carrying the profile biography. Sourced from the
    PolarisProfilePageContentQuery GraphQL response (data.user, served from the
    /api/graphql endpoint) — the only place the viewed subject's bio appears. The
    profile-page HTML carries only the logged-in viewer's PolarisViewer bootstrap
    (the operator, not the subject), so the bio is taken from GraphQL alone."""
    bio = user.biography or None
    account = Account(
        id_on_platform=user.id or user.pk,
        url_suffix=account_url_suffix(user.username),
        display_name=user.full_name or None,
        bio=(bio[:200] if bio else None),  # account.bio is varchar(200) / Field(max_length=200)
        data=user.model_dump(),
        platform="instagram",
    )
    return ExtractedEntitiesFlattened(
        accounts=[account], posts=[], media=[], comments=[], likes=[],
        account_relations=[], tagged_accounts=[]
    )


def graphql_reels_media_to_entities(structure: ReelsMediaConnection) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    for edge in structure.edges:
        highlight = edge.node
        highlight_id = highlight.id.split(":")[-1]
        user = highlight.user
        username = user.username
        user_id = user.pk or user.id or user.user_id
        # 24h stories and highlights both arrive via the reels_media endpoint with a
        # near-identical shape. A 24h story is the user's own reel (reel_type
        # "user_reel"; node id == user pk), whereas a highlight is nested in a
        # collection node (reel_type "highlight_reel"; node id "highlight:{coll_pk}").
        is_highlight = highlight.reel_type == "highlight_reel" or highlight_id != user_id
        for item in highlight.items:
            account = Account(
                id_on_platform=highlight.user.id,
                url_suffix=account_url_suffix(highlight.user.username),
                display_name=None,
                bio=None,
                data=highlight.user.model_dump(),
                platform="instagram"
            )
            extracted_accounts.append(account)
            url_suffix = (
                f"s/{highlight_id}/?story_media_id={item.pk or item.id}"
                if is_highlight
                else f"stories/{username}/{item.pk or item.id}/"
            )
            post = Post(
                id_on_platform=item.pk or item.id,
                url_suffix=url_suffix,
                account_id_on_platform=account.id_on_platform,
                account_url_suffix=account.url_suffix,
                publication_date=datetime.fromtimestamp(item.taken_at, timezone.utc),
                caption=item.caption.text if item.caption else None,
                data=item.model_dump(),
                platform="instagram"
            )
            extracted_posts.append(post)
            item_asset_url = _asset_url_from_item(item)
            extracted_media.append(Media(
                id_on_platform=item.id,
                url_suffix=canonical_cdn_url(item_asset_url) if item_asset_url else None,
                post_id_on_platform=post.id_on_platform,
                post_url_suffix=post.url_suffix,
                local_url=None,
                media_type="video" if _is_video(item) else "image",
                data=item.model_dump(exclude={'carousel_media'}),
                platform="instagram"
            ))
            if item.carousel_media:
                for media_item in item.carousel_media:
                    carousel_asset_url = _asset_url_from_item(media_item)
                    media_url = canonical_cdn_url(carousel_asset_url) if carousel_asset_url else None
                    extracted_media.append(Media(
                        id_on_platform=media_item.id,
                        url_suffix=media_url,
                        post_id_on_platform=post.id_on_platform,
                        post_url_suffix=post.url_suffix,
                        local_url=None,
                        media_type="video" if _is_video(media_item) else "image",
                        data=media_item.model_dump(),
                        platform="instagram"
                    ))
                    if media_item.usertags and media_item.usertags.in_field:
                        for tag in media_item.usertags.in_field:
                            extracted_tagged_accounts.append(TaggedAccount(
                                tagged_account_id_on_platform=tag.user.id,
                                tagged_account_url_suffix=account_url_suffix(tag.user.username),
                                context_post_url_suffix=post.url_suffix,
                                context_media_url_suffix=media_url,
                                context_post_id_on_platform=post.id_on_platform,
                                context_media_id_on_platform=media_item.id,
                                data=None,
                                platform="instagram"
                            ))
                            extracted_accounts.append(Account(
                                id_on_platform=tag.user.id,
                                url_suffix=account_url_suffix(tag.user.username),
                                display_name=tag.user.full_name,
                                bio=None,
                                data=tag.user.model_dump(),
                                platform="instagram"
                            ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], account_relations=[]
    )


def graphql_profile_timeline_to_entities(structure: ProfileTimelineGraphQL) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []

    for edge in structure.edges:
        item = edge.node
        if not item.user or not (item.pk or item.id):
            continue
        account = Account(
            id_on_platform=item.user.id,
            url_suffix=account_url_suffix(item.user.username),
            display_name=None,
            bio=None,
            data=item.user.model_dump(),
            platform="instagram"
        )
        extracted_accounts.append(account)
        post_pk = item.pk or item.id
        post_code = item.code or (media_id_to_shortcode(int(post_pk)) if post_pk else None)
        post = Post(
            id_on_platform=item.pk or item.id,
            url_suffix=f"p/{post_code}" if post_code else None,
            account_id_on_platform=item.user.id,
            account_url_suffix=account.url_suffix,
            publication_date=datetime.fromtimestamp(item.taken_at, timezone.utc) if item.taken_at else None,
            caption=item.caption.text if item.caption else None,
            data=item.model_dump(),
            platform="instagram"
        )
        extracted_posts.append(post)
        if item.usertags and item.usertags.in_field:
            for tag in item.usertags.in_field:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id_on_platform=tag.user.id,
                    tagged_account_url_suffix=account_url_suffix(tag.user.username),
                    context_post_url_suffix=post.url_suffix,
                    context_media_url_suffix=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    data=None,
                    platform="instagram"
                ))
                extracted_accounts.append(Account(
                    id_on_platform=tag.user.id,
                    url_suffix=account_url_suffix(tag.user.username),
                    display_name=tag.user.full_name,
                    bio=None,
                    data=tag.user.model_dump(),
                    platform="instagram"
                ))
        asset_url = _asset_url_from_item(item)
        extracted_media.append(Media(
            id_on_platform=item.id,
            url_suffix=canonical_cdn_url(asset_url) if asset_url else None,
            post_id_on_platform=post.id_on_platform,
            post_url_suffix=post.url_suffix,
            local_url=None,
            media_type="video" if _is_video(item) else "image",
            data=item.model_dump(exclude={'carousel_media'}),
            platform="instagram"
        ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                media_url = _asset_url_from_item(media_item)
                media_url_suffix = canonical_cdn_url(media_url) if media_url else None
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url_suffix=media_url_suffix,
                    post_id_on_platform=post.id_on_platform,
                    post_url_suffix=post.url_suffix,
                    local_url=None,
                    media_type="video" if _is_video(media_item) else "image",
                    data=media_item.model_dump(),
                    platform="instagram"
                ))
                if media_item.usertags and media_item.usertags.in_field:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id_on_platform=tag.user.id,
                            tagged_account_url_suffix=account_url_suffix(tag.user.username),
                            context_post_url_suffix=post.url_suffix,
                            context_media_url_suffix=media_url_suffix,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            data=None,
                            platform="instagram"
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url_suffix=account_url_suffix(tag.user.username),
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump(),
                            platform="instagram"
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], account_relations=[]
    )


def graphql_comments_to_entities(structure: CommentsConnection, context: Any) -> ExtractedEntitiesFlattened:
    variables_raw = context.get('variables', '{}') if isinstance(context, dict) else '{}'
    variables = json.loads(variables_raw) if isinstance(variables_raw, str) else variables_raw
    post_pk: Optional[str] = variables.get('media_id', None)
    post_url = f"p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    extracted_comments: list[Comment] = []
    extracted_accounts: list[Account] = []
    for e in structure.edges:
        c = e.node
        if c.user:
            extracted_accounts.append(Account(
                id_on_platform=c.user.id,
                url_suffix=account_url_suffix(c.user.username),
                display_name=None,
                bio=None,
                data=c.user.model_dump(),
                platform="instagram"
            ))
        comment = Comment(
            id_on_platform=c.pk,
            url_suffix=f"{post_url}c/{c.pk}/" if post_url else None,
            post_id_on_platform=post_pk,
            post_url_suffix=post_url,
            account_id_on_platform=c.user.pk if c.user else None,
            account_url_suffix=account_url_suffix(c.user.username) if c.user else None,
            text=c.text,
            parent_comment_id_on_platform=c.parent_comment_id,
            publication_date=datetime.fromtimestamp(c.created_at) if c.created_at else None,
            data=c.model_dump(),
            platform="instagram"
        )
        extracted_comments.append(comment)
    return ExtractedEntitiesFlattened(
        comments=extracted_comments,
        accounts=extracted_accounts,
        likes=[], account_relations=[], tagged_accounts=[], media=[], posts=[]
    )


def graphql_likes_to_entities(structure: LikersApiV1, context: Any) -> ExtractedEntitiesFlattened:
    variables_raw = context.get('variables', '{}') if isinstance(context, dict) else '{}'
    variables = json.loads(variables_raw) if isinstance(variables_raw, str) else variables_raw
    post_pk: Optional[str] = variables.get('media_id', None)
    post_url = f"p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    extracted_likes: list[Like] = []
    extracted_accounts: list[Account] = []
    for u in structure.users:
        like = Like(
            id_on_platform=None,
            post_id_on_platform=post_pk,
            post_url_suffix=post_url,
            account_id_on_platform=u.pk,
            account_url_suffix=account_url_suffix(u.username),
            data=u.model_dump(),
            platform="instagram"
        )
        extracted_likes.append(like)
        extracted_accounts.append(Account(
            id_on_platform=u.pk,
            url_suffix=like.account_url_suffix,
            display_name=u.full_name,
            bio=None,
            data=u.model_dump(),
            platform="instagram"
        ))
    return ExtractedEntitiesFlattened(
        likes=extracted_likes,
        accounts=extracted_accounts,
        comments=[], account_relations=[], tagged_accounts=[], media=[], posts=[]
    )


def graphql_suggested_accounts_to_entities(structure: FriendsListGraphQL, context: Any) -> ExtractedEntitiesFlattened:
    variables = context.get('variables', '{}') if isinstance(context, dict) else '{}'
    variables = json.loads(variables)
    target_account_id: Optional[str] = variables.get('target_id', None)
    extracted_account_relations: list[AccountRelation] = []
    extracted_accounts: list[Account] = []
    for u in structure.users:
        account = Account(
            url_suffix=account_url_suffix(u.username),
            display_name=u.full_name,
            bio=None,
            id_on_platform=u.id,
            data=u.model_dump(),
            platform="instagram"
        )
        extracted_accounts.append(account)
        relation = AccountRelation(
            follower_account_id_on_platform=target_account_id,
            followed_account_id_on_platform=u.id,
            followed_account_url_suffix=account_url_suffix(u.username),
            relation_type='suggested',
            data=None,
            platform="instagram"
        )
        extracted_account_relations.append(relation)
    return ExtractedEntitiesFlattened(
        account_relations=extracted_account_relations,
        accounts=extracted_accounts,
        comments=[], likes=[], tagged_accounts=[], media=[], posts=[]
    )


def graphql_clips_to_entities(structure: ClipsUserConnection) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []

    for edge in structure.edges:
        item = edge.node.media
        account = Account(
            id_on_platform=item.user.id,
            url_suffix=account_url_suffix(item.user.username),
            display_name=None,
            bio=None,
            data=item.user.model_dump(),
            platform="instagram"
        )
        extracted_accounts.append(account)
        post = Post(
            id_on_platform=item.pk or item.id,
            url_suffix=f"p/{item.code}" if item.code else (
                f"p/{media_id_to_shortcode(int(item.pk))}" if item.pk else None
            ),
            account_id_on_platform=account.id_on_platform,
            account_url_suffix=account.url_suffix,
            publication_date=None,
            caption=None,
            data=item.model_dump(),
            platform="instagram"
        )
        extracted_posts.append(post)
        asset_url = _asset_url_from_item(item)
        extracted_media.append(Media(
            id_on_platform=item.id,
            url_suffix=canonical_cdn_url(asset_url) if asset_url else None,
            post_id_on_platform=post.id_on_platform,
            post_url_suffix=post.url_suffix,
            local_url=None,
            media_type="video" if _is_video(item) else "image",
            data=item.model_dump(exclude={'carousel_media'}),
            platform="instagram"
        ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                carousel_url = _asset_url_from_item(media_item)
                carousel_url_suffix = canonical_cdn_url(carousel_url) if carousel_url else None
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url_suffix=carousel_url_suffix,
                    post_id_on_platform=post.id_on_platform,
                    post_url_suffix=post.url_suffix,
                    local_url=None,
                    media_type="video" if _is_video(media_item) else "image",
                    data=media_item.model_dump(),
                    platform="instagram"
                ))
                if media_item.usertags and media_item.usertags.in_field:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id_on_platform=tag.user.id,
                            tagged_account_url_suffix=account_url_suffix(tag.user.username),
                            context_post_url_suffix=post.url_suffix,
                            context_media_url_suffix=carousel_url_suffix,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            data=None,
                            platform="instagram"
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url_suffix=account_url_suffix(tag.user.username),
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump(),
                            platform="instagram"
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], account_relations=[]
    )


def api_v1_to_entities(structure: ApiV1Response) -> ExtractedEntitiesFlattened:
    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], account_relations=[], tagged_accounts=[]
    )
    if structure.media_info:
        extend_flattened_entities(entities, api_v1_media_info_to_entities(structure.media_info))
    context = structure.context or ApiV1Context()
    if structure.comments:
        extend_flattened_entities(entities, api_v1_comments_to_entities(structure.comments, context))
    if structure.likers:
        extend_flattened_entities(entities, api_v1_likes_to_entities(structure.likers, context))
    if structure.friendships:
        extend_flattened_entities(entities, api_v1_friendships_to_entities(structure.friendships, context))
    return entities


def api_v1_media_info_to_entities(media_info: MediaInfoApiV1) -> ExtractedEntitiesFlattened:
    extracted_posts: list[Post] = []
    extracted_accounts: list[Account] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    extracted_media: list[Media] = []
    for item in media_info.items:
        _username = item.user.username or item.owner.username
        _user_id = item.user.id or item.owner.id
        account = Account(
            id_on_platform=_user_id,
            url_suffix=account_url_suffix(_username),
            display_name=item.user.full_name or item.owner.full_name,
            bio=None,
            data=item.user.model_dump(),
            platform="instagram"
        )
        extracted_accounts.append(account)
        post = Post(
            id_on_platform=item.pk or item.id,
            url_suffix="p/" + (item.code or media_id_to_shortcode(int(item.pk))),
            account_id_on_platform=account.id_on_platform,
            account_url_suffix=account.url_suffix,
            publication_date=datetime.fromtimestamp(item.taken_at, timezone.utc),
            caption=item.caption.text if item.caption else None,
            data=item.model_dump(),
            platform="instagram"
        )
        extracted_posts.append(post)
        media_asset_url = _asset_url_from_item(item)
        extracted_media.append(Media(
            id_on_platform=item.id,
            url_suffix=canonical_cdn_url(media_asset_url) if media_asset_url else None,
            post_id_on_platform=post.id_on_platform,
            post_url_suffix=post.url_suffix,
            local_url=None,
            media_type="video" if _is_video(item) else "image",
            data=item.model_dump(),
            platform="instagram"
        ))
        if item.usertags and item.usertags.in_field:
            for tag in item.usertags.in_field:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id_on_platform=tag.user.id,
                    tagged_account_url_suffix=account_url_suffix(tag.user.username),
                    context_post_url_suffix=post.url_suffix,
                    context_media_url_suffix=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    tag_x_position=tag.position[0] if tag.position and len(tag.position) > 0 else None,
                    tag_y_position=tag.position[1] if tag.position and len(tag.position) > 1 else None,
                    data=None,
                    platform="instagram"
                ))
                extracted_accounts.append(Account(
                    id_on_platform=tag.user.id,
                    url_suffix=account_url_suffix(tag.user.username),
                    display_name=tag.user.full_name,
                    bio=None,
                    data=tag.user.model_dump(),
                    platform="instagram"
                ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                carousel_asset_url = _asset_url_from_item(media_item)
                carousel_url_suffix = canonical_cdn_url(carousel_asset_url) if carousel_asset_url else None
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url_suffix=carousel_url_suffix,
                    post_id_on_platform=post.id_on_platform,
                    post_url_suffix=post.url_suffix,
                    local_url=None,
                    media_type="video" if _is_video(media_item) else "image",
                    data=media_item.model_dump(),
                    platform="instagram"
                ))
                if media_item.usertags and media_item.usertags.in_field:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id_on_platform=tag.user.id,
                            tagged_account_url_suffix=account_url_suffix(tag.user.username),
                            context_post_url_suffix=post.url_suffix,
                            context_media_url_suffix=carousel_url_suffix,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            tag_x_position=tag.position[0] if tag.position and len(tag.position) > 0 else None,
                            tag_y_position=tag.position[1] if tag.position and len(tag.position) > 1 else None,
                            data=None,
                            platform="instagram"
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url_suffix=account_url_suffix(tag.user.username),
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump(),
                            platform="instagram"
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], account_relations=[]
    )


def api_v1_comments_to_entities(comments_insta: CommentsApiV1, context: ApiV1Context) -> ExtractedEntitiesFlattened:
    post_pk: Optional[str] = context.media_id
    comments: list[Comment] = []
    accounts: list[Account] = []

    post_url = f"p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    for c in comments_insta.comments:
        if c.user:
            accounts.append(Account(
                id_on_platform=c.user.id,
                url_suffix=account_url_suffix(c.user.username),
                display_name=None,
                bio=None,
                data=c.user.model_dump(),
                platform="instagram"
            ))
        comment = Comment(
            id_on_platform=c.pk,
            url_suffix=f"{post_url}c/{c.pk}/" if post_url else None,
            post_id_on_platform=post_pk,
            post_url_suffix=post_url,
            account_id_on_platform=c.user.id if c.user else None,
            account_url_suffix=account_url_suffix(c.user.username) if c.user else None,
            text=c.text,
            publication_date=datetime.fromtimestamp(c.created_at) if c.created_at else None,
            data=c.model_dump(),
            platform="instagram"
        )
        comments.append(comment)
    return ExtractedEntitiesFlattened(
        comments=comments,
        accounts=accounts,
        likes=[], account_relations=[], tagged_accounts=[], media=[], posts=[]
    )


def api_v1_likes_to_entities(structure: LikersApiV1, context: ApiV1Context) -> ExtractedEntitiesFlattened:
    post_pk: Optional[str] = context.media_id
    post_url = f"p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    extracted_likes: list[Like] = []
    accounts: list[Account] = []
    for u in structure.users:
        accounts.append(Account(
            id_on_platform=u.pk,
            url_suffix=account_url_suffix(u.username),
            display_name=u.full_name,
            bio=None,
            data=u.model_dump(),
            platform="instagram"
        ))
        extracted_likes.append(Like(
            id_on_platform=None,
            post_id_on_platform=post_pk,
            post_url_suffix=post_url,
            account_id_on_platform=u.pk,
            account_url_suffix=account_url_suffix(u.username),
            data=u.model_dump(),
            platform="instagram"
        ))
    return ExtractedEntitiesFlattened(
        likes=extracted_likes,
        accounts=accounts,
        comments=[], account_relations=[], tagged_accounts=[], media=[], posts=[]
    )


def api_v1_friendships_to_entities(structure: FriendshipsApiV1, context: ApiV1Context) -> ExtractedEntitiesFlattened:
    url: Optional[str] = context.url
    follow_direction = ("followers" if url and "followers" in url
                        else ("following" if url and "following" in url else None))
    target_account_id = url.split("friendships/")[1].split("/")[0] if url else None
    extracted_account_relations: list[AccountRelation] = []
    accounts: list[Account] = []
    for u in structure.users:
        account = Account(
            url_suffix=account_url_suffix(u.username),
            display_name=u.full_name,
            bio=None,
            id_on_platform=u.id,
            data=u.model_dump(),
            platform="instagram"
        )
        accounts.append(account)
        if follow_direction == "followers":
            relation = AccountRelation(
                follower_account_id_on_platform=u.id,
                follower_account_url_suffix=account_url_suffix(u.username),
                followed_account_id_on_platform=target_account_id,
                relation_type='follower',
                data=None,
                platform="instagram"
            )
        else:
            relation = AccountRelation(
                follower_account_id_on_platform=target_account_id,
                followed_account_id_on_platform=u.id,
                followed_account_url_suffix=account_url_suffix(u.username),
                relation_type='follower',
                data=None,
                platform="instagram"
            )
        extracted_account_relations.append(relation)
    return ExtractedEntitiesFlattened(
        account_relations=extracted_account_relations,
        accounts=accounts,
        comments=[], likes=[], tagged_accounts=[], media=[], posts=[]
    )


def page_to_entities(structure: PageResponse) -> ExtractedEntitiesFlattened:
    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], account_relations=[], tagged_accounts=[]
    )
    if structure.posts:
        extend_flattened_entities(entities, page_posts_to_entities(structure.posts))
    if structure.highlight_reels:
        extend_flattened_entities(entities, page_highlight_reels_to_entities(structure.highlight_reels))
    if structure.stories:
        extend_flattened_entities(entities, graphql_reels_media_to_entities(structure.stories))
    if structure.stories_direct:
        extend_flattened_entities(entities, page_stories_to_entities(structure.stories_direct))
    if structure.comments:
        extend_flattened_entities(entities, page_comments_to_entities(structure.comments, structure.posts))
    if structure.timelines:
        extend_flattened_entities(entities, page_timelines_to_entities(structure.timelines))
    return entities


def page_posts_to_entities(structure: MediaShortcode) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    for item in structure.items:
        _username = (item.user.username if item.user else None) or (item.owner.username if item.owner else None)
        _fullname = (item.user.full_name if item.user else None) or (item.owner.full_name if item.owner else None)
        _user_id = (item.user.id if item.user else None) or (item.owner.id if item.owner else None)
        account: Account = Account(
            id_on_platform=_user_id,
            url_suffix=account_url_suffix(_username),
            display_name=_fullname,
            bio=None,
            data=item.user.model_dump() if item.user else None,
            platform="instagram"
        )
        extracted_accounts.append(account)
        post_pk = item.pk or item.id
        post_code = item.code or (media_id_to_shortcode(int(post_pk)) if post_pk else None)
        post = Post(
            id_on_platform=item.pk or item.id,
            url_suffix=f"p/{post_code}" if post_code else None,
            account_id_on_platform=account.id_on_platform,
            account_url_suffix=account.url_suffix,
            publication_date=datetime.fromtimestamp(float(item.taken_at), timezone.utc) if item.taken_at else None,
            caption=item.caption.text if item.caption else None,
            data=item.model_dump(),
            platform="instagram"
        )
        extracted_posts.append(post)
        asset_url = _asset_url_from_item(item)
        first_media = Media(
            id_on_platform=item.id,
            url_suffix=canonical_cdn_url(asset_url) if asset_url else None,
            post_id_on_platform=post.id_on_platform,
            post_url_suffix=post.url_suffix,
            local_url=None,
            media_type="video" if _is_video(item) else "image",
            data=item.model_dump(exclude={'carousel_media'}),
            platform="instagram"
        )
        extracted_media.append(first_media)
        if item.usertags and item.usertags.in_field:
            for tag in item.usertags.in_field:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id_on_platform=tag.user.id,
                    tagged_account_url_suffix=account_url_suffix(tag.user.username),
                    context_post_url_suffix=post.url_suffix,
                    context_media_url_suffix=first_media.url_suffix,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=first_media.id_on_platform,
                    tag_x_position=tag.position[0] if tag.position else None,
                    tag_y_position=tag.position[1] if tag.position and len(tag.position) > 1 else None,
                    data=None,
                    platform="instagram"
                ))
                extracted_accounts.append(Account(
                    id_on_platform=tag.user.id,
                    url_suffix=account_url_suffix(tag.user.username),
                    display_name=tag.user.full_name,
                    bio=None,
                    data=tag.user.model_dump(),
                    platform="instagram"
                ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                url = _asset_url_from_item(media_item)
                url_suffix = canonical_cdn_url(url) if url else None
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url_suffix=url_suffix,
                    post_id_on_platform=post.id_on_platform,
                    post_url_suffix=post.url_suffix,
                    local_url=None,
                    media_type="video" if _is_video(media_item) else "image",
                    data=media_item.model_dump(),
                    platform="instagram"
                ))
                if media_item.usertags and media_item.usertags.in_field:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id_on_platform=tag.user.id,
                            tagged_account_url_suffix=account_url_suffix(tag.user.username),
                            context_post_url_suffix=post.url_suffix,
                            context_media_url_suffix=url_suffix,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            tag_x_position=tag.position[0] if tag.position else None,
                            tag_y_position=tag.position[1] if tag.position and len(tag.position) > 1 else None,
                            data=None,
                            platform="instagram"
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url_suffix=account_url_suffix(tag.user.username),
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump(),
                            platform="instagram"
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        likes=[], comments=[], account_relations=[]
    )


def page_timelines_to_entities(structure: ProfileTimeline) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []

    for item in structure.items:
        if not item.user or not (item.pk or item.id):
            continue
        account = Account(
            id_on_platform=item.user.id,
            url_suffix=account_url_suffix(item.user.username),
            display_name=None,
            bio=None,
            data=item.user.model_dump(),
            platform="instagram"
        )
        extracted_accounts.append(account)
        post_pk = item.pk or item.id
        post_code = item.code or (media_id_to_shortcode(int(post_pk)) if post_pk else None)
        item_data = item.model_dump(exclude={'carousel_media'})
        post = Post(
            id_on_platform=post_pk,
            url_suffix=f"p/{post_code}" if post_code else None,
            account_id_on_platform=item.user.id,
            account_url_suffix=account.url_suffix,
            publication_date=None,
            caption=None,
            data=item_data,
            platform="instagram"
        )
        extracted_posts.append(post)
        asset_url = _asset_url_from_item(item)
        extracted_media.append(Media(
            id_on_platform=item.id,
            url_suffix=canonical_cdn_url(asset_url) if asset_url else None,
            post_id_on_platform=post.id_on_platform,
            post_url_suffix=post.url_suffix,
            local_url=None,
            media_type="video" if _is_video(item) else "image",
            data=item_data,
            platform="instagram"
        ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                carousel_url = _asset_url_from_item(media_item)
                carousel_url_suffix = canonical_cdn_url(carousel_url) if carousel_url else None
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url_suffix=carousel_url_suffix,
                    post_id_on_platform=post.id_on_platform,
                    post_url_suffix=post.url_suffix,
                    local_url=None,
                    media_type="video" if _is_video(media_item) else "image",
                    data=media_item.model_dump(),
                    platform="instagram"
                ))
                if media_item.usertags and media_item.usertags.in_field:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id_on_platform=tag.user.id,
                            tagged_account_url_suffix=account_url_suffix(tag.user.username),
                            context_post_url_suffix=post.url_suffix,
                            context_media_url_suffix=carousel_url_suffix,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            tag_x_position=tag.position[0] if tag.position and len(tag.position) > 0 else None,
                            tag_y_position=tag.position[1] if tag.position and len(tag.position) > 1 else None,
                            data=None,
                            platform="instagram"
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url_suffix=account_url_suffix(tag.user.username),
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump(),
                            platform="instagram"
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], account_relations=[]
    )


def page_highlight_reels_to_entities(structure: HighlightsReelConnection) -> ExtractedEntitiesFlattened:
    extracted_posts: list[Post] = []
    extracted_accounts: list[Account] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    if not structure.edges:
        return ExtractedEntitiesFlattened(
            accounts=[], posts=[], media=[], comments=[], likes=[], account_relations=[],
            tagged_accounts=[]
        )
    for edge in structure.edges:
        highlight = edge.node
        highlight_id = highlight.id.split(":")[-1]
        account = Account(
            id_on_platform=highlight.user.id,
            url_suffix=account_url_suffix(highlight.user.username),
            display_name=None,
            bio=None,
            data=highlight.user.model_dump(),
            platform="instagram"
        )
        extracted_accounts.append(account)
        for reel in highlight.items:
            post = Post(
                id_on_platform=reel.pk or reel.id,
                url_suffix=f"s/{highlight_id}/?story_media_id={reel.pk or reel.id}",
                account_id_on_platform=highlight.user.id,
                account_url_suffix=account.url_suffix,
                publication_date=datetime.fromtimestamp(reel.taken_at, timezone.utc),
                caption=reel.caption.text if reel.caption else None,
                data=reel.model_dump(),
                platform="instagram"
            )
            extracted_posts.append(post)
            reel_asset_url = _asset_url_from_item(reel)
            extracted_media.append(Media(
                id_on_platform=reel.id,
                url_suffix=canonical_cdn_url(reel_asset_url) if reel_asset_url else None,
                post_id_on_platform=post.id_on_platform,
                post_url_suffix=post.url_suffix,
                local_url=None,
                media_type="video" if _is_video(reel) else "image",
                data=reel.model_dump(),
                platform="instagram"
            ))
            if reel.story_bloks_stickers:
                for sticker in reel.story_bloks_stickers:
                    extracted_tagged_accounts.append(TaggedAccount(
                        tagged_account_id_on_platform=None,
                        tagged_account_url_suffix=account_url_suffix(sticker.bloks_sticker.sticker_data.ig_mention.username),
                        context_post_url_suffix=post.url_suffix,
                        context_media_url_suffix=None,
                        context_post_id_on_platform=post.id_on_platform,
                        context_media_id_on_platform=None,
                        data=None,
                        platform="instagram"
                    ))
                    extracted_accounts.append(Account(
                        id_on_platform=None,
                        url_suffix=account_url_suffix(sticker.bloks_sticker.sticker_data.ig_mention.username),
                        display_name=sticker.bloks_sticker.sticker_data.ig_mention.full_name,
                        bio=None,
                        data=sticker.bloks_sticker.sticker_data.ig_mention.model_dump(),
                        platform="instagram"
                    ))
            if reel.carousel_media:
                for media_item in reel.carousel_media:
                    carousel_asset_url = _asset_url_from_item(media_item)
                    media_url_suffix = canonical_cdn_url(carousel_asset_url) if carousel_asset_url else None
                    extracted_media.append(Media(
                        id_on_platform=media_item.id,
                        url_suffix=media_url_suffix,
                        post_id_on_platform=post.id_on_platform,
                        post_url_suffix=post.url_suffix,
                        local_url=None,
                        media_type="video" if _is_video(media_item) else "image",
                        data=media_item.model_dump(),
                        platform="instagram"
                    ))
                    if media_item.usertags and media_item.usertags.in_field:
                        for tag in media_item.usertags.in_field:
                            extracted_tagged_accounts.append(TaggedAccount(
                                tagged_account_id_on_platform=tag.user.id,
                                tagged_account_url_suffix=account_url_suffix(tag.user.username),
                                context_post_url_suffix=post.url_suffix,
                                context_media_url_suffix=media_url_suffix,
                                context_post_id_on_platform=post.id_on_platform,
                                context_media_id_on_platform=media_item.id,
                                tag_x_position=tag.position[0] if tag.position else None,
                                tag_y_position=tag.position[1] if tag.position and len(tag.position) > 1 else None,
                                data=None,
                                platform="instagram"
                            ))
                            extracted_accounts.append(Account(
                                id_on_platform=tag.user.id,
                                url_suffix=account_url_suffix(tag.user.username),
                                display_name=tag.user.full_name,
                                bio=None,
                                data=tag.user.model_dump(),
                                platform="instagram"
                            ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], account_relations=[]
    )


def page_stories_to_entities(structure: StoriesFeed) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    reels_media = structure.reels_media[0] if structure.reels_media and len(structure.reels_media) > 0 else None
    if not reels_media:
        return ExtractedEntitiesFlattened(
            accounts=[], posts=[], media=[], comments=[], likes=[], account_relations=[],
            tagged_accounts=[]
        )
    account = Account(
        id_on_platform=reels_media.user.id,
        url_suffix=account_url_suffix(reels_media.user.username),
        display_name=None,
        bio=None,
        data=reels_media.user.model_dump(),
        platform="instagram"
    )
    extracted_accounts.append(account)
    for item in reels_media.items:
        post = Post(
            id_on_platform=item.pk or item.id,
            url_suffix=f"stories/{reels_media.user.username}/{item.pk or item.id}/",
            account_id_on_platform=reels_media.user.id,
            account_url_suffix=account.url_suffix,
            publication_date=datetime.fromtimestamp(float(item.taken_at), timezone.utc) if item.taken_at else None,
            caption=item.caption.text if item.caption else None,
            data=item.model_dump(),
            platform="instagram"
        )
        extracted_posts.append(post)
        if item.story_bloks_stickers:
            for sticker in item.story_bloks_stickers:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id_on_platform=None,
                    tagged_account_url_suffix=account_url_suffix(sticker.bloks_sticker.sticker_data.ig_mention.username),
                    context_post_url_suffix=post.url_suffix,
                    context_media_url_suffix=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    data=None,
                    platform="instagram"
                ))
                extracted_accounts.append(Account(
                    id_on_platform=None,
                    url_suffix=account_url_suffix(sticker.bloks_sticker.sticker_data.ig_mention.username),
                    display_name=sticker.bloks_sticker.sticker_data.ig_mention.full_name,
                    bio=None,
                    data=sticker.bloks_sticker.sticker_data.ig_mention.model_dump(),
                    platform="instagram"
                ))
        story_asset_url = _asset_url_from_item(item)
        extracted_media.append(Media(
            id_on_platform=item.id,
            url_suffix=canonical_cdn_url(story_asset_url) if story_asset_url else None,
            post_id_on_platform=post.id_on_platform,
            post_url_suffix=post.url_suffix,
            local_url=None,
            media_type="video" if _is_video(item) else "image",
            data=item.model_dump(),
            platform="instagram"
        ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                carousel_asset_url = _asset_url_from_item(media_item)
                media_url_suffix = canonical_cdn_url(carousel_asset_url) if carousel_asset_url else None
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url_suffix=media_url_suffix,
                    post_id_on_platform=post.id_on_platform,
                    post_url_suffix=post.url_suffix,
                    local_url=None,
                    media_type="video" if _is_video(media_item) else "image",
                    data=media_item.model_dump(),
                    platform="instagram"
                ))
                if media_item.usertags and media_item.usertags.in_field:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id_on_platform=tag.user.id,
                            tagged_account_url_suffix=account_url_suffix(tag.user.username),
                            context_post_url_suffix=post.url_suffix,
                            context_media_url_suffix=media_url_suffix,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            tag_x_position=tag.position[0] if tag.position else None,
                            tag_y_position=tag.position[1] if tag.position and len(tag.position) > 1 else None,
                            data=None,
                            platform="instagram"
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url_suffix=account_url_suffix(tag.user.username),
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump(),
                            platform="instagram"
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], account_relations=[]
    )


def page_comments_to_entities(comments_structure: CommentsConnection,
                              post_structure: Optional[MediaShortcode]) -> ExtractedEntitiesFlattened:
    extracted_comments: list[Comment] = []
    extracted_accounts: list[Account] = []
    try:
        post_item = post_structure.items[0] if post_structure and post_structure.items else None
        post_pk: Optional[str] = post_item.pk if post_item else None
        post_code: Optional[str] = post_item.code if post_item else None
        post_url = f"p/{post_code or media_id_to_shortcode(int(post_pk))}/" if post_pk else None
        for e in comments_structure.edges:
            c = e.node
            account = Account(
                id_on_platform=c.user.pk if c.user else None,
                url_suffix=account_url_suffix(c.user.username) if c.user else None,
                data=c.user.model_dump() if c.user else None,
                display_name=None, bio=None,
                platform="instagram"
            )
            extracted_accounts.append(account)
            comment = Comment(
                id_on_platform=c.pk,
                url_suffix=f"{post_url}c/{c.pk}/" if post_url else None,
                post_id_on_platform=post_pk,
                post_url_suffix=post_url,
                account_id_on_platform=account.id_on_platform,
                account_url_suffix=account.url_suffix,
                text=c.text,
                parent_comment_id_on_platform=c.parent_comment_id,
                publication_date=datetime.fromtimestamp(c.created_at) if c.created_at else None,
                data=c.model_dump(),
                platform="instagram"
            )
            extracted_comments.append(comment)
    except Exception as ex:
        print(f"Error extracting comments from page: {ex}")
    return ExtractedEntitiesFlattened(
        comments=extracted_comments,
        accounts=extracted_accounts,
        likes=[], account_relations=[], tagged_accounts=[], media=[], posts=[]
    )
