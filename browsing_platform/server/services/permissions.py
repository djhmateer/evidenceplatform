import json
import os

from fastapi import HTTPException
from starlette.requests import Request

from browsing_platform.server.services.event_logger import log_event
from browsing_platform.server.services.token_manager import check_token


async def get_auth_user(request: Request):
    # Bypass auth in dev mode
    if os.getenv("BROWSING_PLATFORM_DEV"):
        return True
    """verify that user has a valid session"""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        body = await request.body()
        log_event("unauthorized_access", None,
                  request.scope['root_path'] + request.scope['route'].path,
                  json.dumps({"body": body.decode()}))
        raise HTTPException(status_code=401)
    token = auth_header.split(":")[1]
    if not token:
        body = await request.body()
        log_event("unauthorized_access", None,
                  request.scope['root_path'] + request.scope['route'].path,
                  json.dumps({"body": body.decode()}))
        raise HTTPException(status_code=401)
    token_permissions = check_token(token)
    if not token_permissions.valid:
        body = await request.body()
        log_event("unauthorized_access", None,
                  request.scope['root_path'] + request.scope['route'].path,
                  json.dumps({"body": body.decode()}))
        raise HTTPException(status_code=401)
    return True


async def get_user_id(request: Request):
    auth_header = request.headers.get("Authorization")
    token = auth_header.split(":")[1]
    token_permissions = check_token(token)
    return token_permissions.user_id


async def log_server_call(request: Request):
    """verify that user has a valid session"""
    print(request.cookies)
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
