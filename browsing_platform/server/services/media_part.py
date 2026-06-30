import json
from typing import Optional

from browsing_platform.server.services.annotation import Annotation
from extractors.entity_types import Media, MediaPart
from utils import db


def get_media_part_by_id(media_part_id: int) -> Optional[MediaPart]:
    row = db.execute_query(
        """SELECT * FROM media_part WHERE id = %(id)s""",
        {"id": media_part_id},
        return_type="single_row"
    )
    if row is None:
        return None
    return MediaPart(**row)


def insert_media_part(media_part: MediaPart) -> int:
    insert_result = db.execute_query(
        """INSERT INTO media_part (media_id, timestamp_range_start, timestamp_range_end, crop_area)
           VALUES (%(media_id)s, %(timestamp_range_start)s, %(timestamp_range_end)s, %(crop_area)s)""",
        {
            "media_id": media_part.media_id,
            "timestamp_range_start": media_part.timestamp_range_start,
            "timestamp_range_end": media_part.timestamp_range_end,
            "crop_area": json.dumps(media_part.crop_area) if media_part.crop_area is not None else None,
        },
        return_type="id"
    )
    return insert_result


def update_media_part(media_part: MediaPart) -> None:
    db.execute_query(
        """UPDATE media_part
           SET media_id = %(media_id)s,
               timestamp_range_start = %(timestamp_range_start)s,
               timestamp_range_end = %(timestamp_range_end)s,
               crop_area = %(crop_area)s,
               thumbnail_status = 'pending'
           WHERE id = %(id)s""",
        {
            "id": media_part.id,
            "media_id": media_part.media_id,
            "timestamp_range_start": media_part.timestamp_range_start,
            "timestamp_range_end": media_part.timestamp_range_end,
            "crop_area": json.dumps(media_part.crop_area) if media_part.crop_area is not None else None,
        },
        "none"
    )
    return media_part.id


def delete_media_part(media_part_id: int) -> None:
    db.execute_query(
        """DELETE FROM media_part WHERE id = %(id)s""",
        {"id": media_part_id},
        "none"
    )


def get_media_part_by_media(media: list[Media]) -> list[MediaPart]:
    if not media or len(media) == 0:
        return []
    query_args = {f"media_id_{i}": f"{media_item.id}" for i, media_item in enumerate(media)}
    query_in_clause = ', '.join([f"%(media_id_{i})s" for i in range(len(media))])
    media_parts = db.execute_query(
        f"""SELECT * FROM media_part WHERE media_id IN ({query_in_clause})""",  # nosec B608 - query_in_clause contains only %(key)s placeholders, not user input
        query_args,
        return_type="rows"
    )
    return [MediaPart(**m) for m in media_parts]

def annotate_media_part(media_part_id: int, annotation: Annotation) -> None:
    with db.transaction_batch():
        # Clear associated tags
        db.execute_query(
            """DELETE FROM media_part_tag WHERE media_part_id = %(id)s""",
            {"id": media_part_id},
            return_type="none"
        )
        # Add new tags with per-assignment notes
        for tag in (annotation.tags or []):
            db.execute_query(
                """INSERT INTO media_part_tag (media_part_id, tag_id, notes) VALUES (%(media_part_id)s, %(tag_id)s, %(notes)s)""",
                {"media_part_id": media_part_id, "tag_id": tag.id, "notes": tag.notes},
                return_type="none"
            )