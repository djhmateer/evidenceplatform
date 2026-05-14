import json
import logging
from pathlib import Path
from typing import Optional, TypeVar, Generic, Callable, Any

from pydantic import BaseModel, ConfigDict

from extractors.entity_types import EntityBase, ExtractedEntitiesFlattened, Account, Post, Media, Comment, Like, TaggedAccount, AccountRelation
from extractors.reconcile_entities import reconcile_accounts, reconcile_posts, reconcile_media, reconcile_comments, reconcile_likes, reconcile_tagged_accounts, reconcile_account_relations, synthesize_from_archives, reconcile_primitives
from root_anchor import ROOT_ARCHIVES
from utils import db

logger = logging.getLogger(__name__)

LOCAL_ARCHIVES_DIR_ALIAS = 'local_archive_har'
LOCAL_WACZ_ARCHIVES_DIR_ALIAS = "local_archive_wacz"
EntityType = TypeVar("EntityType", bound="EntityBase")


class EntityProcessingConfig(BaseModel, Generic[EntityType]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: str
    table: str
    get_canonical: Callable[[EntityType], Optional[EntityType]]
    get_archive_record: Callable[[int, int], Optional[EntityType]]
    get_all_archives_for_canonical: Callable[[int], list[EntityType]]
    raw_entity_preprocessing: Optional[Callable[[EntityType, Optional[int], Optional[Path]], EntityType]] = None
    store_entity: Callable[[EntityType, Optional[EntityType], Optional[Path]], int]
    store_entity_archive: Callable[[EntityType, int, Optional[int], Optional[int], Optional[Path]], int]
    merge: Callable[[EntityType, Optional[EntityType]], EntityType]
    # Batch variants: replace N individual queries with 1-2 queries per entity type
    batch_get_canonicals: Optional[Any] = None        # (entities) -> list[Optional[entity]]
    batch_get_archive_records: Optional[Any] = None   # (canonical_ids, session_id) -> dict[id, entity]
    batch_get_all_archives: Optional[Any] = None      # (canonical_ids) -> dict[id, list[entity]]
    # Batch INSERT for new entities: replaces N individual INSERTs with 1 multi-row INSERT each
    batch_store_new_entities: Optional[Any] = None       # (entities, archive_location) -> list[int] canonical_ids
    batch_store_new_entity_archives: Optional[Any] = None  # (entities, canonical_ids, session_id, archive_location) -> list[int] archive_ids


# ---------------------------------------------------------------------------
# Generic batch query helpers
# ---------------------------------------------------------------------------

def _is_valid_identifier(value) -> bool:
    """Return False for null-like values that must not be used as entity-match keys.

    Null-like means: Python None, empty string, or the literal string 'None' /
    'None/' which is the f-string artifact of formatting a Python None value.
    Matching multiple distinct entities on a shared null-like identifier would
    incorrectly merge them into the same canonical.
    """
    return bool(value) and str(value).rstrip('/') != 'None'


def batch_get_canonicals_url_and_id(entities: list, table: str, entity_class: type) -> list:
    """One batch lookup for entity types matched by url OR id_on_platform."""
    urls = list({e.url_suffix for e in entities if _is_valid_identifier(getattr(e, 'url_suffix', None))})
    ids = list({e.id_on_platform for e in entities if getattr(e, 'id_on_platform', None)})

    rows: list = []
    if urls:
        ph = ','.join(['%s'] * len(urls))
        rows.extend(db.execute_query(f"SELECT * FROM `{table}` WHERE url_suffix IN ({ph})", urls, return_type="rows") or [])
    if ids:
        ph = ','.join(['%s'] * len(ids))
        rows.extend(db.execute_query(f"SELECT * FROM `{table}` WHERE id_on_platform IN ({ph})", ids, return_type="rows") or [])

    seen: set = set()
    canonicals: list = []
    for row in rows:
        if row['id'] not in seen:
            seen.add(row['id'])
            canonicals.append(entity_class(**row))

    by_url = {c.url_suffix: c for c in canonicals if _is_valid_identifier(getattr(c, 'url_suffix', None))}
    by_id = {c.id_on_platform: c for c in canonicals if getattr(c, 'id_on_platform', None)}
    return [by_url.get(getattr(e, 'url_suffix', None)) or by_id.get(getattr(e, 'id_on_platform', None))
            for e in entities]


def batch_get_canonicals_id_only(entities: list, table: str, entity_class: type) -> list:
    """One batch lookup for entity types matched only by id_on_platform."""
    ids = list({e.id_on_platform for e in entities if getattr(e, 'id_on_platform', None)})
    if not ids:
        return [None] * len(entities)
    ph = ','.join(['%s'] * len(ids))
    rows = db.execute_query(f"SELECT * FROM `{table}` WHERE id_on_platform IN ({ph})", ids, return_type="rows") or []
    by_id = {entity_class(**row).id_on_platform: entity_class(**row) for row in rows}
    return [by_id.get(e.id_on_platform) for e in entities]


def batch_get_archive_records(canonical_ids: list, archive_table: str, archive_session_id: int, entity_class: type) -> dict:
    """One query for all archive records of the given canonicals in the current session."""
    if not canonical_ids:
        return {}
    ph = ','.join(['%s'] * len(canonical_ids))
    rows = db.execute_query(
        f"SELECT * FROM `{archive_table}` WHERE canonical_id IN ({ph}) AND archive_session_id = %s",
        canonical_ids + [archive_session_id],
        return_type="rows"
    ) or []
    return {row['canonical_id']: entity_class(**row) for row in rows}


def batch_get_all_archives(canonical_ids: list, archive_table: str, entity_class: type) -> dict:
    """One query for all archive records of the given canonicals (all sessions)."""
    if not canonical_ids:
        return {}
    ph = ','.join(['%s'] * len(canonical_ids))
    rows = db.execute_query(
        f"SELECT * FROM `{archive_table}` WHERE canonical_id IN ({ph})",
        canonical_ids,
        return_type="rows"
    ) or []
    result: dict = {}
    for row in rows:
        cid = row['canonical_id']
        if cid not in result:
            result[cid] = []
        result[cid].append(entity_class(**row))
    return result


# ---------------------------------------------------------------------------
# Batch FK resolution helpers
# ---------------------------------------------------------------------------

def batch_resolve_account_fks_by_url_and_id(entities: list, url_attr: str, id_attr: str, id_field: str) -> None:
    """Batch-resolve account FK (sets `id_field` on each entity) using url and id_on_platform lookups."""
    urls = list({getattr(e, url_attr) for e in entities if getattr(e, id_field, None) is None and getattr(e, url_attr, None)})
    ids_op = list({getattr(e, id_attr) for e in entities if getattr(e, id_field, None) is None and getattr(e, id_attr, None)})
    by_url, by_id_op = {}, {}
    if urls:
        ph = ','.join(['%s'] * len(urls))
        rows = db.execute_query(f"SELECT id, url_suffix FROM account WHERE url_suffix IN ({ph})", urls, return_type="rows") or []
        by_url = {r['url_suffix']: r['id'] for r in rows}
    if ids_op:
        ph = ','.join(['%s'] * len(ids_op))
        rows = db.execute_query(f"SELECT id, id_on_platform FROM account WHERE id_on_platform IN ({ph})", ids_op, return_type="rows") or []
        by_id_op = {r['id_on_platform']: r['id'] for r in rows}
    for e in entities:
        if getattr(e, id_field, None) is None:
            resolved = by_url.get(getattr(e, url_attr, None)) or by_id_op.get(getattr(e, id_attr, None))
            setattr(e, id_field, resolved)


def batch_resolve_post_fks(entities: list, url_attr: str, id_attr: str, id_field: str) -> None:
    """Batch-resolve post FK (sets `id_field` on each entity) using url and id_on_platform lookups."""
    urls = list({getattr(e, url_attr) for e in entities if getattr(e, id_field, None) is None and getattr(e, url_attr, None)})
    ids_op = list({getattr(e, id_attr) for e in entities if getattr(e, id_field, None) is None and getattr(e, id_attr, None)})
    by_url, by_id_op = {}, {}
    if urls:
        ph = ','.join(['%s'] * len(urls))
        rows = db.execute_query(f"SELECT id, url_suffix FROM post WHERE url_suffix IN ({ph})", urls, return_type="rows") or []
        by_url = {r['url_suffix']: r['id'] for r in rows}
    if ids_op:
        ph = ','.join(['%s'] * len(ids_op))
        rows = db.execute_query(f"SELECT id, id_on_platform FROM post WHERE id_on_platform IN ({ph})", ids_op, return_type="rows") or []
        by_id_op = {r['id_on_platform']: r['id'] for r in rows}
    for e in entities:
        if getattr(e, id_field, None) is None:
            resolved = by_url.get(getattr(e, url_attr, None)) or by_id_op.get(getattr(e, id_attr, None))
            setattr(e, id_field, resolved)


# ---------------------------------------------------------------------------
# Batch INSERT new entities
# ---------------------------------------------------------------------------

def batch_store_new_accounts(new_accounts: list, _) -> list:
    columns = ['url_suffix', 'platform', 'id_on_platform', 'identifiers', 'display_name', 'bio', 'data']
    rows = []
    for a in new_accounts:
        identifiers = []
        if a.id_on_platform:
            identifiers.append(f"id_{a.id_on_platform}")
        if a.url_suffix:
            identifiers.append(f"url_{a.url_suffix}")
        rows.append([a.url_suffix, a.platform, a.id_on_platform, json.dumps(identifiers), a.display_name, a.bio,
                     json.dumps(a.data) if a.data else None])
    return db.batch_insert('account', columns, rows)


def batch_store_new_account_archives(new_accounts: list, canonical_ids: list, archive_session_id: int, _) -> list:
    columns = ['url_suffix', 'platform', 'id_on_platform', 'display_name', 'bio', 'data', 'archive_session_id', 'canonical_id']
    rows = [[a.url_suffix, a.platform, a.id_on_platform, a.display_name, a.bio,
             json.dumps(a.data) if a.data else None, archive_session_id, cid]
            for a, cid in zip(new_accounts, canonical_ids)]
    return db.batch_insert('account_archive', columns, rows)


def batch_store_new_posts(new_posts: list, _) -> list:
    batch_resolve_account_fks_by_url_and_id(new_posts, 'account_url_suffix', 'account_id_on_platform', 'account_id')
    for p in new_posts:
        if p.account_id is None:
            raise ValueError(f"Cannot store post {p.id_on_platform!r}: account not found "
                             f"(url={p.account_url_suffix!r}, id_on_platform={p.account_id_on_platform!r})")
    columns = ['url_suffix', 'platform', 'id_on_platform', 'account_id', 'publication_date', 'caption', 'data']
    rows = [[p.url_suffix, p.platform, p.id_on_platform, p.account_id,
             p.publication_date.isoformat() if p.publication_date else None,
             p.caption, json.dumps(p.data) if p.data else None]
            for p in new_posts]
    return db.batch_insert('post', columns, rows)


def batch_store_new_post_archives(new_posts: list, canonical_ids: list, archive_session_id: int, _) -> list:
    columns = ['url_suffix', 'platform', 'id_on_platform', 'publication_date', 'caption', 'data',
               'archive_session_id', 'canonical_id', 'account_url_suffix', 'account_id_on_platform']
    rows = [[p.url_suffix, p.platform, p.id_on_platform,
             p.publication_date.isoformat() if p.publication_date else None,
             p.caption, json.dumps(p.data) if p.data else None,
             archive_session_id, cid, p.account_url_suffix, p.account_id_on_platform]
            for p, cid in zip(new_posts, canonical_ids)]
    return db.batch_insert('post_archive', columns, rows)


def batch_store_new_media(new_media: list, archive_location) -> list:
    batch_resolve_post_fks(new_media, 'post_url_suffix', 'post_id_on_platform', 'post_id')
    for m in new_media:
        if m.post_id is None:
            raise ValueError(f"Cannot store media {m.id_on_platform!r}: post not found "
                             f"(url={m.post_url_suffix!r}, id_on_platform={m.post_id_on_platform!r})")
    columns = ['url_suffix', 'platform', 'id_on_platform', 'post_id', 'local_url', 'media_type', 'data', 'thumbnail_status']
    rows = [[m.url_suffix, m.platform, m.id_on_platform, m.post_id, m.local_url, m.media_type,
             json.dumps(m.data) if m.data else None, initial_thumbnail_status(m)]
            for m in new_media]
    return db.batch_insert('media', columns, rows)


def batch_store_new_media_archives(new_media: list, canonical_ids: list, archive_session_id: int, _) -> list:
    columns = ['url_suffix', 'platform', 'id_on_platform', 'local_url', 'media_type', 'data',
               'archive_session_id', 'canonical_id', 'post_url_suffix', 'post_id_on_platform']
    rows = [[m.url_suffix, m.platform, m.id_on_platform, m.local_url, m.media_type,
             json.dumps(m.data) if m.data else None,
             archive_session_id, cid, m.post_url_suffix, m.post_id_on_platform]
            for m, cid in zip(new_media, canonical_ids)]
    return db.batch_insert('media_archive', columns, rows)


def batch_store_new_comments(new_comments: list, _) -> list:
    batch_resolve_post_fks(new_comments, 'post_url_suffix', 'post_id_on_platform', 'post_id')
    for c in new_comments:
        if c.post_id is None and (c.post_url or c.post_id_on_platform):
            raise ValueError(f"Cannot store comment {c.id_on_platform!r}: post not found "
                             f"(url={c.post_url_suffix!r}, id_on_platform={c.post_id_on_platform!r})")
    batch_resolve_account_fks_by_url_and_id(new_comments, 'account_url_suffix', 'account_id_on_platform', 'account_id')
    columns = ['id_on_platform', 'url_suffix', 'platform', 'post_id', 'account_id', 'parent_comment_id_on_platform',
               'text', 'publication_date', 'data']
    rows = [[c.id_on_platform, c.url_suffix, c.platform, c.post_id, c.account_id, c.parent_comment_id_on_platform,
             c.text, c.publication_date.isoformat() if c.publication_date else None,
             json.dumps(c.data) if c.data else None]
            for c in new_comments]
    return db.batch_insert('comment', columns, rows)


def batch_store_new_comment_archives(new_comments: list, canonical_ids: list, archive_session_id: int, _) -> list:
    columns = ['id_on_platform', 'url_suffix', 'platform', 'post_url_suffix', 'post_id_on_platform', 'account_id_on_platform',
               'account_url_suffix', 'parent_comment_id_on_platform', 'text', 'publication_date', 'data',
               'archive_session_id', 'canonical_id']
    rows = [[c.id_on_platform, c.url_suffix, c.platform, c.post_url_suffix, c.post_id_on_platform,
             c.account_id_on_platform, c.account_url_suffix, c.parent_comment_id_on_platform,
             c.text, c.publication_date.isoformat() if c.publication_date else None,
             json.dumps(c.data) if c.data else None,
             archive_session_id, cid]
            for c, cid in zip(new_comments, canonical_ids)]
    return db.batch_insert('comment_archive', columns, rows)


def incorporate_structures_into_db(
        structures: ExtractedEntitiesFlattened,
        archive_session_id: int,
        archive_location: Optional[Path]
) -> None:
    """
    Process extracted entities and store them in the database.
    Creates both canonical records and archive-specific records for each entity.

    Re-processing safety: if an archive session is processed more than once, archive
    records for that session are updated in place (no duplicates). The canonical entity
    is then re-synthesized from ALL its archive records (oldest-first, first-non-empty
    wins). Identifier fields (id_on_platform, url) on the canonical are immutable once
    set — re-synthesis can fill them in but never clears them.
    """
    logger.debug(f"Incorporating structures into DB for archive session {archive_session_id}")

    with db.transaction_batch():
        for entity_config in entity_types:
            entities: list = getattr(structures, entity_config.key, [])

            # Posts without an id_on_platform cannot be identified or deduplicated.
            if entity_config.key == "posts":
                valid_entities = [e for e in entities if e.id_on_platform is not None]
                skipped = len(entities) - len(valid_entities)
                if skipped:
                    logger.warning(f"Skipping {skipped} post(s) with no id_on_platform")
                entities = valid_entities

            if entity_config.key in ("likes", "tagged_accounts", "account_relations"):
                valid_entities = [e for e in entities if e.id_on_platform is not None]
                skipped = len(entities) - len(valid_entities)
                if skipped:
                    logger.warning(f"Skipping {skipped} {entity_config.key} with no id_on_platform")
                entities = valid_entities

            # A comment or like that references a post not present in this archive and
            # not previously ingested cannot be linked to its parent. This is a rare
            # Instagram-side artifact (the engagement endpoint loaded without the post
            # endpoint). Drop the affected rows quietly so the rest of the HAR still
            # incorporates rather than failing the whole session.
            if entity_config.key in ("comments", "likes") and entities:
                batch_resolve_post_fks(entities, 'post_url_suffix', 'post_id_on_platform', 'post_id')
                valid_entities = [
                    e for e in entities
                    if not (e.post_id is None and (e.post_url_suffix or e.post_id_on_platform))
                ]
                dropped = len(entities) - len(valid_entities)
                if dropped:
                    logger.warning(
                        f"Dropping {dropped} {entity_config.key} whose parent post is "
                        f"not present in this archive or the database"
                    )
                entities = valid_entities

            if not entities:
                logger.info(f"Processed {entity_config.key}: 0 new, 0 updated")
                continue

            logger.debug(f"Processing {len(entities)} {entity_config.key}")

            # --- Phase 1: Batch-fetch existing canonicals (1-2 queries instead of N) ---
            if entity_config.batch_get_canonicals:
                existing_canonicals = entity_config.batch_get_canonicals(entities)
            else:
                existing_canonicals = [entity_config.get_canonical(e) for e in entities]

            new_entities: list = []
            existing_pairs: list = []  # (entity, existing_canonical)
            for entity, canonical in zip(entities, existing_canonicals):
                if canonical is None:
                    new_entities.append(entity)
                else:
                    existing_pairs.append((entity, canonical))

            # Two extracted entities can resolve to the same DB canonical when each
            # matches it via a different identifier (e.g. one by url_suffix, the other
            # by id_on_platform) and the deduplication step couldn't bridge them.
            # Collapse to one pair per canonical here, merging the observations, so
            # downstream archive insertion doesn't violate uq_<table>_canonical_session.
            if existing_pairs:
                pair_by_canonical_id: dict = {}
                for entity, canonical in existing_pairs:
                    cid = canonical.id
                    prior = pair_by_canonical_id.get(cid)
                    if prior is None:
                        pair_by_canonical_id[cid] = (entity, canonical)
                    else:
                        prior_entity, prior_canonical = prior
                        merged_entity = entity_config.merge(prior_entity, entity)
                        pair_by_canonical_id[cid] = (merged_entity, prior_canonical)
                if len(pair_by_canonical_id) < len(existing_pairs):
                    logger.debug(
                        f"Collapsed {len(existing_pairs) - len(pair_by_canonical_id)} "
                        f"{entity_config.key} that resolved to the same canonical via different identifiers"
                    )
                existing_pairs = list(pair_by_canonical_id.values())

            existing_canonical_ids: list = [c.id for _, c in existing_pairs]

            # --- Phase 2: Batch-fetch archive records; then fetch all archives only for
            #              entities being re-processed. First-time processing uses O(1) merge instead. ---
            if entity_config.batch_get_archive_records and existing_canonical_ids:
                this_session_archive_by_canonical = entity_config.batch_get_archive_records(existing_canonical_ids, archive_session_id)
            else:
                this_session_archive_by_canonical = {c.id: entity_config.get_archive_record(c.id, archive_session_id)
                                                     for _, c in existing_pairs}

            canonical_ids_to_reprocess = [c.id for _, c in existing_pairs if this_session_archive_by_canonical.get(c.id) is not None]
            if canonical_ids_to_reprocess:
                if entity_config.batch_get_all_archives:
                    all_archives_by_canonical = entity_config.batch_get_all_archives(canonical_ids_to_reprocess)
                else:
                    all_archives_by_canonical = {c.id: entity_config.get_all_archives_for_canonical(c.id)
                                                 for _, c in existing_pairs if this_session_archive_by_canonical.get(c.id) is not None}
            else:
                all_archives_by_canonical = {}

            # --- Phase 3: Process new entities ---
            new_count = 0
            if entity_config.batch_store_new_entities and entity_config.batch_store_new_entity_archives and new_entities:
                # Batch path: preprocess all, then multi-row INSERT for canonicals + archives
                preprocessed_new = []
                for entity in new_entities:
                    if entity_config.raw_entity_preprocessing is not None:
                        entity = entity_config.raw_entity_preprocessing(entity, None, archive_location)
                    preprocessed_new.append(entity)
                canonical_ids_new = entity_config.batch_store_new_entities(preprocessed_new, archive_location)
                archive_ids_new = entity_config.batch_store_new_entity_archives(preprocessed_new, canonical_ids_new, archive_session_id, archive_location)
                for entity, aid in zip(preprocessed_new, archive_ids_new):
                    entity.id = aid
                new_count = len(preprocessed_new)
            else:
                for entity in new_entities:
                    if entity_config.raw_entity_preprocessing is not None:
                        entity = entity_config.raw_entity_preprocessing(entity, None, archive_location)
                    canonical_id = entity_config.store_entity(entity, None, archive_location)
                    saved_archive_id = entity_config.store_entity_archive(
                        entity, archive_session_id, None, canonical_id, archive_location
                    )
                    entity.id = saved_archive_id
                    new_count += 1

            # --- Phase 4: Process existing entities ---
            updated_count = 0
            for entity, existing_canonical in existing_pairs:
                existing_canonical_id = existing_canonical.id

                if entity_config.raw_entity_preprocessing is not None:
                    entity = entity_config.raw_entity_preprocessing(entity, existing_canonical_id, archive_location)

                prior_run_archive = this_session_archive_by_canonical.get(existing_canonical_id)
                prior_run_archive_id = prior_run_archive.id if prior_run_archive else None
                is_reprocessing = prior_run_archive is not None

                merged_archive_record = entity_config.merge(entity, prior_run_archive)
                merged_archive_record.id = prior_run_archive_id
                merged_archive_record.canonical_id = existing_canonical_id

                saved_archive_id = entity_config.store_entity_archive(
                    merged_archive_record, archive_session_id, prior_run_archive_id, existing_canonical_id, archive_location
                )
                entity.id = saved_archive_id

                if is_reprocessing:
                    # This session's archive record already existed from a prior run — our update
                    # replaced its old contribution, so re-derive the canonical from all sessions.
                    all_archives = all_archives_by_canonical.get(existing_canonical_id, [])
                    updated_canonical = synthesize_from_archives(all_archives, entity_config.merge)
                else:
                    # First time for this session: canonical already embodies all prior sessions.
                    # O(1): merge existing canonical with this session's archive record.
                    updated_canonical = entity_config.merge(existing_canonical, merged_archive_record)

                # Identifier fields are immutable once set on the canonical.
                preserve_canonical_identifiers(updated_canonical, existing_canonical)
                updated_canonical.id = existing_canonical_id

                entity_config.store_entity(updated_canonical, existing_canonical, archive_location)
                updated_count += 1

            logger.info(f"Processed {entity_config.key}: {new_count} new, {updated_count} updated")

        # Keep account.post_count in sync for every account whose posts were touched.
        db.execute_query(
            """UPDATE account a
               INNER JOIN (
                   SELECT DISTINCT p.account_id
                   FROM post_archive pa
                   JOIN post p ON pa.canonical_id = p.id
                   WHERE pa.archive_session_id = %(session_id)s
                     AND p.account_id IS NOT NULL
               ) affected ON a.id = affected.account_id
               SET a.post_count = (SELECT COUNT(*) FROM post WHERE account_id = a.id)""",
            {"session_id": archive_session_id},
            return_type="none"
        )

        # Sync media.publication_date and media.account_id from the associated post
        # for all media touched by this session.
        db.execute_query(
            """UPDATE media m
               INNER JOIN (
                   SELECT DISTINCT ma.canonical_id AS media_id
                   FROM media_archive ma
                   WHERE ma.archive_session_id = %(session_id)s
               ) affected ON m.id = affected.media_id
               INNER JOIN post p ON m.post_id = p.id
               SET m.publication_date = p.publication_date,
                   m.account_id = p.account_id""",
            {"session_id": archive_session_id},
            return_type="none"
        )


def preserve_canonical_identifiers(synthesized: EntityBase, existing_canonical: EntityBase) -> None:
    """
    Identifier fields on the canonical entity are used as stable external keys
    (e.g. in platform URLs) and must only grow, never shrink. Apply the same
    first-non-empty rule but always favouring the existing canonical value.

    For entities with an identifiers list (Account), the new url_suffix and
    id_on_platform are accumulated into identifiers before url_suffix is
    updated, so that username changes are recorded as a historical record.
    url_suffix itself is updated to the newest known value (prefer synthesized
    over existing_canonical), while id_on_platform remains frozen to the first
    known value (platform IDs are immutable).

    FK integer IDs (e.g. post_id, account_id) are also copied from the existing
    canonical when the synthesized entity has None, to avoid redundant FK lookups
    inside store_entity for updated entities.
    """
    if hasattr(synthesized, 'identifiers') and hasattr(existing_canonical, 'identifiers'):
        ids = list(existing_canonical.identifiers or [])
        new_id = getattr(synthesized, 'id_on_platform', None)
        new_url = getattr(synthesized, 'url_suffix', None)
        if new_id and f"id_{new_id}" not in ids:
            ids.append(f"id_{new_id}")
        if new_url and f"url_{new_url}" not in ids:
            ids.append(f"url_{new_url}")
        synthesized.identifiers = ids

    if hasattr(synthesized, 'id_on_platform'):
        synthesized.id_on_platform = reconcile_primitives(
            existing_canonical.id_on_platform, synthesized.id_on_platform
        )
    if hasattr(synthesized, 'url_suffix'):
        synthesized.url_suffix = reconcile_primitives(synthesized.url_suffix, existing_canonical.url_suffix)
    for fk_field in ('account_id', 'post_id', 'media_id', 'tagged_account_id',
                     'follower_account_id', 'followed_account_id'):
        if hasattr(synthesized, fk_field) and getattr(synthesized, fk_field) is None:
            val = getattr(existing_canonical, fk_field, None)
            if val is not None:
                setattr(synthesized, fk_field, val)


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

def get_canonical_account(account: Account) -> Optional[Account]:
    entry = db.execute_query(
        """SELECT * FROM account
           WHERE (url_suffix = %(url_suffix)s AND url_suffix IS NOT NULL)
              OR (id_on_platform = %(id_on_platform)s AND id_on_platform IS NOT NULL)
           LIMIT 1""",
        {"url_suffix": account.url_suffix, "id_on_platform": account.id_on_platform},
        return_type="single_row"
    )
    return Account(**entry) if entry else None


def get_archive_record_account(canonical_id: int, archive_session_id: int) -> Optional[Account]:
    entry = db.execute_query(
        """SELECT * FROM account_archive
           WHERE canonical_id = %(canonical_id)s
             AND archive_session_id = %(archive_session_id)s""",
        {"canonical_id": canonical_id, "archive_session_id": archive_session_id},
        return_type="single_row"
    )
    return Account(**entry) if entry else None


def get_all_archives_for_canonical_account(canonical_id: int) -> list[Account]:
    entries = db.execute_query(
        "SELECT * FROM account_archive WHERE canonical_id = %(canonical_id)s",
        {"canonical_id": canonical_id},
        return_type="rows"
    )
    return [Account(**entry) for entry in (entries or [])]


def store_account(account: Account, existing_account: Optional[Account], _: Optional[Path]) -> int:
    if existing_account is not None:
        # Identifiers already accumulated by preserve_canonical_identifiers before url_suffix was frozen.
        account_identifiers: list[str] = account.identifiers or []
    else:
        account_identifiers = []
        if account.id_on_platform and f"id_{account.id_on_platform}" not in account_identifiers:
            account_identifiers.append(f"id_{account.id_on_platform}")
        if account.url_suffix and f"url_{account.url_suffix}" not in account_identifiers:
            account_identifiers.append(f"url_{account.url_suffix}")
    if existing_account is not None:
        db.execute_query(
            """UPDATE account
               SET url_suffix     = %(url_suffix)s,
                   platform       = %(platform)s,
                   id_on_platform = %(id_on_platform)s,
                   display_name   = %(display_name)s,
                   identifiers    = %(identifiers)s,
                   bio            = %(bio)s,
                   data           = %(data)s
               WHERE id = %(id)s""",
            {
                "id": account.id,
                "id_on_platform": account.id_on_platform,
                "url_suffix": account.url_suffix,
                "platform": account.platform,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
                "identifiers": json.dumps(account_identifiers),
            },
            return_type="none"
        )
        return account.id
    else:
        return db.execute_query(
            """INSERT INTO account (url_suffix, platform, id_on_platform, identifiers, display_name, bio, data)
               VALUES (%(url_suffix)s, %(platform)s, %(id_on_platform)s, %(identifiers)s, %(display_name)s, %(bio)s, %(data)s)""",
            {
                "id_on_platform": account.id_on_platform,
                "url_suffix": account.url_suffix,
                "platform": account.platform,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
                "identifiers": json.dumps(account_identifiers),
            },
            return_type="id"
        )


def store_account_archive(
        account: Account, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE account_archive
               SET url_suffix         = %(url_suffix)s,
                   platform           = %(platform)s,
                   id_on_platform     = %(id_on_platform)s,
                   display_name       = %(display_name)s,
                   bio                = %(bio)s,
                   data               = %(data)s,
                   archive_session_id = %(archive_session_id)s,
                   canonical_id       = %(canonical_id)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "id_on_platform": account.id_on_platform,
                "url_suffix": account.url_suffix,
                "platform": account.platform,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="none"
        )
        return existing_id
    else:
        return db.execute_query(
            """INSERT INTO account_archive (url_suffix, platform, id_on_platform, display_name, bio, data, archive_session_id, canonical_id)
               VALUES (%(url_suffix)s, %(platform)s, %(id_on_platform)s, %(display_name)s, %(bio)s, %(data)s, %(archive_session_id)s, %(canonical_id)s)""",
            {
                "id_on_platform": account.id_on_platform,
                "url_suffix": account.url_suffix,
                "platform": account.platform,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="id"
        )


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------

def get_canonical_post(post: Post) -> Optional[Post]:
    entry = db.execute_query(
        """SELECT * FROM post
           WHERE (url_suffix = %(url_suffix)s AND url_suffix IS NOT NULL)
              OR (id_on_platform = %(id_on_platform)s AND id_on_platform IS NOT NULL)
           LIMIT 1""",
        {"url_suffix": post.url_suffix, "id_on_platform": post.id_on_platform},
        return_type="single_row"
    )
    return Post(**entry) if entry else None


def get_archive_record_post(canonical_id: int, archive_session_id: int) -> Optional[Post]:
    entry = db.execute_query(
        """SELECT * FROM post_archive
           WHERE canonical_id = %(canonical_id)s
             AND archive_session_id = %(archive_session_id)s""",
        {"canonical_id": canonical_id, "archive_session_id": archive_session_id},
        return_type="single_row"
    )
    return Post(**entry) if entry else None


def get_all_archives_for_canonical_post(canonical_id: int) -> list[Post]:
    entries = db.execute_query(
        "SELECT * FROM post_archive WHERE canonical_id = %(canonical_id)s",
        {"canonical_id": canonical_id},
        return_type="rows"
    )
    return [Post(**entry) for entry in (entries or [])]


def store_post(post: Post, existing_post: Optional[Post], _: Optional[Path]) -> int:
    if post.account_id is None:
        stored_account = get_canonical_account(
            Account(url_suffix=post.account_url_suffix, id_on_platform=post.account_id_on_platform, platform=post.platform)
        )
        if stored_account is None:
            raise ValueError(f"Cannot store post {post.id_on_platform!r}: account not found "
                             f"(url={post.account_url!r}, id_on_platform={post.account_id_on_platform!r})")
        post.account_id = stored_account.id
    if existing_post is not None:
        db.execute_query(
            """UPDATE post
               SET url_suffix        = %(url_suffix)s,
                   platform         = %(platform)s,
                   id_on_platform   = %(id_on_platform)s,
                   account_id       = %(account_id)s,
                   publication_date = %(publication_date)s,
                   caption          = %(caption)s,
                   data             = %(data)s
               WHERE id = %(id)s""",
            {
                "id": post.id,
                "url_suffix": post.url_suffix,
                "platform": post.platform,
                "id_on_platform": post.id_on_platform,
                "account_id": post.account_id,
                "publication_date": post.publication_date.isoformat() if post.publication_date else None,
                "caption": post.caption,
                "data": json.dumps(post.data) if post.data else None,
            },
            return_type="none"
        )
        return post.id
    else:
        return db.execute_query(
            """INSERT INTO post (url_suffix, platform, id_on_platform, account_id, publication_date, caption, data)
               VALUES (%(url_suffix)s, %(platform)s, %(id_on_platform)s, %(account_id)s, %(publication_date)s, %(caption)s, %(data)s)""",
            {
                "url_suffix": post.url_suffix,
                "platform": post.platform,
                "id_on_platform": post.id_on_platform,
                "account_id": post.account_id,
                "publication_date": post.publication_date.isoformat() if post.publication_date else None,
                "caption": post.caption,
                "data": json.dumps(post.data) if post.data else None,
            },
            return_type="id"
        )


def store_post_archive(
        post: Post, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE post_archive
               SET url_suffix              = %(url_suffix)s,
                   platform               = %(platform)s,
                   id_on_platform         = %(id_on_platform)s,
                   publication_date       = %(publication_date)s,
                   caption                = %(caption)s,
                   data                   = %(data)s,
                   archive_session_id     = %(archive_session_id)s,
                   canonical_id           = %(canonical_id)s,
                   account_url_suffix     = %(account_url_suffix)s,
                   account_id_on_platform = %(account_id_on_platform)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "url_suffix": post.url_suffix,
                "platform": post.platform,
                "id_on_platform": post.id_on_platform,
                "publication_date": post.publication_date.isoformat() if post.publication_date else None,
                "caption": post.caption,
                "data": json.dumps(post.data) if post.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "account_url_suffix": post.account_url_suffix,
                "account_id_on_platform": post.account_id_on_platform,
            },
            return_type="none"
        )
        return existing_id
    else:
        return db.execute_query(
            """INSERT INTO post_archive
                   (url_suffix, platform, id_on_platform, publication_date, caption, data,
                    archive_session_id, canonical_id, account_url_suffix, account_id_on_platform)
               VALUES
                   (%(url_suffix)s, %(platform)s, %(id_on_platform)s, %(publication_date)s, %(caption)s, %(data)s,
                    %(archive_session_id)s, %(canonical_id)s, %(account_url_suffix)s, %(account_id_on_platform)s)""",
            {
                "url_suffix": post.url_suffix,
                "platform": post.platform,
                "id_on_platform": post.id_on_platform,
                "publication_date": post.publication_date.isoformat() if post.publication_date else None,
                "caption": post.caption,
                "data": json.dumps(post.data) if post.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "account_url_suffix": post.account_url_suffix,
                "account_id_on_platform": post.account_id_on_platform,
            },
            return_type="id"
        )


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

def preprocess_media(media: Media, _: Optional[int], archive_location: Optional[Path]) -> Media:
    if archive_location is not None and media.local_url is not None:
        media.local_url = (
            f"{LOCAL_ARCHIVES_DIR_ALIAS}/"
            + (archive_location / media.local_url).relative_to(ROOT_ARCHIVES).as_posix()
        )
    return media


def get_canonical_media(media: Media) -> Optional[Media]:
    entry = db.execute_query(
        """SELECT * FROM media
           WHERE (url_suffix = %(url_suffix)s AND url_suffix IS NOT NULL)
              OR (id_on_platform = %(id_on_platform)s AND id_on_platform IS NOT NULL)
           LIMIT 1""",
        {"url_suffix": media.url_suffix, "id_on_platform": media.id_on_platform},
        return_type="single_row"
    )
    return Media(**entry) if entry else None


def get_archive_record_media(canonical_id: int, archive_session_id: int) -> Optional[Media]:
    entry = db.execute_query(
        """SELECT * FROM media_archive
           WHERE canonical_id = %(canonical_id)s
             AND archive_session_id = %(archive_session_id)s""",
        {"canonical_id": canonical_id, "archive_session_id": archive_session_id},
        return_type="single_row"
    )
    return Media(**entry) if entry else None


def get_all_archives_for_canonical_media(canonical_id: int) -> list[Media]:
    entries = db.execute_query(
        "SELECT * FROM media_archive WHERE canonical_id = %(canonical_id)s",
        {"canonical_id": canonical_id},
        return_type="rows"
    )
    return [Media(**entry) for entry in (entries or [])]


def initial_thumbnail_status(media: Media) -> str:
    """Determine the thumbnail_status to assign when first inserting a media record."""
    if media.local_url is None or media.media_type == 'audio':
        return 'not_needed'
    return 'pending'


def store_media(media: Media, existing_media: Optional[Media], archive_location: Path) -> int:
    if media.post_id is None:
        stored_post = get_canonical_post(
            Post(url_suffix=media.post_url_suffix, id_on_platform=media.post_id_on_platform, platform=media.platform, media_type="image")
        )
        if stored_post is None:
            raise ValueError(f"Cannot store media {media.id_on_platform!r}: post not found "
                             f"(url={media.post_url!r}, id_on_platform={media.post_id_on_platform!r})")
        media.post_id = stored_post.id
    if existing_media is not None:
        db.execute_query(
            """UPDATE media
               SET url_suffix        = %(url_suffix)s,
                   platform         = %(platform)s,
                   id_on_platform   = %(id_on_platform)s,
                   post_id          = %(post_id)s,
                   local_url        = %(local_url)s,
                   media_type       = %(media_type)s,
                   data             = %(data)s,
                   thumbnail_status = IF(local_url <=> %(local_url)s, thumbnail_status, %(thumbnail_status)s)
               WHERE id = %(id)s""",
            {
                "id": media.id,
                "url_suffix": media.url_suffix,
                "platform": media.platform,
                "id_on_platform": media.id_on_platform,
                "post_id": media.post_id,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
                "thumbnail_status": initial_thumbnail_status(media),
            },
            return_type="none"
        )
        return media.id
    else:
        return db.execute_query(
            """INSERT INTO media (url_suffix, platform, id_on_platform, post_id, local_url, media_type, data, thumbnail_status)
               VALUES (%(url_suffix)s, %(platform)s, %(id_on_platform)s, %(post_id)s, %(local_url)s, %(media_type)s, %(data)s, %(thumbnail_status)s)""",
            {
                "url_suffix": media.url_suffix,
                "platform": media.platform,
                "id_on_platform": media.id_on_platform,
                "post_id": media.post_id,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
                "thumbnail_status": initial_thumbnail_status(media),
            },
            return_type="id"
        )


def store_media_archive(
        media: Media, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], archive_location: Path
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE media_archive
               SET url_suffix           = %(url_suffix)s,
                   platform            = %(platform)s,
                   id_on_platform      = %(id_on_platform)s,
                   local_url           = %(local_url)s,
                   media_type          = %(media_type)s,
                   data                = %(data)s,
                   archive_session_id  = %(archive_session_id)s,
                   canonical_id        = %(canonical_id)s,
                   post_url_suffix     = %(post_url_suffix)s,
                   post_id_on_platform = %(post_id_on_platform)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "url_suffix": media.url_suffix,
                "platform": media.platform,
                "id_on_platform": media.id_on_platform,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "post_url_suffix": media.post_url_suffix,
                "post_id_on_platform": media.post_id_on_platform,
            },
            return_type="none"
        )
        return existing_id
    else:
        return db.execute_query(
            """INSERT INTO media_archive
                   (url_suffix, platform, id_on_platform, local_url, media_type, data,
                    archive_session_id, canonical_id, post_url_suffix, post_id_on_platform)
               VALUES
                   (%(url_suffix)s, %(platform)s, %(id_on_platform)s, %(local_url)s, %(media_type)s, %(data)s,
                    %(archive_session_id)s, %(canonical_id)s, %(post_url_suffix)s, %(post_id_on_platform)s)""",
            {
                "url_suffix": media.url_suffix,
                "platform": media.platform,
                "id_on_platform": media.id_on_platform,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "post_url_suffix": media.post_url_suffix,
                "post_id_on_platform": media.post_id_on_platform,
            },
            return_type="id"
        )


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------

def get_canonical_comment(comment: Comment) -> Optional[Comment]:
    entry = db.execute_query(
        """SELECT * FROM comment
           WHERE (id_on_platform = %(id_on_platform)s AND id_on_platform IS NOT NULL)
              OR (url_suffix = %(url_suffix)s AND url_suffix IS NOT NULL)
           LIMIT 1""",
        {"id_on_platform": comment.id_on_platform, "url_suffix": comment.url_suffix},
        return_type="single_row"
    )
    return Comment(**entry) if entry else None


def get_archive_record_comment(canonical_id: int, archive_session_id: int) -> Optional[Comment]:
    entry = db.execute_query(
        """SELECT * FROM comment_archive
           WHERE canonical_id = %(canonical_id)s
             AND archive_session_id = %(archive_session_id)s""",
        {"canonical_id": canonical_id, "archive_session_id": archive_session_id},
        return_type="single_row"
    )
    return Comment(**entry) if entry else None


def get_all_archives_for_canonical_comment(canonical_id: int) -> list[Comment]:
    entries = db.execute_query(
        "SELECT * FROM comment_archive WHERE canonical_id = %(canonical_id)s",
        {"canonical_id": canonical_id},
        return_type="rows"
    )
    return [Comment(**entry) for entry in (entries or [])]


def store_comment(comment: Comment, existing_comment: Optional[Comment], _: Optional[Path]) -> int:
    if comment.post_id is None and (comment.post_url_suffix or comment.post_id_on_platform):
        stored_post = get_canonical_post(Post(url_suffix=comment.post_url_suffix, id_on_platform=comment.post_id_on_platform, platform=comment.platform, account_url_suffix=None))
        if stored_post is None:
            raise ValueError(f"Cannot store comment {comment.id_on_platform!r}: post not found "
                             f"(url={comment.post_url_suffix!r}, id_on_platform={comment.post_id_on_platform!r})")
        comment.post_id = stored_post.id
    if comment.account_id is None and comment.account_url_suffix:
        stored_account = db.execute_query(
            "SELECT id FROM account WHERE url_suffix = %(url_suffix)s LIMIT 1",
            {"url_suffix": comment.account_url_suffix},
            return_type="single_row"
        )
        if stored_account:
            comment.account_id = stored_account["id"]
    if comment.account_id is None and comment.account_id_on_platform:
        stored_account = db.execute_query(
            "SELECT id FROM account WHERE id_on_platform = %(id_on_platform)s LIMIT 1",
            {"id_on_platform": comment.account_id_on_platform},
            return_type="single_row"
        )
        if stored_account:
            comment.account_id = stored_account["id"]
    if existing_comment is not None:
        db.execute_query(
            """UPDATE comment
               SET id_on_platform                = %(id_on_platform)s,
                   url_suffix                    = %(url_suffix)s,
                   platform                      = %(platform)s,
                   post_id                       = %(post_id)s,
                   account_id                    = %(account_id)s,
                   parent_comment_id_on_platform = %(parent_comment_id_on_platform)s,
                   text                          = %(text)s,
                   publication_date              = %(publication_date)s,
                   data                          = %(data)s
               WHERE id = %(id)s""",
            {
                "id": comment.id,
                "id_on_platform": comment.id_on_platform,
                "url_suffix": comment.url_suffix,
                "platform": comment.platform,
                "post_id": comment.post_id,
                "account_id": comment.account_id,
                "parent_comment_id_on_platform": comment.parent_comment_id_on_platform,
                "text": comment.text,
                "publication_date": comment.publication_date.isoformat() if comment.publication_date else None,
                "data": json.dumps(comment.data) if comment.data else None,
            },
            return_type="none"
        )
        return comment.id
    else:
        return db.execute_query(
            """INSERT INTO comment
                   (id_on_platform, url_suffix, platform, post_id, account_id, parent_comment_id_on_platform,
                    text, publication_date, data)
               VALUES
                   (%(id_on_platform)s, %(url_suffix)s, %(platform)s, %(post_id)s, %(account_id)s,
                    %(parent_comment_id_on_platform)s, %(text)s, %(publication_date)s, %(data)s)""",
            {
                "id_on_platform": comment.id_on_platform,
                "url_suffix": comment.url_suffix,
                "platform": comment.platform,
                "post_id": comment.post_id,
                "account_id": comment.account_id,
                "parent_comment_id_on_platform": comment.parent_comment_id_on_platform,
                "text": comment.text,
                "publication_date": comment.publication_date.isoformat() if comment.publication_date else None,
                "data": json.dumps(comment.data) if comment.data else None,
            },
            return_type="id"
        )


def store_comment_archive(
        comment: Comment, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE comment_archive
               SET id_on_platform                = %(id_on_platform)s,
                   url_suffix                    = %(url_suffix)s,
                   platform                      = %(platform)s,
                   post_url_suffix               = %(post_url_suffix)s,
                   post_id_on_platform           = %(post_id_on_platform)s,
                   account_id_on_platform        = %(account_id_on_platform)s,
                   account_url_suffix            = %(account_url_suffix)s,
                   parent_comment_id_on_platform = %(parent_comment_id_on_platform)s,
                   text                          = %(text)s,
                   publication_date              = %(publication_date)s,
                   data                          = %(data)s,
                   archive_session_id            = %(archive_session_id)s,
                   canonical_id                  = %(canonical_id)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "id_on_platform": comment.id_on_platform,
                "url_suffix": comment.url_suffix,
                "platform": comment.platform,
                "post_url_suffix": comment.post_url_suffix,
                "post_id_on_platform": comment.post_id_on_platform,
                "account_id_on_platform": comment.account_id_on_platform,
                "account_url_suffix": comment.account_url_suffix,
                "parent_comment_id_on_platform": comment.parent_comment_id_on_platform,
                "text": comment.text,
                "publication_date": comment.publication_date.isoformat() if comment.publication_date else None,
                "data": json.dumps(comment.data) if comment.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="none"
        )
        return existing_id
    else:
        return db.execute_query(
            """INSERT INTO comment_archive
                   (id_on_platform, url_suffix, platform, post_url_suffix, post_id_on_platform,
                    account_id_on_platform, account_url_suffix, parent_comment_id_on_platform,
                    text, publication_date, data, archive_session_id, canonical_id)
               VALUES
                   (%(id_on_platform)s, %(url_suffix)s, %(platform)s, %(post_url_suffix)s,
                    %(post_id_on_platform)s, %(account_id_on_platform)s, %(account_url_suffix)s,
                    %(parent_comment_id_on_platform)s, %(text)s, %(publication_date)s, %(data)s,
                    %(archive_session_id)s, %(canonical_id)s)""",
            {
                "id_on_platform": comment.id_on_platform,
                "url_suffix": comment.url_suffix,
                "platform": comment.platform,
                "post_url_suffix": comment.post_url_suffix,
                "post_id_on_platform": comment.post_id_on_platform,
                "account_id_on_platform": comment.account_id_on_platform,
                "account_url_suffix": comment.account_url_suffix,
                "parent_comment_id_on_platform": comment.parent_comment_id_on_platform,
                "text": comment.text,
                "publication_date": comment.publication_date.isoformat() if comment.publication_date else None,
                "data": json.dumps(comment.data) if comment.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="id"
        )


# ---------------------------------------------------------------------------
# PostLike
# ---------------------------------------------------------------------------

def get_canonical_post_like(like: Like) -> Optional[Like]:
    if not like.id_on_platform:
        return None
    entry = db.execute_query(
        """SELECT * FROM post_like
           WHERE id_on_platform = %(id_on_platform)s AND id_on_platform IS NOT NULL
           LIMIT 1""",
        {"id_on_platform": like.id_on_platform},
        return_type="single_row"
    )
    return Like(**entry) if entry else None


def get_archive_record_post_like(canonical_id: int, archive_session_id: int) -> Optional[Like]:
    entry = db.execute_query(
        """SELECT * FROM post_like_archive
           WHERE canonical_id = %(canonical_id)s
             AND archive_session_id = %(archive_session_id)s""",
        {"canonical_id": canonical_id, "archive_session_id": archive_session_id},
        return_type="single_row"
    )
    return Like(**entry) if entry else None


def get_all_archives_for_canonical_post_like(canonical_id: int) -> list[Like]:
    entries = db.execute_query(
        "SELECT * FROM post_like_archive WHERE canonical_id = %(canonical_id)s",
        {"canonical_id": canonical_id},
        return_type="rows"
    )
    return [Like(**entry) for entry in (entries or [])]


def store_post_like(like: Like, existing_like: Optional[Like], _: Optional[Path]) -> int:
    if like.post_id is None and (like.post_url_suffix or like.post_id_on_platform):
        stored_post = get_canonical_post(Post(url_suffix=like.post_url_suffix, id_on_platform=like.post_id_on_platform, platform=like.platform))
        if stored_post is None:
            raise ValueError(f"Cannot store like {like.id_on_platform!r}: post not found "
                             f"(url={like.post_url_suffix!r}, id_on_platform={like.post_id_on_platform!r})")
        like.post_id = stored_post.id
    if like.account_id is None and like.account_url_suffix:
        stored_account = db.execute_query(
            "SELECT id FROM account WHERE url_suffix = %(url)s LIMIT 1",
            {"url": like.account_url_suffix},
            return_type="single_row"
        )
        if stored_account:
            like.account_id = stored_account["id"]
    if like.account_id is None and like.account_id_on_platform:
        stored_account = db.execute_query(
            "SELECT id FROM account WHERE id_on_platform = %(id_on_platform)s LIMIT 1",
            {"id_on_platform": like.account_id_on_platform},
            return_type="single_row"
        )
        if stored_account:
            like.account_id = stored_account["id"]
    if existing_like is not None:
        db.execute_query(
            """UPDATE post_like
               SET id_on_platform = %(id_on_platform)s,
                   post_id        = %(post_id)s,
                   account_id     = %(account_id)s,
                   data           = %(data)s
               WHERE id = %(id)s""",
            {
                "id": like.id,
                "id_on_platform": like.id_on_platform,
                "post_id": like.post_id,
                "account_id": like.account_id,
                "data": json.dumps(like.data) if like.data else None,
            },
            return_type="none"
        )
        return like.id
    else:
        return db.execute_query(
            """INSERT INTO post_like (id_on_platform, post_id, account_id, data)
               VALUES (%(id_on_platform)s, %(post_id)s, %(account_id)s, %(data)s)""",
            {
                "id_on_platform": like.id_on_platform,
                "post_id": like.post_id,
                "account_id": like.account_id,
                "data": json.dumps(like.data) if like.data else None,
            },
            return_type="id"
        )


def store_post_like_archive(
        like: Like, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE post_like_archive
               SET id_on_platform         = %(id_on_platform)s,
                   post_id_on_platform    = %(post_id_on_platform)s,
                   post_url_suffix        = %(post_url_suffix)s,
                   platform               = %(platform)s,
                   account_id_on_platform = %(account_id_on_platform)s,
                   account_url_suffix     = %(account_url_suffix)s,
                   data                   = %(data)s,
                   archive_session_id     = %(archive_session_id)s,
                   canonical_id           = %(canonical_id)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "id_on_platform": like.id_on_platform,
                "post_id_on_platform": like.post_id_on_platform,
                "post_url_suffix": like.post_url_suffix,
                "platform": like.platform,
                "account_id_on_platform": like.account_id_on_platform,
                "account_url_suffix": like.account_url_suffix,
                "data": json.dumps(like.data) if like.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="none"
        )
        return existing_id
    else:
        return db.execute_query(
            """INSERT INTO post_like_archive
                   (id_on_platform, post_id_on_platform, post_url_suffix, platform,
                    account_id_on_platform, account_url_suffix, data, archive_session_id, canonical_id)
               VALUES
                   (%(id_on_platform)s, %(post_id_on_platform)s, %(post_url_suffix)s, %(platform)s,
                    %(account_id_on_platform)s, %(account_url_suffix)s, %(data)s,
                    %(archive_session_id)s, %(canonical_id)s)""",
            {
                "id_on_platform": like.id_on_platform,
                "post_id_on_platform": like.post_id_on_platform,
                "post_url_suffix": like.post_url_suffix,
                "platform": like.platform,
                "account_id_on_platform": like.account_id_on_platform,
                "account_url_suffix": like.account_url_suffix,
                "data": json.dumps(like.data) if like.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="id"
        )


# ---------------------------------------------------------------------------
# TaggedAccount
# ---------------------------------------------------------------------------

def get_canonical_tagged_account(ta: TaggedAccount) -> Optional[TaggedAccount]:
    if not ta.id_on_platform:
        return None
    entry = db.execute_query(
        """SELECT * FROM tagged_account
           WHERE id_on_platform = %(id_on_platform)s AND id_on_platform IS NOT NULL
           LIMIT 1""",
        {"id_on_platform": ta.id_on_platform},
        return_type="single_row"
    )
    return TaggedAccount(**entry) if entry else None


def get_archive_record_tagged_account(canonical_id: int, archive_session_id: int) -> Optional[TaggedAccount]:
    entry = db.execute_query(
        """SELECT * FROM tagged_account_archive
           WHERE canonical_id = %(canonical_id)s
             AND archive_session_id = %(archive_session_id)s""",
        {"canonical_id": canonical_id, "archive_session_id": archive_session_id},
        return_type="single_row"
    )
    return TaggedAccount(**entry) if entry else None


def get_all_archives_for_canonical_tagged_account(canonical_id: int) -> list[TaggedAccount]:
    entries = db.execute_query(
        "SELECT * FROM tagged_account_archive WHERE canonical_id = %(canonical_id)s",
        {"canonical_id": canonical_id},
        return_type="rows"
    )
    return [TaggedAccount(**entry) for entry in (entries or [])]


def store_tagged_account(ta: TaggedAccount, existing_ta: Optional[TaggedAccount], _: Optional[Path]) -> int:
    if ta.tagged_account_id is None and ta.tagged_account_url_suffix:
        stored_account = db.execute_query(
            "SELECT id FROM account WHERE url_suffix = %(url)s LIMIT 1",
            {"url": ta.tagged_account_url_suffix},
            return_type="single_row"
        )
        if stored_account:
            ta.tagged_account_id = stored_account["id"]
    if ta.tagged_account_id is None and ta.tagged_account_id_on_platform:
        stored_account = db.execute_query(
            "SELECT id FROM account WHERE id_on_platform = %(id_on_platform)s LIMIT 1",
            {"id_on_platform": ta.tagged_account_id_on_platform},
            return_type="single_row"
        )
        if stored_account:
            ta.tagged_account_id = stored_account["id"]
    if ta.post_id is None and (ta.context_post_url_suffix or ta.context_post_id_on_platform):
        stored_post = get_canonical_post(Post(url_suffix=ta.context_post_url_suffix, id_on_platform=ta.context_post_id_on_platform, platform=ta.platform))
        if stored_post:
            ta.post_id = stored_post.id
    if ta.media_id is None and ta.context_media_url_suffix:
        stored_media = get_canonical_media(Media(url_suffix=ta.context_media_url_suffix, media_type="image", platform=ta.platform))
        if stored_media:
            ta.media_id = stored_media.id
    if existing_ta is not None:
        db.execute_query(
            """UPDATE tagged_account
               SET id_on_platform    = %(id_on_platform)s,
                   tagged_account_id = %(tagged_account_id)s,
                   post_id           = %(post_id)s,
                   media_id          = %(media_id)s,
                   tag_x_position    = %(tag_x_position)s,
                   tag_y_position    = %(tag_y_position)s,
                   data              = %(data)s
               WHERE id = %(id)s""",
            {
                "id": ta.id,
                "id_on_platform": ta.id_on_platform,
                "tagged_account_id": ta.tagged_account_id,
                "post_id": ta.post_id,
                "media_id": ta.media_id,
                "tag_x_position": ta.tag_x_position,
                "tag_y_position": ta.tag_y_position,
                "data": json.dumps(ta.data) if ta.data else None,
            },
            return_type="none"
        )
        return ta.id
    else:
        return db.execute_query(
            """INSERT INTO tagged_account
                   (id_on_platform, tagged_account_id, post_id, media_id,
                    tag_x_position, tag_y_position, data)
               VALUES
                   (%(id_on_platform)s, %(tagged_account_id)s, %(post_id)s, %(media_id)s,
                    %(tag_x_position)s, %(tag_y_position)s, %(data)s)""",
            {
                "id_on_platform": ta.id_on_platform,
                "tagged_account_id": ta.tagged_account_id,
                "post_id": ta.post_id,
                "media_id": ta.media_id,
                "tag_x_position": ta.tag_x_position,
                "tag_y_position": ta.tag_y_position,
                "data": json.dumps(ta.data) if ta.data else None,
            },
            return_type="id"
        )


def store_tagged_account_archive(
        ta: TaggedAccount, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE tagged_account_archive
               SET id_on_platform                = %(id_on_platform)s,
                   tagged_account_id_on_platform = %(tagged_account_id_on_platform)s,
                   tagged_account_url_suffix     = %(tagged_account_url_suffix)s,
                   platform                      = %(platform)s,
                   context_post_url_suffix       = %(context_post_url_suffix)s,
                   context_media_url_suffix      = %(context_media_url_suffix)s,
                   context_post_id_on_platform   = %(context_post_id_on_platform)s,
                   context_media_id_on_platform  = %(context_media_id_on_platform)s,
                   tag_x_position                = %(tag_x_position)s,
                   tag_y_position                = %(tag_y_position)s,
                   data                          = %(data)s,
                   archive_session_id            = %(archive_session_id)s,
                   canonical_id                  = %(canonical_id)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "id_on_platform": ta.id_on_platform,
                "tagged_account_id_on_platform": ta.tagged_account_id_on_platform,
                "tagged_account_url_suffix": ta.tagged_account_url_suffix,
                "platform": ta.platform,
                "context_post_url_suffix": ta.context_post_url_suffix,
                "context_media_url_suffix": ta.context_media_url_suffix,
                "context_post_id_on_platform": ta.context_post_id_on_platform,
                "context_media_id_on_platform": ta.context_media_id_on_platform,
                "tag_x_position": ta.tag_x_position,
                "tag_y_position": ta.tag_y_position,
                "data": json.dumps(ta.data) if ta.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="none"
        )
        return existing_id
    else:
        return db.execute_query(
            """INSERT INTO tagged_account_archive
                   (id_on_platform, tagged_account_id_on_platform, tagged_account_url_suffix,
                    platform, context_post_url_suffix, context_media_url_suffix,
                    context_post_id_on_platform, context_media_id_on_platform,
                    tag_x_position, tag_y_position, data, archive_session_id, canonical_id)
               VALUES
                   (%(id_on_platform)s, %(tagged_account_id_on_platform)s, %(tagged_account_url_suffix)s,
                    %(platform)s, %(context_post_url_suffix)s, %(context_media_url_suffix)s,
                    %(context_post_id_on_platform)s, %(context_media_id_on_platform)s,
                    %(tag_x_position)s, %(tag_y_position)s, %(data)s,
                    %(archive_session_id)s, %(canonical_id)s)""",
            {
                "id_on_platform": ta.id_on_platform,
                "tagged_account_id_on_platform": ta.tagged_account_id_on_platform,
                "tagged_account_url_suffix": ta.tagged_account_url_suffix,
                "platform": ta.platform,
                "context_post_url_suffix": ta.context_post_url_suffix,
                "context_media_url_suffix": ta.context_media_url_suffix,
                "context_post_id_on_platform": ta.context_post_id_on_platform,
                "context_media_id_on_platform": ta.context_media_id_on_platform,
                "tag_x_position": ta.tag_x_position,
                "tag_y_position": ta.tag_y_position,
                "data": json.dumps(ta.data) if ta.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="id"
        )


# ---------------------------------------------------------------------------
# AccountRelation
# ---------------------------------------------------------------------------

def get_canonical_account_relation(ar: AccountRelation) -> Optional[AccountRelation]:
    if not ar.id_on_platform:
        return None
    entry = db.execute_query(
        """SELECT * FROM account_relation
           WHERE id_on_platform = %(id_on_platform)s AND id_on_platform IS NOT NULL
           LIMIT 1""",
        {"id_on_platform": ar.id_on_platform},
        return_type="single_row"
    )
    return AccountRelation(**entry) if entry else None


def get_archive_record_account_relation(canonical_id: int, archive_session_id: int) -> Optional[AccountRelation]:
    entry = db.execute_query(
        """SELECT * FROM account_relation_archive
           WHERE canonical_id = %(canonical_id)s
             AND archive_session_id = %(archive_session_id)s""",
        {"canonical_id": canonical_id, "archive_session_id": archive_session_id},
        return_type="single_row"
    )
    return AccountRelation(**entry) if entry else None


def get_all_archives_for_canonical_account_relation(canonical_id: int) -> list[AccountRelation]:
    entries = db.execute_query(
        "SELECT * FROM account_relation_archive WHERE canonical_id = %(canonical_id)s",
        {"canonical_id": canonical_id},
        return_type="rows"
    )
    return [AccountRelation(**entry) for entry in (entries or [])]


def _resolve_account_canonical_id(id_on_platform: Optional[str], url: Optional[str]) -> Optional[int]:
    if url:
        result = db.execute_query(
            "SELECT id FROM account WHERE url_suffix = %(url)s LIMIT 1",
            {"url": url},
            return_type="single_row"
        )
        if result:
            return result["id"]
    if id_on_platform:
        result = db.execute_query(
            "SELECT id FROM account WHERE id_on_platform = %(id_on_platform)s LIMIT 1",
            {"id_on_platform": id_on_platform},
            return_type="single_row"
        )
        if result:
            return result["id"]
    return None


def store_account_relation(ar: AccountRelation, existing_ar: Optional[AccountRelation], _: Optional[Path]) -> int:
    if ar.follower_account_id is None:
        ar.follower_account_id = _resolve_account_canonical_id(
            ar.follower_account_id_on_platform, ar.follower_account_url_suffix
        )
    if ar.followed_account_id is None:
        ar.followed_account_id = _resolve_account_canonical_id(
            ar.followed_account_id_on_platform, ar.followed_account_url_suffix
        )
    if ar.follower_account_id is None or ar.followed_account_id is None:
        raise ValueError(
            f"Cannot store account_relation {ar.id_on_platform!r}: "
            f"could not resolve account IDs (follower={ar.follower_account_id_on_platform!r}/{ar.follower_account_url_suffix!r}, "
            f"followed={ar.followed_account_id_on_platform!r}/{ar.followed_account_url_suffix!r})"
        )
    if existing_ar is not None:
        db.execute_query(
            """UPDATE account_relation
               SET follower_account_id = %(follower_account_id)s,
                   followed_account_id = %(followed_account_id)s,
                   relation_type       = %(relation_type)s,
                   id_on_platform      = %(id_on_platform)s,
                   data                = %(data)s
               WHERE id = %(id)s""",
            {
                "id": ar.id,
                "follower_account_id": ar.follower_account_id,
                "followed_account_id": ar.followed_account_id,
                "relation_type": ar.relation_type,
                "id_on_platform": ar.id_on_platform,
                "data": json.dumps(ar.data) if ar.data else None,
            },
            return_type="none"
        )
        return ar.id
    else:
        return db.execute_query(
            """INSERT INTO account_relation
                   (follower_account_id, followed_account_id, relation_type, id_on_platform, data)
               VALUES
                   (%(follower_account_id)s, %(followed_account_id)s, %(relation_type)s,
                    %(id_on_platform)s, %(data)s)""",
            {
                "follower_account_id": ar.follower_account_id,
                "followed_account_id": ar.followed_account_id,
                "relation_type": ar.relation_type,
                "id_on_platform": ar.id_on_platform,
                "data": json.dumps(ar.data) if ar.data else None,
            },
            return_type="id"
        )


def store_account_relation_archive(
        ar: AccountRelation, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE account_relation_archive
               SET id_on_platform                  = %(id_on_platform)s,
                   follower_account_url_suffix      = %(follower_account_url_suffix)s,
                   follower_account_id_on_platform  = %(follower_account_id_on_platform)s,
                   followed_account_url_suffix      = %(followed_account_url_suffix)s,
                   followed_account_id_on_platform  = %(followed_account_id_on_platform)s,
                   platform                         = %(platform)s,
                   relation_type                    = %(relation_type)s,
                   data                             = %(data)s,
                   archive_session_id               = %(archive_session_id)s,
                   canonical_id                     = %(canonical_id)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "id_on_platform": ar.id_on_platform,
                "follower_account_url_suffix": ar.follower_account_url_suffix,
                "follower_account_id_on_platform": ar.follower_account_id_on_platform,
                "followed_account_url_suffix": ar.followed_account_url_suffix,
                "followed_account_id_on_platform": ar.followed_account_id_on_platform,
                "platform": ar.platform,
                "relation_type": ar.relation_type,
                "data": json.dumps(ar.data) if ar.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="none"
        )
        return existing_id
    else:
        return db.execute_query(
            """INSERT INTO account_relation_archive
                   (id_on_platform, follower_account_url_suffix, follower_account_id_on_platform,
                    followed_account_url_suffix, followed_account_id_on_platform, platform,
                    relation_type, data, archive_session_id, canonical_id)
               VALUES
                   (%(id_on_platform)s, %(follower_account_url_suffix)s, %(follower_account_id_on_platform)s,
                    %(followed_account_url_suffix)s, %(followed_account_id_on_platform)s, %(platform)s,
                    %(relation_type)s, %(data)s, %(archive_session_id)s, %(canonical_id)s)""",
            {
                "id_on_platform": ar.id_on_platform,
                "follower_account_url_suffix": ar.follower_account_url_suffix,
                "follower_account_id_on_platform": ar.follower_account_id_on_platform,
                "followed_account_url_suffix": ar.followed_account_url_suffix,
                "followed_account_id_on_platform": ar.followed_account_id_on_platform,
                "platform": ar.platform,
                "relation_type": ar.relation_type,
                "data": json.dumps(ar.data) if ar.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="id"
        )


# ---------------------------------------------------------------------------
# Entity processing registry
# ---------------------------------------------------------------------------

entity_types: list[EntityProcessingConfig] = [
    EntityProcessingConfig(
        key="accounts",
        table="account",
        get_canonical=get_canonical_account,
        get_archive_record=get_archive_record_account,
        get_all_archives_for_canonical=get_all_archives_for_canonical_account,
        store_entity=store_account,
        store_entity_archive=store_account_archive,
        merge=reconcile_accounts,
        batch_get_canonicals=lambda es: batch_get_canonicals_url_and_id(es, "account", Account),
        batch_get_archive_records=lambda ids, sid: batch_get_archive_records(ids, "account_archive", sid, Account),
        batch_get_all_archives=lambda ids: batch_get_all_archives(ids, "account_archive", Account),
        batch_store_new_entities=lambda es, loc: batch_store_new_accounts(es, loc),
        batch_store_new_entity_archives=lambda es, ids, sid, loc: batch_store_new_account_archives(es, ids, sid, loc),
    ),
    EntityProcessingConfig(
        key="posts",
        table="post",
        get_canonical=get_canonical_post,
        get_archive_record=get_archive_record_post,
        get_all_archives_for_canonical=get_all_archives_for_canonical_post,
        store_entity=store_post,
        store_entity_archive=store_post_archive,
        merge=reconcile_posts,
        batch_get_canonicals=lambda es: batch_get_canonicals_url_and_id(es, "post", Post),
        batch_get_archive_records=lambda ids, sid: batch_get_archive_records(ids, "post_archive", sid, Post),
        batch_get_all_archives=lambda ids: batch_get_all_archives(ids, "post_archive", Post),
        batch_store_new_entities=lambda es, loc: batch_store_new_posts(es, loc),
        batch_store_new_entity_archives=lambda es, ids, sid, loc: batch_store_new_post_archives(es, ids, sid, loc),
    ),
    EntityProcessingConfig(
        key="media",
        table="media",
        get_canonical=get_canonical_media,
        get_archive_record=get_archive_record_media,
        get_all_archives_for_canonical=get_all_archives_for_canonical_media,
        store_entity=store_media,
        store_entity_archive=store_media_archive,
        merge=reconcile_media,
        raw_entity_preprocessing=preprocess_media,
        batch_get_canonicals=lambda es: batch_get_canonicals_url_and_id(es, "media", Media),
        batch_get_archive_records=lambda ids, sid: batch_get_archive_records(ids, "media_archive", sid, Media),
        batch_get_all_archives=lambda ids: batch_get_all_archives(ids, "media_archive", Media),
        batch_store_new_entities=lambda es, loc: batch_store_new_media(es, loc),
        batch_store_new_entity_archives=lambda es, ids, sid, loc: batch_store_new_media_archives(es, ids, sid, loc),
    ),
    EntityProcessingConfig(
        key="comments",
        table="comment",
        get_canonical=get_canonical_comment,
        get_archive_record=get_archive_record_comment,
        get_all_archives_for_canonical=get_all_archives_for_canonical_comment,
        store_entity=store_comment,
        store_entity_archive=store_comment_archive,
        merge=reconcile_comments,
        batch_get_canonicals=lambda es: batch_get_canonicals_url_and_id(es, "comment", Comment),
        batch_get_archive_records=lambda ids, sid: batch_get_archive_records(ids, "comment_archive", sid, Comment),
        batch_get_all_archives=lambda ids: batch_get_all_archives(ids, "comment_archive", Comment),
        batch_store_new_entities=lambda es, loc: batch_store_new_comments(es, loc),
        batch_store_new_entity_archives=lambda es, ids, sid, loc: batch_store_new_comment_archives(es, ids, sid, loc),
    ),
    EntityProcessingConfig(
        key="likes",
        table="post_like",
        get_canonical=get_canonical_post_like,
        get_archive_record=get_archive_record_post_like,
        get_all_archives_for_canonical=get_all_archives_for_canonical_post_like,
        store_entity=store_post_like,
        store_entity_archive=store_post_like_archive,
        merge=reconcile_likes,
        batch_get_canonicals=lambda es: batch_get_canonicals_id_only(es, "post_like", Like),
        batch_get_archive_records=lambda ids, sid: batch_get_archive_records(ids, "post_like_archive", sid, Like),
        batch_get_all_archives=lambda ids: batch_get_all_archives(ids, "post_like_archive", Like),
    ),
    EntityProcessingConfig(
        key="tagged_accounts",
        table="tagged_account",
        get_canonical=get_canonical_tagged_account,
        get_archive_record=get_archive_record_tagged_account,
        get_all_archives_for_canonical=get_all_archives_for_canonical_tagged_account,
        store_entity=store_tagged_account,
        store_entity_archive=store_tagged_account_archive,
        merge=reconcile_tagged_accounts,
        batch_get_canonicals=lambda es: batch_get_canonicals_id_only(es, "tagged_account", TaggedAccount),
        batch_get_archive_records=lambda ids, sid: batch_get_archive_records(ids, "tagged_account_archive", sid, TaggedAccount),
        batch_get_all_archives=lambda ids: batch_get_all_archives(ids, "tagged_account_archive", TaggedAccount),
    ),
    EntityProcessingConfig(
        key="account_relations",
        table="account_relation",
        get_canonical=get_canonical_account_relation,
        get_archive_record=get_archive_record_account_relation,
        get_all_archives_for_canonical=get_all_archives_for_canonical_account_relation,
        store_entity=store_account_relation,
        store_entity_archive=store_account_relation_archive,
        merge=reconcile_account_relations,
        batch_get_canonicals=lambda es: batch_get_canonicals_id_only(es, "account_relation", AccountRelation),
        batch_get_archive_records=lambda ids, sid: batch_get_archive_records(ids, "account_relation_archive", sid, AccountRelation),
        batch_get_all_archives=lambda ids: batch_get_all_archives(ids, "account_relation_archive", AccountRelation),
    ),
]
