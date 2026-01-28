from http.client import HTTPException
from typing import Optional

from fastapi import APIRouter, Depends, Request

from browsing_platform.server.services.media_part import get_media_part_by_id, MediaPart, update_media_part, \
    insert_media_part, delete_media_part
from browsing_platform.server.services.permissions import auth_user_access, auth_entity_view_access

router = APIRouter(
    prefix="/media_part",
    tags=["media_part"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)

async def _auth_media_part_view(req: Request, item_id: int):
    return await auth_entity_view_access(request=req, entity="media_part", entity_id=item_id)


@router.get("/{item_id}/", dependencies=[Depends(_auth_media_part_view)])
async def get_media_part(item_id:int) -> MediaPart:
    media_part = get_media_part_by_id(item_id)
    if not media_part:
        raise HTTPException(status_code=404, detail="Media Part Not Found")
    return media_part


@router.post("/", dependencies=[Depends(auth_user_access)])
async def post_media_part(item: MediaPart) -> Optional[int]:
    try:
        if item.id:
            return update_media_part(item)
        else:
            return insert_media_part(item)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{item_id}/", dependencies=[Depends(auth_user_access)])
async def drop_media_part(item_id:int) -> None:
    media_part = get_media_part_by_id(item_id)
    if not media_part:
        raise HTTPException(status_code=404, detail="Media Part Not Found")
    return delete_media_part(item_id)
