from http.client import HTTPException
from typing import Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Request

from browsing_platform.server.routes.fast_api_request_processor import extract_entities_transform_config
from browsing_platform.server.services.account import get_account_by_id, annotate_account
from browsing_platform.server.services.annotation import Annotation
from browsing_platform.server.services.enriched_entities import get_enriched_account_by_id
from browsing_platform.server.services.media import get_media_by_id, annotate_media
from browsing_platform.server.services.media_part import get_media_part_by_id, annotate_media_part
from browsing_platform.server.services.permissions import get_auth_user
from browsing_platform.server.services.post import get_post_by_id, annotate_post
from extractors.entity_types import ExtractedEntitiesNested

router = APIRouter(
    prefix="/annotate",
    tags=["annotate"],
    dependencies=[Depends(get_auth_user)],
    responses={404: {"description": "Not found"}},
)

EntityType: TypeAlias = Literal["account", "post", "media", "media_part"]



@router.post("/{entity:str}/{item_id:int}", dependencies=[Depends(get_auth_user)])
async def annotate_entity(entity: EntityType, item_id:int, annotation: Annotation) -> Any:
    if entity == "account":
        account = get_account_by_id(item_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account Not Found")
        annotate_account(item_id, annotation)
    elif entity == "post":
        post = get_post_by_id(item_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post Not Found")
        annotate_post(item_id, annotation)
    elif entity == "media":
        media = get_media_by_id(item_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media Not Found")
        annotate_media(item_id, annotation)
    elif entity == "media_part":
        media_part = get_media_part_by_id(item_id)
        if not media_part:
            raise HTTPException(status_code=404, detail="Media Part Not Found")
        annotate_media_part(item_id, annotation)
    else:
        raise HTTPException(status_code=400, detail="Invalid Entity Type")
    return True


@router.get("/{entity:str}/{item_id:int}", dependencies=[Depends(get_auth_user)])
async def get_account(entity: EntityType, item_id: int, req: Request) -> ExtractedEntitiesNested:
    account = get_enriched_account_by_id(item_id, extract_entities_transform_config(req))
    if not account:
        raise HTTPException(status_code=404, detail="Account Not Found")
    return account
