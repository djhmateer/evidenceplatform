import json
import logging
import os

from fastapi import HTTPException
from starlette.requests import Request

from browsing_platform.server.services.event_logger import log_event
from browsing_platform.server.services.token_manager import check_token

logger = logging.getLogger(__name__)


async def get_auth_user(request: Request):
    # Bypass auth in dev mode (only when explicitly set to "1")
    if os.getenv("BROWSING_PLATFORM_DEV") == "1":
        logger.debug("Auth bypassed - dev mode enabled")
        return True
    """verify that user has a valid session"""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        body = await request.body()
        logger.warning(f"Unauthorized access - no auth header: {request.scope['route'].path}")
        log_event("unauthorized_access", None,
                  request.scope['root_path'] + request.scope['route'].path,
                  json.dumps({"body": body.decode()}))
        raise HTTPException(status_code=401)
    token = auth_header.split(":")[1]
    if not token:
        body = await request.body()
        logger.warning(f"Unauthorized access - empty token: {request.scope['route'].path}")
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
    token = auth_header.split(":")[1]
    token_permissions = check_token(token)
    logger.debug(f"Retrieved user_id {token_permissions.user_id}")
    return token_permissions.user_id


async def log_server_call(request: Request):
    """verify that user has a valid session"""
    logger.debug(f"Server call: {request.scope['route'].path}")
    auth_header = request.headers.get("Authorization")
    try:
        token = auth_header.split(":")[1]
        token_permissions = check_token(token)
        user_id = token_permissions.user_id
    except Exception:
        user_id = None
    body = await request.body()
    log_event(
        "server_call", user_id,
        request.scope['root_path'] + request.scope['route'].path,
        json.dumps({"body": body.decode("utf-8"), "path_params": request.path_params})
    )
    return True
