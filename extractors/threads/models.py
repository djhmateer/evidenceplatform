"""Pydantic models for Threads (Meta's "Barcelona") API/HTML responses.

Threads serves the *same* Meta media shape Instagram does (``image_versions2``
/ ``video_versions`` / ``media_type`` / ``carousel_media``), so these models
deliberately reuse those field names — the duck-typed media helpers
(``extractors.extraction_helpers._is_video`` / ``_asset_url_from_item``) then
work on Threads items unchanged.

Every model allows extra fields (``extra="allow"``) so the full raw payload is
preserved through ``model_dump()`` into each entity's ``data`` column — Threads
carries a lot of post metadata (``text_post_app_info`` with repost/quote/reply
info, ``text_fragments``) that we keep verbatim rather than model exhaustively.
"""
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


def _str_id(v: Any) -> Any:
    """Coerce integer IDs to strings (Threads, like Instagram, returns ids as
    either str or int depending on the field/route)."""
    return str(v) if isinstance(v, int) else v


class _ThreadsBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ImageCandidate(_ThreadsBase):
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class ImageVersions2(_ThreadsBase):
    candidates: List[ImageCandidate] = []


class VideoVersion(_ThreadsBase):
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    type: Optional[int] = None


class ThreadsCaption(_ThreadsBase):
    text: Optional[str] = None
    pk: Optional[str] = None

    @field_validator("pk", mode="before")
    @classmethod
    def _coerce_pk(cls, v):
        return _str_id(v)


class ThreadsUser(_ThreadsBase):
    pk: Optional[str] = None
    id: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    is_verified: Optional[bool] = None
    profile_pic_url: Optional[str] = None
    biography: Optional[str] = None
    follower_count: Optional[int] = None

    @field_validator("pk", "id", mode="before")
    @classmethod
    def _coerce_ids(cls, v):
        return _str_id(v)


class ThreadsCarouselItem(_ThreadsBase):
    pk: Optional[str] = None
    id: Optional[str] = None
    code: Optional[str] = None
    media_type: Optional[int] = None
    image_versions2: Optional[ImageVersions2] = None
    video_versions: Optional[List[VideoVersion]] = None
    usertags: Optional[Any] = None

    @field_validator("pk", "id", mode="before")
    @classmethod
    def _coerce_ids(cls, v):
        return _str_id(v)


class ThreadsPost(_ThreadsBase):
    """A single Threads post (Meta ``__typename: XDTThread`` -> ``thread_items[].post``,
    or the bare post object served by the lightbox/column queries). Replies are
    structurally the same object (with ``is_reply`` / ``reply_to_author`` set);
    per project decision they map to a Post whose parent linkage is preserved in
    ``data`` (``text_post_app_info`` / ``reply_to_author``)."""
    pk: Optional[str] = None
    id: Optional[str] = None
    code: Optional[str] = None
    caption: Optional[ThreadsCaption] = None
    taken_at: Optional[int] = None
    like_count: Optional[int] = None
    media_type: Optional[int] = None
    image_versions2: Optional[ImageVersions2] = None
    video_versions: Optional[List[VideoVersion]] = None
    carousel_media: Optional[List[ThreadsCarouselItem]] = None
    usertags: Optional[Any] = None
    user: Optional[ThreadsUser] = None
    text_post_app_info: Optional[Any] = None
    is_reply: Optional[bool] = None

    @field_validator("pk", "id", mode="before")
    @classmethod
    def _coerce_ids(cls, v):
        return _str_id(v)
