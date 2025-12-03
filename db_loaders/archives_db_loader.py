import asyncio
import json
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


def register_archives():
    archive_dirs = [d for d in ROOT_ARCHIVES.iterdir() if d.is_dir()]
    for archive_dir in archive_dirs:
        archive_name = archive_dir.name
        archiving_session = f"har-{archive_name}"
        existing_entry = db.execute_query(
            "SELECT * FROM archive_session WHERE external_id = %(external_id)s",
            {"external_id": archiving_session},
            return_type="single_row"
        )
        if existing_entry:
            print(f"Entry {archiving_session} already exists in the database. Skipping.")
            continue
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
        print(f"Registered archive {archive_name}.")


PARSING_ALGORITHM_VERSION = 1


def strip_media_contents(data: ExtractedHarData) -> None:
    for v in data.videos:
        for t in v.fetched_tracks:
            v.fetched_tracks[t].segments = []
    for p in data.photos:
        p.fetched_assets = None


def parse_archives():
    while True:
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
                print("Extracted entities from all entries.")
                return

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
                        except Exception:
                            pass
            except Exception:
                raise Exception(f"Metadata file {metadata_path} is not valid JSON or does not exist")

            try:
                session_attachments = get_session_attachments(archive_dir).model_dump()
            except Exception as e:
                print(f"Warning: Could not get session attachments for archive {archive_name}: {e}")
                traceback.print_exc()
                session_attachments = dict()

            har_path = archive_dir / "archive.har"
            if not har_path.exists():
                raise Exception(f"HAR file {har_path} does not exist")
            try:
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
            except Exception as e:
                traceback.print_exc()
                raise Exception(f"Error extracting data from HAR file {har_path}: {e}")
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
            except Exception as e:
                traceback.print_exc()
                raise Exception(f"Error saving parsed content to database for archive {entry['external_id'] or entry['id']}: {e}")
        except Exception as e:
            db.execute_query(
                'UPDATE archive_session SET extraction_error = %(extraction_error)s WHERE id = %(id)s',
                {"extraction_error": str(e), "id": entry['id']},
                return_type="none"
            )
            print(f"Error processing archive {entry['external_id'] or entry['id']}: {e}")
            traceback.print_exc()


ENTITY_EXTRACTION_ALGORITHM_VERSION = 1


def extract_entities():
    while True:
        entry = db.execute_query(
            '''SELECT *
               FROM archive_session 
               WHERE extracted_entities IS NULL AND source_type = 1 AND extraction_error IS NULL AND parsed_content IS NOT NULL
               LIMIT 1''',
            {},
            return_type="single_row"
        )
        if entry is None:
            print("Extracted entities from all entries.")
            return
        entry_id = entry['external_id'] or entry['id']
        try:
            print("Extracting entities for entry", entry_id)
            archive_name = entry['archive_location'].split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[1]
            archive_dir = ROOT_ARCHIVES / archive_name
            har_path = archive_dir / "archive.har"
            har_data = ExtractedHarData(**json.loads(entry['structures']))
            entities = har_data_to_entities(
                har_path,
                har_data.structures,
                har_data.videos,
                har_data.photos
            )
            incorporate_structures_into_db(entities, entry['id'], archive_dir)
            db.execute_query(
                "UPDATE archive_session SET extraction_error = NULL, extracted_entities = %(v)s WHERE external_id = %(id)s",
                {"id": entry_id, "v": ENTITY_EXTRACTION_ALGORITHM_VERSION},
                return_type="none"
            )
        except Exception as e:
            print(f"Error extracting entities for {entry_id}: {e}")
            db.execute_query(
                "UPDATE archive_session SET extracted_entities = 2, extraction_error = %(extraction_error)s, extracted_entities = %(v)s WHERE external_id = %(id)s",
                {"id": entry_id, "extraction_error": str(e), "v": ENTITY_EXTRACTION_ALGORITHM_VERSION},
                return_type="none"
            )
            traceback.print_exc()


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
    stage = input("Enter stage (register, parse, extract, full, add_attachments, clear_errors, add_metadata): ").strip().lower()
    if stage == "register":
        register_archives()
    elif stage == "parse":
        parse_archives()
    elif stage == "extract":
        extract_entities()
    elif stage == "full":
        register_archives()
        parse_archives()
        extract_entities()
        asyncio.run(generate_missing_thumbnails())
    elif stage == "add_attachments":
        add_missing_attachments()
    elif stage == "add_metadata":
        add_missing_metadata()
    elif stage == "clear_errors":
        clear_extraction_errors()