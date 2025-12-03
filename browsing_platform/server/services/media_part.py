import json
from typing import Optional

from pydantic import field_validator

from browsing_platform.server.services.annotation import Annotation
from extractors.entity_types import Media, EntityBase
from utils import db


class MediaPart(EntityBase):
    media_id: int
    timestamp_range_start: Optional[float] = None
    timestamp_range_end: Optional[float] = None
    crop_area: Optional[list[float]] = None
    notes: Optional[str] = None

    @field_validator('crop_area', mode='before')
    def parse_data(cls, v, _):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                v = None
        return v



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
        """INSERT INTO media_part (media_id, timestamp_range_start, timestamp_range_end, crop_area, notes)
           VALUES (%(media_id)s, %(timestamp_range_start)s, %(timestamp_range_end)s, %(crop_area)s, %(notes)s)""",
        {
            "media_id": media_part.media_id,
            "timestamp_range_start": media_part.timestamp_range_start,
            "timestamp_range_end": media_part.timestamp_range_end,
            "crop_area": json.dumps(media_part.crop_area) if media_part.crop_area is not None else None,
            "notes": media_part.notes
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
               notes = %(notes)s
           WHERE id = %(id)s""",
        {
            "id": media_part.id,
            "media_id": media_part.media_id,
            "timestamp_range_start": media_part.timestamp_range_start,
            "timestamp_range_end": media_part.timestamp_range_end,
            "crop_area": json.dumps(media_part.crop_area) if media_part.crop_area is not None else None,
            "notes": media_part.notes
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
        f"""SELECT * FROM media_part WHERE media_id IN ({query_in_clause})""",
        query_args,
        return_type="rows"
    )
    return [MediaPart(**m) for m in media_parts]

def annotate_media_part(media_part_id: int, annotation: Annotation) -> None:
    # Set notes field
    db.execute_query(
        """UPDATE media_part SET notes = %(notes)s WHERE id = %(id)s""",
        {"id": media_part_id, "notes": annotation.notes},
        return_type="none"
    )
    # Clear associated tags
    db.execute_query(
        """DELETE FROM media_part_tag WHERE media_part_id = %(id)s""",
        {"id": media_part_id},
        return_type="none"
    )
    # Add new tags
    for tag_id in annotation.tags:
        db.execute_query(
            """INSERT INTO media_part_tag (media_part_id, tag_id) VALUES (%(media_part_id)s, %(tag_id)s)""",
            {"media_part_id": media_part_id, "tag_id": tag_id},
            return_type="none"
        )