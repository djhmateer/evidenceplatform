import json
import logging
from pathlib import Path
from typing import Optional, TypeVar, Generic, Callable

from pydantic import BaseModel

from extractors.entity_types import EntityBase, ExtractedEntitiesFlattened, Account, Post, Media
from extractors.reconcile_entities import reconcile_accounts, reconcile_posts, reconcile_media
from root_anchor import ROOT_DIR
from utils import db

logger = logging.getLogger(__name__)

LOCAL_ARCHIVES_DIR_ALIAS = 'local_archive_har'
ROOT_ARCHIVES = Path(ROOT_DIR) / "archives"
EntityType = TypeVar("EntityType", bound="EntityBase")


class EntityProcessingConfig(BaseModel, Generic[EntityType]):
    key: str
    table: str
    get_entity: Callable[[EntityType, Optional[int]], Optional[EntityType]]
    raw_entity_preprocessing: Optional[Callable[[EntityType, Optional[int], Optional[Path]], EntityType]] = None
    store_entity: Callable[[EntityType, Optional[int], Optional[Path]], int]
    store_entity_archive: Callable[[EntityType, int, Optional[int], Optional[int], Optional[Path]], int]
    merge: Callable[[EntityType, Optional[EntityType]], EntityType]


def incorporate_structures_into_db(structures: ExtractedEntitiesFlattened, archive_session_id: int, archive_location: Optional[Path]) -> None:
    """
    Process extracted entities and store them in the database.
    Creates both canonical records and archive-specific records for each entity.
    """
    logger.debug(f"Incorporating structures into DB for archive session {archive_session_id}")

    # Use transaction batching - commits once at the end instead of after every query
    # This provides ~5x speedup for bulk operations
    with db.transaction_batch():
        for entity_config in entity_types:
            entities: list = getattr(structures, entity_config.key, [])
            entity_count = len(entities)
            new_count = 0
            updated_count = 0

            logger.debug(f"Processing {entity_count} {entity_config.key}")

            for entity in entities:
                # Check if entity already exists in canonical table
                existing_entity = entity_config.get_entity(entity, None)
                existing_entity_id = existing_entity.id if existing_entity is not None else None

                # Apply any preprocessing (e.g., path normalization for media)
                if entity_config.raw_entity_preprocessing is not None:
                    entity = entity_config.raw_entity_preprocessing(entity, existing_entity_id, archive_location)

                # Store/update the canonical entity record
                entity_id = entity_config.store_entity(
                    entity_config.merge(entity, existing_entity),
                    existing_entity_id,
                    archive_location
                )

                if existing_entity_id is None:
                    new_count += 1
                else:
                    updated_count += 1

                # Now handle the archive-specific record
                existing_entity_within_archive = entity_config.get_entity(
                    existing_entity, archive_session_id
                ) if existing_entity else None
                existing_entity_within_archive_id = existing_entity_within_archive.id if existing_entity_within_archive is not None else None

                entity_within_archive_for_storage = entity_config.merge(entity, existing_entity_within_archive)
                entity_within_archive_for_storage.canonical_id = entity_id
                entity_within_archive_for_storage.id = existing_entity_within_archive_id

                entity_within_archive_id = entity_config.store_entity_archive(
                    entity_within_archive_for_storage,
                    archive_session_id,
                    existing_entity_within_archive_id,
                    entity_id,
                    archive_location
                )
                entity.id = entity_within_archive_id

            logger.info(f"Processed {entity_config.key}: {new_count} new, {updated_count} updated")


def get_stored_account_archive(account: Account, archive_session_id: Optional[int] = None) -> Optional[Account]:
    entry = db.execute_query(
        f'''SELECT * 
           FROM account{'_archive' if archive_session_id else ''}
           WHERE 
               ((url=%(url)s AND url IS NOT NULL) OR (id_on_platform=%(id_on_platform)s AND id_on_platform IS NOT NULL))
             {'AND archive_session_id=%(archive_session_id)s' if archive_session_id else ''}
        ''',
        {
            "url": account.url,
            "id_on_platform": account.id_on_platform,
            "archive_session_id": archive_session_id
        },
        return_type="single_row"
    )
    if not entry:
        return None
    return Account(**entry)


def get_stored_post_archive(post: Post, archive_session_id: Optional[int] = None) -> Optional[Post]:
    entry = db.execute_query(
        f'''SELECT * 
           FROM post{'_archive' if archive_session_id else ''}
           WHERE 
               ((url=%(url)s AND url IS NOT NULL) OR (id_on_platform=%(id_on_platform)s AND id_on_platform IS NOT NULL))
             {'AND archive_session_id=%(archive_session_id)s' if archive_session_id else ''}
        ''',
        {
            "url": post.url,
            "id_on_platform": post.id_on_platform,
            "archive_session_id": archive_session_id
        },
        return_type="single_row"
    )
    if not entry:
        return None
    return Post(**entry)


def get_stored_media_archive(media: Media, archive_session_id: Optional[int] = None) -> Optional[Media]:
    entry = db.execute_query(
        f'''SELECT * 
           FROM media{'_archive' if archive_session_id else ''}
           WHERE 
               ((url=%(url)s AND url IS NOT NULL) OR (id_on_platform=%(id_on_platform)s AND id_on_platform IS NOT NULL))
             {'AND archive_session_id=%(archive_session_id)s' if archive_session_id else ''}
        ''',
        {
            "url": media.url,
            "id_on_platform": media.id_on_platform,
            "archive_session_id": archive_session_id
        },
        return_type="single_row"
    )
    if not entry:
        return None
    return Media(**entry)


def store_account(
        account: Account, existing_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE account
               SET url            = %(url)s,
                   id_on_platform = %(id_on_platform)s,
                   display_name   = %(display_name)s,
                   bio            = %(bio)s,
                   data           = %(data)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "id_on_platform": account.id_on_platform,
                "url": account.url,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
            },
            return_type="none"
        )
        return account.id
    else:
        account_id = db.execute_query(
            """INSERT INTO account (url, id_on_platform, display_name, bio, data)
               VALUES (%(url)s, %(id_on_platform)s, %(display_name)s, %(bio)s, %(data)s)""",
            {
                "id_on_platform": account.id_on_platform,
                "url": account.url,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
            },
            return_type="id"
        )
        return account_id


def store_account_archive(
        account: Account, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE account_archive
               SET url                = %(url)s,
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
                "url": account.url,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
            },
            return_type="none"
        )
        return account.id
    else:
        account_id = db.execute_query(
            """INSERT INTO account_archive (url, id_on_platform, display_name, bio, data, archive_session_id,
                                            canonical_id)
               VALUES (%(url)s, %(id_on_platform)s, %(display_name)s, %(bio)s, %(data)s, %(archive_session_id)s,
                       %(canonical_id)s)""",
            {
                "id_on_platform": account.id_on_platform,
                "url": account.url,
                "display_name": account.display_name,
                "bio": account.bio,
                "data": json.dumps(account.data) if account.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id
            },
            return_type="id"
        )
        return account_id


def store_post(
        post: Post, existing_id: Optional[int], _: Optional[Path]
) -> int:
    if post.account_id is None:
        stored_account = get_stored_account_archive(
            Account(url=post.account_url, id_on_platform=post.account_id_on_platform), None
        )
        if stored_account is None:
            raise ValueError("Post must have account_id set before storing.")
        else:
            post.account_id = stored_account.id
    if existing_id is not None:
        db.execute_query(
            """UPDATE post
               SET url              = %(url)s,
                   id_on_platform   = %(id_on_platform)s,
                   account_id       = %(account_id)s,
                   publication_date = %(publication_date)s,
                   caption          = %(caption)s,
                   data             = %(data)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "url": post.url,
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
        post_id = db.execute_query(
            """INSERT INTO post (url, id_on_platform, account_id, publication_date, caption, data)
               VALUES (%(url)s, %(id_on_platform)s, %(account_id)s, %(publication_date)s, %(caption)s, %(data)s)""",
            {
                "url": post.url,
                "id_on_platform": post.id_on_platform,
                "account_id": post.account_id,
                "publication_date": post.publication_date.isoformat() if post.publication_date else None,
                "caption": post.caption,
                "data": json.dumps(post.data) if post.data else None,
            },
            return_type="id"
        )
        return post_id


def store_post_archive(
        post: Post, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], _: Optional[Path]
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE post_archive
               SET url                    = %(url)s,
                   id_on_platform         = %(id_on_platform)s,
                   publication_date       = %(publication_date)s,
                   caption                = %(caption)s,
                   data                   = %(data)s,
                   archive_session_id     = %(archive_session_id)s,
                   canonical_id           = %(canonical_id)s,
                   account_url            = %(account_url)s,
                   account_id_on_platform = %(account_id_on_platform)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "url": post.url,
                "id_on_platform": post.id_on_platform,
                "publication_date": post.publication_date.isoformat() if post.publication_date else None,
                "caption": post.caption,
                "data": json.dumps(post.data) if post.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "account_url": post.account_url,
                "account_id_on_platform": post.account_id_on_platform
            },
            return_type="none"
        )
        return post.id
    else:
        post_id = db.execute_query(
            """INSERT INTO post_archive (url, id_on_platform, publication_date, caption, data, archive_session_id,
                                         canonical_id, account_url, account_id_on_platform)
               VALUES (%(url)s, %(id_on_platform)s, %(publication_date)s, %(caption)s, %(data)s, %(archive_session_id)s,
                       %(canonical_id)s, %(account_url)s, %(account_id_on_platform)s)""",
            {
                "url": post.url,
                "id_on_platform": post.id_on_platform,
                "publication_date": post.publication_date.isoformat() if post.publication_date else None,
                "caption": post.caption,
                "data": json.dumps(post.data) if post.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "account_url": post.account_url,
                "account_id_on_platform": post.account_id_on_platform
            },
            return_type="id"
        )
        return post_id


def preprocess_media(media: Media, _: Optional[int], archive_location: Path) -> Media:
    local_url = (f"{LOCAL_ARCHIVES_DIR_ALIAS}/" + (archive_location / media.local_url).relative_to(ROOT_ARCHIVES).as_posix()) if media.local_url is not None else None
    media.local_url = local_url
    return media


def store_media(
        media: Media, existing_id: Optional[int], archive_location: Path
) -> int:
    if media.post_id is None:
        stored_post = get_stored_post_archive(
            Post(url=media.post_url, id_on_platform=media.post_id_on_platform), None
        )
        if stored_post is None:
            raise ValueError("Media must have post_id set before storing.")
        else:
            media.post_id = stored_post.id
    if existing_id is not None:
        db.execute_query(
            """UPDATE media
               SET url            = %(url)s,
                   id_on_platform = %(id_on_platform)s,
                   post_id        = %(post_id)s,
                   local_url      = %(local_url)s,
                   media_type     = %(media_type)s,
                   data           = %(data)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "url": media.url,
                "id_on_platform": media.id_on_platform,
                "post_id": media.post_id,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
            },
            return_type="none"
        )
        return media.id
    else:
        media_id = db.execute_query(
            """INSERT INTO media (url, id_on_platform, post_id, local_url, media_type, data)
               VALUES (%(url)s, %(id_on_platform)s, %(post_id)s, %(local_url)s, %(media_type)s, %(data)s)""",
            {
                "url": media.url,
                "id_on_platform": media.id_on_platform,
                "post_id": media.post_id,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
            },
            return_type="id"
        )
        return media_id


def store_media_archive(
        media: Media, archive_session_id: int, existing_id: Optional[int], canonical_id: Optional[int], archive_location: Path
) -> int:
    if existing_id is not None:
        db.execute_query(
            """UPDATE media_archive
               SET url                 = %(url)s,
                   id_on_platform      = %(id_on_platform)s,
                   local_url           = %(local_url)s,
                   media_type          = %(media_type)s,
                   data                = %(data)s,
                   archive_session_id  = %(archive_session_id)s,
                   canonical_id        = %(canonical_id)s,
                   post_url            = %(post_url)s,
                   post_id_on_platform = %(post_id_on_platform)s
               WHERE id = %(id)s""",
            {
                "id": existing_id,
                "url": media.url,
                "id_on_platform": media.id_on_platform,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "post_url": media.post_url,
                "post_id_on_platform": media.post_id_on_platform
            },
            return_type="none"
        )
        return media.id
    else:
        media_id = db.execute_query(
            """INSERT INTO media_archive (url, id_on_platform, local_url, media_type, data, archive_session_id,
                                          canonical_id, post_url, post_id_on_platform)
               VALUES (%(url)s, %(id_on_platform)s, %(local_url)s, %(media_type)s, %(data)s, %(archive_session_id)s,
                       %(canonical_id)s, %(post_url)s, %(post_id_on_platform)s)""",
            {
                "url": media.url,
                "id_on_platform": media.id_on_platform,
                "local_url": media.local_url,
                "media_type": media.media_type,
                "data": json.dumps(media.data) if media.data else None,
                "archive_session_id": archive_session_id,
                "canonical_id": canonical_id,
                "post_url": media.post_url,
                "post_id_on_platform": media.post_id_on_platform
            },
            return_type="id"
        )
        return media_id


entity_types: list[EntityProcessingConfig] = [
    EntityProcessingConfig(
        key="accounts",
        table="account",
        get_entity=get_stored_account_archive,
        store_entity=store_account,
        store_entity_archive=store_account_archive,
        merge=reconcile_accounts
    ),
    EntityProcessingConfig(
        key="posts",
        table="post",
        get_entity=get_stored_post_archive,
        store_entity=store_post,
        store_entity_archive=store_post_archive,
        merge=reconcile_posts
    ),
    EntityProcessingConfig(
        key="media",
        table="media",
        get_entity=get_stored_media_archive,
        store_entity=store_media,
        store_entity_archive=store_media_archive,
        merge=reconcile_media,
        raw_entity_preprocessing=preprocess_media
    ),
]
