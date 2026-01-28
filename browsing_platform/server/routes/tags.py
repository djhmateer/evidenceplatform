from typing import Any

from fastapi import APIRouter, Depends, Request

from browsing_platform.server.services.permissions import auth_user_access
from browsing_platform.server.services.tag import auto_complete_tags

router = APIRouter(
    prefix="/tags",
    tags=["tags"],
    dependencies=[Depends(auth_user_access)],
    responses={404: {"description": "Not found"}},
)


@router.get("/", dependencies=[Depends(auth_user_access)])
async def lookup_tags(req: Request) -> Any:
    search_query = req.query_params.get("q", "")
    return auto_complete_tags(search_query)

