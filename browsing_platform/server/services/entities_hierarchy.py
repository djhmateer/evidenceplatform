from typing import Literal

from extractors.entity_types import ExtractedEntitiesFlattened, ExtractedEntitiesNested, AccountAndAssociatedEntities, \
    PostAndAssociatedEntities, MediaAndAssociatedEntities

T_Entities = Literal["archiving_session", "account", "post", "media", "media_part"]


def nest_entities(
        entities: ExtractedEntitiesFlattened,
) -> ExtractedEntitiesNested:
    nested_accounts: list[AccountAndAssociatedEntities] = []
    orphaned_posts: list[PostAndAssociatedEntities] = []
    orphaned_media: list[MediaAndAssociatedEntities] = []

    account_map: dict[int, AccountAndAssociatedEntities] = {}
    for account in entities.accounts:
        account_map[account.id] = AccountAndAssociatedEntities(
            **account.model_dump(),
            account_posts=[],
            account_followers=[],
            account_suggested_accounts=[]
        )
        nested_accounts.append(account_map[account.id])

    post_map: dict[int, PostAndAssociatedEntities] = {}
    for post in entities.posts:
        post_map[post.id] = PostAndAssociatedEntities(
            **post.model_dump(),
            post_media=[],
            post_comments=[],
            post_likes=[],
            post_tagged_accounts=[],
            post_author=None
        )
        if post.account_id in account_map:
            # post_map[post.id].post_author = account_map[post.account_id]
            account_map[post.account_id].account_posts.append(post_map[post.id])
        else:
            orphaned_posts.append(post_map[post.id])

    for media in entities.media:
        if media.post_id in post_map:
            post_map[media.post_id].post_media.append(MediaAndAssociatedEntities(
                **media.model_dump(),
                media_parent_post=None
            ))
        else:
            orphaned_media.append(MediaAndAssociatedEntities(
                **media.model_dump(),
                media_parent_post=None
            ))

    return ExtractedEntitiesNested(
        accounts=nested_accounts,
        posts=orphaned_posts,
        media=orphaned_media
    )
