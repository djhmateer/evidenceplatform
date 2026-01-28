from typing import Any

from fastapi import APIRouter, Depends, Request

from browsing_platform.server.services.entities_hierarchy import T_Entities
from browsing_platform.server.services.permissions import auth_user_access, get_user_id
from browsing_platform.server.services.sharing_manager import EntitySharePermissions, create_share_link, \
    get_existing_share_link

router = APIRouter(
    prefix="/share",
    tags=["share"],
    dependencies=[Depends(auth_user_access)],
    responses={404: {"description": "Not found"}},
)


@router.post("/", dependencies=[Depends(auth_user_access)])
async def new_share_link(scope: EntitySharePermissions, req: Request) -> Any:
    user_id = get_user_id(req)
    return create_share_link(scope, user_id)


@router.get("/{entity}/{entity_id}/", dependencies=[Depends(auth_user_access)])
async def new_share_link(entity: T_Entities, entity_id: int) -> Any:
    existing_share_link = get_existing_share_link(entity, entity_id)
    if not existing_share_link:
        return None
    else:
        return existing_share_link.link_suffix

