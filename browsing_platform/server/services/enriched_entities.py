from typing import Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from pydantic import BaseModel

from browsing_platform.server.services.account import get_account_by_id
from browsing_platform.server.services.archiving_session import ArchiveSessionWithEntities, get_archiving_session_by_id, \
    ArchiveSession, censor_archiving_session, ArchivingSessionTransform, sign_archiving_session
from browsing_platform.server.services.entities_hierarchy import nest_entities
from browsing_platform.server.services.file_tokens import generate_file_token
from browsing_platform.server.services.media import get_media_by_posts, get_media_by_id
from browsing_platform.server.services.post import get_post_by_id, get_posts_by_accounts
from browsing_platform.server.services.tag import get_tags_by_entity_ids, ITagWithType
from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS
from db_loaders.thumbnail_generator import LOCAL_THUMBNAILS_DIR_ALIAS
from extractors.entity_types import ExtractedEntitiesNested, Media, ExtractedEntitiesFlattened, Account, Post, \
    Comment, Like, TaggedAccount, AccountRelation
from utils import db


class AccountInteractions(BaseModel):
    comments: list[Comment] = []
    likes: list[Like] = []
    tagged_in: list[TaggedAccount] = []
    account_tags: dict[int, list[ITagWithType]] = {}


class AccountRelationsResponse(BaseModel):
    relations: list[AccountRelation]
    account_tags: dict[int, list[ITagWithType]] = {}


class CommentsResponse(BaseModel):
    comments: list[Comment]
    account_tags: dict[int, list[ITagWithType]] = {}


class LikesResponse(BaseModel):
    likes: list[Like]
    account_tags: dict[int, list[ITagWithType]] = {}


class AccountInteractionCounts(BaseModel):
    comments_count: int = 0
    likes_count: int = 0
    tagged_in_count: int = 0


class AccountAuxiliaryCounts(BaseModel):
    relations_count: int = 0
    interaction_counts: AccountInteractionCounts = AccountInteractionCounts()


class PostAuxiliaryCounts(BaseModel):
    comments_count: int = 0
    likes_count: int = 0


def _build_in_clause(ids: list[int]) -> tuple[dict, str]:
    """Returns (query_args_dict, IN clause string) for a list of int IDs."""
    args = {f"id_{i}": id_ for i, id_ in enumerate(ids)}
    clause = ", ".join(f"%(id_{i})s" for i in range(len(ids)))
    return args, clause


_ACCOUNT_TAG_SELECT = """
    SELECT at.account_id AS entity_id, t.*, at.notes AS assignment_notes,
           tt.name AS tag_type_name, tt.description AS tag_type_description,
           tt.notes AS tag_type_notes, tt.entity_affinity AS tag_type_entity_affinity
    FROM account_tag at
    JOIN tag t ON at.tag_id = t.id
    LEFT JOIN tag_type tt ON t.tag_type_id = tt.id
"""


def _group_tags_by_account_id(rows: list[dict]) -> dict[int, list[ITagWithType]]:
    result: dict[int, list[ITagWithType]] = {}
    for row in rows:
        account_id = row.pop("entity_id")
        result.setdefault(account_id, []).append(ITagWithType(**row))
    return result


def get_account_tags_for_post_comments(post_ids: list[int]) -> dict[int, list[ITagWithType]]:
    """Tags for accounts that commented on the given posts."""
    if not post_ids:
        return {}
    args, clause = _build_in_clause(post_ids)
    rows = db.execute_query(
        f"""SELECT DISTINCT at.account_id AS entity_id, t.*, at.notes AS assignment_notes,
                   tt.name AS tag_type_name, tt.description AS tag_type_description,
                   tt.notes AS tag_type_notes, tt.entity_affinity AS tag_type_entity_affinity
            FROM account_tag at
            JOIN comment c ON at.account_id = c.account_id
            JOIN tag t ON at.tag_id = t.id
            LEFT JOIN tag_type tt ON t.tag_type_id = tt.id
            WHERE c.post_id IN ({clause})""",
        args,
        return_type="rows"
    )
    return _group_tags_by_account_id(rows)


def get_account_tags_for_post_likes(post_id: int) -> dict[int, list[ITagWithType]]:
    """Tags for accounts that liked a post."""
    rows = db.execute_query(
        """SELECT at.account_id AS entity_id, t.*, at.notes AS assignment_notes,
                  tt.name AS tag_type_name, tt.description AS tag_type_description,
                  tt.notes AS tag_type_notes, tt.entity_affinity AS tag_type_entity_affinity
           FROM account_tag at
           JOIN post_like pl ON at.account_id = pl.account_id
           JOIN tag t ON at.tag_id = t.id
           LEFT JOIN tag_type tt ON t.tag_type_id = tt.id
           WHERE pl.post_id = %(post_id)s""",
        {"post_id": post_id},
        return_type="rows"
    )
    return _group_tags_by_account_id(rows)


def get_account_tags_for_account_relations(account_id: int) -> dict[int, list[ITagWithType]]:
    """Tags for all accounts related to a given account (both directions)."""
    rows = db.execute_query(
        """SELECT at.account_id AS entity_id, t.*, at.notes AS assignment_notes,
                  tt.name AS tag_type_name, tt.description AS tag_type_description,
                  tt.notes AS tag_type_notes, tt.entity_affinity AS tag_type_entity_affinity
           FROM account_tag at
           JOIN tag t ON at.tag_id = t.id
           LEFT JOIN tag_type tt ON t.tag_type_id = tt.id
           WHERE at.account_id IN (
               SELECT follower_account_id FROM account_relation
                 WHERE follower_account_id = %(id)s OR followed_account_id = %(id)s
               UNION
               SELECT followed_account_id FROM account_relation
                 WHERE follower_account_id = %(id)s OR followed_account_id = %(id)s
           )""",
        {"id": account_id},
        return_type="rows"
    )
    return _group_tags_by_account_id(rows)


def get_account_tags_for_tagged_accounts(post_ids: list[int]) -> dict[int, list[ITagWithType]]:
    """Tags for tagged_account_id values in the given posts."""
    if not post_ids:
        return {}
    args, clause = _build_in_clause(post_ids)
    rows = db.execute_query(
        f"""SELECT DISTINCT at.account_id AS entity_id, t.*, at.notes AS assignment_notes,
                   tt.name AS tag_type_name, tt.description AS tag_type_description,
                   tt.notes AS tag_type_notes, tt.entity_affinity AS tag_type_entity_affinity
            FROM account_tag at
            JOIN tagged_account ta ON at.account_id = ta.tagged_account_id
            JOIN tag t ON at.tag_id = t.id
            LEFT JOIN tag_type tt ON t.tag_type_id = tt.id
            WHERE ta.post_id IN ({clause})""",
        args,
        return_type="rows"
    )
    return _group_tags_by_account_id(rows)


def get_comments_by_post_ids(post_ids: list[int]) -> list[Comment]:
    if not post_ids:
        return []
    args, clause = _build_in_clause(post_ids)
    rows = db.execute_query(
        f"""SELECT c.*, a.url_suffix AS account_url_suffix, a.platform AS platform,
                   a.id_on_platform AS account_id_on_platform,
                   a.display_name AS account_display_name,
                   p.url_suffix AS post_url_suffix, p.id_on_platform AS post_id_on_platform
            FROM comment c
            LEFT JOIN account a ON c.account_id = a.id
            LEFT JOIN post p ON c.post_id = p.id
            WHERE c.post_id IN ({clause})
            ORDER BY c.publication_date""",
        args,
        return_type="rows"
    )
    return [Comment(**r) for r in rows]


def get_tagged_accounts_by_post_ids(post_ids: list[int]) -> list[TaggedAccount]:
    if not post_ids:
        return []
    args, clause = _build_in_clause(post_ids)
    rows = db.execute_query(
        f"""SELECT ta.*, a.url_suffix AS tagged_account_url_suffix, a.platform AS platform,
                   a.id_on_platform AS tagged_account_id_on_platform,
                   a.display_name AS tagged_account_display_name
            FROM tagged_account ta
            LEFT JOIN account a ON ta.tagged_account_id = a.id
            WHERE ta.post_id IN ({clause})""",
        args,
        return_type="rows"
    )
    return [TaggedAccount(**r) for r in rows]


def get_likes_by_post_id(post_id: int) -> list[Like]:
    rows = db.execute_query(
        """SELECT pl.*, a.url_suffix AS account_url_suffix, a.platform AS platform,
                  a.id_on_platform AS account_id_on_platform,
                  a.display_name AS account_display_name,
                  p.url_suffix AS post_url_suffix, p.id_on_platform AS post_id_on_platform
           FROM post_like pl
           LEFT JOIN account a ON pl.account_id = a.id
           LEFT JOIN post p ON pl.post_id = p.id
           WHERE pl.post_id = %(post_id)s""",
        {"post_id": post_id},
        return_type="rows"
    )
    return [Like(**r) for r in rows]


def get_account_relations_by_account_id(account_id: int) -> list[AccountRelation]:
    rows = db.execute_query(
        """SELECT ar.*,
                  fa.url_suffix AS follower_account_url_suffix, fa.platform AS platform,
                  fa.id_on_platform AS follower_account_id_on_platform,
                  fa.display_name AS follower_account_display_name,
                  fd.url_suffix AS followed_account_url_suffix,
                  fd.id_on_platform AS followed_account_id_on_platform,
                  fd.display_name AS followed_account_display_name
           FROM account_relation ar
           LEFT JOIN account fa ON ar.follower_account_id = fa.id
           LEFT JOIN account fd ON ar.followed_account_id = fd.id
           WHERE ar.follower_account_id = %(id)s OR ar.followed_account_id = %(id)s""",
        {"id": account_id},
        return_type="rows"
    )
    return [AccountRelation(**r) for r in rows]


def get_interactions_by_account_id(account_id: int) -> AccountInteractions:
    comment_rows = db.execute_query(
        """SELECT c.*, a.url_suffix AS account_url_suffix, a.platform AS platform,
                  a.id_on_platform AS account_id_on_platform,
                  a.display_name AS account_display_name,
                  p.url_suffix AS post_url_suffix, p.id_on_platform AS post_id_on_platform,
                  p.publication_date AS post_publication_date,
                  pa.id AS post_author_account_id,
                  pa.url_suffix AS post_author_url_suffix,
                  pa.display_name AS post_author_display_name
           FROM comment c
           LEFT JOIN account a ON c.account_id = a.id
           LEFT JOIN post p ON c.post_id = p.id
           LEFT JOIN account pa ON p.account_id = pa.id
           WHERE c.account_id = %(id)s
           ORDER BY c.publication_date""",
        {"id": account_id},
        return_type="rows"
    )
    like_rows = db.execute_query(
        """SELECT pl.*, a.url_suffix AS account_url_suffix, a.platform AS platform,
                  a.id_on_platform AS account_id_on_platform,
                  a.display_name AS account_display_name,
                  p.url_suffix AS post_url_suffix, p.id_on_platform AS post_id_on_platform,
                  p.publication_date AS post_publication_date,
                  pa.id AS post_author_account_id,
                  pa.url_suffix AS post_author_url_suffix,
                  pa.display_name AS post_author_display_name
           FROM post_like pl
           LEFT JOIN account a ON pl.account_id = a.id
           LEFT JOIN post p ON pl.post_id = p.id
           LEFT JOIN account pa ON p.account_id = pa.id
           WHERE pl.account_id = %(id)s""",
        {"id": account_id},
        return_type="rows"
    )
    tagged_rows = db.execute_query(
        """SELECT ta.*, a.url_suffix AS tagged_account_url_suffix, a.platform AS platform,
                  a.id_on_platform AS tagged_account_id_on_platform,
                  a.display_name AS tagged_account_display_name,
                  p.url_suffix AS context_post_url_suffix, p.id_on_platform AS context_post_id_on_platform,
                  p.publication_date AS post_publication_date,
                  pa.id AS post_author_account_id,
                  pa.url_suffix AS post_author_url_suffix,
                  pa.display_name AS post_author_display_name,
                  m.url_suffix AS context_media_url_suffix, m.id_on_platform AS context_media_id_on_platform
           FROM tagged_account ta
           LEFT JOIN account a ON ta.tagged_account_id = a.id
           LEFT JOIN post p ON ta.post_id = p.id
           LEFT JOIN account pa ON p.account_id = pa.id
           LEFT JOIN media m ON ta.media_id = m.id
           WHERE ta.tagged_account_id = %(id)s""",
        {"id": account_id},
        return_type="rows"
    )
    return AccountInteractions(
        comments=[Comment(**r) for r in comment_rows],
        likes=[Like(**r) for r in like_rows],
        tagged_in=[TaggedAccount(**r) for r in tagged_rows],
        account_tags=get_tags_by_entity_ids('account', [account_id])
    )


def get_account_auxiliary_counts(account_id: int) -> AccountAuxiliaryCounts:
    relations_row = db.execute_query(
        """SELECT COUNT(*) AS relations_count FROM account_relation
           WHERE follower_account_id = %(id)s OR followed_account_id = %(id)s""",
        {"id": account_id},
        return_type="single_row"
    )
    interactions_row = db.execute_query(
        """SELECT
             (SELECT COUNT(*) FROM comment WHERE account_id = %(id)s) AS comments_count,
             (SELECT COUNT(*) FROM post_like WHERE account_id = %(id)s) AS likes_count,
             (SELECT COUNT(*) FROM tagged_account WHERE tagged_account_id = %(id)s) AS tagged_in_count""",
        {"id": account_id},
        return_type="single_row"
    )
    return AccountAuxiliaryCounts(
        relations_count=relations_row["relations_count"],
        interaction_counts=AccountInteractionCounts(**interactions_row)
    )


def get_post_auxiliary_counts(post_id: int) -> PostAuxiliaryCounts:
    row = db.execute_query(
        """SELECT
             (SELECT COUNT(*) FROM comment WHERE post_id = %(id)s) AS comments_count,
             (SELECT COUNT(*) FROM post_like WHERE post_id = %(id)s) AS likes_count""",
        {"id": post_id},
        return_type="single_row"
    )
    return PostAuxiliaryCounts(**row)


class FlattenedEntitiesTransform(BaseModel):
    local_files_root: Optional[str] = None
    access_token: Optional[str] = None
    retain_only_media_with_local_files: bool = False
    strip_raw_data: bool = True


def apply_flattened_entities_transform(
        entities: ExtractedEntitiesFlattened,
        transform: FlattenedEntitiesTransform
) -> ExtractedEntitiesFlattened:
    if transform.retain_only_media_with_local_files:
        entities.media = [
            m for m in entities.media if m.local_url is not None and m.local_url.strip() != ""
        ]
    if transform.local_files_root is not None:
        for m in entities.media:
            if m.local_url is not None and m.local_url.strip() != "":
                if m.local_url.startswith(f"{LOCAL_ARCHIVES_DIR_ALIAS}/"):
                    m.local_url = m.local_url.replace(LOCAL_ARCHIVES_DIR_ALIAS, f"{transform.local_files_root}/archives", 1)
            if m.thumbnail_path is not None and m.thumbnail_path.strip() != "":
                if m.thumbnail_path.startswith(f"{LOCAL_ARCHIVES_DIR_ALIAS}/"):
                    m.thumbnail_path = m.thumbnail_path.replace(LOCAL_ARCHIVES_DIR_ALIAS, f"{transform.local_files_root}/archives", 1)
                elif m.thumbnail_path.startswith(f"{LOCAL_THUMBNAILS_DIR_ALIAS}/"):
                    m.thumbnail_path = m.thumbnail_path.replace(LOCAL_THUMBNAILS_DIR_ALIAS, f"{transform.local_files_root}/thumbnails", 1)
    if transform.access_token is not None:
        for m in entities.media:
            if m.local_url is not None and m.local_url.strip() != "":
                parsed = urlparse(m.local_url)
                qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
                qs['ft'] = generate_file_token(transform.access_token, parsed.path)
                new_query = urlencode(qs, doseq=True)
                m.local_url = str(urlunparse(parsed._replace(query=new_query)))
            if m.thumbnail_path is not None and m.thumbnail_path.strip() != "":
                parsed_t = urlparse(m.thumbnail_path)
                qs_t = dict(parse_qsl(parsed_t.query, keep_blank_values=True))
                qs_t['ft'] = generate_file_token(transform.access_token, parsed_t.path)
                m.thumbnail_path = str(urlunparse(parsed_t._replace(query=urlencode(qs_t, doseq=True))))
    if transform.strip_raw_data:
        for a in entities.accounts:
            a.data = None
        for p in entities.posts:
            p.data = None
        for m in entities.media:
            m.data = None
    return entities


class NestedEntitiesTransform(BaseModel):
    retain_only_posts_with_media: bool = False
    retain_only_accounts_with_posts: bool = False


def apply_nested_entities_transform(
        entities: ExtractedEntitiesNested,
        transform: NestedEntitiesTransform
) -> ExtractedEntitiesNested:
    if transform.retain_only_posts_with_media:
        entities.posts = [
            p for p in entities.posts if p.post_media and len(p.post_media) > 0
        ]
        for account in entities.accounts:
            account.account_posts = [
                p for p in account.account_posts if p.post_media and len(p.post_media) > 0
            ]
    if transform.retain_only_accounts_with_posts:
        entities.accounts = [
            a for a in entities.accounts if a.account_posts and len(a.account_posts) > 0
        ]
    return entities


class EntitiesTransformConfig(BaseModel):
    flattened_entities_transform: Optional[FlattenedEntitiesTransform] = None
    nested_entities_transform: Optional[NestedEntitiesTransform] = None
    cluster_posts_under_accounts: bool = True
    include_tags: bool = True


def transform_and_nest(
        flattened_entities: ExtractedEntitiesFlattened,
        config: Optional[EntitiesTransformConfig] = None
) -> ExtractedEntitiesNested:
    if config and config.flattened_entities_transform:
        flattened_entities = apply_flattened_entities_transform(
            flattened_entities,
            config.flattened_entities_transform
        )
    if config and config.include_tags:
        account_ids = [a.id for a in flattened_entities.accounts if a.id is not None]
        post_ids = [p.id for p in flattened_entities.posts if p.id is not None]
        media_ids = [m.id for m in flattened_entities.media if m.id is not None]
        accounts_tags = get_tags_by_entity_ids("account", account_ids)
        posts_tags = get_tags_by_entity_ids("post", post_ids)
        media_tags = get_tags_by_entity_ids("media", media_ids)
        for a in flattened_entities.accounts:
            if a.id in accounts_tags:
                a.tags = accounts_tags[a.id]
        for p in flattened_entities.posts:
            if p.id in posts_tags:
                p.tags = posts_tags[p.id]
        for m in flattened_entities.media:
            if m.id in media_tags:
                m.tags = media_tags[m.id]
    nested_entities = nest_entities(flattened_entities)
    if config and config.nested_entities_transform:
        nested_entities = apply_nested_entities_transform(
            nested_entities,
            config.nested_entities_transform
        )
    return nested_entities


def _include_data(config: Optional[EntitiesTransformConfig]) -> bool:
    return not (
        config is not None
        and config.flattened_entities_transform is not None
        and config.flattened_entities_transform.strip_raw_data
    )


def get_enriched_media_by_id(
        media_id: int,
        config: Optional[EntitiesTransformConfig] = None
) -> Optional[ExtractedEntitiesNested]:
    include_data = _include_data(config)
    media = get_media_by_id(media_id, include_data=include_data)
    if media is None:
        return None
    post = get_post_by_id(media.post_id, include_data=include_data)
    account = get_account_by_id(post.account_id, include_data=include_data) if post else None

    post_ids = [post.id] if post else []
    tagged_accounts = get_tagged_accounts_by_post_ids(post_ids)

    accounts = [account] if account else []
    posts = [post] if post else []
    flattened_entities = ExtractedEntitiesFlattened(
        accounts=accounts,
        posts=posts,
        media=[media],
        tagged_accounts=tagged_accounts
    )
    nested_entities = transform_and_nest(flattened_entities, config)
    return nested_entities


def get_enriched_post_by_id(
        post_id: int,
        config: Optional[EntitiesTransformConfig] = None
) -> Optional[ExtractedEntitiesNested]:
    include_data = _include_data(config)
    post = get_post_by_id(post_id, include_data=include_data)
    if post is None:
        return None
    account = get_account_by_id(post.account_id, include_data=include_data)
    media = get_media_by_posts([post], include_data=include_data)
    comments = get_comments_by_post_ids([post_id])
    tagged_accounts = get_tagged_accounts_by_post_ids([post_id])

    accounts = [account] if account else []
    flattened_entities = ExtractedEntitiesFlattened(
        accounts=accounts,
        posts=[post],
        media=media,
        comments=comments,
        tagged_accounts=tagged_accounts
    )
    nested_entities = transform_and_nest(flattened_entities, config)
    nested_entities.account_tags = {
        **get_account_tags_for_post_comments([post_id]),
        **get_account_tags_for_tagged_accounts([post_id]),
    }
    return nested_entities


def get_enriched_account_by_id(
        account_id: int,
        config: Optional[EntitiesTransformConfig] = None
) -> Optional[ExtractedEntitiesNested]:
    include_data = _include_data(config)
    account = get_account_by_id(account_id, include_data=include_data)
    if account is None:
        return None
    posts = get_posts_by_accounts([account], include_data=include_data)
    media = get_media_by_posts(posts, include_data=include_data)
    post_ids = [p.id for p in posts if p.id is not None]
    tagged_accounts = get_tagged_accounts_by_post_ids(post_ids)

    flattened_entities = ExtractedEntitiesFlattened(
        accounts=[account],
        posts=posts,
        media=media,
        tagged_accounts=tagged_accounts
    )
    nested_entities = transform_and_nest(flattened_entities, config)
    if post_ids:
        nested_entities.account_tags = get_account_tags_for_tagged_accounts(post_ids)
    return nested_entities


def get_enriched_archiving_session_by_id(
        session_id: int,
        entities_transform: Optional[EntitiesTransformConfig] = None,
        session_transform: Optional[ArchivingSessionTransform] = None
) -> Optional[ArchiveSessionWithEntities]:
    session = get_archiving_session_by_id(session_id)
    if session is None:
        return None
    session = apply_sessions_transform([session], session_transform)[0]
    account_rows = db.execute_query(
        """SELECT a.id, aa.url_suffix, aa.platform, aa.archive_session_id, aa.display_name, aa.bio
           FROM account_archive AS aa
                    LEFT JOIN account AS a ON aa.canonical_id = a.id
           WHERE archive_session_id = %(id)s
        """,
        {"id": session_id},
        return_type="rows"
    )
    post_rows = db.execute_query(
        """SELECT p.id, p.account_id, pa.url_suffix, pa.platform, pa.archive_session_id, pa.caption, pa.publication_date, pa.data
           FROM post_archive AS pa
                    LEFT JOIN post AS p ON pa.canonical_id = p.id
           WHERE archive_session_id = %(id)s
        """,
        {"id": session_id},
        return_type="rows"
    )
    media_rows = db.execute_query(
        """SELECT m.id, m.post_id, ma.url_suffix, ma.platform, ma.local_url, ma.archive_session_id, ma.media_type, ma.data
           FROM media_archive AS ma
                    LEFT JOIN media AS m ON ma.canonical_id = m.id
           WHERE archive_session_id = %(id)s
        """,
        {"id": session_id},
        return_type="rows"
    )
    accounts = [Account(**a) for a in account_rows]
    posts = [Post(**p) for p in post_rows]
    media = [Media(**m) for m in media_rows]

    # Flatten and nest entities
    flattened_entities = ExtractedEntitiesFlattened(
        accounts=accounts,
        posts=posts,
        media=media
    )
    nested_entities = transform_and_nest(flattened_entities, entities_transform)
    return ArchiveSessionWithEntities(
        session=session,
        entities=nested_entities
    )


def apply_sessions_transform(
        sessions: list[ArchiveSession],
        transform: ArchivingSessionTransform
) -> list[ArchiveSession]:
    if transform.access_token is not None:
        sessions = [sign_archiving_session(s, transform) for s in sessions]
    if transform.properties_to_censor:
        sessions = [censor_archiving_session(s, transform.properties_to_censor) for s in sessions]
    return sessions


def get_archiving_sessions_by_account_id(
        account_id: int,
        transform: ArchivingSessionTransform
) -> list[ArchiveSession]:
    # fetching all sessions in which at least one post from the account was archived
    # additional sessions in which only the account was archived are not included,
    # in order not to confuse users through the inclusions of content the account merely engaged with
    account = get_account_by_id(account_id)
    if account is None:
        return []
    posts = get_posts_by_accounts([account])
    if not posts or len(posts) == 0:
        return []
    post_ids = [p.id for p in posts]
    query_args = {f"post_id_{i}": f"{post_id}" for i, post_id in enumerate(post_ids)}
    query_in_clause = ', '.join([f"%(post_id_{i})s" for i in range(len(post_ids))])
    session_rows = db.execute_query(
        f"""SELECT DISTINCT a_s.id, a_s.create_date, a_s.update_date, a_s.external_id,
                   a_s.archived_url_suffix, a_s.platform, a_s.archive_location, a_s.parse_algorithm_version,
                   a_s.metadata, a_s.attachments, a_s.extract_algorithm_version,
                   a_s.archiving_timestamp, a_s.notes, a_s.extraction_error,
                   a_s.source_type, a_s.incorporation_status
            FROM archive_session AS a_s
            LEFT JOIN post_archive AS p_a ON a_s.id = p_a.archive_session_id
            WHERE p_a.canonical_id IN ({query_in_clause})
        """,
        query_args,
        return_type="rows"
    )
    sessions = [ArchiveSession(**s) for s in session_rows]
    sessions = apply_sessions_transform(sessions, transform)
    return sessions


def get_archiving_sessions_by_post_id(
        post_id: int,
        transform: ArchivingSessionTransform
) -> list[ArchiveSession]:
    post = get_post_by_id(post_id)
    if post is None:
        return []
    session_rows = db.execute_query(
        """SELECT a_s.id, a_s.create_date, a_s.update_date, a_s.external_id,
                  a_s.archived_url_suffix, a_s.platform, a_s.archive_location, a_s.parse_algorithm_version,
                  a_s.metadata, a_s.attachments, a_s.extract_algorithm_version,
                  a_s.archiving_timestamp, a_s.notes, a_s.extraction_error,
                  a_s.source_type, a_s.incorporation_status
            FROM archive_session AS a_s
            LEFT JOIN post_archive AS p_a ON a_s.id = p_a.archive_session_id
            WHERE p_a.canonical_id = %(post_id)s
        """,
        {"post_id": post_id},
        return_type="rows"
    )
    sessions = [ArchiveSession(**s) for s in session_rows]
    sessions = apply_sessions_transform(sessions, transform)
    return sessions


def get_archiving_sessions_by_media_id(
        media_id: int,
        transform: ArchivingSessionTransform
) -> list[ArchiveSession]:
    media = db.execute_query(
        """SELECT id FROM media WHERE id = %(id)s""",
        {"id": media_id},
        return_type="single_row"
    )
    if media is None:
        return []
    session_rows = db.execute_query(
        """SELECT a_s.id, a_s.create_date, a_s.update_date, a_s.external_id,
                  a_s.archived_url_suffix, a_s.platform, a_s.archive_location, a_s.parse_algorithm_version,
                  a_s.metadata, a_s.attachments, a_s.extract_algorithm_version,
                  a_s.archiving_timestamp, a_s.notes, a_s.extraction_error,
                  a_s.source_type, a_s.incorporation_status
            FROM archive_session AS a_s
            LEFT JOIN media_archive AS m_a ON a_s.id = m_a.archive_session_id
            WHERE m_a.canonical_id = %(media_id)s""",
        {"media_id": media_id},
        return_type="rows"
    )
    sessions = [ArchiveSession(**s) for s in session_rows]
    sessions = apply_sessions_transform(sessions, transform)
    return sessions

