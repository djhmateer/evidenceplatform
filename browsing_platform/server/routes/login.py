import json
import logging
import re
import traceback

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from browsing_platform.server.rate_limiter import limiter
from browsing_platform.server.services.event_logger import log_event
from browsing_platform.server.services.password_authenticator import (
    AccountLockedException,
    LoginStepResponse,
    login_with_password,
)
from browsing_platform.server.services.permissions import parse_token_from_header
from browsing_platform.server.services.pre_auth_manager import consume_pre_auth_token
from browsing_platform.server.services.token_manager import AuthTokenResponse, generate_token, remove_token
from browsing_platform.server.services.totp_manager import verify_totp_code
from utils import db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/login",
    tags=["login"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)

_TOTP_PATTERN = re.compile(r"^\d{6}$")


class LoginCredentialsPass(BaseModel):
    email: str
    password: str


class Verify2FARequest(BaseModel):
    pre_auth_token: str
    totp_code: str


@router.post("/")
@limiter.limit("10/15minutes")
async def login_with_pass(data: LoginCredentialsPass, request: Request) -> LoginStepResponse:
    try:
        return login_with_password(data.email, data.password)
    except AccountLockedException as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception:
        logger.error(f"Login error: {traceback.format_exc()}")
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/verify-2fa")
@limiter.limit("10/15minutes")
async def verify_2fa(data: Verify2FARequest, request: Request) -> AuthTokenResponse:
    user_id = consume_pre_auth_token(data.pre_auth_token, "verify_totp")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA token")

    user_row = db.execute_query(
        "SELECT totp_secret, admin FROM user WHERE id = %(uid)s",
        {"uid": user_id}, "single_row"
    )
    if not user_row or not user_row["totp_secret"]:
        raise HTTPException(status_code=401, detail="2FA not configured")

    code = data.totp_code.strip()
    if not _TOTP_PATTERN.match(code) or not verify_totp_code(user_row["totp_secret"], code, user_id):
        log_event("2fa_attempt", user_id, json.dumps({"success": False}), "{}")
        raise HTTPException(status_code=401, detail="Invalid 2FA code")

    token = generate_token()
    db.execute_query(
        "INSERT INTO token (user_id, token) VALUES (%(uid)s, %(tok)s)",
        {"uid": user_id, "tok": token}, "none"
    )

    return AuthTokenResponse(token=token, permissions=bool(user_row["admin"]))


@router.post("/logout")
async def logout(request: Request):
    """Logout user and invalidate token"""
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    if not token:
        raise HTTPException(status_code=401)
    remove_token(token)
    return {"success": True}
