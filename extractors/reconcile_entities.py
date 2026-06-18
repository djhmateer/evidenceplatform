import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, TypeVar, Any

from extractors.entity_types import Account, Post, Media, Comment, Like, TaggedAccount, AccountRelation
from root_anchor import ROOT_DIR, ROOT_ARCHIVES

T = TypeVar('T')


def is_empty(value: Optional[Any]) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return len(value) == 0
    if isinstance(value, str):
        return value.strip() == ""
    return False


def reconcile_primitives(a: Optional[Any], b: Optional[Any]) -> Optional[Any]:
    """Return the first non-empty value; prefer a over b."""
    is_empty_a = is_empty(a)
    is_empty_b = is_empty(b)
    if is_empty_a and is_empty_b:
        return None
    if is_empty_a:
        return b
    if is_empty_b:
        return a
    return a


def reconcile_lists(a: Optional[list], b: Optional[list]) -> Optional[list]:
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    seen = set()
    result = []
    for item in a + b:
        try:
            key = json.dumps(item, default=str, sort_keys=True)
        except Exception:
            key = None  # Unserializable, treat as unique
        if key is not None:
            if key not in seen:
                seen.add(key)
                result.append(item)
        else:
            result.append(item)
    return result


def reconcile_dicts(a: Optional[dict], b: Optional[dict]) -> Optional[dict]:
    if a is None and b is None:
        return {}
    if a is None:
        return b
    if b is None:
        return a
    result = a.copy()
    for key, value in b.items():
        if key in result:
            if isinstance(result[key], list) and isinstance(value, list):
                result[key] = reconcile_lists(result[key], value)
            elif isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = reconcile_dicts(result[key], value)
            else:
                result[key] = reconcile_primitives(result[key], value)
        else:
            result[key] = value
    return result


def reconcile_accounts(new_account: Account, existing_account: Optional[Account]) -> Account:
    if existing_account is None:
        return new_account
    existing_account.id_on_platform = reconcile_primitives(existing_account.id_on_platform, new_account.id_on_platform)
    existing_account.url_suffix = reconcile_primitives(existing_account.url_suffix, new_account.url_suffix)
    existing_account.display_name = reconcile_primitives(existing_account.display_name, new_account.display_name)
    existing_account.bio = reconcile_primitives(existing_account.bio, new_account.bio)
    existing_account.data = reconcile_dicts(existing_account.data, new_account.data)
    return existing_account


def reconcile_posts(new_post: Post, existing_post: Optional[Post]) -> Post:
    if existing_post is None:
        return new_post
    existing_post.id_on_platform = reconcile_primitives(existing_post.id_on_platform, new_post.id_on_platform)
    existing_post.url_suffix = reconcile_primitives(existing_post.url_suffix, new_post.url_suffix)
    existing_post.account_url_suffix = reconcile_primitives(existing_post.account_url_suffix, new_post.account_url_suffix)
    existing_post.publication_date = reconcile_primitives(existing_post.publication_date, new_post.publication_date)
    existing_post.caption = reconcile_primitives(existing_post.caption, new_post.caption)
    existing_post.data = reconcile_dicts(existing_post.data, new_post.data)
    return existing_post


def reconcile_media(new_media: Media, existing_media: Optional[Media]) -> Media:
    if existing_media is None:
        return new_media
    existing_media.id_on_platform = reconcile_primitives(existing_media.id_on_platform, new_media.id_on_platform)
    # video beats image regardless of which record arrived first — a DASH-only video
    # carries video_dash_manifest only in the detail endpoint response, not in
    # timeline/thumbnail responses. Downgrading "video" → "image" on a later record
    # would lose the correct classification and the video url_suffix.
    if (existing_media.media_type == "video") != (new_media.media_type == "video"):
        existing_media.media_type = "video"
        video_url = (new_media.url_suffix if new_media.media_type == "video"
                     else existing_media.url_suffix)
        existing_media.url_suffix = video_url or reconcile_primitives(existing_media.url_suffix, new_media.url_suffix)
    else:
        existing_media.url_suffix = reconcile_primitives(existing_media.url_suffix, new_media.url_suffix)
        existing_media.media_type = reconcile_primitives(existing_media.media_type, new_media.media_type)
    existing_media.post_url_suffix = reconcile_primitives(existing_media.post_url_suffix, new_media.post_url_suffix)
    new_size = _local_url_size(new_media.local_url)
    existing_size = _local_url_size(existing_media.local_url)
    if new_size > existing_size:
        existing_media.local_url = new_media.local_url
        existing_media.thumbnail_path = None
        existing_media.thumbnail_status = 'pending'
    else:
        existing_media.local_url = reconcile_primitives(existing_media.local_url, new_media.local_url)
    existing_media.data = reconcile_dicts(existing_media.data, new_media.data)
    return existing_media


def reconcile_comments(new_comment: Comment, existing_comment: Optional[Comment]) -> Comment:
    if existing_comment is None:
        return new_comment
    existing_comment.id_on_platform = reconcile_primitives(existing_comment.id_on_platform, new_comment.id_on_platform)
    existing_comment.url_suffix = reconcile_primitives(existing_comment.url_suffix, new_comment.url_suffix)
    existing_comment.post_id_on_platform = reconcile_primitives(existing_comment.post_id_on_platform, new_comment.post_id_on_platform)
    existing_comment.post_url_suffix = reconcile_primitives(existing_comment.post_url_suffix, new_comment.post_url_suffix)
    existing_comment.account_id_on_platform = reconcile_primitives(existing_comment.account_id_on_platform, new_comment.account_id_on_platform)
    existing_comment.account_url_suffix = reconcile_primitives(existing_comment.account_url_suffix, new_comment.account_url_suffix)
    existing_comment.parent_comment_id_on_platform = reconcile_primitives(existing_comment.parent_comment_id_on_platform, new_comment.parent_comment_id_on_platform)
    existing_comment.text = reconcile_primitives(existing_comment.text, new_comment.text)
    existing_comment.publication_date = reconcile_primitives(existing_comment.publication_date, new_comment.publication_date)
    existing_comment.data = reconcile_dicts(existing_comment.data, new_comment.data)
    return existing_comment


def reconcile_likes(new_like: Like, existing_like: Optional[Like]) -> Like:
    if existing_like is None:
        return new_like
    existing_like.id_on_platform = reconcile_primitives(existing_like.id_on_platform, new_like.id_on_platform)
    existing_like.post_id_on_platform = reconcile_primitives(existing_like.post_id_on_platform, new_like.post_id_on_platform)
    existing_like.post_url_suffix = reconcile_primitives(existing_like.post_url_suffix, new_like.post_url_suffix)
    existing_like.account_id_on_platform = reconcile_primitives(existing_like.account_id_on_platform, new_like.account_id_on_platform)
    existing_like.account_url_suffix = reconcile_primitives(existing_like.account_url_suffix, new_like.account_url_suffix)
    existing_like.data = reconcile_dicts(existing_like.data, new_like.data)
    return existing_like


def reconcile_tagged_accounts(new_ta: TaggedAccount, existing_ta: Optional[TaggedAccount]) -> TaggedAccount:
    if existing_ta is None:
        return new_ta
    existing_ta.id_on_platform = reconcile_primitives(existing_ta.id_on_platform, new_ta.id_on_platform)
    existing_ta.tagged_account_id_on_platform = reconcile_primitives(existing_ta.tagged_account_id_on_platform, new_ta.tagged_account_id_on_platform)
    existing_ta.tagged_account_url_suffix = reconcile_primitives(existing_ta.tagged_account_url_suffix, new_ta.tagged_account_url_suffix)
    existing_ta.context_post_url_suffix = reconcile_primitives(existing_ta.context_post_url_suffix, new_ta.context_post_url_suffix)
    existing_ta.context_media_url_suffix = reconcile_primitives(existing_ta.context_media_url_suffix, new_ta.context_media_url_suffix)
    existing_ta.context_post_id_on_platform = reconcile_primitives(existing_ta.context_post_id_on_platform, new_ta.context_post_id_on_platform)
    existing_ta.context_media_id_on_platform = reconcile_primitives(existing_ta.context_media_id_on_platform, new_ta.context_media_id_on_platform)
    existing_ta.tag_x_position = reconcile_primitives(existing_ta.tag_x_position, new_ta.tag_x_position)
    existing_ta.tag_y_position = reconcile_primitives(existing_ta.tag_y_position, new_ta.tag_y_position)
    existing_ta.data = reconcile_dicts(existing_ta.data, new_ta.data)
    return existing_ta


def reconcile_account_relations(new_ar: AccountRelation, existing_ar: Optional[AccountRelation]) -> AccountRelation:
    if existing_ar is None:
        return new_ar
    existing_ar.id_on_platform = reconcile_primitives(existing_ar.id_on_platform, new_ar.id_on_platform)
    existing_ar.follower_account_id_on_platform = reconcile_primitives(existing_ar.follower_account_id_on_platform, new_ar.follower_account_id_on_platform)
    existing_ar.follower_account_url_suffix = reconcile_primitives(existing_ar.follower_account_url_suffix, new_ar.follower_account_url_suffix)
    existing_ar.followed_account_id_on_platform = reconcile_primitives(existing_ar.followed_account_id_on_platform, new_ar.followed_account_id_on_platform)
    existing_ar.followed_account_url_suffix = reconcile_primitives(existing_ar.followed_account_url_suffix, new_ar.followed_account_url_suffix)
    existing_ar.relation_type = reconcile_primitives(existing_ar.relation_type, new_ar.relation_type)
    existing_ar.data = reconcile_dicts(existing_ar.data, new_ar.data)
    return existing_ar


def synthesize_from_archives(records: list[T], reconcile_fn: Callable[[T, T], T]) -> Optional[T]:
    """
    Fold a list of archive records into a single synthesized entity.

    Sorted oldest-first before folding so that first-non-empty wins semantics
    preserve the earliest observed value for each field (consistent with the
    pairwise merge used during initial ingestion).

    Returns None if records is empty.
    """
    if not records:
        return None
    sorted_records = sorted(records, key=lambda r: getattr(r, 'create_date', None) or datetime.min, reverse=True)
    result = sorted_records[0]
    for older in sorted_records[1:]:
        result = reconcile_fn(older, result)  # existing=result (newest) wins over older
    return result


def _local_url_size(local_url: Optional[str]) -> int:
    """
    Return the file size in bytes of the file pointed to by a local_url alias path.

    local_url format: "{alias}/{ROOT_ARCHIVES-relative-path}"
    Both known aliases (local_archive_har, local_archive_wacz) prefix a
    ROOT_ARCHIVES-relative path, so stripping the first segment resolves any alias.

    Returns 0 if the URL is None, the path segment is malformed, or the file
    does not exist (OSError).
    """
    if not local_url:
        return 0
    parts = local_url.split("/", 1)
    if len(parts) < 2:
        return 0
    try:
        return (ROOT_ARCHIVES / parts[1]).stat().st_size
    except OSError:
        return 0
