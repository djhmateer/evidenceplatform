import json
from typing import Optional

from pydantic import BaseModel

from browsing_platform.server.services.tag import ITagWithType
from utils import db


# ── Models ────────────────────────────────────────────────────────────────────

class ITagType(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    notes: Optional[str] = None
    entity_affinity: Optional[list] = None
    quick_access: bool = False


class ITagParent(BaseModel):
    id: int
    name: str


class ITagDetail(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    tag_type_id: Optional[int] = None
    tag_type_name: Optional[str] = None
    quick_access: bool = False
    omit_from_tag_type_dropdown: bool = False
    notes_recommended: bool = True
    parents: list[ITagParent] = []


class ITagHierarchyEntry(BaseModel):
    super_tag_id: int
    sub_tag_id: int
    notes: Optional[str] = None
    super_tag_name: Optional[str] = None
    sub_tag_name: Optional[str] = None


class ITagUsage(BaseModel):
    accounts: int = 0
    posts: int = 0
    media: int = 0
    media_parts: int = 0


class ITagStat(BaseModel):
    tag_id: int
    tag_name: str
    tag_type_name: Optional[str] = None
    count: int


# ── Tag Types ─────────────────────────────────────────────────────────────────

def list_tag_types() -> list[ITagType]:
    rows = db.execute_query(
        "SELECT id, name, description, notes, entity_affinity, quick_access FROM tag_type ORDER BY name",
        {},
        return_type="rows"
    )
    result = []
    for row in rows:
        ea = row.get("entity_affinity")
        if isinstance(ea, str):
            try:
                ea = json.loads(ea)
            except (json.JSONDecodeError, TypeError):
                ea = None
        result.append(ITagType(
            id=row["id"],
            name=row["name"],
            description=row.get("description"),
            notes=row.get("notes"),
            entity_affinity=ea,
            quick_access=bool(row.get("quick_access")),
        ))
    return result


def create_tag_type(name: str, description: Optional[str], notes: Optional[str], entity_affinity: Optional[list], quick_access: bool = False) -> ITagType:
    ea_json = json.dumps(entity_affinity) if entity_affinity is not None else None
    new_id = db.execute_query(
        "INSERT INTO tag_type (name, description, notes, entity_affinity, quick_access) VALUES (%(name)s, %(description)s, %(notes)s, %(entity_affinity)s, %(quick_access)s)",
        {"name": name, "description": description, "notes": notes, "entity_affinity": ea_json, "quick_access": quick_access},
        return_type="id"
    )
    return ITagType(id=new_id, name=name, description=description, notes=notes, entity_affinity=entity_affinity, quick_access=quick_access)


def update_tag_type(tag_type_id: int, name: str, description: Optional[str], notes: Optional[str], entity_affinity: Optional[list], quick_access: bool = False) -> bool:
    ea_json = json.dumps(entity_affinity) if entity_affinity is not None else None
    db.execute_query(
        "UPDATE tag_type SET name=%(name)s, description=%(description)s, notes=%(notes)s, entity_affinity=%(entity_affinity)s, quick_access=%(quick_access)s WHERE id=%(id)s",
        {"id": tag_type_id, "name": name, "description": description, "notes": notes, "entity_affinity": ea_json, "quick_access": quick_access},
        return_type="none"
    )
    return True


def delete_tag_type(tag_type_id: int) -> tuple[bool, str]:
    usage = db.execute_query(
        "SELECT COUNT(*) AS cnt FROM tag WHERE tag_type_id = %(id)s",
        {"id": tag_type_id},
        return_type="single_row"
    )
    if usage and usage["cnt"] > 0:
        return False, f"Cannot delete: {usage['cnt']} tag(s) reference this type"
    db.execute_query(
        "DELETE FROM tag_type WHERE id = %(id)s",
        {"id": tag_type_id},
        return_type="none"
    )
    return True, ""


# ── Tag Counts ────────────────────────────────────────────────────────────────

def get_tag_counts_by_type() -> dict[str, int]:
    """Returns {type_id_str: count} plus key 'null' for untyped tags."""
    rows = db.execute_query(
        "SELECT COALESCE(CAST(tag_type_id AS CHAR), 'null') AS k, COUNT(*) AS cnt FROM tag GROUP BY tag_type_id",
        {},
        return_type="rows"
    )
    return {row["k"]: row["cnt"] for row in rows}


# ── Tags ──────────────────────────────────────────────────────────────────────

def list_tags(tag_type_id: Optional[int] = None, q: Optional[str] = None, page: int = 1, page_size: int = 50) -> list[ITagDetail]:
    args: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    where = []
    if tag_type_id is not None:
        where.append("t.tag_type_id = %(tag_type_id)s")
        args["tag_type_id"] = tag_type_id
    if q:
        where.append("t.name LIKE %(q)s")
        args["q"] = f"%{q}%"
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute_query(
        f"""SELECT t.id, t.name, t.description, t.tag_type_id, t.quick_access,
                   t.omit_from_tag_type_dropdown, t.notes_recommended,
                   tt.name AS tag_type_name,
                   (SELECT JSON_ARRAYAGG(JSON_OBJECT('id', pt.id, 'name', pt.name))
                    FROM tag_hierarchy th JOIN tag pt ON th.super_tag_id = pt.id
                    WHERE th.sub_tag_id = t.id) AS parents_json
            FROM tag t
            LEFT JOIN tag_type tt ON t.tag_type_id = tt.id
            {where_sql}
            ORDER BY t.name
            LIMIT %(limit)s OFFSET %(offset)s""",
        args,
        return_type="rows"
    )
    results = []
    for row in rows:
        parents_raw = row.pop("parents_json", None)
        if isinstance(parents_raw, str):
            parents_raw = json.loads(parents_raw)
        row["parents"] = parents_raw or []
        results.append(ITagDetail(**row))
    return results


class IQuickAccessTypeDropdown(BaseModel):
    type_id: int
    type_name: Optional[str]
    tags: list[ITagWithType]
    hierarchy: list[ITagHierarchyEntry] = []


class IQuickAccessData(BaseModel):
    individual_tags: list[ITagWithType]
    type_dropdowns: list[IQuickAccessTypeDropdown]


_QUICK_ACCESS_TAG_COLS = """
    tag.*,
    tag_type.name AS tag_type_name,
    tag_type.description AS tag_type_description,
    tag_type.notes AS tag_type_notes,
    tag_type.entity_affinity AS tag_type_entity_affinity
"""


def list_quick_access_data(entity: Optional[str] = None) -> IQuickAccessData:
    affinity_clause = ""
    args: dict = {}
    if entity is not None:
        affinity_clause = " AND (tag_type.entity_affinity IS NULL OR JSON_CONTAINS(tag_type.entity_affinity, %(entity_json)s))"
        args["entity_json"] = json.dumps(entity)

    individual_rows = db.execute_query(
        f"SELECT {_QUICK_ACCESS_TAG_COLS} FROM tag LEFT JOIN tag_type ON tag.tag_type_id = tag_type.id WHERE tag.quick_access = 1{affinity_clause} ORDER BY tag.name",
        args,
        return_type="rows"
    )
    individual_tags = [ITagWithType(**row) for row in individual_rows]

    dropdown_rows = db.execute_query(
        f"""SELECT {_QUICK_ACCESS_TAG_COLS}
            FROM tag
            JOIN tag_type ON tag.tag_type_id = tag_type.id
            WHERE tag_type.quick_access = 1 AND tag.omit_from_tag_type_dropdown = 0{affinity_clause}
            ORDER BY tag_type.name, tag.name""",
        args,
        return_type="rows"
    )
    type_dropdowns_map: dict[int, IQuickAccessTypeDropdown] = {}
    for row in dropdown_rows:
        type_id = row["tag_type_id"]
        if type_id not in type_dropdowns_map:
            type_dropdowns_map[type_id] = IQuickAccessTypeDropdown(
                type_id=type_id, type_name=row["tag_type_name"], tags=[]
            )
        type_dropdowns_map[type_id].tags.append(ITagWithType(**row))

    hierarchy_rows = db.execute_query(
        f"""SELECT th.super_tag_id, th.sub_tag_id, sup.tag_type_id
            FROM tag_hierarchy th
            JOIN tag sup ON th.super_tag_id = sup.id
            JOIN tag sub ON th.sub_tag_id = sub.id
            JOIN tag_type ON sup.tag_type_id = tag_type.id
            WHERE tag_type.quick_access = 1
              AND sup.omit_from_tag_type_dropdown = 0
              AND sub.omit_from_tag_type_dropdown = 0
              AND sup.tag_type_id = sub.tag_type_id{affinity_clause}""",
        args,
        return_type="rows"
    )
    for row in hierarchy_rows:
        type_id = row["tag_type_id"]
        if type_id in type_dropdowns_map:
            type_dropdowns_map[type_id].hierarchy.append(
                ITagHierarchyEntry(super_tag_id=row["super_tag_id"], sub_tag_id=row["sub_tag_id"])
            )

    return IQuickAccessData(individual_tags=individual_tags, type_dropdowns=list(type_dropdowns_map.values()))


def get_tag(tag_id: int) -> Optional[ITagDetail]:
    rows = db.execute_query(
        """SELECT t.id, t.name, t.description, t.tag_type_id, t.quick_access,
                  t.omit_from_tag_type_dropdown, t.notes_recommended,
                  tt.name AS tag_type_name,
                  (SELECT JSON_ARRAYAGG(JSON_OBJECT('id', pt.id, 'name', pt.name))
                   FROM tag_hierarchy th JOIN tag pt ON th.super_tag_id = pt.id
                   WHERE th.sub_tag_id = t.id) AS parents_json
           FROM tag t
           LEFT JOIN tag_type tt ON t.tag_type_id = tt.id
           WHERE t.id = %(id)s""",
        {"id": tag_id},
        return_type="rows"
    )
    if not rows:
        return None
    row = rows[0]
    parents_raw = row.pop("parents_json", None)
    if isinstance(parents_raw, str):
        parents_raw = json.loads(parents_raw)
    row["parents"] = parents_raw or []
    return ITagDetail(**row)


def create_tag(name: str, description: Optional[str], tag_type_id: Optional[int], quick_access: bool = False, omit_from_tag_type_dropdown: bool = False, notes_recommended: bool = True) -> ITagDetail:
    new_id = db.execute_query(
        "INSERT INTO tag (name, description, tag_type_id, quick_access, omit_from_tag_type_dropdown, notes_recommended) VALUES (%(name)s, %(description)s, %(tag_type_id)s, %(quick_access)s, %(omit_from_tag_type_dropdown)s, %(notes_recommended)s)",
        {"name": name, "description": description, "tag_type_id": tag_type_id, "quick_access": quick_access, "omit_from_tag_type_dropdown": omit_from_tag_type_dropdown, "notes_recommended": notes_recommended},
        return_type="id"
    )
    return ITagDetail(id=new_id, name=name, description=description, tag_type_id=tag_type_id, quick_access=quick_access, omit_from_tag_type_dropdown=omit_from_tag_type_dropdown, notes_recommended=notes_recommended)


def update_tag(tag_id: int, name: str, description: Optional[str], tag_type_id: Optional[int], quick_access: bool = False, omit_from_tag_type_dropdown: bool = False, notes_recommended: bool = True) -> bool:
    db.execute_query(
        "UPDATE tag SET name=%(name)s, description=%(description)s, tag_type_id=%(tag_type_id)s, quick_access=%(quick_access)s, omit_from_tag_type_dropdown=%(omit_from_tag_type_dropdown)s, notes_recommended=%(notes_recommended)s WHERE id=%(id)s",
        {"id": tag_id, "name": name, "description": description, "tag_type_id": tag_type_id, "quick_access": quick_access, "omit_from_tag_type_dropdown": omit_from_tag_type_dropdown, "notes_recommended": notes_recommended},
        return_type="none"
    )
    return True


def delete_tag(tag_id: int) -> tuple[bool, str]:
    usage = get_tag_usage_counts(tag_id)
    total = usage.accounts + usage.posts + usage.media + usage.media_parts
    if total > 0:
        return False, f"Cannot delete: tag is assigned to {total} entity(ies)"
    db.execute_query("DELETE FROM tag WHERE id = %(id)s", {"id": tag_id}, return_type="none")
    return True, ""


def get_tag_usage_counts(tag_id: int) -> ITagUsage:
    # Counts entities tagged with tag_id or any of its descendants (hierarchy-aware),
    # matching the recursive expansion used by the search page's tag filter.
    # A single query computes all four counts in one CTE pass.
    row = db.execute_query(
        """
        WITH RECURSIVE tag_desc AS (
            SELECT id FROM tag WHERE id = %(id)s
            UNION ALL
            SELECT th.sub_tag_id FROM tag_hierarchy th JOIN tag_desc td ON th.super_tag_id = td.id
        ),
        all_tagged AS (
            SELECT 'account'    AS entity_type, account_id    AS entity_id FROM account_tag    WHERE tag_id IN (SELECT id FROM tag_desc)
            UNION ALL
            SELECT 'post',                       post_id                    FROM post_tag        WHERE tag_id IN (SELECT id FROM tag_desc)
            UNION ALL
            SELECT 'media',                      media_id                   FROM media_tag       WHERE tag_id IN (SELECT id FROM tag_desc)
            UNION ALL
            SELECT 'media_part',                 media_part_id              FROM media_part_tag  WHERE tag_id IN (SELECT id FROM tag_desc)
        )
        SELECT
            COUNT(DISTINCT CASE WHEN entity_type = 'account'    THEN entity_id END) AS accounts,
            COUNT(DISTINCT CASE WHEN entity_type = 'post'       THEN entity_id END) AS posts,
            COUNT(DISTINCT CASE WHEN entity_type = 'media'      THEN entity_id END) AS media,
            COUNT(DISTINCT CASE WHEN entity_type = 'media_part' THEN entity_id END) AS media_parts
        FROM all_tagged
        """,
        {"id": tag_id},
        return_type="single_row"
    )
    return ITagUsage(
        accounts=row["accounts"] if row else 0,
        posts=row["posts"] if row else 0,
        media=row["media"] if row else 0,
        media_parts=row["media_parts"] if row else 0,
    )


# ── Hierarchy ─────────────────────────────────────────────────────────────────

def list_children(tag_id: int) -> list[ITagHierarchyEntry]:
    rows = db.execute_query(
        """SELECT th.super_tag_id, th.sub_tag_id, th.notes,
                  ts.name AS sub_tag_name, tp.name AS super_tag_name
           FROM tag_hierarchy th
           JOIN tag ts ON th.sub_tag_id = ts.id
           JOIN tag tp ON th.super_tag_id = tp.id
           WHERE th.super_tag_id = %(id)s""",
        {"id": tag_id},
        return_type="rows"
    )
    return [ITagHierarchyEntry(**row) for row in rows]


def list_parents(tag_id: int) -> list[ITagHierarchyEntry]:
    rows = db.execute_query(
        """SELECT th.super_tag_id, th.sub_tag_id, th.notes,
                  ts.name AS sub_tag_name, tp.name AS super_tag_name
           FROM tag_hierarchy th
           JOIN tag ts ON th.sub_tag_id = ts.id
           JOIN tag tp ON th.super_tag_id = tp.id
           WHERE th.sub_tag_id = %(id)s""",
        {"id": tag_id},
        return_type="rows"
    )
    return [ITagHierarchyEntry(**row) for row in rows]


def would_create_cycle(super_tag_id: int, sub_tag_id: int) -> bool:
    """Return True if adding super→sub would create a cycle (i.e. super is already a descendant of sub)."""
    if super_tag_id == sub_tag_id:
        return True
    # Check if super_tag_id is reachable from sub_tag_id via existing hierarchy
    row = db.execute_query(
        """WITH RECURSIVE descendants AS (
               SELECT sub_tag_id AS id FROM tag_hierarchy WHERE super_tag_id = %(sub_id)s
               UNION ALL
               SELECT th.sub_tag_id FROM tag_hierarchy th JOIN descendants d ON th.super_tag_id = d.id
           )
           SELECT COUNT(*) AS cnt FROM descendants WHERE id = %(super_id)s""",
        {"sub_id": sub_tag_id, "super_id": super_tag_id},
        return_type="single_row"
    )
    return bool(row and row["cnt"] > 0)


def add_hierarchy(super_tag_id: int, sub_tag_id: int, notes: Optional[str]) -> ITagHierarchyEntry:
    db.execute_query(
        "INSERT INTO tag_hierarchy (super_tag_id, sub_tag_id, notes) VALUES (%(super_id)s, %(sub_id)s, %(notes)s)",
        {"super_id": super_tag_id, "sub_id": sub_tag_id, "notes": notes},
        return_type="none"
    )
    return ITagHierarchyEntry(super_tag_id=super_tag_id, sub_tag_id=sub_tag_id, notes=notes)


def remove_hierarchy(super_tag_id: int, sub_tag_id: int) -> bool:
    db.execute_query(
        "DELETE FROM tag_hierarchy WHERE super_tag_id = %(super_id)s AND sub_tag_id = %(sub_id)s",
        {"super_id": super_tag_id, "sub_id": sub_tag_id},
        return_type="none"
    )
    return True


def update_hierarchy_notes(super_tag_id: int, sub_tag_id: int, notes: Optional[str]) -> bool:
    db.execute_query(
        "UPDATE tag_hierarchy SET notes=%(notes)s WHERE super_tag_id=%(super_id)s AND sub_tag_id=%(sub_id)s",
        {"super_id": super_tag_id, "sub_id": sub_tag_id, "notes": notes},
        return_type="none"
    )
    return True


# ── Import helpers ────────────────────────────────────────────────────────────

def get_tag_type_by_name(name: str) -> Optional[ITagType]:
    row = db.execute_query(
        "SELECT id, name, description, notes, entity_affinity FROM tag_type WHERE LOWER(TRIM(name)) = LOWER(TRIM(%(name)s)) LIMIT 1",
        {"name": name},
        return_type="single_row"
    )
    if not row:
        return None
    ea = row.get("entity_affinity")
    if isinstance(ea, str):
        try:
            ea = json.loads(ea)
        except (json.JSONDecodeError, TypeError):
            ea = None
    return ITagType(id=row["id"], name=row["name"], description=row.get("description"),
                    notes=row.get("notes"), entity_affinity=ea)


def get_tag_by_name_and_type(name: str, tag_type_id: Optional[int]) -> Optional[ITagDetail]:
    if tag_type_id is not None:
        row = db.execute_query(
            "SELECT t.id, t.name, t.description, t.tag_type_id, t.quick_access, tt.name AS tag_type_name "
            "FROM tag t LEFT JOIN tag_type tt ON t.tag_type_id = tt.id "
            "WHERE LOWER(TRIM(t.name)) = LOWER(TRIM(%(name)s)) AND t.tag_type_id = %(type_id)s LIMIT 1",
            {"name": name, "type_id": tag_type_id},
            return_type="single_row"
        )
    else:
        row = db.execute_query(
            "SELECT t.id, t.name, t.description, t.tag_type_id, t.quick_access, tt.name AS tag_type_name "
            "FROM tag t LEFT JOIN tag_type tt ON t.tag_type_id = tt.id "
            "WHERE LOWER(TRIM(t.name)) = LOWER(TRIM(%(name)s)) AND t.tag_type_id IS NULL LIMIT 1",
            {"name": name},
            return_type="single_row"
        )
    if not row:
        return None
    return ITagDetail(id=row["id"], name=row["name"], description=row.get("description"),
                      tag_type_id=row.get("tag_type_id"), tag_type_name=row.get("tag_type_name"),
                      quick_access=bool(row.get("quick_access")))


def upsert_tag(name: str, description: Optional[str], tag_type_id: Optional[int],
               quick_access: bool = False) -> tuple[ITagDetail, bool]:
    """Returns (tag, was_created). SELECT-then-INSERT to avoid REPLACE INTO side-effects.
    The name is stripped of leading/trailing whitespace before storing."""
    name = name.strip()
    existing = get_tag_by_name_and_type(name, tag_type_id)
    if existing:
        return existing, False
    tag = create_tag(name, description, tag_type_id, quick_access)
    return tag, True


def add_hierarchy_ignore_duplicate(super_tag_id: int, sub_tag_id: int) -> str:
    """Returns 'added', 'exists', or 'cycle'."""
    if would_create_cycle(super_tag_id, sub_tag_id):
        return "cycle"
    existing = db.execute_query(
        "SELECT id FROM tag_hierarchy WHERE super_tag_id = %(super_id)s AND sub_tag_id = %(sub_id)s",
        {"super_id": super_tag_id, "sub_id": sub_tag_id},
        return_type="single_row"
    )
    if existing:
        return "exists"
    db.execute_query(
        "INSERT INTO tag_hierarchy (super_tag_id, sub_tag_id) VALUES (%(super_id)s, %(sub_id)s)",
        {"super_id": super_tag_id, "sub_id": sub_tag_id},
        return_type="none"
    )
    return "added"


# ── Related Account Tag Stats ─────────────────────────────────────────────────

def get_related_account_tag_stats(account_id: int) -> list[ITagStat]:
    rows = db.execute_query(
        """SELECT t.id AS tag_id, t.name AS tag_name, tt.name AS tag_type_name,
                  COUNT(DISTINCT related.account_id) AS count
           FROM (
               -- follow: the account is followed / follows
               SELECT DISTINCT follower_account_id AS account_id
               FROM account_relation WHERE followed_account_id = %(id)s
               UNION
               SELECT DISTINCT followed_account_id
               FROM account_relation WHERE follower_account_id = %(id)s
               UNION
               -- comment: someone commented on the account's post
               SELECT DISTINCT c.account_id
               FROM comment c JOIN post p ON c.post_id = p.id
               WHERE p.account_id = %(id)s AND c.account_id != %(id)s
               UNION
               -- comment: the account commented on someone's post
               SELECT DISTINCT p.account_id
               FROM comment c JOIN post p ON c.post_id = p.id
               WHERE c.account_id = %(id)s AND p.account_id != %(id)s
               UNION
               -- like: someone liked the account's post
               SELECT DISTINCT pl.account_id
               FROM post_like pl JOIN post p ON pl.post_id = p.id
               WHERE p.account_id = %(id)s AND pl.account_id != %(id)s
               UNION
               -- like: the account liked someone's post
               SELECT DISTINCT p.account_id
               FROM post_like pl JOIN post p ON pl.post_id = p.id
               WHERE pl.account_id = %(id)s AND p.account_id != %(id)s
               UNION
               -- tag: the account tagged someone in a post
               SELECT DISTINCT ta.tagged_account_id
               FROM tagged_account ta JOIN post p ON ta.post_id = p.id
               WHERE p.account_id = %(id)s AND ta.tagged_account_id != %(id)s
               UNION
               -- tag: the account tagged someone in media
               SELECT DISTINCT ta.tagged_account_id
               FROM tagged_account ta JOIN media m ON ta.media_id = m.id
               WHERE m.account_id = %(id)s AND ta.tagged_account_id != %(id)s
               UNION
               -- tag: the account was tagged in someone's post
               SELECT DISTINCT p.account_id
               FROM tagged_account ta JOIN post p ON ta.post_id = p.id
               WHERE ta.tagged_account_id = %(id)s AND p.account_id != %(id)s
               UNION
               -- tag: the account was tagged in someone's media
               SELECT DISTINCT m.account_id
               FROM tagged_account ta JOIN media m ON ta.media_id = m.id
               WHERE ta.tagged_account_id = %(id)s AND m.account_id != %(id)s
           ) related
           JOIN account_tag at ON at.account_id = related.account_id
           JOIN tag t ON t.id = at.tag_id
           LEFT JOIN tag_type tt ON tt.id = t.tag_type_id
           GROUP BY t.id, t.name, tt.name
           ORDER BY count DESC
           LIMIT 20""",
        {"id": account_id},
        return_type="rows"
    )
    return [ITagStat(**row) for row in rows]
