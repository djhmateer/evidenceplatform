"""Threads structures -> abstract entities mappers.

Mirrors the Instagram mappers (``extractors.instagram.structures_to_entities``)
but stamps ``platform="threads"`` and builds Threads-shaped URL suffixes
(``@{username}`` for profiles, ``@{username}/post/{code}`` for posts).

Scope (per project decision): accounts, posts, media (incl. carousels) and the
profile timeline — everything the sampled capture proves. Likers, follower/
following lists and repost/quote *relations* are intentionally out of scope for
now. Threads replies are themselves posts; they map to a Post and their parent
linkage is preserved inside ``Post.data`` (``text_post_app_info`` /
``reply_to_author``) rather than as a separate Comment.
"""
from datetime import datetime, timezone
from typing import Optional

from extractors.entity_types import Post, Account, Media, ExtractedEntitiesFlattened
from extractors.extraction_helpers import _is_video, _asset_url_from_item, \
    canonical_cdn_url, extend_flattened_entities
from extractors.threads.models import ThreadsPost, ThreadsUser
from extractors.threads.structures_extraction import ThreadsResponse


def threads_account_url_suffix(username: Optional[str]) -> Optional[str]:
    """Threads profile url_suffix: ``@{username}`` (None when absent).

    Mirrors the rationale of the Instagram ``account_url_suffix``: never format a
    missing username into a literal-string sentinel that distinct usernameless
    accounts would collide on — return None so id-only accounts stay distinct.
    """
    return f"@{username}" if username else None


def threads_post_url_suffix(username: Optional[str], code: Optional[str]) -> Optional[str]:
    if not code or not username:
        return None
    return f"@{username}/post/{code}"


def threads_user_to_entities(user: ThreadsUser) -> ExtractedEntitiesFlattened:
    """Emit a single Account carrying the profile bio (from the hovercard /
    profile-info query — the only Threads response with ``biography``)."""
    bio = user.biography or None
    account = Account(
        id_on_platform=user.pk or user.id,
        url_suffix=threads_account_url_suffix(user.username),
        display_name=user.full_name or None,
        bio=(bio[:200] if bio else None),  # account.bio is varchar(200) / Field(max_length=200)
        data=user.model_dump(),
        platform="threads",
    )
    return ExtractedEntitiesFlattened(
        accounts=[account], posts=[], media=[], comments=[], likes=[],
        account_relations=[], tagged_accounts=[]
    )


def threads_post_to_entities(post: ThreadsPost) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []

    user = post.user
    username = user.username if user else None
    user_id = (user.pk or user.id) if user else None

    account = Account(
        id_on_platform=user_id,
        url_suffix=threads_account_url_suffix(username),
        display_name=user.full_name if user else None,
        bio=None,
        data=user.model_dump() if user else None,
        platform="threads",
    )
    extracted_accounts.append(account)

    post_entity = Post(
        id_on_platform=post.pk or post.id,
        url_suffix=threads_post_url_suffix(username, post.code),
        account_id_on_platform=user_id,
        account_url_suffix=account.url_suffix,
        publication_date=datetime.fromtimestamp(post.taken_at, timezone.utc) if post.taken_at else None,
        caption=post.caption.text if post.caption else None,
        data=post.model_dump(),
        platform="threads",
    )
    extracted_posts.append(post_entity)

    # Only emit a top-level Media when the post itself carries an asset AND is not
    # a carousel. Threads has an abundance of text-only posts and replies (no
    # image/video of their own) — emitting a Media for them would create
    # identity-less junk rows, since media identity is url_suffix (the CDN
    # filename), which would be NULL there. Carousels are excluded for the opposite
    # reason: a carousel parent carries its own image_versions2 (the cover/preview
    # image) even when every slide is a video, so _asset_url_from_item(post) would
    # return that cover jpg and emit a spurious still-image row alongside the real
    # per-slide assets, which live in carousel_media below.
    asset_url = _asset_url_from_item(post)
    if asset_url and not post.carousel_media:
        extracted_media.append(Media(
            id_on_platform=post.id,
            url_suffix=canonical_cdn_url(asset_url),
            post_id_on_platform=post_entity.id_on_platform,
            post_url_suffix=post_entity.url_suffix,
            local_url=None,
            media_type="video" if _is_video(post) else "image",
            data=post.model_dump(exclude={'carousel_media'}),
            platform="threads",
        ))

    if post.carousel_media:
        for media_item in post.carousel_media:
            carousel_url = _asset_url_from_item(media_item)
            if not carousel_url:
                continue
            extracted_media.append(Media(
                id_on_platform=media_item.id,
                url_suffix=canonical_cdn_url(carousel_url),
                post_id_on_platform=post_entity.id_on_platform,
                post_url_suffix=post_entity.url_suffix,
                local_url=None,
                media_type="video" if _is_video(media_item) else "image",
                data=media_item.model_dump(),
                platform="threads",
            ))

    # NOTE: positional usertags / textual mentions (text_fragments) are not mapped
    # to TaggedAccount yet — the sampled capture carries no usertag payload to model
    # against. Mentions remain preserved in Post.data. TODO once a tagged capture exists.

    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        comments=[], likes=[], account_relations=[], tagged_accounts=[]
    )


def threads_to_entities(structure: ThreadsResponse) -> ExtractedEntitiesFlattened:
    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], account_relations=[], tagged_accounts=[]
    )
    for user in structure.users:
        try:
            extend_flattened_entities(entities, threads_user_to_entities(user))
        except Exception as e:
            print(f"[threads_to_entities] Error processing user: {e}")
    for post in structure.posts:
        try:
            extend_flattened_entities(entities, threads_post_to_entities(post))
        except Exception as e:
            print(f"[threads_to_entities] Error processing post: {e}")
    return entities
