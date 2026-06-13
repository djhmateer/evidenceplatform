from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi import HTTPException

from browsing_platform.server.routes.fast_api_request_processor import extract_entities_transform_config
from browsing_platform.server.services.account import account_exists, get_account_data_by_id, \
    get_account_by_platform_id, get_account_by_url
from browsing_platform.server.services.enriched_entities import get_enriched_account_by_id, \
    get_account_relations_by_account_id, get_interactions_by_account_id, AccountInteractions, \
    get_account_auxiliary_counts, AccountAuxiliaryCounts, AccountRelationsResponse, \
    get_account_tags_for_account_relations
from browsing_platform.server.services.permissions import auth_entity_view_access, require_any_auth
from browsing_platform.server.services.tag_management import get_related_account_tag_stats, ITagStat
from db_loaders.account_merge import resolve_account_redirect
from extractors.entity_types import ExtractedEntitiesNested

router = APIRouter(
    prefix="/account",
    tags=["account"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)

async def _auth_account_view(req: Request, item_id: int):
    return await auth_entity_view_access(request=req, entity="account", entity_id=item_id)


async def _resolved_account_id(item_id: int) -> int:
    # A tombstone of a merged account serves its keeper, so cited URLs survive merges.
    return resolve_account_redirect(item_id)


@router.get("/pk/{platform_id}/")
@router.get("/pk/{platform_id}")
async def get_account_by_pk(platform_id: str, req: Request) -> ExtractedEntitiesNested:
    await require_any_auth(req)
    account = get_account_by_platform_id(platform_id, include_data=False)
    if not account:
        raise HTTPException(status_code=404, detail="Account Not Found")
    await auth_entity_view_access(request=req, entity="account", entity_id=account.id)
    return get_enriched_account_by_id(account.id, extract_entities_transform_config(req))


@router.get("/url/{account_url:path}")
async def get_account_by_url_path(account_url: str, req: Request) -> ExtractedEntitiesNested:
    await require_any_auth(req)
    account = get_account_by_url(account_url, include_data=False)
    if not account:
        raise HTTPException(status_code=404, detail="Account Not Found")
    await auth_entity_view_access(request=req, entity="account", entity_id=account.id)
    return get_enriched_account_by_id(account.id, extract_entities_transform_config(req))


@router.get("/data/{item_id:int}", dependencies=[Depends(_auth_account_view)])
@router.get("/data/{item_id:int}/", dependencies=[Depends(_auth_account_view)])
async def get_account_data(item_id: int = Depends(_resolved_account_id)) -> Any:
    found, data = get_account_data_by_id(item_id)
    if not found:
        raise HTTPException(status_code=404, detail="Account Not Found")
    return data


@router.get("/{item_id}/relations/", dependencies=[Depends(_auth_account_view)])
@router.get("/{item_id}/relations", dependencies=[Depends(_auth_account_view)])
async def get_relations(item_id: int = Depends(_resolved_account_id)) -> AccountRelationsResponse:
    if not account_exists(item_id):
        raise HTTPException(status_code=404, detail="Account Not Found")
    return AccountRelationsResponse(
        relations=get_account_relations_by_account_id(item_id),
        account_tags=get_account_tags_for_account_relations(item_id),
    )


@router.get("/{item_id}/interactions/", dependencies=[Depends(_auth_account_view)])
@router.get("/{item_id}/interactions", dependencies=[Depends(_auth_account_view)])
async def get_interactions(item_id: int = Depends(_resolved_account_id)) -> AccountInteractions:
    if not account_exists(item_id):
        raise HTTPException(status_code=404, detail="Account Not Found")
    return get_interactions_by_account_id(item_id)


@router.get("/{item_id}/related_tag_stats/", dependencies=[Depends(_auth_account_view)])
@router.get("/{item_id}/related_tag_stats", dependencies=[Depends(_auth_account_view)])
async def get_related_tag_stats(item_id: int = Depends(_resolved_account_id)) -> list[ITagStat]:
    if not account_exists(item_id):
        raise HTTPException(status_code=404, detail="Account Not Found")
    return get_related_account_tag_stats(item_id)


@router.get("/{item_id}/auxiliary-counts/", dependencies=[Depends(_auth_account_view)])
@router.get("/{item_id}/auxiliary-counts", dependencies=[Depends(_auth_account_view)])
async def get_account_auxiliary_counts_route(item_id: int = Depends(_resolved_account_id)) -> AccountAuxiliaryCounts:
    if not account_exists(item_id):
        raise HTTPException(status_code=404, detail="Account Not Found")
    return get_account_auxiliary_counts(item_id)


@router.get("/{item_id}/", dependencies=[Depends(_auth_account_view)])
@router.get("/{item_id}", dependencies=[Depends(_auth_account_view)])
async def get_account(req: Request, item_id: int = Depends(_resolved_account_id)) -> ExtractedEntitiesNested:
    account = get_enriched_account_by_id(item_id, extract_entities_transform_config(req))
    if not account:
        raise HTTPException(status_code=404, detail="Account Not Found")
    return account
