import asyncio
import json
import logging
import os
import threading

from enum import Enum
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel


class IncorporationMode(str, Enum):
    register = "register"
    rerun = "rerun"


class ResetStatusRequest(BaseModel):
    target_status: Literal["pending", "parsed"]
    id_min: Optional[int] = None
    id_max: Optional[int] = None
    archiving_from: Optional[str] = None  # ISO datetime, inclusive lower bound
    archiving_to: Optional[str] = None    # ISO datetime, inclusive upper bound
    dry_run: bool = True
    confirmation: Optional[str] = None    # must equal "I am sure!" when dry_run is False


RESET_CONFIRMATION_PHRASE = "I am sure!"

from browsing_platform.server.rate_limiter import _get_real_ip
from browsing_platform.server.services.incorporation_service import manager, _run_incorporation, incorporation_ws, reset_incorporation_status
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
    client_ip = _get_real_ip(request)
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
# Reset incorporation status — revert a session or range of sessions so the
# next run reprocesses them. Pure status mutation; entity de-duplication is
# handled idempotently by db_intake.py on the next incorporation.
# ---------------------------------------------------------------------------

@router.post("/reset-status")
def reset_status(body: ResetStatusRequest, request: Request, permissions=Depends(auth_admin_access)):
    if not body.dry_run:
        if body.confirmation != RESET_CONFIRMATION_PHRASE:
            raise HTTPException(
                status_code=400,
                detail=f'Confirmation required: type "{RESET_CONFIRMATION_PHRASE}" to apply the reset.',
            )
        # A reset that mutates status while the pipeline is mid-run would race its
        # queue snapshots (Part B drains 'pending', Part C drains 'parsed').
        # Previews (dry_run) are read-only and always allowed.
        if manager.is_running():
            raise HTTPException(
                status_code=409,
                detail="An incorporation job is currently running; wait for it to finish before resetting status.",
            )

    try:
        affected = reset_incorporation_status(
            target_status=body.target_status,
            id_min=body.id_min,
            id_max=body.id_max,
            archiving_from=body.archiving_from,
            archiving_to=body.archiving_to,
            dry_run=body.dry_run,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if body.dry_run:
        return {"count": affected}

    user_id = getattr(permissions, "user_id", None)
    client_ip = _get_real_ip(request)
    logger.info(
        "Reset incorporation_status to %s for %s session(s) by user=%s ip=%s "
        "(id_min=%s id_max=%s archiving_from=%s archiving_to=%s)",
        body.target_status, affected, user_id, client_ip,
        body.id_min, body.id_max, body.archiving_from, body.archiving_to,
    )
    return {"updated": affected}


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
