"""
Auto-Archiver (AA) Archive Loader
==================================
Loads data captured by the Bellingcat Auto-Archiver tool into the browsing platform
database.  Mirrors the architecture of db_loaders/archives_db_loader.py but operates
on AA HTML summaries downloaded from a CDN rather than local HAR/WACZ files.

Source: db_loaders/aa_archive_loading/aa_sheets_src/source_data.xlsx
  - Each row represents one archived URL (Instagram post, reel, etc.)
  - The Archive_location column holds the CDN URL of the HTML summary page

Pipeline stages
---------------
  A  register   Read the xlsx and create pending archive_session records
  B  parse      Download each HTML summary via Playwright, then parse it with BS4
  C  extract    Convert parsed structures to entities and insert into DB
     (thumbnails are set to not_needed — media is served directly from the CDN URL)

USAGE:
  uv run db_loaders/aa/aa_archive_loader.py register
  uv run db_loaders/aa/aa_archive_loader.py parse
  uv run db_loaders/aa/aa_archive_loader.py extract
  uv run db_loaders/aa/aa_archive_loader.py full
  uv run db_loaders/aa/aa_archive_loader.py full --limit N
  uv run db_loaders/aa/aa_archive_loader.py clear_errors
"""

import asyncio
import json
import logging
import os
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import openpyxl
from dateutil import parser as dateutil_parser

import root_anchor
from db_loaders.aa.aa_entity_extractor import _extract_url_suffix, extract_entities
from db_loaders.aa.aa_html_parser import ParsedHTMLSummary, parse_html_summary
from db_loaders.db_intake import incorporate_structures_into_db
from utils import db

logger = logging.getLogger(__name__)

XLSX_PATH = Path(root_anchor.ROOT_DIR) / "db_loaders" / "aa_archive_loading" / "aa_sheets_src" / "source_data.xlsx"
AA_PARSING_ALGORITHM_VERSION = 1
AA_ENTITY_EXTRACTION_ALGORITHM_VERSION = 1
_PLAYWRIGHT_TIMEOUT_MS = 60_000
_REGISTER_INSERT_BATCH = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_xlsx_rows(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["CombinedSheet"]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


# ---------------------------------------------------------------------------
# Stage A: register
# ---------------------------------------------------------------------------

def register_aa_archives(limit: Optional[int] = None) -> None:
    """
    Part A — reads the source xlsx and inserts a pending archive_session record for
    each Instagram row that has not already been registered.
    """
    start = time.time()
    logger.info(f"Part A — loading {XLSX_PATH}")
    rows = _load_xlsx_rows(XLSX_PATH)
    logger.info(f"Part A — {len(rows)} rows in xlsx")

    # Batch-fetch all already-registered AA external_ids.
    # Keyset pagination by id: an OFFSET scan with no ORDER BY has no stable
    # cross-page ordering in MySQL, so above one page it could drop already-
    # registered external_ids and re-insert duplicates. Paging on the PK is stable.
    registered: set[str] = set()
    last_id = 0
    batch = 5_000
    while True:
        existing = db.execute_query(
            "SELECT id, external_id FROM archive_session "
            "WHERE source_type = 'AA_xlsx' AND id > %(last_id)s "
            "ORDER BY id LIMIT %(limit)s",
            {"limit": batch, "last_id": last_id},
            return_type="rows",
        ) or []
        for r in existing:
            registered.add(r["external_id"])
        if len(existing) < batch:
            break
        last_id = existing[-1]["id"]
    logger.info(f"Part A — {len(registered)} AA sessions already registered")

    skipped_no_id = 0
    skipped_not_instagram = 0
    skipped_no_archive_location = 0
    to_insert: list[dict] = []

    for xlsx_row in rows:
        if limit is not None and len(to_insert) >= limit:
            break

        entry_number = xlsx_row.get("Entry_Number")
        if not entry_number:
            skipped_no_id += 1
            continue

        link = xlsx_row.get("Link") or ""
        if "instagram.com" not in link:
            skipped_not_instagram += 1
            continue

        archive_location = xlsx_row.get("Archive_location") or ""
        if not archive_location:
            skipped_no_archive_location += 1
            logger.debug(f"Skipping entry {entry_number}: no Archive_location")
            continue

        external_id = f"aa-{entry_number}"
        if external_id in registered:
            continue

        archived_url_suffix = _extract_url_suffix(link)
        to_insert.append({
            "external_id": external_id,
            "archived_url_suffix": archived_url_suffix,
            "archive_location": archive_location,
            "notes": xlsx_row.get("NOTES") or None,
        })
        registered.add(external_id)

    # ON DUPLICATE KEY UPDATE id=id is a defensive no-op: external_id is UNIQUE
    # (V036), so a racing/duplicate registration resolves to the existing row
    # instead of raising and aborting the batch.
    insert_sql = """INSERT INTO archive_session
                       (external_id, archived_url_suffix, archive_location, notes,
                        source_type, platform, incorporation_status)
                   VALUES (%(external_id)s, %(archived_url_suffix)s, %(archive_location)s,
                           %(notes)s, 'AA_xlsx', 'instagram', 'pending')
                   ON DUPLICATE KEY UPDATE id = id"""
    # return_type="id" is the new auto-increment id on a real INSERT, or False
    # when the row already existed and the statement no-opped (ON DUPLICATE KEY
    # UPDATE id=id). Count only true inserts so a suppressed duplicate isn't
    # reported as registered.
    inserted = 0
    for batch_start in range(0, len(to_insert), _REGISTER_INSERT_BATCH):
        batch = to_insert[batch_start:batch_start + _REGISTER_INSERT_BATCH]
        with db.transaction_batch():
            for params in batch:
                new_id = db.execute_query(insert_sql, params, return_type="id")
                if new_id:
                    logger.info(f"Registered {params['external_id']} ({params['archived_url_suffix']})")
                    inserted += 1
                else:
                    logger.debug(f"AA session already registered (race), skipped: {params['external_id']}")
    elapsed = time.time() - start
    logger.info(
        f"Part A complete in {elapsed:.1f}s — inserted {inserted}, "
        f"skipped: {skipped_no_id} no-id, {skipped_not_instagram} non-instagram, "
        f"{skipped_no_archive_location} no-archive-location"
    )


# ---------------------------------------------------------------------------
# Stage B: parse (download + HTML parse)
# ---------------------------------------------------------------------------

async def _download_htmls_async(sessions: list[dict]) -> dict[int, "str | Exception"]:
    """Download HTML summaries for multiple sessions, reusing a single Playwright browser."""
    from playwright.async_api import async_playwright
    results: dict[int, "str | Exception"] = {}
    async with async_playwright() as pw:
        browser = await pw.firefox.launch(headless=True)
        try:
            for s in sessions:
                try:
                    page = await browser.new_page()
                    page.set_default_timeout(_PLAYWRIGHT_TIMEOUT_MS)
                    await page.goto(s["archive_location"], wait_until="networkidle")
                    results[s["id"]] = await page.content()
                    await page.close()
                except Exception as e:
                    results[s["id"]] = e
        finally:
            await browser.close()
    return results


def parse_aa_archives(limit: Optional[int] = None) -> None:
    """
    Part B — for each pending AA session:
      B1. Download the HTML summary via Playwright (single browser, batched).
      B2. Parse the stored HTML into structures + metadata JSON.
    """
    start = time.time()
    # Fetch queue without summary_html to avoid loading large text blobs into memory.
    # Use a flag to identify sessions that already have stored HTML.
    queue = db.execute_query(
        "SELECT id, external_id, archived_url_suffix, archive_location, "
        "       (summary_html IS NOT NULL) AS has_html "
        "FROM archive_session "
        "WHERE incorporation_status = 'pending' AND source_type = 'AA_xlsx'",
        {},
        return_type="rows",
    ) or []
    if limit is not None:
        queue = queue[:limit]
    logger.info(f"Part B — {len(queue)} sessions to parse")

    parsed_count = 0
    error_count = 0
    failed_ids: set[int] = set()

    # B1: batch-download HTML for sessions that don't have it yet (one browser session)
    needs_download = [e for e in queue if not e["has_html"]]
    if needs_download:
        logger.info(f"B1 downloading HTML for {len(needs_download)} sessions")
        download_results = asyncio.run(_download_htmls_async(needs_download))
        for entry in needs_download:
            sid = entry["id"]
            entry_id = entry["external_id"] or sid
            result = download_results.get(sid)
            if isinstance(result, Exception):
                logger.error(f"Download error for {entry_id}: {result}")
                db.execute_query(
                    "UPDATE archive_session SET incorporation_status = 'parse_failed', "
                    "extraction_error = %(err)s WHERE id = %(id)s",
                    {"id": sid, "err": str(result)[:499]},
                    return_type="none",
                )
                failed_ids.add(sid)
                error_count += 1
            else:
                db.execute_query(
                    "UPDATE archive_session SET summary_html = %(html)s WHERE id = %(id)s",
                    {"html": result, "id": sid},
                    return_type="none",
                )
                logger.debug(f"B1 stored summary_html for {entry_id} ({len(result)} chars)")

    # B2: parse each session — fetch summary_html per-entry so it's GC'd after use
    for entry in queue:
        session_id = entry["id"]
        if session_id in failed_ids:
            continue
        entry_id = entry["external_id"] or session_id
        try:
            logger.info(f"B2 parsing HTML for {entry_id}")
            row = db.execute_query(
                "SELECT summary_html FROM archive_session WHERE id = %(id)s",
                {"id": session_id},
                return_type="single_row",
            )
            html = row["summary_html"] if row else None
            if not html:
                raise ValueError("summary_html is empty after download step")

            parsed = parse_html_summary(html)

            archiving_timestamp = None
            ts_raw = parsed.metadata.get("_processed_at")
            if ts_raw:
                try:
                    archiving_timestamp = dateutil_parser.isoparse(str(ts_raw)).strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OverflowError):
                    pass

            db.execute_query(
                """UPDATE archive_session
                   SET structures = %(structures)s,
                       metadata = %(metadata)s,
                       archiving_timestamp = %(archiving_timestamp)s,
                       incorporation_status = 'parsed',
                       parse_algorithm_version = %(version)s,
                       extraction_error = NULL
                   WHERE id = %(id)s""",
                {
                    "id": session_id,
                    "structures": json.dumps(parsed.structures, ensure_ascii=False),
                    "metadata": json.dumps(parsed.metadata, ensure_ascii=False),
                    "archiving_timestamp": archiving_timestamp,
                    "version": AA_PARSING_ALGORITHM_VERSION,
                },
                return_type="none",
            )
            logger.info(f"Parsed {entry_id}: {len(parsed.structures)} structures")
            parsed_count += 1

        except Exception as e:
            logger.error(f"Parse error for {entry_id}: {e}")
            db.execute_query(
                """UPDATE archive_session
                   SET incorporation_status = 'parse_failed',
                       extraction_error = %(err)s
                   WHERE id = %(id)s""",
                {"id": session_id, "err": str(e)[:499]},
                return_type="none",
            )
            traceback.print_exc()
            error_count += 1

    elapsed = time.time() - start
    logger.info(f"Part B complete in {elapsed:.1f}s — {parsed_count} parsed, {error_count} errors")


# ---------------------------------------------------------------------------
# Stage C: extract entities
# ---------------------------------------------------------------------------

def extract_aa_entities(limit: Optional[int] = None) -> None:
    """
    Part C — for each parsed AA session, extract Account / Post / Media entities
    and incorporate them into the canonical DB tables.

    After insertion, media thumbnail_status is set to 'not_needed' because local_url
    contains a CDN URL — the thumbnail generator cannot process it, and the UI falls
    back to local_url directly when no thumbnail path is present.
    """
    start = time.time()

    # Fetch lightweight queue first; load full row (including large structures JSON) per entry
    queue = db.execute_query(
        "SELECT id, external_id FROM archive_session "
        "WHERE incorporation_status = 'parsed' AND source_type = 'AA_xlsx'",
        {},
        return_type="rows",
    ) or []
    if limit is not None:
        queue = queue[:limit]
    logger.info(f"Part C — {len(queue)} sessions to extract")

    extracted_count = 0
    error_count = 0

    for stub in queue:
        entry = db.execute_query(
            "SELECT id, external_id, archived_url_suffix, archive_location, structures, metadata, notes "
            "FROM archive_session WHERE id = %(id)s",
            {"id": stub["id"]},
            return_type="single_row",
        )
        if entry is None:
            continue

        entry_id = entry["external_id"] or entry["id"]
        session_id = entry["id"]
        entry_start = time.time()
        try:
            logger.info(f"Extracting entities for {entry_id}")

            structures_raw = entry.get("structures")
            metadata_raw = entry.get("metadata")
            if not structures_raw or not metadata_raw:
                raise ValueError("structures or metadata column is empty — re-run parse stage")

            parsed = ParsedHTMLSummary(
                structures=json.loads(structures_raw),
                metadata=json.loads(metadata_raw),
            )

            archived_url_suffix = entry.get("archived_url_suffix") or ""
            notes = entry.get("notes")

            # Derive the CDN base URL (scheme + host) from the HTML summary's location.
            # Used to expand bare storage-key paths (e.g. "pal8472/file.mp4") into full URLs.
            cdn_base: Optional[str] = None
            archive_location = entry.get("archive_location")
            if archive_location:
                loc = urlparse(archive_location)
                cdn_base = f"{loc.scheme}://{loc.netloc}/"

            entities = extract_entities(archived_url_suffix, parsed, notes, cdn_base=cdn_base)
            if entities is None:
                raise ValueError(
                    f"extract_entities returned None for {entry_id} — "
                    "could not extract minimum required data (account + post)"
                )

            logger.debug(
                f"Extracted: {len(entities.accounts)} accounts, "
                f"{len(entities.posts)} posts, {len(entities.media)} media"
            )

            incorporate_structures_into_db(entities, session_id, archive_location=None)

            # CDN-URL media cannot be thumbnailed locally — mark as not_needed.
            # The conditions guard against accidentally resetting 'generated' status on media
            # that was already thumbnailed from a HAR/WACZ archive of the same post.
            db.execute_query(
                """UPDATE media
                   SET thumbnail_status = 'not_needed'
                   WHERE local_url LIKE 'https://%'
                     AND thumbnail_status = 'pending'
                     AND id IN (
                         SELECT canonical_id FROM media_archive WHERE archive_session_id = %(id)s
                     )""",
                {"id": session_id},
                return_type="none",
            )

            db.execute_query(
                """UPDATE archive_session
                   SET incorporation_status = 'done',
                       extract_algorithm_version = %(version)s,
                       extraction_error = NULL
                   WHERE id = %(id)s""",
                {"id": session_id, "version": AA_ENTITY_EXTRACTION_ALGORITHM_VERSION},
                return_type="none",
            )
            elapsed_entry = time.time() - entry_start
            logger.info(f"Extracted {entry_id} in {elapsed_entry:.1f}s")
            extracted_count += 1

        except Exception as e:
            logger.error(f"Extract error for {entry_id}: {e}")
            db.execute_query(
                """UPDATE archive_session
                   SET incorporation_status = 'extract_failed',
                       extraction_error = %(err)s
                   WHERE id = %(id)s""",
                {"id": session_id, "err": str(e)[:499]},
                return_type="none",
            )
            traceback.print_exc()
            error_count += 1

    elapsed = time.time() - start
    logger.info(f"Part C complete in {elapsed:.1f}s — {extracted_count} extracted, {error_count} errors")


# ---------------------------------------------------------------------------
# clear_errors
# ---------------------------------------------------------------------------

def clear_aa_errors() -> None:
    """Reset extract_failed AA sessions back to 'parsed' so they will be retried."""
    db.execute_query(
        """UPDATE archive_session
           SET incorporation_status = 'parsed', extraction_error = NULL
           WHERE source_type = 'AA_xlsx' AND incorporation_status = 'extract_failed'""",
        {},
        return_type="none",
    )
    logger.info("Cleared extract_failed AA sessions (reset to 'parsed')")


def clear_aa_parse_errors() -> None:
    """Reset parse_failed AA sessions back to 'pending' so they will be retried."""
    db.execute_query(
        """UPDATE archive_session
           SET incorporation_status = 'pending', extraction_error = NULL
           WHERE source_type = 'AA_xlsx' AND incorporation_status = 'parse_failed'""",
        {},
        return_type="none",
    )
    logger.info("Cleared parse_failed AA sessions (reset to 'pending')")


def reset_aa_done_for_reextract() -> None:
    """Reset 'done' AA sessions back to 'parsed' so Stage C re-runs and refreshes entity data."""
    db.execute_query(
        """UPDATE archive_session
           SET incorporation_status = 'parsed', extraction_error = NULL
           WHERE source_type = 'AA_xlsx' AND incorporation_status = 'done'""",
        {},
        return_type="none",
    )
    logger.info("Reset done AA sessions to 'parsed' for re-extraction")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logs_dir = os.path.join(root_anchor.ROOT_DIR, "logs_db_loader")
    os.makedirs(logs_dir, exist_ok=True)

    log_format = "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    debug_file_handler = RotatingFileHandler(
        os.path.join(logs_dir, "1debug_aa_loader.log"), maxBytes=10_000_000, backupCount=5
    )
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(formatter)

    error_file_handler = RotatingFileHandler(
        os.path.join(logs_dir, "5error_aa_loader.log"), maxBytes=10_000_000, backupCount=5
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)

    logging.basicConfig(level=logging.DEBUG, format=log_format,
                        handlers=[console_handler, debug_file_handler, error_file_handler])

    valid_stages = ["register", "parse", "extract", "full", "clear_errors", "clear_parse_errors", "reset_done"]

    stage = input(f"Enter stage ({', '.join(valid_stages)}): ").strip().lower()
    if stage not in valid_stages:
        print(f"Unknown stage: {stage!r}")
        sys.exit(1)

    limit: Optional[int] = None
    if stage in ("register", "parse", "extract", "full"):
        raw = input("Limit (number of items to process, leave empty or 0 for all): ").strip()
        if raw and raw != "0":
            try:
                limit = int(raw)
            except ValueError:
                print(f"Invalid limit {raw!r}, processing all items")

    if stage == "register":
        register_aa_archives(limit=limit)
    elif stage == "parse":
        parse_aa_archives(limit=limit)
    elif stage == "extract":
        extract_aa_entities(limit=limit)
    elif stage == "full":
        full_start = time.time()
        register_aa_archives(limit=limit)
        parse_aa_archives(limit=limit)
        extract_aa_entities(limit=limit)
        logger.info(f"Full pipeline complete in {time.time() - full_start:.1f}s")
    elif stage == "clear_errors":
        clear_aa_errors()
    elif stage == "clear_parse_errors":
        clear_aa_parse_errors()
    elif stage == "reset_done":
        reset_aa_done_for_reextract()
