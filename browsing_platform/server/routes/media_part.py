from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi import HTTPException

from browsing_platform.server.services.media_part import get_media_part_by_id, MediaPart, update_media_part, \
    insert_media_part, delete_media_part
from browsing_platform.server.services.permissions import auth_user_access, auth_entity_view_access
from db_loaders.thumbnail_generator import generate_media_part_thumbnail

router = APIRouter(
    prefix="/media_part",
    tags=["media_part"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)

async def _auth_media_part_view(req: Request, item_id: int):
    return await auth_entity_view_access(request=req, entity="media_part", entity_id=item_id)


@router.get("/{item_id}/", dependencies=[Depends(_auth_media_part_view)])
@router.get("/{item_id}", dependencies=[Depends(_auth_media_part_view)])
async def get_media_part(item_id:int) -> MediaPart:
    media_part = get_media_part_by_id(item_id)
    if not media_part:
        raise HTTPException(status_code=404, detail="Media Part Not Found")
    return media_part


@router.post("/", dependencies=[Depends(auth_user_access)])
async def post_media_part(item: MediaPart, background_tasks: BackgroundTasks) -> MediaPart:
    """Create or update a media_part. The crop/time range determine the part's thumbnail, so a
    save (re)sets thumbnail_status='pending' and schedules background regeneration. Returns the
    saved part (with its id) so the client can capture the new id for auto-save."""
    try:
        if item.id:
            update_media_part(item)
            part_id = item.id
        else:
            part_id = insert_media_part(item)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    background_tasks.add_task(generate_media_part_thumbnail, part_id)
    saved = get_media_part_by_id(part_id)
    if not saved:
        raise HTTPException(status_code=500, detail="Media part vanished after save")
    return saved


@router.delete("/{item_id}/", dependencies=[Depends(auth_user_access)])
async def drop_media_part(item_id:int) -> None:
    media_part = get_media_part_by_id(item_id)
    if not media_part:
        raise HTTPException(status_code=404, detail="Media Part Not Found")
    return delete_media_part(item_id)
