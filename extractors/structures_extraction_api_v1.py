from typing import Optional

from pydantic import BaseModel

from extractors.models_api_v1 import FriendshipsApiV1, CommentsApiV1, LikersApiV1, MediaInfoApiV1
from extractors.models_har import HarRequest


class ApiV1Context(BaseModel):
    url: Optional[str] = None
    media_id: Optional[int] = None

class ApiV1Response(BaseModel):
    context: Optional[ApiV1Context] = None
    friendships: Optional[FriendshipsApiV1] = None
    likers: Optional[LikersApiV1] = None
    comments: Optional[CommentsApiV1] = None
    media_info: Optional[MediaInfoApiV1] = None


def extract_data_from_api_v1_entry(api_data: dict, req: HarRequest) -> Optional[ApiV1Response]:
    res = ApiV1Response()
    res.context = ApiV1Context(url=req.url, media_id=int(req.url.split('media/')[1].split('/')[0]) if 'media/' in req.url else None)
    if "/friendships/" in req.url:
        res.friendships = FriendshipsApiV1(**api_data)
    elif "/likers/" in req.url:
        res.likers = LikersApiV1(**api_data)
    elif "/comments/" in req.url:
        res.comments = CommentsApiV1(**api_data)
    elif "/info/" in req.url:
        res.media_info = MediaInfoApiV1(**api_data)
    return res if any([res.friendships, res.likers, res.comments, res.media_info]) else None
