from http.client import HTTPException
from typing import Any

from fastapi import APIRouter, Depends, Request

from browsing_platform.server.routes.account import _auth_account_view
from browsing_platform.server.routes.fast_api_request_processor import extract_entities_transform_config, \
    extract_session_transform_config
from browsing_platform.server.routes.media import _auth_media_view
from browsing_platform.server.routes.post import _auth_post_view
from browsing_platform.server.services.archiving_session import ArchiveSessionWithEntities, ArchiveSession, \
    get_archiving_session_by_id
from browsing_platform.server.services.enriched_entities import get_enriched_archiving_session_by_id, \
    get_archiving_sessions_by_account_id, get_archiving_sessions_by_post_id, \
    get_archiving_sessions_by_media_id
from browsing_platform.server.services.permissions import auth_entity_view_access

router = APIRouter(
    prefix="/archiving_session",
    tags=["archiving_session"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)

async def _auth_archiving_session_view(req: Request, item_id: int):
    return await auth_entity_view_access(request=req, entity="archiving_session", entity_id=item_id)


@router.get("/data/{item_id}/", dependencies=[Depends(_auth_archiving_session_view)])
async def get_archiving_session_data(item_id:int) -> Any:
    session = get_archiving_session_by_id(item_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session Not Found")
    return session.structures


@router.get("/{item_id}/", dependencies=[Depends(_auth_archiving_session_view)])
async def get_archiving_session(item_id:int, req: Request) -> ArchiveSessionWithEntities:
    session = get_enriched_archiving_session_by_id(item_id, extract_entities_transform_config(req))
    if not session:
        raise HTTPException(status_code=404, detail="Session Not Found")
    return session


@router.get("/account/{item_id}/", dependencies=[Depends(_auth_account_view)])
async def get_archiving_sessions_for_account(item_id:int, req: Request) -> list[ArchiveSession]:
    sessions = get_archiving_sessions_by_account_id(item_id, extract_session_transform_config(req))
    return sessions


@router.get("/post/{item_id}/", dependencies=[Depends(_auth_post_view)])
async def get_archiving_sessions_for_post(item_id:int, req: Request) -> list[ArchiveSession]:
    sessions = get_archiving_sessions_by_post_id(item_id, extract_session_transform_config(req))
    return sessions


@router.get("/media/{item_id}/", dependencies=[Depends(_auth_media_view)])
async def get_archiving_sessions_for_media(item_id:int, req: Request) -> list[ArchiveSession]:
    sessions = get_archiving_sessions_by_media_id(item_id, extract_session_transform_config(req))
    return sessions