import logging
from dataclasses import Field
from typing import Literal, Optional, Any
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl

from pydantic import BaseModel, field_validator

from browsing_platform.server.services.file_tokens import generate_file_token
from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS
from db_loaders.thumbnail_generator import LOCAL_THUMBNAILS_DIR_ALIAS

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

from browsing_platform.server.services.archiving_session import ArchiveSession
from browsing_platform.server.services.media import get_media_by_posts, get_media_thumbnail_path
from extractors.entity_types import Account, Post, Media
from utils import db

T_Search_Mode = Literal["media", "posts", "accounts", "archive_sessions", "all"]


class ISearchQuery(BaseModel):
    search_term: Optional[str] = None
    advanced_filters: Optional[dict] = None
    search_mode: T_Search_Mode
    page_number: int
    page_size: int


class SearchResultTransform(BaseModel):
    local_files_root: Optional[str] = None
    access_token: Optional[str] = None


class SearchResult(BaseModel):
    page: str
    id: int
    title: str
    details: Optional[str]
    thumbnails: Optional[list[str]] = None

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


def search_archive_sessions(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    where_clauses = []
    if query.search_term:
        query_args["search_term_match_against"] = default_fulltext_query(query.search_term)
        query_args["search_term_like"] = f'%{query.search_term}%'
        where_clauses.append('''MATCH(`archived_url`, `archived_url_parts`, `notes`) AGAINST (%(search_term_match_against)s IN BOOLEAN MODE) OR 
        `notes` LIKE %(search_term_like)s''')
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "archive_session")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    rows = db.execute_query(
        f"""SELECT *
           FROM archive_session
              {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY archiving_timestamp DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    sessions = [ArchiveSession(**row) for row in rows]
    return [SearchResult(
        page="archive",
        id=s.id,
        title=f"Archive Session {s.id}",
        details=f"{s.archived_url}" + (f" ({s.notes})" if s.notes else "")
    ) for s in sessions]


def search_accounts(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    where_clauses = []
    if query.search_term:
        query_args["search_term"] = default_fulltext_query(query.search_term)
        where_clauses.append("MATCH(`url`, `url_parts`, `bio`, `display_name`, `notes`) AGAINST (%(search_term)s IN BOOLEAN MODE)")
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "account")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    rows = db.execute_query(
        f"""SELECT *
           FROM account
           {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY id DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    accounts = [Account(**row) for row in rows]
    results = [SearchResult(
        page="account",
        id=a.id,
        title=a.url + (f" ({a.display_name})" if a.display_name else ""),
        details=a.bio or ""
    ) for a in accounts]
    results = apply_search_results_transform(results, search_results_transform)
    return results


def search_posts(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    where_clauses = []
    if query.search_term:
        query_args["search_term"] = default_fulltext_query(query.search_term)
        where_clauses.append("MATCH(`url`, `caption`, `notes`) AGAINST (%(search_term)s IN BOOLEAN MODE)")
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "post")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    rows = db.execute_query(
        f"""SELECT *
           FROM post
           {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY publication_date DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    posts = [Post(**row) for row in rows]
    media = get_media_by_posts(posts)
    post_thumbnails: dict[int, list[str]] = {}
    for m in media:
        if m.post_id not in post_thumbnails:
            post_thumbnails[m.post_id] = []
        media_thumbnail = get_media_thumbnail_path(m.thumbnail_path, m.local_url)
        if media_thumbnail:
            post_thumbnails[m.post_id].append(media_thumbnail)
    results: list[SearchResult] = []
    for p in posts:
        results.append(
            SearchResult(
                page="post",
                id=p.id,
                title=p.url,
                details=(p.caption[:100] + '...') if p.caption and len(p.caption) > 100 else (p.caption or ""),
                thumbnails=post_thumbnails[p.id] if p.id in post_thumbnails else None
            )
        )
    results = apply_search_results_transform(results, search_results_transform)
    return results


def search_media(query: ISearchQuery, search_results_transform: SearchResultTransform) -> list[SearchResult]:
    query_args: dict["str", Any] = {
        "limit": query.page_size,
        "offset": (query.page_number - 1) * query.page_size,
    }
    where_clauses = [
        "local_url IS NOT NULL"
    ]
    if query.search_term:
        query_args["search_term"] = default_fulltext_query(query.search_term)
        where_clauses.append("MATCH(`annotation`, `notes`) AGAINST (%(search_term)s IN BOOLEAN MODE)")
    if query.advanced_filters:
        general_filter, general_args = json_logic_format_to_where_clause(query.advanced_filters, "post")
        where_clauses.append(general_filter)
        query_args.update(general_args)
    rows = db.execute_query(
        f"""SELECT *
           FROM media
           {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY id DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    media = [Media(**row) for row in rows]
    results: list[SearchResult] = []
    for m in media:
        media_thumbnail = get_media_thumbnail_path(m.thumbnail_path, m.local_url)
        results.append(
            SearchResult(
                page="media",
                id=m.id,
                title=m.url,
                details="",
                thumbnails=[media_thumbnail] if media_thumbnail else None
            )
        )
    results = apply_search_results_transform(results, search_results_transform)
    return results


def sign_search_result_thumbnails(res: SearchResult, transform: SearchResultTransform) -> SearchResult:
    if not res.thumbnails:
        return res
    for i in range(len(res.thumbnails)):
        thumb: str = res.thumbnails[i]
        if LOCAL_ARCHIVES_DIR_ALIAS in thumb:
            local_path = thumb.replace(LOCAL_ARCHIVES_DIR_ALIAS, f"{transform.local_files_root}/archives", 1)
        if LOCAL_THUMBNAILS_DIR_ALIAS in thumb:
            local_path = thumb.replace(LOCAL_THUMBNAILS_DIR_ALIAS, f"{transform.local_files_root}/thumbnails", 1)
        parsed = urlparse(local_path)
        qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
        qs['ft'] = generate_file_token(
            transform.access_token,
            local_path.split(f"{transform.local_files_root}")[-1]
        )
        new_query = urlencode(qs, doseq=True)
        local_signed_url = str(urlunparse(parsed._replace(query=new_query)))
        res.thumbnails[i] = local_signed_url
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
        ("url", "text"),
        ("display_name", "text"),
        ("bio", "text"),
        ("data", "text"),
        ("notes", "text"),
        ("url_parts", "text"),
    ],
    "archive_session": [
        ("id", "number"),
        ("create_date", "date"),
        ("update_date", "date"),
        ("external_id", "text"),
        ("archived_url", "text"),
        ("archive_location", "text"),
        ("summary_html", "text"),
        ("parsed_content", "number"),
        ("structures", "text"),
        ("metadata", "text"),
        ("extracted_entities", "number"),
        ("archiving_timestamp", "date"),
        ("notes", "text"),
        ("extraction_error", "text"),
        ("source_type", "number"),
        ("attachments", "text"),
        ("archived_url_parts", "text"),
    ],
    "post": [
        ("id", "number"),
        ("create_date", "date"),
        ("update_date", "date"),
        ("id_on_platform", "text"),
        ("url", "text"),
        ("account_id", "number"),
        ("publication_date", "date"),
        ("caption", "text"),
        ("data", "text"),
        ("notes", "text"),
    ],
    "media": [
        ("id", "number"),
        ("create_date", "date"),
        ("update_date", "date"),
        ("id_on_platform", "text"),
        ("url", "text"),
        ("post_id", "number"),
        ("local_url", "text"),
        ("media_type", "text"),
        ("data", "text"),
        ("notes", "text"),
        ("annotation", "text"),
        ("thumbnail_path", "text"),
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

    def parse_logic(logic_rec: dict, args_rec: dict, table_rec: str) -> str:
        if not isinstance(logic_rec, dict):
            raise ValueError("Logic must be a dict")
        for op, val in logic_rec.items():
            if op == "==":
                col, v = val
                col_def = sanitize_column(col, table_rec)
                col = col_def.column_name
                arg_key = f"{col}_eq"
                args_rec[arg_key] = v
                if col_def.data_type == "date":
                    return f"DATE(`{col}`) = DATE(%({arg_key})s)"
                else:
                    return f"`{col}` = %({arg_key})s"
            if op == "in":
                v, col = val
                col_def = sanitize_column(col, table_rec)
                col = col_def.column_name
                arg_key = f"{col}_like"
                args_rec[arg_key] = f'%{v}%'
                return f"`{col}` LIKE %({arg_key})s"
            elif op == "!=":
                col, v = val
                col_def = sanitize_column(col, table_rec)
                col = col_def.column_name
                arg_key = f"{col}_neq"
                args_rec[arg_key] = v
                return f"`{col}` != %({arg_key})s"
            elif op == ">":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = f"{col}_gt"
                    args_rec[arg_key] = v
                    return f"`{col}` > %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = f"{col}_gt"
                    arg_key2 = f"{col}_lt"
                    args_rec[arg_key1] = v1
                    args_rec[arg_key2] = v2
                    return f"`{col}` > %({arg_key1})s AND `{col}` < %({arg_key2})s"
            elif op == "<":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = f"{col}_lt"
                    args_rec[arg_key] = v
                    return f"`{col}` < %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = f"{col}_gt"
                    arg_key2 = f"{col}_lt"
                    args_rec[arg_key1] = v1
                    args_rec[arg_key2] = v2
                    return f"`{col}` > %({arg_key1})s AND `{col}` < %({arg_key2})s"
            elif op == "<=":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = f"{col}_lte"
                    args_rec[arg_key] = v
                    return f"`{col}` <= %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = f"{col}_gte"
                    arg_key2 = f"{col}_lte"
                    args_rec[arg_key1] = v1
                    args_rec[arg_key2] = v2
                    return f"`{col}` >= %({arg_key1})s AND `{col}` <= %({arg_key2})s"
            elif op == ">=":
                if len(val) == 2:
                    col, v = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key = f"{col}_gte"
                    args_rec[arg_key] = v
                    return f"`{col}` >= %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col_def = sanitize_column(col, table_rec)
                    col = col_def.column_name
                    arg_key1 = f"{col}_gte"
                    arg_key2 = f"{col}_lte"
                    args_rec[arg_key1] = v1
                    args_rec[arg_key2] = v2
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
