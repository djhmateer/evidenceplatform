import string
from datetime import datetime
from secrets import choice
from typing import Optional

from pydantic import BaseModel

from browsing_platform.server.services.entities_hierarchy import T_Entities
from browsing_platform.server.services.media import get_media_by_id
from browsing_platform.server.services.media_part import get_media_part_by_id
from browsing_platform.server.services.post import get_post_by_id
from utils import db

SHARE_LINK_LENGTH = 24


class EntityShare(BaseModel):
    entity: T_Entities
    entity_id: int


class EntityShareLink(EntityShare):
    id: Optional[int]
    create_date: Optional[datetime] = None
    update_date: Optional[datetime] = None
    created_by_user_id: int
    valid: bool
    link_suffix: str


def generate_suffix() -> str:
    """Generate a random token string of TOKEN_LENGTH characters."""
    return ''.join(choice(string.ascii_letters + string.digits) for _ in range(SHARE_LINK_LENGTH))


class SharePermissions(BaseModel):
    view: bool = False
    edit: bool = False
    censored_session_properties: Optional[list[str]] = None


class EntitySharePermissions(SharePermissions):
    shared_entity: Optional[EntityShare] = None


class ShareLinkCreationResult(BaseModel):
    success: bool
    link_suffix: Optional[str] = None
    error: Optional[str] = None


def create_share_link(scope: EntitySharePermissions, user_id: int) -> ShareLinkCreationResult:
    try:
        suffix = generate_suffix()
        db.execute_query(
            '''INSERT INTO entity_share_link
            (created_by_user_id, entity, entity_id, valid, link_suffix)
            VALUES (%(created_by_user_id)s, %(entity)s, %(entity_id)s, TRUE, %(link_suffix)s)'''
            , {
                "created_by_user_id": user_id,
                "entity": scope.shared_entity.entity,
                "entity_id": scope.shared_entity.entity_id,
                "link_suffix": suffix
            }, "none"
        )
        return ShareLinkCreationResult(
            success=True,
            link_suffix=suffix,
        )
    except Exception as e:
        return ShareLinkCreationResult(
            success=False,
            error=str(e)
        )


def get_existing_share_link(entity: T_Entities, entity_id: int) -> Optional[EntityShareLink]:
    link_share = db.execute_query(
        '''SELECT * FROM entity_share_link
        WHERE entity = %(entity)s AND entity_id = %(entity_id)s AND valid = TRUE'''
        , {"entity": entity, "entity_id": entity_id}, "single_row"
    )
    if link_share is None:
        return None
    else:
        return EntityShareLink(**link_share)


def get_link_permissions(link_suffix: str) -> EntitySharePermissions:
    try:
        if not link_suffix:
            return EntitySharePermissions(view=False)
        token_check = db.execute_query(
            '''SELECT * FROM entity_share_link
            WHERE link_suffix = %(token)s'''
            , {"token": link_suffix}, "single_row"
        )
        if token_check is None:
            return EntitySharePermissions(view=False)
        else:
            share_link = EntityShareLink(**token_check)
            if not share_link.valid:
                return EntitySharePermissions(view=False)
            else:
                return EntitySharePermissions(view=True, shared_entity=EntityShare(
                    entity=share_link.entity,
                    entity_id=share_link.entity_id
                ))
    except Exception:
        return EntitySharePermissions(view=False)


def check_share_permissions(link_suffix: str, requested_entity: T_Entities, requested_entity_id: int) -> SharePermissions:
    share_scope = get_link_permissions(link_suffix)
    share_permissions = SharePermissions(**share_scope.model_dump(exclude={"shared_entity"}))
    shared_entity = share_scope.shared_entity
    if not shared_entity:
        return SharePermissions(view=False)
    if shared_entity.entity == requested_entity and shared_entity.entity_id == requested_entity_id:
        return share_permissions
    if shared_entity.entity == "account":
        if requested_entity == "post":
            post = get_post_by_id(requested_entity_id)
            if post and post.account_id == shared_entity.entity_id:
                return share_permissions
        elif requested_entity == "media":
            media = get_media_by_id(requested_entity_id)
            if media:
                post = get_post_by_id(media.post_id)
                if post and post.account_id == shared_entity.entity_id:
                    return share_permissions
        elif requested_entity == "media_part":
            media_part = get_media_part_by_id(requested_entity_id)
            if media_part and media_part.media_id:
                media = get_media_by_id(media_part.media_id)
                if media:
                    post = get_post_by_id(media.post_id)
                    if post and post.account_id == shared_entity.entity_id:
                        return share_permissions
    if shared_entity.entity == "post":
        if requested_entity == "media":
            media = get_media_by_id(requested_entity_id)
            if media and media.post_id == shared_entity.entity_id:
                return share_permissions
        elif requested_entity == "media_part":
            media_part = get_media_part_by_id(requested_entity_id)
            if media_part and media_part.media_id:
                media = get_media_by_id(media_part.media_id)
                if media and media.post_id == shared_entity.entity_id:
                    return share_permissions
    if shared_entity.entity == "media":
        if requested_entity == "media_part":
            media_part = get_media_part_by_id(requested_entity_id)
            if media_part and media_part.media_id == shared_entity.entity_id:
                return share_permissions
    return SharePermissions(view=False)



def invalidate_suffix(link_suffix: str):
    db.execute_query(
        '''UPDATE entity_share_link SET valid = FALSE WHERE link_suffix = %(link_suffix)s'''
        , {"link_suffix": link_suffix}, "none"
    )
    return True
