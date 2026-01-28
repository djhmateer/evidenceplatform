from http.client import HTTPException
from typing import Any

from fastapi import APIRouter, Depends, Request

from browsing_platform.server.routes.fast_api_request_processor import extract_entities_transform_config
from browsing_platform.server.services.enriched_entities import get_enriched_media_by_id
from browsing_platform.server.services.media import get_media_by_id
from browsing_platform.server.services.media_part import get_media_part_by_media
from browsing_platform.server.services.permissions import auth_entity_view_access
from extractors.entity_types import ExtractedEntitiesNested

router = APIRouter(
    prefix="/media",
    tags=["media"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)

async def _auth_media_view(req: Request, item_id: int):
    return await auth_entity_view_access(request=req, entity="media", entity_id=item_id)


@router.get("/data/{item_id}/", dependencies=[Depends(_auth_media_view)])
async def get_media_data(item_id:int) -> Any:
    media = get_media_by_id(item_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media Not Found")
    return media.data


@router.get("/parts/{item_id}/", dependencies=[Depends(_auth_media_view)])
async def get_media_parts(item_id:int) -> Any:
    media = get_media_by_id(item_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media Not Found")
    return get_media_part_by_media([media])


@router.get("/{item_id}/", dependencies=[Depends(_auth_media_view)])
async def get_media(item_id:int, req: Request) -> ExtractedEntitiesNested:
    media = get_enriched_media_by_id(item_id, extract_entities_transform_config(req))
    if not media:
        raise HTTPException(status_code=404, detail="Media Not Found")
    return media
