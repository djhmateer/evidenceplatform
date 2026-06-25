import asyncio
import json
import logging
import os
import threading

from enum import Enum
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect


class IncorporationMode(str, Enum):
    register = "register"
    rerun = "rerun"

from browsing_platform.server.services.incorporation_service import manager, _run_incorporation, incorporation_ws
from browsing_platform.server.services.permissions import auth_admin_access
from browsing_platform.server.services.token_manager import check_token
from utils import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incorporate", tags=["incorporate"])


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

@router.post("/start")
def start(
    request: Request,
    background_tasks: BackgroundTasks,
    limit: Optional[int] = Query(
        None,
        description="Max archives to process, newest-first. Omit for env/dev default; "
                    "<=0 means no limit.",
    ),
    name_filter: Optional[str] = Query(
        None,
        alias="filter",
        description="Only process archives whose directory name matches this substring or glob.",
    ),
    mode: IncorporationMode = Query(
        IncorporationMode.register,
        description="'register' (default) ingests new archives; 'rerun' re-incorporates "
                    "the latest already-registered archives in place (no accumulation). "
                    "Any other value is rejected with 422.",
    ),
    permissions=Depends(auth_admin_access),
):
    user_id = getattr(permissions, "user_id", None)
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )
    try:
        job_id = manager.try_start(triggered_by_user_id=user_id, triggered_by_ip=client_ip)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    background_tasks.add_task(_run_in_thread, job_id, limit, name_filter, mode.value)
    return {"status": "started", "job_id": job_id}


def _run_in_thread(job_id: int, limit=None, name_filter=None, mode=None):
    """Wrapper that launches the incorporation work in a daemon thread."""
    t = threading.Thread(
        target=_run_incorporation,
        args=(job_id, limit, name_filter, mode),
        daemon=True,
    )
    t.start()


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

@router.post("/stop")
def stop(_=Depends(auth_admin_access)):
    if not manager.is_running():
        raise HTTPException(status_code=409, detail="No incorporation job is currently running")
    manager.request_cancel()
    return {"status": "cancel_requested"}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status")
def status(_=Depends(auth_admin_access)):
    job_id = manager.current_job_id()
    if manager.is_running() and job_id is not None:
        row = db.execute_query(
            "SELECT * FROM incorporation_job WHERE id = %(id)s",
            {"id": job_id},
            return_type="single_row",
        )
        return {"running": True, "job": row}
    return {"running": False, "job": None}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("/history")
def history(_=Depends(auth_admin_access)):
    rows = db.execute_query(
        "SELECT * FROM incorporation_job ORDER BY started_at DESC LIMIT 50",
        {},
        return_type="rows",
    )
    return {"jobs": rows or []}


# ---------------------------------------------------------------------------
# WebSocket — real-time log stream
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # Accept first so we can send a proper close frame if auth fails.
    # Tokens must NOT be passed in the URL (they appear in server logs); instead
    # the client sends {"token": "<value>"} as its very first message.
    await websocket.accept()
    is_dev = os.getenv("BROWSING_PLATFORM_DEV") == "1"
    if not is_dev:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            msg = json.loads(raw)
            token = msg.get("token") if isinstance(msg, dict) else None
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            await websocket.close(code=4003)
            return
        perms = check_token(token)
        if not perms.valid or not perms.admin:
            await websocket.close(code=4003)
            return
    q = incorporation_ws.subscribe()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_text(json.dumps(msg))
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
    finally:
        incorporation_ws.unsubscribe(q)
