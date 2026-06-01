import logging
import re
from typing import Literal, Optional, Any
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl

from pydantic import BaseModel, field_validator

from browsing_platform.server.services.file_tokens import generate_file_token
from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS
from db_loaders.thumbnail_generator import LOCAL_THUMBNAILS_DIR_ALIAS

logger = logging.getLogger(__name__)

from browsing_platform.server.services.media import get_media_thumbnail_path
from extractors.entity_types import reconstruct_url, parse_search_url
from utils import db

T_Search_Mode = Literal["media", "posts", "accounts", "archive_sessions", "all"]


class ISearchQuery(BaseModel):
    search_term: Optional[str] = None
    advanced_filters: Optional[dict] = None
    search_mode: T_Search_Mode
    page_number: int
    page_size: int
    tag_ids: Optional[list[int]] = None
    tag_filter_mode: Optional[Literal["any", "all"]] = None
    tag_scopes: Optional[list[str]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = None


class SearchResultTransform(BaseModel):
    local_files_root: Optional[str] = None
    access_token: Optional[str] = None


class Thumbnail(BaseModel):
    src: str
    aspect_ratio: Optional[float] = None


class SearchResult(BaseModel):
    page: str
    id: int
    title: str
    details: Optional[str]
    thumbnails: Optional[list[Thumbnail]] = None
    metadata: Optional[dict] = None

    @field_validator('thumbnails', mode='before')
    def parse_thumbnails(cls, v, _):
        if not v:
            v = []
        return v


def search_base(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    if query.search_mode == "archive_sessions":
        return search_archive_sessions(query, search_results_transform)
    elif query.search_mode == "accounts":
        return search_accounts(query, search_results_transform)
    elif query.search_mode == "posts":
        return search_posts(query, search_results_transform)
    elif query.search_mode == "media":
        return search_media(query, search_results_transform)
    else:
        print(f"Search mode {query.search_mode} not implemented yet.")
        return []


def default_fulltext_query(search_term: Optional[str]) -> Optional[str]:
    if not search_term or search_term.strip() == "":
        return None
    if "+" in search_term or "-" in search_term or "*" in search_term:
        return search_term
    return " ".join([f'+"{word}"' for word in search_term.split() if word])


# Whitelist of user-selectable sort columns per search mode. Values are table-qualified to
# match where each ORDER BY is injected (accounts: outer query on `account`;
# posts/media: inner subquery on `post`/`media`).
SORTABLE_COLUMNS: dict[str, dict[str, str]] = {
    "accounts": {"id": "account.id", "url_suffix": "account.url_suffix", "display_name": "account.display_name"},
    "posts":    {"id": "post.id", "publication_date": "post.publication_date"},
    "media":    {"id": "media.id", "publication_date": "media.publication_date"},
}


def resolve_order_by(search_mode: str, sort_by: Optional[str], sort_order: Optional[str], fallback: str) -> str:
    """Return an ORDER BY expression for an explicit user sort, or `fallback` when none/invalid.
    The column expression is taken only from the SORTABLE_COLUMNS whitelist and the direction is
    clamped to ASC/DESC, so the result is injection-safe (consistent with sanitize_column)."""
    cols = SORTABLE_COLUMNS.get(search_mode, {})
    if sort_by and sort_by in cols:
        direction = "ASC" if (sort_order or "").lower() == "asc" else "DESC"
        return f"{cols[sort_by]} {direction}"
    return fallback


def search_archive_sessions(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    where_clauses = []
    if query.search_term:
        parsed_url = parse_search_url(query.search_term)
        if parsed_url:
            # Full platform URL → exact suffix + platform match
            query_args["p_suffix"]   = parsed_url.suffix
            query_args["p_platform"] = parsed_url.platform
            where_clauses.append("archived_url_suffix = %(p_suffix)s AND platform = %(p_platform)s")
        else:
            query_args["search_term_match_against"] = default_fulltext_query(query.search_term)
            where_clauses.append("MATCH(`archived_url_suffix`, `archived_url_parts`, `notes`) AGAINST (%(search_term_match_against)s IN BOOLEAN MODE)")
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "archive_session")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    rows = db.execute_query(
        f"""SELECT id, archived_url_suffix, platform, notes, archiving_timestamp
           FROM archive_session
              {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY archiving_timestamp DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args,
        timeout_ms=10_000
    )
    if not rows:
        return []
    session_ids = [row["id"] for row in rows]
    thumb_args = {f"sid_{i}": sid for i, sid in enumerate(session_ids)}
    thumb_in = ", ".join(f"%(sid_{i})s" for i in range(len(session_ids)))
    thumb_rows = db.execute_query(  # nosec B608 - thumb_in contains only %(key)s placeholders
        f"""SELECT archive_session_id, thumbnail_path, local_url, media_count, aspect_ratio
            FROM (
                SELECT ma.archive_session_id, m.thumbnail_path, m.local_url, m.aspect_ratio,
                       COUNT(*) OVER (PARTITION BY ma.archive_session_id) AS media_count,
                       ROW_NUMBER() OVER (PARTITION BY ma.archive_session_id ORDER BY m.id) AS rn
                FROM media_archive ma
                JOIN media m ON ma.canonical_id = m.id
                WHERE ma.archive_session_id IN ({thumb_in})
                  AND m.local_url IS NOT NULL
            ) ranked
            WHERE rn <= 4""",
        thumb_args
    )
    session_thumbnails: dict[int, list[Thumbnail]] = {}
    session_media_count: dict[int, int] = {}
    for t in thumb_rows:
        sid = t["archive_session_id"]
        session_media_count[sid] = t["media_count"]
        src = get_media_thumbnail_path(t["thumbnail_path"], t["local_url"])
        if src:
            session_thumbnails.setdefault(sid, []).append(Thumbnail(src=src, aspect_ratio=t.get("aspect_ratio")))
    results = [
        SearchResult(
            page="archive",
            id=row["id"],
            title=reconstruct_url(row["archived_url_suffix"], row["platform"]) or f"Archive Session {row['id']}",
            details=row["notes"] or "",
            thumbnails=session_thumbnails.get(row["id"]),
            metadata={
                "archiving_timestamp": row["archiving_timestamp"].isoformat() if row["archiving_timestamp"] else None,
                "media_count": session_media_count.get(row["id"], 0),
            }
        )
        for row in rows
    ]
    results = apply_search_results_transform(results, search_results_transform)
    return results


def extract_account_handle(s: str) -> Optional[str]:
    """Return the bare Instagram handle if s looks like '@handle' or 'handle' (no URL prefix).
    Does not parse full URLs — call parse_search_url first for those.
    Returns the handle string without trailing slash, or None."""
    if not s:
        return None
    s = s.strip()
    if s.startswith('@'):
        s = s[1:]
    # Reject anything that looks like a URL — parse_search_url handles those
    if '://' in s or s.lower().startswith('www.') or '.' in s.split('/')[0]:
        return None
    # Strip any trailing path/query noise and take only the first segment
    handle = s.split('/')[0].split('?')[0].split('#')[0].strip()
    if not handle:
        return None
    # Validate basic Instagram username rules: letters, numbers, dot, underscore; up to 30 chars
    if re.fullmatch(r'[A-Za-z0-9._]{1,30}', handle):
        return handle
    return None


# Per (searched entity, tag scope): a SELECT producing (matched_id, root_id) that drives from the
# `tag_desc` descendant CTE into the indexed association table(s), then maps back to the searched
# entity's id. Driving from `tag_desc` (a small set) into `idx_*_tag_id` and the FK indexes keeps
# every branch index-friendly. `media_part` is only ever a tag *source* (never searched), so its
# tags roll up to the parent media's id (and onward to the post/account).
_SCOPE_BRANCHES: dict[tuple[str, str], str] = {
    ("media", "media"):        "SELECT mt.media_id AS matched_id, td.root_id FROM tag_desc td JOIN media_tag mt ON mt.tag_id = td.id",
    ("media", "post"):         "SELECT m.id AS matched_id, td.root_id FROM tag_desc td JOIN post_tag pt ON pt.tag_id = td.id JOIN media m ON m.post_id = pt.post_id",
    ("media", "account"):      "SELECT m.id AS matched_id, td.root_id FROM tag_desc td JOIN account_tag at ON at.tag_id = td.id JOIN media m ON m.account_id = at.account_id",
    ("media", "media_part"):   "SELECT mp.media_id AS matched_id, td.root_id FROM tag_desc td JOIN media_part_tag mpt ON mpt.tag_id = td.id JOIN media_part mp ON mp.id = mpt.media_part_id",
    ("post", "post"):          "SELECT pt.post_id AS matched_id, td.root_id FROM tag_desc td JOIN post_tag pt ON pt.tag_id = td.id",
    ("post", "media"):         "SELECT m.post_id AS matched_id, td.root_id FROM tag_desc td JOIN media_tag mt ON mt.tag_id = td.id JOIN media m ON m.id = mt.media_id WHERE m.post_id IS NOT NULL",
    ("post", "account"):       "SELECT p.id AS matched_id, td.root_id FROM tag_desc td JOIN account_tag at ON at.tag_id = td.id JOIN post p ON p.account_id = at.account_id",
    ("post", "media_part"):    "SELECT m.post_id AS matched_id, td.root_id FROM tag_desc td JOIN media_part_tag mpt ON mpt.tag_id = td.id JOIN media_part mp ON mp.id = mpt.media_part_id JOIN media m ON m.id = mp.media_id WHERE m.post_id IS NOT NULL",
    ("account", "account"):    "SELECT at.account_id AS matched_id, td.root_id FROM tag_desc td JOIN account_tag at ON at.tag_id = td.id",
    ("account", "post"):       "SELECT p.account_id AS matched_id, td.root_id FROM tag_desc td JOIN post_tag pt ON pt.tag_id = td.id JOIN post p ON p.id = pt.post_id WHERE p.account_id IS NOT NULL",
    ("account", "media"):      "SELECT m.account_id AS matched_id, td.root_id FROM tag_desc td JOIN media_tag mt ON mt.tag_id = td.id JOIN media m ON m.id = mt.media_id WHERE m.account_id IS NOT NULL",
    ("account", "media_part"): "SELECT m.account_id AS matched_id, td.root_id FROM tag_desc td JOIN media_part_tag mpt ON mpt.tag_id = td.id JOIN media_part mp ON mp.id = mpt.media_part_id JOIN media m ON m.id = mp.media_id WHERE m.account_id IS NOT NULL",
}

# Allowed tag scopes per searched entity, derived from _SCOPE_BRANCHES so the whitelist can never
# reference a scope that has no branch (which would KeyError below). Insertion order is preserved,
# so the first scope per entity is its own (the default). This is the single backend source of
# truth; it mirrors SCOPE_OPTIONS in the client's lib/tagScopes.ts across the language boundary.
_ALLOWED_SCOPES: dict[str, list[str]] = {}
for _branch_entity, _branch_scope in _SCOPE_BRANCHES:
    _ALLOWED_SCOPES.setdefault(_branch_entity, []).append(_branch_scope)


def build_tag_filter_join(entity: str, tag_ids: list[int], tag_filter_mode: str,
                          tag_scopes: Optional[list[str]] = None) -> tuple[str, dict]:
    """Build a JOIN subquery that filters `entity` rows by tag, expanding each tag to its
    descendants in the hierarchy and consulting tags across one or more related-entity *scopes*.

    A row qualifies for a given tag if any of its associated entities in a selected scope (or the
    entity itself) carries the tag or a descendant of it, so selecting more scopes yields more
    matches. `tag_filter_mode`:
      - "any": match rows reachable from at least one input tag (via any selected scope)
      - "all": match rows where every input tag is satisfied by some selected-scope association
               (tag-level AND, scope-level OR)
    Scopes are intersected against the whitelist for `entity` (preserving its order); an empty or
    invalid selection falls back to `[entity]`, which reproduces the legacy direct-tagging filter.
    """
    allowed = _ALLOWED_SCOPES[entity]
    requested = set(tag_scopes or [entity])
    scopes = [s for s in allowed if s in requested] or [entity]

    args: dict = {}
    # Recursive descendant CTE, carrying root_id so "all" mode can require coverage of every tag.
    seeds = "\n        UNION ALL ".join(
        f"SELECT %(tid_{i})s AS id, %(tid_{i})s AS root_id" for i in range(len(tag_ids))
    )
    for i, tid in enumerate(tag_ids):
        args[f"tid_{i}"] = tid

    branches = "\n        UNION ALL\n        ".join(_SCOPE_BRANCHES[(entity, s)] for s in scopes)

    if tag_filter_mode == "all":
        args["tag_count"] = len(tag_ids)
        having = "\n    HAVING COUNT(DISTINCT root_id) = %(tag_count)s"
    else:
        having = ""

    sql = f"""JOIN (
    WITH RECURSIVE tag_desc AS (
        {seeds}
        UNION ALL
        SELECT th.sub_tag_id, td.root_id
        FROM tag_hierarchy th JOIN tag_desc td ON th.super_tag_id = td.id
    )
    SELECT matched_id FROM (
        {branches}
    ) reach
    GROUP BY matched_id{having}
) _tag_filter ON {entity}.id = _tag_filter.matched_id"""
    return sql, args


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so user input is treated as a literal string.
    Uses '!' as the escape character (declared via ESCAPE '!' in the query)."""
    return value.replace('!', '!!').replace('%', '!%').replace('_', '!_')


def search_accounts(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    where_clauses = []
    has_fulltext = False
    if query.search_term:
        parsed_url = parse_search_url(query.search_term)
        if parsed_url:
            # Full platform URL → exact suffix + platform match, plus identifier fallback
            query_args["p_suffix"]     = parsed_url.suffix
            query_args["p_platform"]   = parsed_url.platform
            query_args["p_identifier"] = f"url_{parsed_url.suffix}"
            where_clauses.append(
                "(url_suffix = %(p_suffix)s AND platform = %(p_platform)s) "
                "OR JSON_CONTAINS(`identifiers`, JSON_QUOTE(%(p_identifier)s))"
            )
        else:
            handle = extract_account_handle(query.search_term)
            if handle:
                # Bare handle / @handle → identifier lookup + fulltext on handle token
                query_args["search_term"]         = default_fulltext_query(handle)
                query_args["account_search_term"] = f"url_{handle}/"
                where_clauses.append(
                    "JSON_CONTAINS(`identifiers`, JSON_QUOTE(%(account_search_term)s)) "
                    "OR MATCH(`url_suffix`, `url_parts`, `bio`, `display_name`) AGAINST (%(search_term)s IN BOOLEAN MODE)"
                )
                has_fulltext = True
            else:
                # Free text → fulltext only
                query_args["search_term"] = default_fulltext_query(query.search_term)
                where_clauses.append(
                    "MATCH(`url_suffix`, `url_parts`, `bio`, `display_name`) AGAINST (%(search_term)s IN BOOLEAN MODE)"
                )
                has_fulltext = True
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "account")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    tag_filter_join = ""
    if query.tag_ids:
        tag_filter_join, tag_filter_args = build_tag_filter_join("account", query.tag_ids, query.tag_filter_mode or "any", query.tag_scopes)
        query_args.update(tag_filter_args)
    order_by = (
        "MATCH(`url_suffix`, `url_parts`, `bio`, `display_name`) AGAINST (%(search_term)s IN BOOLEAN MODE) DESC"
        if has_fulltext else "account.id DESC"
    )
    order_by = resolve_order_by("accounts", query.sort_by, query.sort_order, order_by)
    rows = db.execute_query(  # nosec B608 - tag_filter_join built from safe templates only
        f"""SELECT account.id, account.url_suffix, account.platform, account.display_name, account.bio
           FROM account
           {tag_filter_join}
           {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY {order_by}
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args,
        timeout_ms=10_000
    )
    if not rows:
        return []
    account_ids = [row["id"] for row in rows]
    thumb_args = {f"aid_{i}": aid for i, aid in enumerate(account_ids)}
    thumb_in = ", ".join(f"%(aid_{i})s" for i in range(len(account_ids)))
    thumb_rows = db.execute_query(  # nosec B608 - thumb_in contains only %(key)s placeholders
        f"""SELECT account_id, thumbnail_path, local_url, media_count, aspect_ratio
            FROM (
                SELECT account_id, thumbnail_path, local_url, aspect_ratio,
                       COUNT(*) OVER (PARTITION BY account_id) AS media_count,
                       ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY publication_date DESC) AS rn
                FROM media
                WHERE account_id IN ({thumb_in})
                  AND local_url IS NOT NULL
            ) ranked
            WHERE rn <= 8""",
        thumb_args
    )
    account_thumbnails: dict[int, list[Thumbnail]] = {}
    account_media_count: dict[int, int] = {}
    for t in thumb_rows:
        aid = t["account_id"]
        account_media_count[aid] = t["media_count"]
        src = get_media_thumbnail_path(t["thumbnail_path"], t["local_url"])
        if src:
            account_thumbnails.setdefault(aid, []).append(Thumbnail(src=src, aspect_ratio=t.get("aspect_ratio")))
    results = [SearchResult(
        page="account",
        id=row["id"],
        title=reconstruct_url(row["url_suffix"], row["platform"]) or row["url_suffix"] or "",
        details=row["bio"] or "",
        thumbnails=account_thumbnails.get(row["id"]),
        metadata={"media_count": account_media_count.get(row["id"], 0), "display_name": row["display_name"] or None, "url_suffix": row["url_suffix"] or None},
    ) for row in rows]
    results = apply_search_results_transform(results, search_results_transform)
    return results


def search_posts(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    where_clauses = []
    has_fulltext = False
    if query.search_term:
        parsed_url = parse_search_url(query.search_term)
        if parsed_url:
            # Full platform URL → exact suffix + platform match
            query_args["p_suffix"]   = parsed_url.suffix
            query_args["p_platform"] = parsed_url.platform
            where_clauses.append("url_suffix = %(p_suffix)s AND platform = %(p_platform)s")
        else:
            query_args["search_term"] = default_fulltext_query(query.search_term)
            where_clauses.append("MATCH(`url_suffix`, `caption`) AGAINST (%(search_term)s IN BOOLEAN MODE)")
            has_fulltext = True
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "post")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    tag_filter_join = ""
    if query.tag_ids:
        tag_filter_join, tag_filter_args = build_tag_filter_join("post", query.tag_ids, query.tag_filter_mode or "any", query.tag_scopes)
        query_args.update(tag_filter_args)
    inner_where = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
    order_by = (
        "MATCH(`url_suffix`, `caption`) AGAINST (%(search_term)s IN BOOLEAN MODE) DESC"
        if has_fulltext else "publication_date DESC"
    )
    order_by = resolve_order_by("posts", query.sort_by, query.sort_order, order_by)
    rows = db.execute_query(  # nosec B608 - inner_where, order_by, tag_filter_join built from safe clauses only
        f"""SELECT p.id, p.url_suffix, p.platform, p.id_on_platform, p.caption, p.publication_date,
                   a.display_name AS account_display_name, a.url_suffix AS account_url_suffix, a.platform AS account_platform
           FROM (
               SELECT post.id, post.url_suffix, post.platform, post.id_on_platform, post.caption, post.publication_date, post.account_id
               FROM post
               {tag_filter_join}
               {inner_where}
               ORDER BY {order_by}
               LIMIT %(limit)s OFFSET %(offset)s
           ) p
           LEFT JOIN account a ON p.account_id = a.id""",
        query_args,
        timeout_ms=10_000
    )
    if not rows:
        return []
    post_ids = [row["id"] for row in rows]
    media_args = {f"pid_{i}": pid for i, pid in enumerate(post_ids)}
    media_in = ", ".join(f"%(pid_{i})s" for i in range(len(post_ids)))
    media_rows = db.execute_query(  # nosec B608 - media_in contains only %(key)s placeholders
        f"SELECT post_id, thumbnail_path, local_url, aspect_ratio FROM media WHERE post_id IN ({media_in})",
        media_args
    )
    post_thumbnails: dict[int, list[Thumbnail]] = {}
    for m in media_rows:
        src = get_media_thumbnail_path(m["thumbnail_path"], m["local_url"])
        if src:
            post_thumbnails.setdefault(m["post_id"], []).append(Thumbnail(src=src, aspect_ratio=m.get("aspect_ratio")))
    results = [
        SearchResult(
            page="post",
            id=row["id"],
            title=reconstruct_url(row["url_suffix"], row["platform"]) or row["url_suffix"] or f"item {row['id_on_platform']}",
            details=(row["caption"][:100] + '...') if row["caption"] and len(row["caption"]) > 100 else (row["caption"] or ""),
            thumbnails=post_thumbnails.get(row["id"]),
            metadata={
                "publication_date": row["publication_date"].isoformat() if row["publication_date"] else None,
                "account_display_name": row["account_display_name"],
                "account_url": reconstruct_url(row["account_url_suffix"], row["account_platform"]),
            }
        )
        for row in rows
    ]
    results = apply_search_results_transform(results, search_results_transform)
    return results


def search_media(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    if query.search_term:
        parsed_url = parse_search_url(query.search_term)
    else:
        parsed_url = None
    if parsed_url:
        # CDN URL → exact suffix + platform match (no local_url requirement)
        query_args["p_suffix"]   = parsed_url.suffix
        query_args["p_platform"] = parsed_url.platform
        where_clauses = ["url_suffix = %(p_suffix)s AND platform = %(p_platform)s"]
    else:
        where_clauses = ["local_url IS NOT NULL"]
        if query.search_term:
            query_args["search_term"] = default_fulltext_query(query.search_term)
            where_clauses.append("MATCH(`annotation`) AGAINST (%(search_term)s IN BOOLEAN MODE)")
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "media")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    tag_filter_join = ""
    if query.tag_ids:
        tag_filter_join, tag_filter_args = build_tag_filter_join("media", query.tag_ids, query.tag_filter_mode or "any", query.tag_scopes)
        query_args.update(tag_filter_args)
    inner_where = ' AND '.join(where_clauses)
    order_by = resolve_order_by("media", query.sort_by, query.sort_order, "media.id DESC")
    rows = db.execute_query(  # nosec B608 - inner_where, order_by and tag_filter_join built from safe clauses only
        f"""SELECT m.id, m.thumbnail_path, m.local_url, m.aspect_ratio, m.media_type, m.publication_date,
                   a.display_name AS account_display_name, a.url_suffix AS account_url_suffix, a.platform AS account_platform
           FROM (
               SELECT media.id, media.thumbnail_path, media.local_url, media.aspect_ratio, media.publication_date, media.account_id, media.media_type
               FROM media
               {tag_filter_join}
               WHERE {inner_where}
               ORDER BY {order_by}
               LIMIT %(limit)s OFFSET %(offset)s
           ) m
           LEFT JOIN account a ON m.account_id = a.id""",
        query_args,
        timeout_ms=10_000
    )
    results = [
        SearchResult(
            page="media",
            id=row["id"],
            title=reconstruct_url(row["account_url_suffix"], row["account_platform"]) or "",
            details="",
            thumbnails=[Thumbnail(src=src, aspect_ratio=row.get("aspect_ratio")) for src in [
                get_media_thumbnail_path(row["thumbnail_path"], row["local_url"]),
                row["local_url"],
            ] if src],
            metadata={
                "publication_date": row["publication_date"].isoformat() if row["publication_date"] else None,
                "account_display_name": row["account_display_name"],
                "account_url": reconstruct_url(row["account_url_suffix"], row["account_platform"]),
                "media_type": row["media_type"],
            }
        )
        for row in rows
    ]
    results = apply_search_results_transform(results, search_results_transform)
    return results


def sign_thumbnail_path(path: str, transform: SearchResultTransform) -> str:
    if LOCAL_ARCHIVES_DIR_ALIAS in path:
        local_path = path.replace(LOCAL_ARCHIVES_DIR_ALIAS, f"{transform.local_files_root}/archives", 1)
    elif LOCAL_THUMBNAILS_DIR_ALIAS in path:
        local_path = path.replace(LOCAL_THUMBNAILS_DIR_ALIAS, f"{transform.local_files_root}/thumbnails", 1)
    else:
        local_path = path
    parsed = urlparse(local_path)
    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    qs['ft'] = generate_file_token(
        transform.access_token,
        local_path.split(f"{transform.local_files_root}")[-1]
    )
    return str(urlunparse(parsed._replace(query=urlencode(qs, doseq=True))))


def sign_search_result_thumbnails(res: SearchResult, transform: SearchResultTransform) -> SearchResult:
    if not res.thumbnails:
        return res
    res.thumbnails = [Thumbnail(src=sign_thumbnail_path(t.src, transform), aspect_ratio=t.aspect_ratio) for t in res.thumbnails]
    return res


def apply_search_results_transform(
        results: list[SearchResult],
        transform: SearchResultTransform
) -> list[SearchResult]:
    if transform.access_token is not None:
        results = [sign_search_result_thumbnails(s, transform) for s in results]
    return results


class SearchableColumn(BaseModel):
    column_name: str
    data_type: Literal["text", "number", "date"]


# compact definition: tuples of (column_name, data_type) per table
_ALLOWED_COLUMNS_RAW: dict[str, list[tuple[str, Literal["text", "number", "date"]]]] = {
    "account": [
        ("id", "number"),
        ("create_date", "date"),
        ("update_date", "date"),
        ("id_on_platform", "text"),
        ("url_suffix", "text"),
        ("display_name", "text"),
        ("bio", "text"),
        ("data", "text"),
        ("url_parts", "text"),
        ("post_count", "number"),
    ],
    "archive_session": [
        ("id", "number"),
        ("create_date", "date"),
        ("update_date", "date"),
        ("external_id", "text"),
        ("archived_url_suffix", "text"),
        ("archive_location", "text"),
        ("summary_html", "text"),
        ("parse_algorithm_version", "number"),
        ("structures", "text"),
        ("metadata", "text"),
        ("extract_algorithm_version", "number"),
        ("archiving_timestamp", "date"),
        ("notes", "text"),
        ("extraction_error", "text"),
        ("incorporation_status", "text"),
        ("source_type", "text"),
        ("attachments", "text"),
        ("archived_url_parts", "text"),
    ],
    "post": [
        ("id", "number"),
        ("create_date", "date"),
        ("update_date", "date"),
        ("id_on_platform", "text"),
        ("url_suffix", "text"),
        ("account_id", "number"),
        ("publication_date", "date"),
        ("caption", "text"),
        ("data", "text"),
    ],
    "media": [
        ("id", "number"),
        ("create_date", "date"),
        ("update_date", "date"),
        ("id_on_platform", "text"),
        ("url_suffix", "text"),
        ("post_id", "number"),
        ("local_url", "text"),
        ("media_type", "text"),
        ("data", "text"),
        ("annotation", "text"),
        ("thumbnail_path", "text"),
        ("publication_date", "date"),
    ],
}

# instantiate SearchableColumn objects from the compact raw definition
ALLOWED_COLUMNS: dict[str, dict[str, SearchableColumn]] = {
    table: {name: SearchableColumn(column_name=name, data_type=data_type) for name, data_type in cols}
    for table, cols in _ALLOWED_COLUMNS_RAW.items()
}


def sanitize_column(column: str, table: str) -> SearchableColumn:
    column = column.get("var") if isinstance(column, dict) and "var" in column else column
    if not isinstance(column, str):
        logger.warning(f"SQL injection attempt - column not a string: {type(column)} = {column}")
        raise ValueError(f"Column must be a string, got {type(column)}")
    # Only allow alphanumeric and underscore
    if not column.replace("_", "").isalnum():
        logger.warning(f"SQL injection attempt - invalid characters in column: {column}")
        raise ValueError(f"Invalid column name: {column}")
    # Check against whitelist
    allowed = ALLOWED_COLUMNS.get(table, set())
    if not allowed or column not in allowed:
        logger.warning(f"SQL injection attempt - column '{column}' not in whitelist for table '{table}'")
        raise ValueError(f"Column '{column}' not allowed for table '{table}'")
    logger.debug(f"Column sanitization passed: {table}.{column}")
    return allowed[column]


def json_logic_format_to_where_clause(json_logic: dict, table_name: str) -> tuple[str, dict]:
    """
    Converts a JSONLogic object to a MySQL WHERE clause and argument dict.
    """
    counter = [0]

    def next_key(col: str, suffix: str) -> str:
        counter[0] += 1
        return f"{col}_{suffix}_{counter[0]}"

    def parse_logic(logic_rec: dict, args_rec: dict, table_rec: str) -> str:
        if not isinstance(logic_rec, dict):
            raise ValueError("Logic must be a dict")

        def bind_value(key: str, v: Any, c_def: SearchableColumn) -> None:
            if c_def.data_type == "date" and isinstance(v, str):
                v = v[:10]  # strip time component from ISO-8601 strings e.g. "2024-01-15T00:00:00.000Z"
            args_rec[key] = v

        for op, val in logic_rec.items():
            if op == "==":
                col, v = val
                col_def = sanitize_column(col, table_rec)
                col = col_def.column_name
                arg_key = next_key(col, "eq")
                bind_value(arg_key, v, col_def)
                if col_def.data_type == "date":
                    return f"DATE(`{col}`) = DATE(%({arg_key})s)"
                else:
                    return f"`{col}` = %({arg_key})s"
            if op == "in":
                v, col = val
                col_def = sanitize_column(col, table_rec)
                col = col_def.column_name
                arg_key = next_key(col, "like")
                args_rec[arg_key] = f'%{_escape_like(v)}%'
                return f"`{col}` LIKE %({arg_key})s ESCAPE '!'"
            elif op == "!=":
                col, v = val
                col_def = sanitize_column(col, table_rec)
                col = col_def.column_name
                arg_key = next_key(col, "neq")
                bind_value(arg_key, v, col_def)
                return f"`{col}` != %({arg_key})s"
            elif op == ">":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = next_key(col, "gt")
                    bind_value(arg_key, v, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) > DATE(%({arg_key})s)"
                    return f"`{col}` > %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = next_key(col, "gt")
                    arg_key2 = next_key(col, "lt")
                    bind_value(arg_key1, v1, col_def)
                    bind_value(arg_key2, v2, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) > DATE(%({arg_key1})s) AND DATE(`{col}`) < DATE(%({arg_key2})s)"
                    return f"`{col}` > %({arg_key1})s AND `{col}` < %({arg_key2})s"
            elif op == "<":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = next_key(col, "lt")
                    bind_value(arg_key, v, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) < DATE(%({arg_key})s)"
                    return f"`{col}` < %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = next_key(col, "gt")
                    arg_key2 = next_key(col, "lt")
                    bind_value(arg_key1, v1, col_def)
                    bind_value(arg_key2, v2, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) > DATE(%({arg_key1})s) AND DATE(`{col}`) < DATE(%({arg_key2})s)"
                    return f"`{col}` > %({arg_key1})s AND `{col}` < %({arg_key2})s"
            elif op == "<=":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = next_key(col, "lte")
                    bind_value(arg_key, v, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) <= DATE(%({arg_key})s)"
                    return f"`{col}` <= %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = next_key(col, "gte")
                    arg_key2 = next_key(col, "lte")
                    bind_value(arg_key1, v1, col_def)
                    bind_value(arg_key2, v2, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) >= DATE(%({arg_key1})s) AND DATE(`{col}`) <= DATE(%({arg_key2})s)"
                    return f"`{col}` >= %({arg_key1})s AND `{col}` <= %({arg_key2})s"
            elif op == ">=":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = next_key(col, "gte")
                    bind_value(arg_key, v, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) >= DATE(%({arg_key})s)"
                    return f"`{col}` >= %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = next_key(col, "gte")
                    arg_key2 = next_key(col, "lte")
                    bind_value(arg_key1, v1, col_def)
                    bind_value(arg_key2, v2, col_def)
                    if col_def.data_type == "date":
                        return f"DATE(`{col}`) >= DATE(%({arg_key1})s) AND DATE(`{col}`) <= DATE(%({arg_key2})s)"
                    return f"`{col}` >= %({arg_key1})s AND `{col}` <= %({arg_key2})s"
            elif op == "and":
                clauses = [parse_logic(item, args_rec, table_rec) for item in val]
                return "(" + " AND ".join(clauses) + ")"
            elif op == "or":
                clauses = [parse_logic(item, args_rec, table_rec) for item in val]
                return "(" + " OR ".join(clauses) + ")"
            else:
                raise NotImplementedError(f"Operator {op} not supported")
        raise ValueError("Invalid logic structure")

    args = {}
    where_clause = parse_logic(json_logic, args, table_name)
    return where_clause, args
