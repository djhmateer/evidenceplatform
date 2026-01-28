from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from utils import db


class ITag(BaseModel):
    id: Optional[int] = None
    create_date: Optional[datetime] = None
    update_date: Optional[datetime] = None
    name: str
    description: Optional[str] = None
    tag_type_id: Optional[int] = None

class ITagWithType(ITag):
    tag_type_name: Optional[str] = None
    tag_type_description: Optional[str] = None
    tag_type_notes: Optional[str] = None



def auto_complete_tags(query: str) -> list[ITagWithType]:
    matching_rows = db.execute_query(
        """SELECT 
                tag.*,
                tag_type.name AS tag_type_name,
                tag_type.description AS tag_type_description,
                tag_type.notes AS tag_type_notes
            FROM tag
            LEFT JOIN tag_type ON tag.tag_type_id = tag_type.id
            WHERE tag.name LIKE %(query)s
            LIMIT 10""",
        {"query": f"%{query}%"},
        return_type="rows"
    )
    return [ITagWithType(**row) for row in matching_rows]


ENTITY_TAG_TABLES = {
    'account': ('account_tag', 'account_id'),
    'post': ('post_tag', 'post_id'),
    'media': ('media_tag', 'media_id'),
    'media_part': ('media_part_tag', 'media_part_id'),
    'archive_session': ('archive_session_tag', 'archive_session_id'),
}


def get_tags_by_entity_ids(entity:str , ids: list[int]) -> dict[int, list[ITagWithType]]:
    if not ids or len(ids) == 0:
        return {}
    if entity not in ENTITY_TAG_TABLES:
        raise ValueError(f"Unsupported entity for tag retrieval: {entity}")
    table_name, id_column = ENTITY_TAG_TABLES[entity]
    query_args = {f"id_{i}": f"{id_}" for i, id_ in enumerate(ids)}
    query_in_clause = ', '.join([f"%(id_{i})s" for i in range(len(ids))])
    tag_rows = db.execute_query(
        f"""SELECT
                t.*,
                te.{id_column} AS entity_id,
                tag_type.name AS tag_type_name,
                tag_type.description AS tag_type_description,
                tag_type.notes AS tag_type_notes
            FROM {table_name} AS te
            LEFT JOIN tag AS t ON te.tag_id = t.id
            LEFT JOIN tag_type ON t.tag_type_id = tag_type.id
            WHERE te.{id_column} IN ({query_in_clause})""",
        query_args,
        return_type="rows"
    )
    tags_by_entity_id: dict[int, list[ITagWithType]] = {}
    for row in tag_rows:
        entity_id = row.pop("entity_id")
        tag = ITagWithType(**row)
        if entity_id not in tags_by_entity_id:
            tags_by_entity_id[entity_id] = []
        tags_by_entity_id[entity_id].append(tag)
    return tags_by_entity_id