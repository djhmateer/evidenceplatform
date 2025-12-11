import asyncio
import json
import logging
import sys
import traceback

from dateutil import parser
from pytz import timezone as pytz_timezone
from tzlocal import get_localzone_name

from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS, ROOT_ARCHIVES
from db_loaders.db_intake import incorporate_structures_into_db
from db_loaders.thumbnail_generator import generate_missing_thumbnails
from extractors.extract_photos import PhotoAcquisitionConfig
from extractors.extract_videos import VideoAcquisitionConfig
from extractors.session_attachments import get_session_attachments
from extractors.structures_to_entities import extract_data_from_har, ExtractedHarData, har_data_to_entities
from utils import db

logger = logging.getLogger(__name__)


def register_archives():
    """
     Part A of full - scans directory. puts in an archive_session record for each unregistered archive
    """
    import time
    start_time = time.time()
    # Get all subdirectories in the archives root folder eg archives/eran_20250530_160037
    archive_dirs = [d for d in ROOT_ARCHIVES.iterdir() if d.is_dir()]
    logger.info(f"Part A - Found {len(archive_dirs)} archive directories in {ROOT_ARCHIVES}")

    for archive_dir in archive_dirs:
        # Extract directory name to use as archive identifier eg eran_20250530_160037
        archive_name = archive_dir.name
        # Prefix with "har-" to indicate this is a HAR-based archive (source_type=1)
        archiving_session = f"har-{archive_name}"

        # Check if this archive has already been registered
        existing_entry = db.execute_query(
            "SELECT * FROM archive_session WHERE external_id = %(external_id)s",
            {"external_id": archiving_session},
            return_type="single_row"
        )

        if existing_entry:
            logger.debug(f"Archive '{archiving_session}' already exists in database, skipping")
            continue

        # Insert new archive_session record
        # source_type=1 indicates a HAR archive (as opposed to other archive formats)
        db.execute_query(
            """INSERT INTO archive_session
                   (external_id, archive_location, source_type)
               VALUES (%(external_id)s, %(archive_location)s, 1)""",
            {
                "external_id": archiving_session,
                "archive_location": f'{LOCAL_ARCHIVES_DIR_ALIAS}/{archive_name}'
            },
            return_type="id"
        )
        logger.info(f"Registered new archive: {archive_name}")

    elapsed = time.time() - start_time
    logger.info(f"Part A register_archives complete in {elapsed:.1f}s")


PARSING_ALGORITHM_VERSION = 1


def strip_media_contents(data: ExtractedHarData) -> None:
    for v in data.videos:
        for t in v.fetched_tracks:
            v.fetched_tracks[t].segments = []
    for p in data.photos:
        p.fetched_assets = None


def parse_archives():
    """
     Part B of full - queries archive_session where parsed_content is null.
     looks for metadata.json.
     looks for archive.har and does parsing.
     updates archive_session - structures (lots of json), metadata
    """
    import time
    start_time = time.time()
    logger.info("Part B - Starting archive parsing")
    parsed_count = 0
    error_count = 0

    while True:
        # Find the next unparsed archive session (source_type=1 means HAR archive)
        # Only process archives that haven't been parsed and don't have errors
        entry = db.execute_query(
            f'''
            SELECT *
            FROM archive_session
            WHERE
                parsed_content IS NULL AND
                extraction_error IS NULL AND
                source_type = 1
            LIMIT 1
            ''',
            {},
            return_type="single_row"
        )
        try:
            if entry is None:
                # No more unparsed archives remain
                elapsed = time.time() - start_time
                logger.info(f"Part B complete: {parsed_count} archives parsed, {error_count} errors in {elapsed:.1f}s")
                return

            # Extract the archive directory name from the stored location
            # e.g., "local_archive_har/eran_20250530_160037" -> "eran_20250530_160037"
            archive_name = entry['archive_location'].split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[1]
            entry_id = entry['external_id'] or entry['id']
            logger.info(f"Parsing archive: {entry_id}")

            archive_dir = ROOT_ARCHIVES / archive_name

            # --- Step 1: Read metadata.json ---
            # Contains target_url, notes, archiving_start_timestamp
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

                # Convert timestamp to UTC if present
                # Assumes local timezone if not specified in the timestamp
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
            logger.debug(f"Finished Step 1 - Metadata for {entry_id}: {metadata}")

            # --- Step 2: Get session attachments (screenshots, etc.) ---
            try:
                session_attachments = get_session_attachments(archive_dir).model_dump()
                logger.debug(f"Found {len(session_attachments)} attachments for {entry_id}")
            except Exception as e:
                logger.warning(f"Could not get session attachments for archive {archive_name}: {e}")
                traceback.print_exc()
                session_attachments = dict()

            # --- Step 3: Parse the HAR file ---
            # Extract social media structures (posts, accounts, media references)
            logger.debug(f"Starting Step 3 - Parsing HAR for {entry_id}")
            har_path = archive_dir / "archive.har"
            if not har_path.exists():
                raise Exception(f"HAR file {har_path} does not exist")
            try:
                logger.debug(f"Extracting data from HAR file: {har_path}")
                # Configure extraction to NOT download any media - just parse what's in the HAR
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
                # Remove binary media content before storing (keeps JSON size manageable)
                strip_media_contents(extracted_data)
                logger.debug(f"Extracted {len(extracted_data.videos)} videos, {len(extracted_data.photos)} photos")
            except Exception as e:
                traceback.print_exc()
                raise Exception(f"Error extracting data from HAR file {har_path}: {e}")

            # --- Step 4: Save parsed content to database ---
            try:
                db.execute_query(
                    '''
                    UPDATE archive_session
                    SET
                        parsed_content = %(parsing_code_version)s,
                        structures = %(structures)s,
                        metadata = %(metadata)s,
                        extraction_error = NULL,
                        attachments = %(attachments)s,
                        notes = %(notes)s
                    WHERE id = %(id)s
                    ''',
                    {
                        "id": entry['id'],
                        "structures": json.dumps(extracted_data.model_dump(), default=str, ensure_ascii=False),
                        "parsing_code_version": PARSING_ALGORITHM_VERSION,
                        "metadata": json.dumps(metadata, ensure_ascii=False, default=str),
                        "attachments": json.dumps(session_attachments, ensure_ascii=False, default=str),
                        "archived_url": archived_url,
                        "archiving_timestamp": iso_timestamp,
                        "notes": notes
                    },
                    'none'
                )
                logger.info(f"End of Part B - Step 4 - Successfully parsed archive: {entry_id}")
                parsed_count += 1
            except Exception as e:
                traceback.print_exc()
                raise Exception(f"Error saving parsed content to database for archive {entry_id}: {e}")

        except Exception as e:
            # Record the error in the database so this archive is skipped on future runs
            db.execute_query(
                'UPDATE archive_session SET extraction_error = %(extraction_error)s WHERE id = %(id)s',
                {"extraction_error": str(e), "id": entry['id']},
                return_type="none"
            )
            logger.error(f"Error processing archive {entry['external_id'] or entry['id']}: {e}")
            error_count += 1
            traceback.print_exc()


ENTITY_EXTRACTION_ALGORITHM_VERSION = 1


def extract_entities():
    """
    Part C of full - does db inserts for main entities... extraction error if a problem in archive_session
    """
    import time
    start_time = time.time()
    logger.info("Part C Starting entity extraction")
    extracted_count = 0
    error_count = 0

    # Cumulative timing for summary
    total_c1_time = 0.0  # deserialize structures
    total_c2_time = 0.0  # har_data_to_entities
    total_c3_time = 0.0  # incorporate_structures_into_db
    total_c4_time = 0.0  # update archive_session
    total_entities = {"accounts": 0, "posts": 0, "media": 0}

    while True:
        # Find the next archive session that has been parsed but not yet had entities extracted
        # Requires: parsed_content set (Part B done), no errors, HAR source type
        entry = db.execute_query(
            '''SELECT *
               FROM archive_session
               WHERE extracted_entities IS NULL AND source_type = 1 AND extraction_error IS NULL AND parsed_content IS NOT NULL
               LIMIT 1''',
            {},
            return_type="single_row"
        )
        if entry is None:
            # No more archives to process
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
            return

        entry_id = entry['external_id'] or entry['id']
        entry_start = time.time()
        try:
            logger.info(f"Extracting entities for: {entry_id}")

            # Resolve the archive directory path from the stored location
            archive_name = entry['archive_location'].split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[1]
            archive_dir = ROOT_ARCHIVES / archive_name
            har_path = archive_dir / "archive.har"

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
                "UPDATE archive_session SET extraction_error = NULL, extracted_entities = %(v)s WHERE external_id = %(id)s",
                {"id": entry_id, "v": ENTITY_EXTRACTION_ALGORITHM_VERSION},
                return_type="none"
            )
            c4_time = time.time() - step_start
            total_c4_time += c4_time
            logger.debug(f"  C4 update archive_session: {c4_time:.2f}s")

            entry_elapsed = time.time() - entry_start
            logger.info(f"Successfully extracted entities for: {entry_id} in {entry_elapsed:.1f}s")
            extracted_count += 1

        except Exception as e:
            # Record error in DB so this archive is skipped on future runs
            logger.error(f"Error extracting entities for {entry_id}: {e}")
            db.execute_query(
                "UPDATE archive_session SET extracted_entities = 2, extraction_error = %(extraction_error)s, extracted_entities = %(v)s WHERE external_id = %(id)s",
                {"id": entry_id, "extraction_error": str(e), "v": ENTITY_EXTRACTION_ALGORITHM_VERSION},
                return_type="none"
            )
            traceback.print_exc()
            error_count += 1


def clear_extraction_errors():
    db.execute_query(
        "UPDATE archive_session SET extraction_error = NULL WHERE source_type = 1",
        {},
        return_type="none"
    )


def add_missing_attachments():
    while True:
        entry = db.execute_query(
            '''SELECT *
               FROM archive_session 
               WHERE attachments IS NULL AND source_type = 1 AND extraction_error IS NULL
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
            archive_dir = ROOT_ARCHIVES / archive_name
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
               WHERE archiving_timestamp IS NULL AND source_type = 1 AND extraction_error IS NULL
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
            archive_dir = ROOT_ARCHIVES / archive_name
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
                    archived_url = %(archived_url)s,
                    archiving_timestamp = %(archiving_timestamp)s,
                    notes = %(notes)s
                   WHERE id = %(id)s''',
                {
                    "id": entry['id'],
                    "archived_url": archived_url,
                    "archiving_timestamp": iso_timestamp,
                    "notes": notes
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
    import os
    from logging.handlers import RotatingFileHandler
    from root_anchor import ROOT_DIR

    # Ensure logs directory exists in project root
    logs_dir = os.path.join(ROOT_DIR, "logs_db_loader")
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

    valid_stages = ["register", "parse", "extract", "full", "add_attachments", "clear_errors", "add_metadata"]

    if len(sys.argv) > 1:
        stage = sys.argv[1].strip().lower()
    else:
        stage = input(f"Enter stage ({', '.join(valid_stages)}): ").strip().lower()

    if stage == "register":
        register_archives()
    elif stage == "parse":
        parse_archives()
    elif stage == "extract":
        extract_entities()
    elif stage == "full":
        import time
        full_start = time.time()
        timings = {}

        # Part A: Register archives
        part_a_start = time.time()
        register_archives()
        timings['A'] = time.time() - part_a_start

        # Part B: Parse archives
        part_b_start = time.time()
        parse_archives()
        timings['B'] = time.time() - part_b_start

        # Part C: Extract entities
        part_c_start = time.time()
        extract_entities()
        timings['C'] = time.time() - part_c_start

        # Part D: Generate thumbnails for any media missing them
        part_d_start = time.time()
        logger.info("Starting thumbnail generation")
        asyncio.run(generate_missing_thumbnails())
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