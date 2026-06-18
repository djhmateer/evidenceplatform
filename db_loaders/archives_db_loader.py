"""
Archive Database Loader - Evidence Platform
============================================

PURPOSE:
    Processes social media archives (HAR files) and loads their content into the database.
    Handles registration, parsing, entity extraction, and thumbnail generation in a
    fault-tolerant, resumable pipeline.

HOW IT WORKS:
    The loader operates in 4 sequential stages (A → B → C → D):

    A) REGISTER - Scan archives directory and create database records
       - Scans the 'archives/' folder for new archive directories
       - Creates an archive_session record for each unregistered archive
       - Archives are identified by directory name (e.g., eran_20250530_160037)
       - Safe to run multiple times - only registers new archives

    B) PARSE - Extract structures from HAR files
       - Reads metadata.json for URL and timestamp
       - Parses archive.har files to extract social media structures
       - Identifies accounts, posts, photos, videos without downloading media
       - Saves parsed structures as JSON in the database
       - Records any errors in extraction_error field

    C) EXTRACT - Convert structures to normalized database entities
       - Deserializes parsed structures from Part B
       - Converts HAR data to normalized account/post/media entities
       - Inserts/updates entities in database tables
       - Links entities to their source archive_session
       - Tracks extraction with algorithm version numbers

    D) THUMBNAILS - Generate preview images for media
       - Creates thumbnails for images and video first frames
       - Only generates for media with missing thumbnail_path
       - Stores thumbnails in thumbnails/ directory
       - Uses MD5 hash-based filenames for deduplication

USAGE:
    Run with a stage argument:
        uv run db_loaders/archives_db_loader.py <stage>
        uv run db_loaders/archives_db_loader.py <stage> --limit N

    Options:
        --limit N         Process only N new archives (useful for testing)
        --archives-dir    Override the archives directory path

    Available stages:

    • full           - Run all 4 parts (A → B → C → D) sequentially
                      Use this for normal operation

    • register       - Run only Part A (scan and register new archives)

    • parse          - Run only Part B (parse HAR files for already-registered archives)

    • extract        - Run only Part C (extract entities from already-parsed archives)

    • add_attachments - Backfill session attachments (screenshots, recordings) for archives

    • add_metadata   - Backfill archiving timestamps and URLs for archives

    • clear_errors   - Clear extraction_error field to retry failed archives
                      Use this after fixing issues that caused failures

REGENERATING THUMBNAILS:
    To regenerate ALL thumbnails (e.g., to change size or fix corrupted images):

    1. Clear existing thumbnail paths in database:
       UPDATE media SET thumbnail_path = NULL WHERE thumbnail_path IS NOT NULL;

    2. Run the full pipeline or just Part D:
       uv run db_loaders/archives_db_loader.py full
       # or just:
       python3 -c "import asyncio; from db_loaders.thumbnail_generator import generate_missing_thumbnails; asyncio.run(generate_missing_thumbnails())"

    Note: Thumbnails are generated only for media where thumbnail_path IS NULL

FAULT TOLERANCE:
    - All stages are designed to be idempotent and resumable
    - Errors are recorded in archive_session.extraction_error
    - Failed archives are automatically skipped on subsequent runs
    - Use 'clear_errors' stage to retry after fixing issues
    - Algorithm versions track parsing/extraction changes

LOGGING:
    Logs are written to logs_db_loader/ directory:
    - 1debug_db_loader.log - All messages (DEBUG and above)
    - 5error_db_loader.log - Errors only
    - Console output shows progress

PERFORMANCE:
    - Part B (parsing): ~1-5 seconds per archive
    - Part C (extraction): ~2-10 seconds per archive
    - Part D (thumbnails): ~0.5-2 seconds per media item
    - Large batches: Run 'full' and let it process overnight
    - Interrupted runs: Simply restart - will continue where it left off

EXAMPLE WORKFLOWS:

    # Initial load of all archives
    uv run db_loaders/archives_db_loader.py full

    # Process only 1 new archive (useful for testing)
    uv run db_loaders/archives_db_loader.py full --limit 1

    # After adding new archives to the archives/ folder
    uv run db_loaders/archives_db_loader.py full

    # Retry failed archives after fixing issues
    uv run db_loaders/archives_db_loader.py clear_errors
    uv run db_loaders/archives_db_loader.py full

    # Process only newly added archives (skip already-processed)
    uv run db_loaders/archives_db_loader.py register
    uv run db_loaders/archives_db_loader.py parse
    uv run db_loaders/archives_db_loader.py extract
"""

import asyncio
import json
import logging
import sys
import os
import time
import traceback
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional

from dateutil import parser
from pytz import timezone as pytz_timezone
from tzlocal import get_localzone_name

import root_anchor
from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS, LOCAL_WACZ_ARCHIVES_DIR_ALIAS
from db_loaders.db_intake import incorporate_structures_into_db
from db_loaders.thumbnail_generator import generate_missing_thumbnails
from extractors.extract_photos import PhotoAcquisitionConfig
from extractors.extract_videos import VideoAcquisitionConfig
from extractors.session_attachments import get_session_attachments
from extractors.structures_from_wacz import scan_wacz
from extractors.structures_to_entities import extract_data_from_har, ExtractedHarData, har_data_to_entities
from extractors.wacz_metadata import extract_wacz_metadata
from utils import db

logger = logging.getLogger(__name__)


_REGISTER_FETCH_BATCH = 5_000   # rows per page when loading existing registrations
_REGISTER_INSERT_BATCH = 500    # archives per transaction when inserting new ones


def register_archives(limit: Optional[int] = None, cancel_check: Optional[Callable[[], bool]] = None, emit: Optional[Callable[[str], None]] = None):
    """
    Part A of full - scans directory, puts in an archive_session record for each
    unregistered archive.

    Optimised: fetches all already-registered external_ids in paginated batches,
    builds a set, then bulk-inserts only the new ones (also in batches).
    This avoids the previous N+1 per-archive lookup pattern.
    """
    start_time = time.time()

    # --- Step 1: collect archive directories from disk ---
    archive_dirs = [d for d in root_anchor.ROOT_ARCHIVES.iterdir() if d.is_dir()]
    logger.info(f"Part A - Found {len(archive_dirs)} archive directories in {root_anchor.ROOT_ARCHIVES}")

    # --- Step 2: fetch all already-registered external_ids in paginated batches ---
    # Keyset pagination by id (not LIMIT/OFFSET). An OFFSET scan with no ORDER BY
    # has no stable cross-page ordering in MySQL, so once the row count passes
    # _REGISTER_FETCH_BATCH pages could overlap/skip and drop already-registered
    # external_ids from this set — causing the archive to be re-registered under a
    # NEW id and silently duplicated. Keyset paging on the PK is stable and gap-free.
    registered: set[str] = set()
    last_id = 0
    while True:
        rows = db.execute_query(
            "SELECT id, external_id FROM archive_session "
            "WHERE source_type IN ('local_har', 'local_wacz') AND id > %(last_id)s "
            "ORDER BY id LIMIT %(limit)s",
            {"limit": _REGISTER_FETCH_BATCH, "last_id": last_id},
            return_type="rows",
        )
        if not rows:
            break
        for row in rows:
            registered.add(row["external_id"])
        last_id = rows[-1]["id"]
        if len(rows) < _REGISTER_FETCH_BATCH:
            break

    logger.info(f"Part A - {len(registered)} archives already registered in DB")

    # --- Step 3: determine which directories are new ---
    # Each entry is (archive_dir, external_id, source_type, location_alias).
    # HAR takes precedence if a directory contains both archive types.
    to_register: list[tuple] = []
    for d in archive_dirs:
        if (d / "archive.har").exists():
            ext_id = f"har-{d.name}"
            if ext_id not in registered:
                to_register.append((d, ext_id, "local_har", LOCAL_ARCHIVES_DIR_ALIAS))
        elif (d / "archive.wacz").exists():
            ext_id = f"wacz-{d.name}"
            if ext_id not in registered:
                to_register.append((d, ext_id, "local_wacz", LOCAL_WACZ_ARCHIVES_DIR_ALIAS))

    if limit is not None:
        to_register = to_register[:limit]
    logger.info(f"Part A - {len(to_register)} new archives to register")

    # --- Step 4: insert new archives in batches inside a single transaction ---
    registered_count = 0
    for batch_start in range(0, len(to_register), _REGISTER_INSERT_BATCH):
        batch = to_register[batch_start: batch_start + _REGISTER_INSERT_BATCH]
        with db.transaction_batch():
            for archive_dir, ext_id, source_type, location_alias in batch:
                if cancel_check and cancel_check():
                    raise InterruptedError("Cancelled by user")
                # ON DUPLICATE KEY UPDATE id=id is a defensive no-op: external_id
                # is UNIQUE (V036), so a concurrent/racing registration can't crash
                # the batch or insert a second row — it quietly resolves to the
                # existing row instead of raising.
                # return_type="id" yields the new auto-increment id on a real
                # INSERT, or False when the row already existed and the statement
                # no-opped (ON DUPLICATE KEY UPDATE id=id). Only count/log a true
                # insert so a suppressed race-duplicate isn't reported as "registered".
                new_id = db.execute_query(
                    """INSERT INTO archive_session
                           (external_id, archive_location, source_type)
                       VALUES (%(external_id)s, %(archive_location)s, %(source_type)s)
                       ON DUPLICATE KEY UPDATE id = id""",
                    {
                        "external_id": ext_id,
                        "archive_location": f"{location_alias}/{archive_dir.name}",
                        "source_type": source_type,
                    },
                    return_type="id",
                )
                if new_id:
                    logger.info(f"Registered new archive: {archive_dir.name} ({source_type})")
                    if emit:
                        emit(f"Part A — registered {archive_dir.name}")
                    registered_count += 1
                else:
                    logger.debug(f"Archive already registered (race), skipped insert: {archive_dir.name}")

    elapsed = time.time() - start_time
    logger.info(f"Part A register_archives complete in {elapsed:.1f}s (registered {registered_count} new archives)")


# ---------------------------------------------------------------------------
# Algorithm version numbers
# ---------------------------------------------------------------------------
# Increment the relevant constant any time the corresponding algorithm changes
# in a way that would produce different output for the same input archive.
# The stored version on each archive_session row lets an admin queue stale
# rows for re-processing with a targeted UPDATE, e.g.:
#
#   -- Re-queue all sessions parsed by an outdated version:
#   UPDATE archive_session
#   SET    incorporation_status = 'pending'
#   WHERE  source_type = 'local_har'
#     AND  parse_algorithm_version < <new_version>
#     AND  incorporation_status NOT IN ('parse_failed');
#
#   -- Re-queue all sessions extracted by an outdated version:
#   UPDATE archive_session
#   SET    incorporation_status = 'parsed'
#   WHERE  source_type = 'local_har'
#     AND  extract_algorithm_version < <new_version>
#     AND  incorporation_status NOT IN ('extract_failed');
#
# Changelog
# ---------
# PARSING_ALGORITHM_VERSION
#   1 — initial HAR parsing logic
#
# ENTITY_EXTRACTION_ALGORITHM_VERSION
#   1 — initial extraction (db_intake.py v1)
#   2 — db_intake refactor: split get_entity into get_canonical/get_archive_record;
#       re-synthesis from all archives on re-processing; url reconciliation added
#       to reconcile_posts and reconcile_media; archive record lookup now uses
#       canonical_id instead of url/id_on_platform match
#   3 — new entity types: comment (with parent_comment_id_on_platform), post_like,
#       tagged_account (with tag_x/y_position), account_relation (replaces Follower
#       + SuggestedAccount); dropped post_engagement tables
# ---------------------------------------------------------------------------

PARSING_ALGORITHM_VERSION = 1
ENTITY_EXTRACTION_ALGORITHM_VERSION = 3


def strip_media_contents(data: ExtractedHarData) -> None:
    for v in data.videos:
        if v and v.fetched_tracks:
            for t in v.fetched_tracks:
                v.fetched_tracks[t].segments = []
    for p in data.photos:
        if p:
            p.fetched_assets = None


def parse_archives(limit: Optional[int] = None, cancel_check: Optional[Callable[[], bool]] = None, emit: Optional[Callable[[str], None]] = None):
    """
    Part B of full — queries archive_session where incorporation_status = 'pending'
    for both HAR (local_har) and WACZ (local_wacz) source types.

    HAR path:  reads metadata.json + archive.har
    WACZ path: reads archive.wacz, extracts metadata with extract_wacz_metadata(),
               writes metadata.json to the archive directory, then calls scan_wacz().

    Both paths converge on the same DB UPDATE (structures, metadata, archived_url, etc.).
    """
    start_time = time.time()
    logger.info(f"Part B - Starting archive parsing{f' (limit: {limit})' if limit else ''}")
    parsed_count = 0
    error_count = 0

    # Fetch the full list of unprocessed archives upfront (one query, small columns only).
    # This avoids running a repeated filter scan for every single archive.
    queue = db.execute_query(
        "SELECT id, external_id, archive_location, source_type FROM archive_session "
        "WHERE incorporation_status = 'pending' AND source_type IN ('local_har', 'local_wacz')",
        {},
        return_type="rows",
    ) or []
    if limit is not None:
        queue = queue[:limit]
    logger.info(f"Part B - {len(queue)} archives to parse")

    for entry in queue:
        if cancel_check and cancel_check():
            raise InterruptedError("Cancelled by user")
        try:
            # Reconstruct the archive directory; path alias differs by source type.
            source_type = entry.get('source_type', 'local_har')
            if source_type == 'local_wacz':
                archive_name = entry['archive_location'].split(f"{LOCAL_WACZ_ARCHIVES_DIR_ALIAS}/")[1]
            else:
                archive_name = entry['archive_location'].split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[1]

            entry_id = entry['external_id'] or entry['id']
            logger.info(f"Parsing archive: {entry_id} ({source_type})")
            if emit:
                emit(f"Part B — parsing {entry_id}")

            archive_dir = root_anchor.ROOT_ARCHIVES / archive_name

            iso_timestamp = None
            archived_url = None
            notes = None
            metadata = {}

            if source_type == 'local_wacz':
                # ---------------------------------------------------------- #
                # WACZ path: extract metadata from archive.wacz, write to
                # metadata.json, then scan the WARC records for structures.
                # ---------------------------------------------------------- #
                wacz_path = archive_dir / "archive.wacz"
                if not wacz_path.exists():
                    raise Exception(f"WACZ file {wacz_path} does not exist")

                # --- Step 1: Extract and persist metadata ---
                logger.debug(f"Extracting WACZ metadata for {entry_id}")
                try:
                    metadata = extract_wacz_metadata(wacz_path)
                    metadata_path = archive_dir / "metadata.json"
                    metadata_path.write_text(
                        json.dumps(metadata, ensure_ascii=False, default=str, indent=2),
                        encoding="utf-8",
                    )
                    logger.debug(f"Wrote metadata.json for {entry_id}")
                except Exception as e:
                    traceback.print_exc()
                    raise Exception(f"Error extracting WACZ metadata for {entry_id}: {e}")

                archived_url = metadata.get("primary_url")
                notes = metadata.get("title")

                # WACZ timestamps are always UTC ISO 8601 with Z suffix
                created_ts = metadata.get("created")
                if created_ts:
                    try:
                        dt = parser.isoparse(created_ts)
                        iso_timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        logger.warning(f"Could not parse WACZ created timestamp for {entry_id}")
                logger.debug(f"WACZ metadata: url={archived_url}, ts={iso_timestamp}")

                # --- Step 2: Scan WACZ WARC records ---
                logger.debug(f"Scanning WACZ records for {entry_id}")
                try:
                    structures, videos, photos = scan_wacz(wacz_path, archive_dir)
                    extracted_data = ExtractedHarData(
                        structures=structures, videos=videos, photos=photos
                    )
                    strip_media_contents(extracted_data)
                    logger.debug(
                        f"WACZ scan: {len(structures)} structures, "
                        f"{len(videos)} videos, {len(photos)} photos"
                    )
                except Exception as e:
                    traceback.print_exc()
                    raise Exception(f"Error scanning WACZ file {wacz_path}: {e}")

            else:
                # ---------------------------------------------------------- #
                # HAR path (existing logic, unchanged)
                # ---------------------------------------------------------- #

                # --- Step 1: Read metadata.json ---
                logger.debug(f"Extracting metadata...")
                metadata_path = archive_dir / "metadata.json"
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        metadata = json.loads(f.read())
                    archived_url = metadata.get("target_url", None) if isinstance(metadata, dict) else None
                    notes = metadata.get("notes", None) if isinstance(metadata, dict) else None
                    timestamp = metadata.get("archiving_start_timestamp", None) if isinstance(metadata, dict) else None

                    # Convert timestamp to UTC if present
                    timezone = get_localzone_name()
                    if timestamp is not None:
                        dt = parser.isoparse(timestamp)
                        if dt.tzinfo is None:
                            try:
                                tz = pytz_timezone(timezone)
                                dt = tz.localize(dt)
                                iso_timestamp = dt.astimezone(pytz_timezone("UTC")).strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                logger.warning(f"Could not parse timezone for {entry_id}")
                    logger.debug(f"Loaded metadata for {entry_id}: url={archived_url}")
                except Exception:
                    raise Exception(f"Metadata file {metadata_path} is not valid JSON or does not exist")
                logger.debug(f"Metadata for {entry_id} extracted: {metadata}")

                # --- Step 2: Parse the HAR file ---
                logger.debug(f"Parsing HAR for {entry_id}")
                har_path = archive_dir / "archive.har"
                if not har_path.exists():
                    raise Exception(f"HAR file {har_path} does not exist")
                try:
                    logger.debug(f"Extracting data from HAR file: {har_path}")
                    extracted_data = extract_data_from_har(
                        har_path,
                        VideoAcquisitionConfig(
                            download_missing=False,
                            download_media_not_in_structures=False,
                            download_unfetched_media=False,
                            download_full_versions_of_fetched_media=False,
                            download_highest_quality_assets_from_structures=False
                        ),
                        PhotoAcquisitionConfig(
                            download_missing=False,
                            download_media_not_in_structures=False,
                            download_unfetched_media=False,
                            download_highest_quality_assets_from_structures=False
                        )
                    )
                    strip_media_contents(extracted_data)
                    logger.debug(f"Extracted {len(extracted_data.videos)} videos, {len(extracted_data.photos)} photos")
                except Exception as e:
                    traceback.print_exc()
                    raise Exception(f"Error extracting data from HAR file {har_path}: {e}")

            # --- Step 3 (shared): Get session attachments (screen recordings, etc.) ---
            logger.debug(f"Collecting session attachments for {entry_id}")
            try:
                session_attachments = get_session_attachments(archive_dir).model_dump()
                logger.debug(f"Found {len(session_attachments)} attachments for {entry_id}")
            except Exception as e:
                logger.warning(f"Could not get session attachments for {archive_name}: {e}")
                traceback.print_exc()
                session_attachments = dict()

            # --- Step 4: Save parsed content to database ---
            try:
                logger.debug(f"Storing extracted structures...")
                structures_json = json.dumps(extracted_data.model_dump(), default=str, ensure_ascii=False)
                db.execute_query(
                    '''
                    UPDATE archive_session
                    SET
                        parse_algorithm_version = %(parsing_code_version)s,
                        incorporation_status = 'parsed',
                        structures = %(structures)s,
                        metadata = %(metadata)s,
                        extraction_error = NULL,
                        attachments = %(attachments)s,
                        archived_url_suffix = %(archived_url_suffix)s,
                        archiving_timestamp = %(archiving_timestamp)s,
                        notes = %(notes)s
                    WHERE id = %(id)s
                    ''',
                    {
                        "id": entry['id'],
                        "structures": structures_json,
                        "parsing_code_version": PARSING_ALGORITHM_VERSION,
                        "metadata": json.dumps(metadata, ensure_ascii=False, default=str),
                        "attachments": json.dumps(session_attachments, ensure_ascii=False, default=str),
                        "archived_url_suffix": archived_url,
                        "archiving_timestamp": iso_timestamp,
                        "notes": notes,
                    },
                    'none'
                )
                logger.info(f"Successfully parsed archive: {entry_id}")
                if emit:
                    emit(f"Part B — parsed {entry_id}")
                parsed_count += 1
            except Exception as e:
                traceback.print_exc()
                raise Exception(f"Error saving parsed content to database for archive {entry_id}: {e}")

        except Exception as e:
            traceback.print_exc()
            # Record the error in the database so this archive is skipped on future runs
            db.execute_query(
                'UPDATE archive_session SET incorporation_status = %(s)s, extraction_error = %(extraction_error)s WHERE id = %(id)s',
                {"s": "parse_failed", "extraction_error": str(e), "id": entry['id']},
                return_type="none"
            )
            logger.error(f"Error processing archive {entry['external_id'] or entry['id']}: {e}")
            if emit:
                emit(f"Part B — error parsing {entry['external_id'] or entry['id']}: {e}")
            error_count += 1

    elapsed = time.time() - start_time
    logger.info(f"Part B complete: {parsed_count} archives parsed, {error_count} errors in {elapsed:.1f}s")


def extract_entities(limit: Optional[int] = None, cancel_check: Optional[Callable[[], bool]] = None, emit: Optional[Callable[[str], None]] = None):
    """
    Part C of full - does db inserts for main entities... extraction error if a problem in archive_session
    """
    import time
    start_time = time.time()
    logger.info(f"Part C Starting entity extraction{f' (limit: {limit})' if limit else ''}")
    extracted_count = 0
    error_count = 0

    # Cumulative timing for summary
    total_c1_time = 0.0  # deserialize structures
    total_c2_time = 0.0  # har_data_to_entities
    total_c3_time = 0.0  # incorporate_structures_into_db
    total_c4_time = 0.0  # update archive_session
    total_entities = {"accounts": 0, "posts": 0, "media": 0}

    # Fetch the IDs of all archives ready for entity extraction upfront (one query).
    # structures JSON can be large, so we fetch only lightweight columns here and
    # do a PK lookup per archive when we actually need the full row.
    queue = db.execute_query(
        "SELECT id, external_id, archive_location, source_type FROM archive_session "
        "WHERE incorporation_status = 'parsed' AND source_type IN ('local_har', 'local_wacz')",
        {},
        return_type="rows",
    ) or []
    if limit is not None:
        queue = queue[:limit]
    logger.info(f"Part C - {len(queue)} archives to extract")

    for stub in queue:
        if cancel_check and cancel_check():
            raise InterruptedError("Cancelled by user")
        # PK lookup — fast, and loads the large structures JSON only when needed
        entry = db.execute_query(
            "SELECT * FROM archive_session WHERE id = %(id)s",
            {"id": stub["id"]},
            return_type="single_row",
        )
        if entry is None:
            continue

        entry_id = entry['external_id'] or entry['id']
        entry_start = time.time()
        try:
            logger.info(f"Extracting entities for: {entry_id}")
            if emit:
                emit(f"Part C — extracting {entry_id}")

            # Resolve the archive directory path from the stored location
            source_type = entry.get('source_type', 'local_har')
            if source_type == 'local_wacz':
                archive_name = entry['archive_location'].split(f"{LOCAL_WACZ_ARCHIVES_DIR_ALIAS}/")[1]
                archive_path = root_anchor.ROOT_ARCHIVES / archive_name / "archive.wacz"
            else:
                archive_name = entry['archive_location'].split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[1]
                archive_path = root_anchor.ROOT_ARCHIVES / archive_name / "archive.har"
            archive_dir = root_anchor.ROOT_ARCHIVES / archive_name
            har_path = archive_path  # name kept for compatibility with downstream calls

            # Step C1: Deserialize the parsed structures from Part B (stored as JSON in the DB)
            step_start = time.time()
            har_data = ExtractedHarData(**json.loads(entry['structures']))
            c1_time = time.time() - step_start
            total_c1_time += c1_time
            logger.debug(f"  C1 deserialize structures: {c1_time:.2f}s")

            # Step C2: Convert raw HAR structures into normalized entity objects (accounts, posts, media)
            step_start = time.time()
            entities = har_data_to_entities(
                har_path,
                har_data.structures,
                har_data.videos,
                har_data.photos
            )
            c2_time = time.time() - step_start
            total_c2_time += c2_time
            total_entities["accounts"] += len(entities.accounts)
            total_entities["posts"] += len(entities.posts)
            total_entities["media"] += len(entities.media)
            logger.debug(
                f"  C2 har_data_to_entities: {c2_time:.2f}s "
                f"(accounts={len(entities.accounts)}, posts={len(entities.posts)}, media={len(entities.media)})"
            )

            # Step C3: Insert/update entities in the database tables (account, post, media, etc.)
            # Also links entities to this archive_session
            step_start = time.time()
            incorporate_structures_into_db(entities, entry['id'], archive_dir)
            c3_time = time.time() - step_start
            total_c3_time += c3_time
            logger.debug(f"  C3 incorporate_structures_into_db: {c3_time:.2f}s")

            # Step C4: Mark this archive session as successfully processed
            step_start = time.time()
            db.execute_query(
                "UPDATE archive_session SET incorporation_status = 'done', extract_algorithm_version = %(v)s WHERE external_id = %(id)s",
                {"id": entry_id, "v": ENTITY_EXTRACTION_ALGORITHM_VERSION},
                return_type="none"
            )
            c4_time = time.time() - step_start
            total_c4_time += c4_time
            logger.debug(f"  C4 update archive_session: {c4_time:.2f}s")

            entry_elapsed = time.time() - entry_start
            logger.info(f"Successfully extracted entities for: {entry_id} in {entry_elapsed:.1f}s")
            if emit:
                emit(f"Part C — extracted {entry_id}")
            extracted_count += 1

        except Exception as e:
            # Record error in DB so this archive is skipped on future runs
            logger.error(f"Error extracting entities for {entry_id}: {e}")
            if emit:
                emit(f"Part C — error extracting {entry_id}: {e}")
            db.execute_query(
                "UPDATE archive_session SET incorporation_status = 'extract_failed', extraction_error = %(extraction_error)s WHERE external_id = %(id)s",
                {"id": entry_id, "extraction_error": str(e)},
                return_type="none"
            )
            traceback.print_exc()
            error_count += 1

    elapsed = time.time() - start_time
    logger.info(f"Part C complete: {extracted_count} archives processed, {error_count} errors in {elapsed:.1f}s")
    logger.info(
        f"Part C timing breakdown: "
        f"C1 deserialize={total_c1_time:.1f}s, "
        f"C2 har_to_entities={total_c2_time:.1f}s, "
        f"C3 db_insert={total_c3_time:.1f}s, "
        f"C4 update={total_c4_time:.1f}s"
    )
    logger.info(
        f"Part C totals: "
        f"{total_entities['accounts']} accounts, "
        f"{total_entities['posts']} posts, "
        f"{total_entities['media']} media"
    )


def clear_extraction_errors():
    db.execute_query(
        "UPDATE archive_session SET incorporation_status = 'pending', extraction_error = NULL "
        "WHERE incorporation_status = 'parse_failed' AND source_type = 'local_har'",
        {},
        return_type="none"
    )
    db.execute_query(
        "UPDATE archive_session SET incorporation_status = 'parsed', extraction_error = NULL "
        "WHERE incorporation_status = 'extract_failed' AND source_type = 'local_har'",
        {},
        return_type="none"
    )


def add_missing_attachments():
    while True:
        entry = db.execute_query(
            '''SELECT *
               FROM archive_session 
               WHERE attachments IS NULL AND source_type = 'local_har' AND incorporation_status NOT IN ('parse_failed', 'extract_failed')
               LIMIT 1''',
            {},
            return_type="single_row"
        )
        if entry is None:
            print("Added attachments to all entries.")
            return
        entry_id = entry['external_id'] or entry['id']
        try:
            print("Adding attachments for entry", entry_id)
            archive_name = entry['archive_location'].split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[1]
            archive_dir = root_anchor.ROOT_ARCHIVES / archive_name
            session_attachments = get_session_attachments(archive_dir).model_dump()
            db.execute_query(
                "UPDATE archive_session SET attachments = %(attachments)s WHERE id = %(id)s",
                {"id": entry['id'], "attachments": json.dumps(session_attachments, ensure_ascii=False, default=str)},
                return_type="none"
            )
        except Exception as e:
            db.execute_query(
                "UPDATE archive_session SET extraction_error = %(extraction_error)s WHERE external_id = %(id)s",
                {"id": entry_id, "extraction_error": f"Error adding attachments: {str(e)}"},
                return_type="none"
            )
            print(f"Error adding attachments for {entry_id}: {e}")
            traceback.print_exc()


def add_missing_metadata():
    while True:
        entry = db.execute_query(
            '''SELECT *
               FROM archive_session 
               WHERE archiving_timestamp IS NULL AND source_type = 'local_har' AND incorporation_status NOT IN ('parse_failed', 'extract_failed')
               LIMIT 1''',
            {},
            return_type="single_row"
        )
        if entry is None:
            print("Added metadata to all entries.")
            return
        entry_id = entry['external_id'] or entry['id']
        try:
            print("Adding metadata for entry", entry_id)
            archive_name = entry['archive_location'].split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[1]
            archive_dir = root_anchor.ROOT_ARCHIVES / archive_name
            metadata_path = archive_dir / "metadata.json"
            iso_timestamp = None
            archived_url = None
            notes = None
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.loads(f.read())
                archived_url = metadata.get("target_url", None) if isinstance(metadata, dict) else None
                notes = metadata.get("notes", None) if isinstance(metadata, dict) else None
                timestamp = metadata.get("archiving_start_timestamp", None) if isinstance(metadata, dict) else None
                timezone = get_localzone_name()
                if timestamp is not None:
                    dt = parser.isoparse(timestamp)
                    if dt.tzinfo is None:
                        try:
                            tz = pytz_timezone(timezone)
                            dt = tz.localize(dt)
                            iso_timestamp = dt.astimezone(pytz_timezone("UTC")).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception as e:
                            print(str(e))
            except Exception:
                raise Exception(f"Metadata file {metadata_path} is not valid JSON or does not exist")
            db.execute_query(
                '''UPDATE archive_session SET
                    archived_url_suffix = %(archived_url_suffix)s,
                    archiving_timestamp = %(archiving_timestamp)s,
                    notes = %(notes)s
                   WHERE id = %(id)s''',
                {
                    "id": entry['id'],
                    "archived_url_suffix": archived_url,
                    "archiving_timestamp": iso_timestamp,
                    "notes": notes,
                },
                return_type="none"
            )
        except Exception as e:
            db.execute_query(
                "UPDATE archive_session SET extraction_error = %(extraction_error)s WHERE external_id = %(id)s",
                {"id": entry_id, "extraction_error": f"Error adding attachments: {str(e)}"},
                return_type="none"
            )
            print(f"Error adding attachments for {entry_id}: {e}")
            traceback.print_exc()


if __name__ == "__main__":

    # Ensure logs directory exists in project root
    logs_dir = os.path.join(root_anchor.ROOT_DIR, "logs_db_loader")
    os.makedirs(logs_dir, exist_ok=True)

    # Configure logging format (includes filename and line number)
    log_format = "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Console handler - DEBUG and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # Debug file handler - DEBUG and above (all messages)
    debug_file_handler = RotatingFileHandler(
        os.path.join(logs_dir, "1debug_db_loader.log"),
        maxBytes=10_000_000,  # 10MB
        backupCount=5
    )
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(formatter)

    # Error file handler - ERROR and above only
    error_file_handler = RotatingFileHandler(
        os.path.join(logs_dir, "5error_db_loader.log"),
        maxBytes=10_000_000,  # 10MB
        backupCount=5
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)

    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        format=log_format,
        handlers=[console_handler, debug_file_handler, error_file_handler]
    )

    import argparse
    from pathlib import Path

    valid_stages = ["register", "parse", "extract", "full", "add_attachments", "clear_errors", "add_metadata"]

    arg_parser = argparse.ArgumentParser(description="Archive Database Loader")
    arg_parser.add_argument("stage", nargs="?", choices=valid_stages,
                            help=f"Processing stage to run ({', '.join(valid_stages)})")
    arg_parser.add_argument("--archives-dir", type=str, default=None,
                            help="Override the archives directory path (default: archives/ in project root)")
    arg_parser.add_argument("--limit", type=int, default=None,
                            help="Limit number of archives to process (default: no limit)")
    args = arg_parser.parse_args()

    if args.archives_dir:
        archives_path = Path(args.archives_dir)
        if not archives_path.exists():
            print(f"Error: archives directory does not exist: {archives_path}")
            sys.exit(1)
        # Override ROOT_ARCHIVES in all modules that import it
        import db_loaders.db_intake as _db_intake
        import db_loaders.thumbnail_generator as _thumbnail_gen
        root_anchor.ROOT_ARCHIVES = archives_path
        root_anchor.ROOT_ARCHIVES = archives_path
        globals()['ROOT_ARCHIVES'] = archives_path
        logger.info(f"Using custom archives directory: {archives_path}")

    if args.stage:
        stage = args.stage
    else:
        stage = input(f"Enter stage ({', '.join(valid_stages)}): ").strip().lower()

    if stage == "register":
        register_archives(limit=args.limit)
    elif stage == "parse":
        parse_archives(limit=args.limit)
    elif stage == "extract":
        extract_entities(limit=args.limit)
    elif stage == "full":
        import time
        full_start = time.time()
        timings = {}

        # Part A: Register archives
        part_a_start = time.time()
        register_archives(limit=args.limit)
        timings['A'] = time.time() - part_a_start

        # Part B: Parse archives
        part_b_start = time.time()
        parse_archives(limit=args.limit)
        timings['B'] = time.time() - part_b_start

        # Part C: Extract entities
        part_c_start = time.time()
        extract_entities(limit=args.limit)
        timings['C'] = time.time() - part_c_start

        # Part D: Generate thumbnails for any media missing them
        part_d_start = time.time()
        logger.info(f"Starting thumbnail generation{f' (limit: {args.limit})' if args.limit else ''}")
        asyncio.run(generate_missing_thumbnails(limit=args.limit))
        timings['D'] = time.time() - part_d_start

        # Summary
        total_elapsed = time.time() - full_start
        logger.info(
            f"Full pipeline complete in {total_elapsed:.1f}s - "
            f"Part A: {timings['A']:.1f}s, Part B: {timings['B']:.1f}s, "
            f"Part C: {timings['C']:.1f}s, Part D: {timings['D']:.1f}s"
        )
    elif stage == "add_attachments":
        add_missing_attachments()
    elif stage == "add_metadata":
        add_missing_metadata()
    elif stage == "clear_errors":
        clear_extraction_errors()
    else:
        print(f"Unknown stage: {stage}")
        print(f"Valid stages: {', '.join(valid_stages)}")
        sys.exit(1)