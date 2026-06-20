"""Generic, platform-agnostic leaf helpers shared by the per-platform
structures->entities mappers (Instagram, Threads, ...).

These live in their own module (rather than in the generic
``structures_to_entities`` orchestration module) so the per-platform mapper
modules can import them without creating an import cycle with the orchestration
module, which in turn imports the per-platform mappers for dispatch.

The media helpers are duck-typed on purpose: any object exposing ``media_type``
/ ``video_versions`` / ``image_versions2`` / ``video_dash_manifest`` works,
regardless of which platform's Pydantic model it is. Instagram and Threads both
serve the shared Meta media shape (``image_versions2``/``video_versions``), so
the same helpers apply unchanged.
"""
import html as _html
import re as _re
from typing import Optional

from extractors.entity_types import ExtractedEntitiesFlattened


def _is_video(item) -> bool:
    if getattr(item, 'media_type', None) == 2:
        return True
    if getattr(item, 'video_versions', None):
        return True
    manifest = getattr(item, 'video_dash_manifest', None)
    if manifest and isinstance(manifest, str) and manifest.strip():
        return True
    return False


def _asset_url_from_item(item) -> Optional[str]:
    video_versions = getattr(item, 'video_versions', None)
    if video_versions:
        return video_versions[0].url
    manifest = getattr(item, 'video_dash_manifest', None)
    if manifest and isinstance(manifest, str):
        for raw in _re.findall(r'<BaseURL>([^<]+)</BaseURL>', manifest):
            url = _html.unescape(raw).strip()
            if url:
                return url
    image_versions2 = getattr(item, 'image_versions2', None)
    if image_versions2 and image_versions2.candidates:
        return image_versions2.candidates[0].url
    return None


def canonical_cdn_url(url: str) -> str:
    return url.split("?")[0].split("/")[-1]


def extend_flattened_entities(
        entities_1: ExtractedEntitiesFlattened,
        entities_2: ExtractedEntitiesFlattened
) -> None:
    entities_1.accounts.extend(entities_2.accounts)
    entities_1.posts.extend(entities_2.posts)
    entities_1.media.extend(entities_2.media)
    entities_1.comments.extend(entities_2.comments)
    entities_1.likes.extend(entities_2.likes)
    entities_1.account_relations.extend(entities_2.account_relations)
    entities_1.tagged_accounts.extend(entities_2.tagged_accounts)
