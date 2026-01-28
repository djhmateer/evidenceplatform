from http.client import HTTPException
from typing import Any

from fastapi import APIRouter, Depends, Request

from browsing_platform.server.routes.fast_api_request_processor import extract_entities_transform_config
from browsing_platform.server.services.enriched_entities import get_enriched_post_by_id
from browsing_platform.server.services.permissions import auth_entity_view_access
from browsing_platform.server.services.post import get_post_by_id
from extractors.entity_types import ExtractedEntitiesNested

router = APIRouter(
    prefix="/post",
    tags=["post"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)


async def _auth_post_view(req: Request, item_id: int):
    return await auth_entity_view_access(request=req, entity="post", entity_id=item_id)


@router.get("/data/{item_id}/", dependencies=[Depends(_auth_post_view)])
async def get_post_data(item_id:int) -> Any:
    post = get_post_by_id(item_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post Not Found")
    return post.data


@router.get("/{item_id}/", dependencies=[Depends(_auth_post_view)])
async def get_post(item_id:int, req: Request) -> ExtractedEntitiesNested:
    post = get_enriched_post_by_id(item_id, extract_entities_transform_config(req))
    if not post:
        raise HTTPException(status_code=404, detail="Post Not Found")
    return post
