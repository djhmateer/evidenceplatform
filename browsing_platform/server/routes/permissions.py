from fastapi import APIRouter, Depends, HTTPException, Request

from browsing_platform.server.services.permissions import auth_user_access
from browsing_platform.server.services.token_manager import check_token

router = APIRouter(
    prefix="/permissions",
    tags=["permissions"],
    dependencies=[Depends(auth_user_access)],
    responses={404: {"description": "Not found"}},
)


@router.get("/")
async def get_permissions(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401)
    token = auth_header.split(":")[1]
    if not token:
        raise HTTPException(status_code=401)
    token_permissions = check_token(token)
    if not token_permissions.valid:
        raise HTTPException(status_code=401)
    return token_permissions