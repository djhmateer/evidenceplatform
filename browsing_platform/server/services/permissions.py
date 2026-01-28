import json
import logging
import os
from typing import Optional

from fastapi import HTTPException
from starlette.requests import Request

from browsing_platform.server.services.event_logger import log_event
from browsing_platform.server.services.token_manager import check_token

logger = logging.getLogger(__name__)


def parse_token_from_header(auth_header: Optional[str]) -> Optional[str]:
    """Safely parse token from Authorization header. Expected format: 'token:xxx'"""
    if not auth_header:
        return None
    parts = auth_header.split(":", 1)
    if len(parts) != 2 or parts[0] != "token":
        return None
    return parts[1] if parts[1] else None


async def get_auth_user(request: Request):
    # Bypass auth in dev mode (only when explicitly set to "1")
    if os.getenv("BROWSING_PLATFORM_DEV") == "1":
        logger.debug("Auth bypassed - dev mode enabled")
        return True
    """verify that user has a valid session"""
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    if not token:
        body = await request.body()
        logger.warning(f"Unauthorized access - missing or invalid auth header: {request.scope['route'].path}")
        log_event("unauthorized_access", None,
                  request.scope['root_path'] + request.scope['route'].path,
                  json.dumps({"body": body.decode()}))
        raise HTTPException(status_code=401)
    token_permissions = check_token(token)
    if not token_permissions.valid:
        body = await request.body()
        logger.warning(f"Unauthorized access - invalid token: {request.scope['route'].path}")
        log_event("unauthorized_access", None,
                  request.scope['root_path'] + request.scope['route'].path,
                  json.dumps({"body": body.decode()}))
        raise HTTPException(status_code=401)
    logger.debug(f"Auth successful for user {token_permissions.user_id}: {request.scope['route'].path}")
    return True


async def get_user_id(request: Request):
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    if not token:
        return None
    token_permissions = check_token(token)
    logger.debug(f"Retrieved user_id {token_permissions.user_id}")
    return token_permissions.user_id


async def log_server_call(request: Request):
    """Log server call with user info if available"""
    logger.debug(f"Server call: {request.scope['route'].path}")
    user_id = None
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    if token:
        try:
            token_permissions = check_token(token)
            user_id = token_permissions.user_id
        except Exception:
            pass
    body = await request.body()
    log_event(
        "server_call", user_id,
        request.scope['root_path'] + request.scope['route'].path,
        json.dumps({"body": body.decode("utf-8"), "path_params": request.path_params})
    )
    return True
