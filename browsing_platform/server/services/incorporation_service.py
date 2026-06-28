"""
IncorporationManager — manages the lifecycle of a single incorporation job
(concurrency gate, cancel flag, DB records).

WebSocket broadcasting is handled by the module-level ``incorporation_ws``
BroadcastManager instance. Only messages that are explicitly intended for the
client should be passed to it; backend logging stays in the standard logger.
"""

import asyncio
import logging
import os
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import root_anchor
from browsing_platform.server.services.ws_manager import BroadcastManager
from db_loaders.archives_db_loader import (
    register_archives,
    requeue_archives,
    parse_archives,
    extract_entities,
    set_archives_dir,
)
from db_loaders.thumbnail_generator import generate_missing_thumbnails
from utils import db

logger = logging.getLogger(__name__)

# One broadcast channel dedicated to incorporation progress.
# Import this in routes/incorporate.py for the WebSocket endpoint.
incorporation_ws = BroadcastManager()


class IncorporationManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._current_job_id: Optional[int] = None
        self._cancel_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def try_start(self, triggered_by_user_id: Optional[int], triggered_by_ip: Optional[str]) -> int:
        """Start an incorporation run. Returns the new job_id.

        Raises RuntimeError if a job is already running.
        """
        with self._lock:
            if self._running:
                raise RuntimeError("An incorporation job is already running")
            job_id = db.execute_query(
                "INSERT INTO incorporation_job (status, triggered_by_user_id, triggered_by_ip, started_at) "
                "VALUES ('running', %(user_id)s, %(ip)s, NOW())",
                {"user_id": triggered_by_user_id, "ip": triggered_by_ip},
                return_type="id",
            )
            self._current_job_id = job_id
            self._running = True
            self._cancel_event.clear()
            incorporation_ws.clear_buffer()
        return job_id

    def finish(self, job_id: int, status: str, error_message: Optional[str] = None):
        db.execute_query(
            """UPDATE incorporation_job
               SET status = %(s)s, completed_at = %(t)s, error = %(e)s
               WHERE id = %(id)s""",
            {
                "s": status,
                "t": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "e": error_message,
                "id": job_id,
            },
            return_type="none",
        )
        with self._lock:
            self._running = False
            self._current_job_id = None

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def current_job_id(self) -> Optional[int]:
        with self._lock:
            return self._current_job_id

    def request_cancel(self):
        """Signal the running job to stop after the current archive completes."""
        self._cancel_event.set()

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()


# Module-level singleton
manager = IncorporationManager()


def _resolve_scope(limit: Optional[int], name_filter: Optional[str], mode: Optional[str]):
    """Resolve the effective incorporation scope from explicit args + env defaults.

    limit:  explicit value wins; else INCORPORATION_DEV_LIMIT; else 100 in dev,
            unbounded otherwise. A value <= 0 means "no limit". Selection is
            newest-first, so a limit picks the most recent archives.
    filter: explicit value wins; else INCORPORATION_DEV_FILTER. Substring or glob
            matched against the archive directory name.
    mode:   'register' (default) registers new archives then runs B→C→D;
            'rerun' re-incorporates the latest already-registered archives in
            place (idempotent, no accumulation).
    """
    is_dev = os.getenv("BROWSING_PLATFORM_DEV") == "1"

    if limit is None:
        env_limit = os.getenv("INCORPORATION_DEV_LIMIT")
        if env_limit not in (None, ""):
            try:
                limit = int(env_limit)
            except ValueError:
                logger.warning(f"Ignoring non-integer INCORPORATION_DEV_LIMIT={env_limit!r}")
                limit = None
        elif is_dev:
            limit = 100
    if limit is not None and limit <= 0:
        limit = None  # explicit "process everything"

    if name_filter is None:
        name_filter = os.getenv("INCORPORATION_DEV_FILTER") or None

    mode = (mode or "register").lower()
    if mode not in ("register", "rerun"):
        logger.warning(f"Unknown incorporation mode {mode!r}, falling back to 'register'")
        mode = "register"

    return limit, name_filter, mode


def _resolve_archives_dir_override() -> Optional[Path]:
    """Return an alternate archives root for dev ingestion, or None.

    Honored only in dev (BROWSING_PLATFORM_DEV=1). DEV_ARCHIVES_DIR lets the
    incorporation pipeline read from a small curated fixture folder instead of the
    full ./archives corpus. Returns None when unset, empty, or pointing at the
    default ROOT_ARCHIVES — in which case ingestion proceeds against ./archives
    with the newest-first / limit / filter behaviour fully in effect.

    NB: this only redirects the ingestion *read* path. The browsing platform still
    serves media from the statically mounted ./archives, so a separate fixture dir
    is for verifying ingestion, not for browsing its media.
    """
    if os.getenv("BROWSING_PLATFORM_DEV") != "1":
        return None
    raw = os.getenv("DEV_ARCHIVES_DIR")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    try:
        if candidate.resolve() == root_anchor.ROOT_ARCHIVES.resolve():
            return None
    except OSError:
        pass
    if not candidate.is_dir():
        logger.warning(f"DEV_ARCHIVES_DIR={raw!r} is not an existing directory; ignoring")
        return None
    return candidate


def _run_incorporation(job_id: int, limit: Optional[int] = None, name_filter: Optional[str] = None, mode: Optional[str] = None):
    """Entry point for the background thread.

    Only messages explicitly passed to incorporation_ws.broadcast() will reach
    the client. All other log output stays server-side.
    """
    def emit(text: str, msg_type: str = "status"):
        logger.info(text)
        incorporation_ws.broadcast({"type": msg_type, "text": text})

    cancel = manager.is_cancel_requested
    error_message = None
    status = "completed"

    limit, name_filter, mode = _resolve_scope(limit, name_filter, mode)
    scope_desc = (
        f"mode={mode}, limit={'∞' if limit is None else limit}"
        + (f", filter='{name_filter}'" if name_filter else "")
    )

    # #3 — optional dev fixture directory. Applied for the duration of the job and
    # restored afterwards so other code paths keep seeing the default ./archives.
    archives_override = _resolve_archives_dir_override()
    original_archives_dir = root_anchor.ROOT_ARCHIVES

    try:
        emit(f"Starting incorporation pipeline… ({scope_desc})")

        if archives_override is not None:
            set_archives_dir(archives_override)
            emit(f"Dev archives directory: {archives_override}")

        if mode == "rerun":
            emit("Part A — re-queuing latest archives")
            requeued = requeue_archives(limit=limit, cancel_check=cancel, emit=emit, name_filter=name_filter)
            emit(f"Part A — {requeued} archives re-queued")
        else:
            emit("Part A — registering archives")
            register_archives(limit=limit, cancel_check=cancel, emit=emit, name_filter=name_filter)

        # The scope is bounded entirely by Part A (which rows are 'pending'); B/C/D
        # then drain whatever is pending/parsed. We must NOT pass `limit` to B/C/D:
        # their queues have no ORDER BY, so a slice could process unrelated leftover
        # rows and skip the cohort A just selected — and the thumbnail `limit` counts
        # media rows, not archives, so it would under-generate. Draining is also what
        # lets archives left pending by an earlier interrupted run get finished.
        emit("Part B — parsing HAR files")
        parse_archives(cancel_check=cancel, emit=emit)

        emit("Part C — extracting entities")
        extract_entities(cancel_check=cancel, emit=emit)

        emit("Part D — generating thumbnails")
        # Use a manually managed loop instead of asyncio.run() to avoid blocking
        # on shutdown_default_executor(). asyncio.run() waits for ALL executor
        # threads to finish before returning — including any cv2 threads that
        # survived an asyncio.wait_for timeout and are still running. Those
        # zombie threads would hang the pipeline indefinitely.
        _loop = asyncio.new_event_loop()
        try:
            _loop.run_until_complete(generate_missing_thumbnails(cancel_check=cancel, emit=emit))
        finally:
            _loop.close()

        emit("Incorporation complete.")
        incorporation_ws.broadcast({"type": "done", "status": "completed"})

    except InterruptedError:
        error_message = "Cancelled by user"
        status = "failed"
        logger.info(f"Incorporation job {job_id} cancelled by user")
        emit("Job cancelled by user.")
        incorporation_ws.broadcast({"type": "done", "status": "failed", "error": error_message})
    except Exception as e:
        error_message = str(e)
        status = "failed"
        logger.error(f"Incorporation job {job_id} failed: {e}")
        traceback.print_exc()
        emit(f"ERROR: {e}")
        incorporation_ws.broadcast({"type": "done", "status": "failed", "error": error_message})
    finally:
        # Restore the default archives root so file serving / later jobs are unaffected.
        if archives_override is not None:
            set_archives_dir(original_archives_dir)
        manager.finish(job_id, status, error_message)


def cleanup_stale_jobs():
    """Mark any jobs left in 'running' state as 'failed' (called at server startup)."""
    db.execute_query(
        "UPDATE incorporation_job SET status = 'failed', error = 'Server restarted while job was running' "
        "WHERE status = 'running'",
        {},
        return_type="none",
    )
    logger.info("Stale incorporation jobs marked as failed")


# ---------------------------------------------------------------------------
# Reset incorporation status (re-queue a session or range of sessions)
# ---------------------------------------------------------------------------

# Which current statuses may be reverted to a given target. Encodes the
# revert-only rule: status topology is
#   'pending' < ('parse_failed'|'parsed') < ('extract_failed'|'done')
# and a reset may only lower a session's status, never raise or move it
# laterally. Sessions at or below the target are silently skipped.
#   - target 'pending'  : revert anything above 'pending'.
#   - target 'parsed'   : revert only the top tier; NOT 'parse_failed' (lateral,
#                         and it has no valid `structures` to extract from).
_RESETTABLE_FROM = {
    "pending": ("parse_failed", "parsed", "extract_failed", "done"),
    "parsed": ("extract_failed", "done"),
}

# The pipeline only ever reprocesses these source types.
_REPROCESSABLE_SOURCE_TYPES = ("local_har", "local_wacz")


def reset_incorporation_status(
    target_status: str,
    id_min: Optional[int] = None,
    id_max: Optional[int] = None,
    archiving_from: Optional[str] = None,
    archiving_to: Optional[str] = None,
    dry_run: bool = True,
) -> int:
    """Revert the incorporation_status of in-range archive sessions to `target_status`.

    Only sessions whose current status is strictly above the target (per the
    revert-only rule in `_RESETTABLE_FROM`) and whose source_type is reprocessable
    are affected; all others are silently skipped.

    Range bounds (`id_min`/`id_max` on `id`, `archiving_from`/`archiving_to` on
    `archiving_timestamp`) are each optional and combine with AND, so the range may
    be open on either end or bounded on both.

    When `dry_run` is True, returns the count of sessions that *would* change without
    mutating. Otherwise performs the UPDATE (also clearing `extraction_error`, mirroring
    the requeue/upload paths) and returns the number of rows changed.
    """
    allowed_from = _RESETTABLE_FROM.get(target_status)
    if allowed_from is None:
        raise ValueError(f"Unsupported reset target_status: {target_status!r}")

    # mysql-connector does not expand a list into an IN clause, so build named
    # placeholders explicitly (the convention used elsewhere in the loaders).
    params: dict = {}
    src_ph = []
    for i, st in enumerate(_REPROCESSABLE_SOURCE_TYPES):
        key = f"src{i}"
        src_ph.append(f"%({key})s")
        params[key] = st
    from_ph = []
    for i, st in enumerate(allowed_from):
        key = f"from{i}"
        from_ph.append(f"%({key})s")
        params[key] = st

    where = [
        f"source_type IN ({', '.join(src_ph)})",
        f"incorporation_status IN ({', '.join(from_ph)})",
    ]
    if id_min is not None:
        where.append("id >= %(id_min)s")
        params["id_min"] = id_min
    if id_max is not None:
        where.append("id <= %(id_max)s")
        params["id_max"] = id_max
    if archiving_from:
        where.append("archiving_timestamp >= %(archiving_from)s")
        params["archiving_from"] = archiving_from
    if archiving_to:
        where.append("archiving_timestamp <= %(archiving_to)s")
        params["archiving_to"] = archiving_to

    where_sql = " AND ".join(where)

    if dry_run:
        row = db.execute_query(
            f"SELECT COUNT(*) AS n FROM archive_session WHERE {where_sql}",
            params,
            return_type="single_row",
        )
        return int(row["n"]) if row else 0

    params["target"] = target_status
    return db.execute_query(
        f"UPDATE archive_session SET incorporation_status = %(target)s, extraction_error = NULL "
        f"WHERE {where_sql}",
        params,
        return_type="rowcount",
    )
