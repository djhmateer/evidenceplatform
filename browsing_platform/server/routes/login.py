import logging
import traceback

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from browsing_platform.server.services.password_authenticator import login_with_password
from browsing_platform.server.services.permissions import parse_token_from_header
from browsing_platform.server.services.token_manager import remove_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/login",
    tags=["login"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)


class LoginCredentialsPass(BaseModel):
    email: str
    password: str


@router.post('/')
async def login_with_pass(data: LoginCredentialsPass):
    try:
        login_res = login_with_password(data.email, data.password)
        return login_res
    except Exception as e:
        logger.error(f"Login error: {traceback.format_exc()}")
        return {"error": "Authentication failed"}


@router.post('/logout')
async def logout(request: Request):
    """Logout user and invalidate token"""
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    if not token:
        raise HTTPException(status_code=401)
    remove_token(token)
    return {"success": True}
