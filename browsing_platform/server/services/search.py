from typing import Literal, Optional, Any

from pydantic import BaseModel

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


class SearchResult(BaseModel):
    page: str
    id: int
    title: str
    details: Optional[str]
    thumbnails: Optional[list[str]] = None


def search_base(query: ISearchQuery) -> list[SearchResult]:
    if query.search_mode == "archive_sessions":
        return search_archive_sessions(query)
    elif query.search_mode == "accounts":
        return search_accounts(query)
    elif query.search_mode == "posts":
        return search_posts(query)
    elif query.search_mode == "media":
        return search_media(query)
    else:
        print(f"Search mode {query.search_mode} not implemented yet.")
        return []


def default_fulltext_query(search_term: Optional[str]) -> Optional[str]:
    if not search_term or search_term.strip() == "":
        return None
    if "+" in search_term or "-" in search_term or "*" in search_term:
        return search_term
    return " ".join([f'+"{word}' for word in search_term.split() if word])


def search_archive_sessions(query: ISearchQuery) -> list[SearchResult]:
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
    results = db.execute_query(
        f"""SELECT *
           FROM archive_session
              {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY archiving_timestamp DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    sessions = [ArchiveSession(**row) for row in results]
    return [SearchResult(
        page="archive",
        id=s.id,
        title=f"Archive Session {s.id}",
        details=f"{s.archived_url}" + (f" ({s.notes})" if s.notes else "")
    ) for s in sessions]


def search_accounts(query: ISearchQuery) -> list[SearchResult]:
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
    results = db.execute_query(
        f"""SELECT *
           FROM account
           {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY id DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    accounts = [Account(**row) for row in results]
    return [SearchResult(
        page="account",
        id=a.id,
        title=a.url + (f" ({a.display_name})" if a.display_name else ""),
        details=a.bio or ""
    ) for a in accounts]


def search_posts(query: ISearchQuery) -> list[SearchResult]:
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
    results = db.execute_query(
        f"""SELECT *
           FROM post
           {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY publication_date DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    posts = [Post(**row) for row in results]
    media = get_media_by_posts(posts)
    post_thumbnails: dict[int, list[str]] = {}
    for m in media:
        if m.post_id not in post_thumbnails:
            post_thumbnails[m.post_id] = []
        media_thumbnail = get_media_thumbnail_path(m.thumbnail_path, m.local_url)
        if media_thumbnail:
            post_thumbnails[m.post_id].append(media_thumbnail)
    search_results: list[SearchResult] = []
    for p in posts:
        search_results.append(
            SearchResult(
                page="post",
                id=p.id,
                title=p.url,
                details=(p.caption[:100] + '...') if p.caption and len(p.caption) > 100 else (p.caption or ""),
                thumbnails=post_thumbnails[p.id] if p.id in post_thumbnails else None
            )
        )
    return search_results


def search_media(query: ISearchQuery) -> list[SearchResult]:
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
    results = db.execute_query(
        f"""SELECT *
           FROM media
           {'WHERE ' + ' AND '.join(where_clauses) if len(where_clauses) else ''}
           ORDER BY id DESC
           LIMIT %(limit)s OFFSET %(offset)s""",
        query_args
    )
    media = [Media(**row) for row in results]
    search_results: list[SearchResult] = []
    for m in media:
        media_thumbnail = get_media_thumbnail_path(m.thumbnail_path, m.local_url)
        search_results.append(
            SearchResult(
                page="media",
                id=m.id,
                title=m.url,
                details="",
                thumbnails=[media_thumbnail] if media_thumbnail else None
            )
        )
    return search_results


def sanitize_column(column: str, table: str) -> str:
    column = column.get("var") if isinstance(column, dict) and "var" in column else column
    # TODO: Implement proper sanitization based on allowed columns
    return column


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
                col = sanitize_column(col, table_rec)
                arg_key = f"{col}_eq"
                args_rec[arg_key] = v
                return f"`{col}` = %({arg_key})s"
            if op == "in":
                v, col = val
                col = sanitize_column(col, table_rec)
                arg_key = f"{col}_like"
                args_rec[arg_key] = f'%{v}%'
                return f"`{col}` LIKE %({arg_key})s"
            elif op == "!=":
                col, v = val
                col = sanitize_column(col, table_rec)
                arg_key = f"{col}_neq"
                args_rec[arg_key] = v
                return f"`{col}` != %({arg_key})s"
            elif op == ">":
                if len(val) == 2:
                    col, v = val
                    col = sanitize_column(col, table_rec)
                    arg_key = f"{col}_gt"
                    args_rec[arg_key] = v
                    return f"`{col}` > %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col = sanitize_column(col, table_rec)
                    arg_key1 = f"{col}_gt"
                    arg_key2 = f"{col}_lt"
                    args_rec[arg_key1] = v1
                    args_rec[arg_key2] = v2
                    return f"`{col}` > %({arg_key1})s AND `{col}` < %({arg_key2})s"
            elif op == "<":
                if len(val) == 2:
                    col, v = val
                    col = sanitize_column(col, table_rec)
                    arg_key = f"{col}_lt"
                    args_rec[arg_key] = v
                    return f"`{col}` < %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col = sanitize_column(col, table_rec)
                    arg_key1 = f"{col}_gt"
                    arg_key2 = f"{col}_lt"
                    args_rec[arg_key1] = v1
                    args_rec[arg_key2] = v2
                    return f"`{col}` > %({arg_key1})s AND `{col}` < %({arg_key2})s"
            elif op == "<=":
                if len(val) == 2:
                    col, v = val
                    col = sanitize_column(col, table_rec)
                    arg_key = f"{col}_lte"
                    args_rec[arg_key] = v
                    return f"`{col}` <= %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col = sanitize_column(col, table_rec)
                    arg_key1 = f"{col}_gte"
                    arg_key2 = f"{col}_lte"
                    args_rec[arg_key1] = v1
                    args_rec[arg_key2] = v2
                    return f"`{col}` >= %({arg_key1})s AND `{col}` <= %({arg_key2})s"
            elif op == ">=":
                if len(val) == 2:
                    col, v = val
                    col = sanitize_column(col, table_rec)
                    arg_key = f"{col}_gte"
                    args_rec[arg_key] = v
                    return f"`{col}` >= %({arg_key})s"
                elif len(val) == 3:
                    v1, col, v2 = val
                    col = sanitize_column(col, table_rec)
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
