import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Callable, TypeVar

import pyperclip
from pydantic import BaseModel

from extractors.entity_types import Post, Account, Media, \
    ExtractedEntitiesFlattened, Comment, Like, Follower, \
    SuggestedAccount, TaggedAccount, ExtractedEntitiesNested, AccountAndAssociatedEntities, PostAndAssociatedEntities, \
    MediaAndAssociatedEntities
from extractors.extract_photos import acquire_photos, PhotoAcquisitionConfig, Photo
from extractors.extract_videos import acquire_videos, VideoAcquisitionConfig, Video
from extractors.models import MediaShortcode, HighlightsReelConnection, StoriesFeed, CommentsConnection
from extractors.models_api_v1 import MediaInfoApiV1, CommentsApiV1, LikersApiV1, FriendshipsApiV1
from extractors.models_graphql import ProfileTimelineGraphQL, ReelsMediaConnection, FriendsListGraphQL
from extractors.reconcile_entities import reconcile_accounts, reconcile_posts, reconcile_media
from extractors.structures_extraction import StructureType, structures_from_har
from extractors.structures_extraction_api_v1 import ApiV1Response, ApiV1Context
from extractors.structures_extraction_graphql import GraphQLResponse
from extractors.structures_extraction_html import PageResponse


class ExtractedHarData(BaseModel):
    structures: list[StructureType]
    videos: list[Video]
    photos: list[Photo]


def extract_data_from_har(
        har_path: Path,
        video_acquisition_config: VideoAcquisitionConfig = VideoAcquisitionConfig(
            download_missing=True, download_media_not_in_structures=True, download_unfetched_media=True,
            download_full_versions_of_fetched_media=True, download_highest_quality_assets_from_structures=True
        ),
        photo_acquisition_config: PhotoAcquisitionConfig = PhotoAcquisitionConfig(
            download_missing=True, download_media_not_in_structures=True, download_unfetched_media=True,
            download_highest_quality_assets_from_structures=True
        )
) -> ExtractedHarData:
    archive_dir = har_path.parent

    structures = structures_from_har(har_path)

    videos = acquire_videos(
        har_path,
        archive_dir / "videos",
        structures=structures,
        config=video_acquisition_config
    )

    photos = acquire_photos(
        har_path,
        archive_dir / "photos",
        structures=structures,
        config=photo_acquisition_config
    )

    return ExtractedHarData(
        structures=structures,
        videos=videos,
        photos=photos
    )


def har_data_to_entities(
        har_path: Path,
        structures: list[StructureType],
        videos: list[Video],
        photos: list[Photo]
) -> ExtractedEntitiesFlattened:
    archive_dir = har_path.parent
    local_files_map = dict()
    for video in videos:
        if video.fetched_tracks:
            for track in video.fetched_tracks.values():
                if len(video.local_files):
                    local_files_map[canonical_cdn_url(track.base_url) + ".mp4"] = video.local_files[0]
        if video.full_asset:
            local_files_map[canonical_cdn_url(video.full_asset)] = video.local_files[0]
    for photo in photos:
        if len(photo.local_files) > 0:
            local_files_map[canonical_cdn_url(photo.url)] = photo.local_files[0]

    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], followers=[], suggested_accounts=[], tagged_accounts=[]
    )
    for structure in structures:
        try:
            extend_flattened_entities(entities, convert_structure_to_entities(structure))
        except Exception as e:
            print(f"Error converting structure to entities: {e}")
            print(traceback.format_exc())
            continue
    flattened_entities = deduplicate_entities(entities)
    attach_media_to_entities(flattened_entities, local_files_map, archive_dir)
    return flattened_entities


def extract_entities_from_har(
        har_path: Path,
        video_acquisition_config: VideoAcquisitionConfig = VideoAcquisitionConfig(
            download_missing=True, download_media_not_in_structures=True, download_unfetched_media=True,
            download_full_versions_of_fetched_media=True, download_highest_quality_assets_from_structures=True
        ),
        photo_acquisition_config: PhotoAcquisitionConfig = PhotoAcquisitionConfig(
            download_missing=True, download_media_not_in_structures=True, download_unfetched_media=True,
            download_highest_quality_assets_from_structures=True
        )
) -> ExtractedEntitiesFlattened:
    har_data = extract_data_from_har(
        har_path,
        video_acquisition_config=video_acquisition_config,
        photo_acquisition_config=photo_acquisition_config
    )
    flattened_entities = har_data_to_entities(
        har_path,
        har_data.structures,
        har_data.videos,
        har_data.photos
    )
    return flattened_entities


def nest_entities_from_archive_session(entities: ExtractedEntitiesFlattened) -> ExtractedEntitiesNested:
    nested_accounts: list[AccountAndAssociatedEntities] = []
    orphaned_posts: list[PostAndAssociatedEntities] = []
    orphaned_media: list[MediaAndAssociatedEntities] = []

    account_map: dict[str, AccountAndAssociatedEntities] = {}
    for account in entities.accounts:
        account_map[account.url] = AccountAndAssociatedEntities(
            **account.model_dump(),
            account_posts=[],
            account_followers=[],
            account_suggested_accounts=[]
        )
        nested_accounts.append(account_map[account.url])

    post_map: dict[str, PostAndAssociatedEntities] = {}
    for post in entities.posts:
        post_map[post.url] = PostAndAssociatedEntities(
            **post.model_dump(),
            post_media=[],
            post_comments=[],
            post_likes=[],
            post_tagged_accounts=[],
            post_author=None
        )
        account_url = post.account_url
        if account_url in account_map:
            post_map[post.url].post_author = account_map[account_url]
            account_map[account_url].account_posts.append(post_map[post.url])
        else:
            orphaned_posts.append(post_map[post.url])

    for media in entities.media:
        if media.post_url in post_map:
            post_map[media.post_url].post_media.append(MediaAndAssociatedEntities(
                **media.model_dump(),
                media_parent_post=post_map[media.post_url]
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


def attach_media_to_entities(
        entities: ExtractedEntitiesFlattened,
        local_files_map: dict[str, Path],
        archive_dir: Path
) -> None:
    for media in entities.media:
        clean_media_url = media.url
        if clean_media_url in local_files_map:
            local_media_url = local_files_map[clean_media_url]
            relative_path = local_media_url.relative_to(archive_dir)
            media.local_url = str(relative_path)
    # TODO: filter out media without local files?


def convert_structure_to_entities(structure: StructureType) -> ExtractedEntitiesFlattened:
    if isinstance(structure, GraphQLResponse):
        return graphql_to_entities(structure)
    elif isinstance(structure, ApiV1Response):
        return api_v1_to_entities(structure)
    elif isinstance(structure, PageResponse):
        return page_to_entities(structure)
    else:
        raise ValueError(f"Unsupported structure type: {type(structure)}")


def extend_flattened_entities(
        entities_1: ExtractedEntitiesFlattened,
        entities_2: ExtractedEntitiesFlattened
) -> None:
    entities_1.accounts.extend(entities_2.accounts)
    entities_1.posts.extend(entities_2.posts)
    entities_1.media.extend(entities_2.media)
    entities_1.comments.extend(entities_2.comments)
    entities_1.likes.extend(entities_2.likes)
    entities_1.followers.extend(entities_2.followers)
    entities_1.suggested_accounts.extend(entities_2.suggested_accounts)
    entities_1.tagged_accounts.extend(entities_2.tagged_accounts)


def graphql_to_entities(structure: GraphQLResponse) -> ExtractedEntitiesFlattened:
    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], followers=[], suggested_accounts=[], tagged_accounts=[]
    )
    if structure.reels_media:
        extend_flattened_entities(entities, graphql_reels_media_to_entities(structure.reels_media))
    if structure.stories_feed:
        extend_flattened_entities(entities, page_stories_to_entities(structure.stories_feed))
    if structure.profile_timeline:
        extend_flattened_entities(entities, graphql_profile_timeline_to_entities(structure.profile_timeline))
    if structure.comments_connection:
        extend_flattened_entities(entities,
                                  graphql_comments_to_entities(structure.comments_connection, structure.context)),
    if structure.likes:
        extend_flattened_entities(entities, graphql_likes_to_entities(structure.likes, structure.context))
    if structure.friends_list:
        extend_flattened_entities(entities, graphql_friends_to_entities(structure.friends_list, structure.context))
    return entities


def graphql_reels_media_to_entities(structure: ReelsMediaConnection) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    for edge in structure.edges:
        highlight = edge.node
        for item in highlight.items:
            account = Account(
                id_on_platform=highlight.user.id,
                url=f"https://www.instagram.com/{highlight.user.username}/",
                display_name=None,
                bio=None,
                data=highlight.user.model_dump()
            )
            extracted_accounts.append(account)
            post = Post(
                id_on_platform=item.id,
                url="https://www.instagram.com/p/" + media_id_to_shortcode(int(item.pk)),
                account_id_on_platform=account.id_on_platform,
                account_url=account.url,
                publication_date=datetime.fromtimestamp(item.taken_at),
                caption=item.caption.text if item.caption else None,
                data=item.model_dump()
            )
            extracted_posts.append(post)
            extracted_media.append(Media(
                id_on_platform=item.id,
                url=canonical_cdn_url(
                    item.video_versions[0].url if item.video_versions
                    else item.image_versions2.candidates[0].url
                ),
                post_id_on_platform=post.id_on_platform,
                post_url=post.url,
                local_url=None,
                media_type="video" if item.video_versions else "image",
                data=item.model_dump(exclude={'carousel_media'})
            ))
            if item.carousel_media:
                for media_item in item.carousel_media:
                    media_url = canonical_cdn_url(
                        item.video_versions[0].url if item.video_versions
                        else item.image_versions2.candidates[0].url
                    )
                    extracted_media.append(Media(
                        id_on_platform=media_item.id,
                        url=media_url,
                        post_id_on_platform=post.id_on_platform,
                        post_url=post.url,
                        local_url=None,
                        media_type="image" if media_item.media_type == 1 else "video",
                        data=media_item.model_dump()
                    ))
                    if media_item.usertags:
                        for tag in media_item.usertags.in_field:
                            extracted_tagged_accounts.append(TaggedAccount(
                                tagged_account_id=tag.user.id,
                                tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                                context_account_id=highlight.user.id,
                                context_post_url=post.url,
                                context_media_url=media_url,
                                context_post_id_on_platform=post.id_on_platform,
                                context_media_id_on_platform=media_item.id,
                                data=None
                            ))
                            extracted_accounts.append(Account(
                                id_on_platform=tag.user.id,
                                url=f"https://www.instagram.com/{tag.user.username}/",
                                display_name=tag.user.full_name,
                                bio=None,
                                data=tag.user.model_dump()
                            ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], followers=[], suggested_accounts=[]
    )


def graphql_profile_timeline_to_entities(structure: ProfileTimelineGraphQL) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []

    for edge in structure.edges:
        item = edge.node
        account = Account(
            id_on_platform=item.user.id,
            url=f"https://www.instagram.com/{item.user.username}/",
            display_name=None,
            bio=None,
            data=item.user.model_dump()
        )
        extracted_accounts.append(account)
        post = Post(
            id_on_platform=item.id,
            url="https://www.instagram.com/p/" + media_id_to_shortcode(int(item.pk)),
            account_id_on_platform=item.user.id,
            account_url=account.url,
            publication_date=datetime.fromtimestamp(item.taken_at),
            caption=item.caption.text if item.caption else None,
            data=item.model_dump()
        )
        extracted_posts.append(post)
        tagged_accounts: list[TaggedAccount] = []
        if item.usertags:
            for tag in item.usertags.in_field:
                tagged_accounts.append(TaggedAccount(
                    tagged_account_id=tag.user.id,
                    tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                    context_account_id=item.user.id,
                    context_post_url=post.url,
                    context_media_url=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    data=None
                ))
                extracted_accounts.append(Account(
                    id_on_platform=tag.user.id,
                    url=f"https://www.instagram.com/{tag.user.username}/",
                    display_name=tag.user.full_name,
                    bio=None,
                    data=tag.user.model_dump()
                ))
        extracted_media.append(Media(
            id_on_platform=item.id,
            url=canonical_cdn_url(
                item.video_versions[0].url if item.video_versions else item.image_versions2.candidates[0].url),
            post_id_on_platform=post.id_on_platform,
            post_url=post.url,
            local_url=None,
            media_type="video" if item.video_versions else "image",
            data=item.model_dump(exclude={'carousel_media'})
        ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                media_url = media_item.video_versions[0].url if media_item.video_versions else \
                    media_item.image_versions2.candidates[0].url
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url=canonical_cdn_url(media_url),
                    post_id_on_platform=post.id_on_platform,
                    post_url=post.url,
                    local_url=None,
                    media_type="image" if media_item.media_type == 1 else "video",
                    data=media_item.model_dump()
                ))
                if media_item.usertags:
                    for tag in media_item.usertags.in_field:
                        tagged_accounts.append(TaggedAccount(
                            tagged_account_id=tag.user.id,
                            tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                            context_account_id=item.user.id,
                            context_post_url=post.url,
                            context_media_url=media_url,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            data=None
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url=f"https://www.instagram.com/{tag.user.username}/",
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump()
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], followers=[], suggested_accounts=[]
    )


def graphql_comments_to_entities(structure: CommentsConnection, context: Any) -> ExtractedEntitiesFlattened:
    variables = context.get('variables', {}) if isinstance(context, dict) else {}
    post_pk: Optional[str] = variables.get('media_id', None)
    post_url = f"https://www.instagram.com/p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    extracted_comments: list[Comment] = []
    extracted_accounts: list[Account] = []
    for e in structure.edges:
        c = e.node
        if c.user:
            extracted_accounts.append(Account(
                id_on_platform=c.user.id,
                url=f"https://www.instagram.com/{c.user.username}/",
                display_name=None,
                bio=None,
                data=c.user.model_dump()
            ))
        comment = Comment(
            id_on_platform=c.pk,
            url=f"{post_url}c/{c.pk}/" if post_url else None,
            post_id_on_platform=post_pk,
            post_url=post_url,
            account_id_on_platform=c.user.pk if c.user else None,
            account_url=f"https://www.instagram.com/{c.user.username}/" if c.user else None,
            text=c.text,
            publication_date=datetime.fromtimestamp(c.created_at) if c.created_at else None,
            data=c.model_dump()
        )
        extracted_comments.append(comment)
    return ExtractedEntitiesFlattened(
        comments=extracted_comments,
        accounts=extracted_accounts,
        likes=[], followers=[], suggested_accounts=[], tagged_accounts=[], media=[], posts=[]
    )


def graphql_likes_to_entities(structure: LikersApiV1, context: Any) -> ExtractedEntitiesFlattened:
    variables = context.get('variables', {}) if isinstance(context, dict) else {}
    post_pk: Optional[int] = variables.get('media_id', None)
    post_url = f"https://www.instagram.com/p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    extracted_likes: list[Like] = []
    extracted_accounts: list[Account] = []
    for u in structure.users:
        like = Like(
            id_on_platform=None,
            post_id_on_platform=post_pk,
            post_url=post_url,
            account_id_on_platform=u.pk,
            account_url=f"https://www.instagram.com/{u.username}/",
            data=u.model_dump(),
        )
        extracted_likes.append(like)
        extracted_accounts.append(Account(
            id_on_platform=u.pk,
            url=like.account_url,
            display_name=u.full_name,
            bio=None,
            data=u.model_dump()
        ))
    return ExtractedEntitiesFlattened(
        likes=extracted_likes,
        accounts=extracted_accounts,
        comments=[], followers=[], suggested_accounts=[], tagged_accounts=[], media=[], posts=[]
    )


def graphql_friends_to_entities(structure: FriendsListGraphQL, context: Any) -> ExtractedEntitiesFlattened:
    variables = context.get('variables', '{}') if isinstance(context, dict) else '{}'
    variables = json.loads(variables)
    target_account_id: Optional[str] = variables.get('target_id', None)
    extracted_suggested_accounts: list[SuggestedAccount] = []
    extracted_accounts: list[Account] = []
    for u in structure.users:
        account = Account(
            url=f"https://www.instagram.com/{u.username}/",
            display_name=u.full_name,
            bio=None,
            id_on_platform=u.id,
            data=u.model_dump()
        )
        extracted_accounts.append(account)
        follower = SuggestedAccount(
            context_account_id=target_account_id,
            suggested_account_id=u.id,
            data=None
        )
        extracted_suggested_accounts.append(follower)
    return ExtractedEntitiesFlattened(
        suggested_accounts=extracted_suggested_accounts,
        accounts=extracted_accounts,
        comments=[], followers=[], likes=[], tagged_accounts=[], media=[], posts=[]
    )


def api_v1_to_entities(structure: ApiV1Response) -> ExtractedEntitiesFlattened:
    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], followers=[], suggested_accounts=[], tagged_accounts=[]
    )
    if structure.media_info:
        extend_flattened_entities(entities, api_v1_media_info_to_entities(structure.media_info))
    if structure.comments:
        extend_flattened_entities(entities, api_v1_comments_to_entities(structure.comments, structure.context))
    if structure.likers:
        extend_flattened_entities(entities, api_v1_likes_to_entities(structure.likers, structure.context))
    if structure.friendships:
        extend_flattened_entities(entities, api_v1_friendships_to_entities(structure.friendships, structure.context))
    return entities


def api_v1_media_info_to_entities(media_info: MediaInfoApiV1) -> ExtractedEntitiesFlattened:
    extracted_posts: list[Post] = []
    extracted_accounts: list[Account] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    extracted_media: list[Media] = []
    for item in media_info.items:
        account = Account(
            id_on_platform=item.owner.id,
            url=f"https://www.instagram.com/{item.owner.username}/",
            display_name=item.owner.full_name,
            bio=None,
            data=item.owner.model_dump()
        )
        extracted_accounts.append(account)
        post = Post(
            id_on_platform=item.id,
            url="https://www.instagram.com/p/" + media_id_to_shortcode(int(item.pk)),
            account_id_on_platform=account.id_on_platform,
            account_url=account.url,
            publication_date=datetime.fromtimestamp(item.taken_at),
            caption=item.caption.text if item.caption else None,
            data=item.model_dump()
        )
        extracted_posts.append(post)
        extracted_media.append(Media(
            id_on_platform=item.id,
            url=canonical_cdn_url(
                item.video_versions[0].url if item.video_versions else item.image_versions2.candidates[0].url),
            post_id_on_platform=post.id_on_platform,
            post_url=post.url,
            local_url=None,
            media_type="video" if item.video_versions else "image",
            data=item.model_dump(exclude={'carousel_media'})
        ))
        if item.usertags:
            for tag in item.usertags.in_field:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id=tag.user.id,
                    tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                    context_account_id=item.owner.id,
                    context_post_url=post.url,
                    context_media_url=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    data=None
                ))
                extracted_accounts.append(Account(
                    id_on_platform=tag.user.id,
                    url=f"https://www.instagram.com/{tag.user.username}/",
                    display_name=tag.user.full_name,
                    bio=None,
                    data=tag.user.model_dump()
                ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], followers=[], suggested_accounts=[]
    )


def api_v1_comments_to_entities(comments_insta: CommentsApiV1, context: ApiV1Context) -> ExtractedEntitiesFlattened:
    post_pk: Optional[str] = context.media_id
    comments: list[Comment] = []
    accounts: list[Account] = []

    post_url = f"https://www.instagram.com/p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    for c in comments_insta.comments:
        if c.user:
            accounts.append(Account(
                id_on_platform=c.user.id,
                url=f"https://www.instagram.com/{c.user.username}/",
                display_name=None,
                bio=None,
                data=c.user.model_dump()
            ))
        comment = Comment(
            id_on_platform=c.pk,
            url=f"{post_url}c/{c.pk}/" if post_url else None,
            post_id_on_platform=post_pk,
            post_url=post_url,
            account_id_on_platform=c.user.id,
            account_url=f"https://www.instagram.com/{c.user.username}/" if c.user else None,
            text=c.text,
            publication_date=datetime.fromtimestamp(c.created_at) if c.created_at else None,
            data=c.model_dump()
        )
        comments.append(comment)
    return ExtractedEntitiesFlattened(
        comments=comments,
        accounts=accounts,
        likes=[], followers=[], suggested_accounts=[], tagged_accounts=[], media=[], posts=[]
    )


def api_v1_likes_to_entities(structure: LikersApiV1, context: ApiV1Context) -> ExtractedEntitiesFlattened:
    post_pk: Optional[int] = context.media_id
    post_url = f"https://www.instagram.com/p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
    extracted_likes: list[Like] = []
    accounts: list[Account] = []
    for u in structure.users:
        accounts.append(Account(
            id_on_platform=u.pk,
            url=f"https://www.instagram.com/{u.username}/",
            display_name=u.full_name,
            bio=None,
            data=u.model_dump()
        ))
        extracted_likes.append(Like(
            id_on_platform=None,
            post_id_on_platform=post_pk,
            post_url=post_url,
            account_id_on_platform=u.pk,
            account_url=f"https://www.instagram.com/{u.username}/",
            data=u.model_dump(),
        ))
    return ExtractedEntitiesFlattened(
        likes=extracted_likes,
        accounts=accounts,
        comments=[], followers=[], suggested_accounts=[], tagged_accounts=[], media=[], posts=[]
    )


def api_v1_friendships_to_entities(structure: FriendshipsApiV1, context: ApiV1Context) -> ExtractedEntitiesFlattened:
    url: Optional[str] = context.url
    follow_direction = "followers" if "followers" in url else ("following" if "following" in url else None)
    target_account_id = url.split("friendships/")[1].split("/")[0] if url else None
    extracted_friends: list[Follower] = []
    accounts: list[Account] = []
    for u in structure.users:
        account = Account(
            url=f"https://www.instagram.com/{u.username}/",
            display_name=u.full_name,
            bio=None,
            id_on_platform=u.id,
            data=u.model_dump()
        )
        accounts.append(account)
        like = Follower(
            follower_account_id=u.id if follow_direction == "followers" else target_account_id,
            following_account_id=u.id if follow_direction == "following" else target_account_id,
            data=None
        )
        extracted_friends.append(like)
    return ExtractedEntitiesFlattened(
        followers=extracted_friends,
        accounts=accounts,
        comments=[], likes=[], suggested_accounts=[], tagged_accounts=[], media=[], posts=[]
    )


def page_to_entities(structure: PageResponse) -> ExtractedEntitiesFlattened:
    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], followers=[], suggested_accounts=[], tagged_accounts=[]
    )
    if structure.posts:
        extend_flattened_entities(entities, page_posts_to_entities(structure.posts))
    if structure.highlight_reels:
        extend_flattened_entities(entities, page_highlight_reels_to_entities(structure.highlight_reels))
    if structure.stories:
        extend_flattened_entities(entities, graphql_reels_media_to_entities(structure.stories))
    if structure.stories_direct:
        extend_flattened_entities(entities, page_stories_to_entities(structure.stories_direct))
    if structure.comments:
        extend_flattened_entities(entities, page_comments_to_entities(structure.comments, structure.posts))
    return entities


def page_posts_to_entities(structure: MediaShortcode) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    for item in structure.items:
        account: Account = Account(
            id_on_platform=item.owner.id,
            url=f"https://www.instagram.com/{item.owner.username}/",
            display_name=item.owner.full_name,
            bio=None,
            data=item.owner.model_dump()
        )
        extracted_accounts.append(account)
        post = Post(
            id_on_platform=item.id,
            url="https://www.instagram.com/p/" + media_id_to_shortcode(int(item.pk)),
            account_id_on_platform=item.owner.id,
            account_url=account.url,
            publication_date=datetime.fromtimestamp(item.taken_at),
            caption=item.caption.text if item.caption else None,
            data=item.model_dump()
        )
        extracted_posts.append(post)
        extracted_media.append(Media(
            id_on_platform=item.id,
            url=canonical_cdn_url(
                item.video_versions[0].url if item.video_versions else item.image_versions2.candidates[0].url),
            post_id_on_platform=post.id_on_platform,
            post_url=post.url,
            local_url=None,
            media_type="video" if item.video_versions else "image",
            data=item.model_dump(exclude={'carousel_media'})
        ))
        if item.usertags:
            for tag in item.usertags.in_field:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id=tag.user.id,
                    tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                    context_account_id=item.owner.id,
                    context_post_url=post.url,
                    context_media_url=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    data=None
                ))
                extracted_accounts.append(Account(
                    id_on_platform=tag.user.id,
                    url=f"https://www.instagram.com/{tag.user.username}/",
                    display_name=tag.user.full_name,
                    bio=None,
                    data=tag.user.model_dump()
                ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                url = (media_item.video_versions[0].url
                       if media_item.video_versions and len(media_item.video_versions)
                       else (
                    media_item.image_versions2.candidates[0].url
                    if media_item.image_versions2 and len(media_item.image_versions2.candidates)
                    else None
                ))
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url=canonical_cdn_url(url),
                    post_id_on_platform=post.id_on_platform,
                    post_url=post.url,
                    local_url=None,
                    media_type="image" if media_item.media_type == 1 else "video",
                    data=media_item.model_dump()
                ))
                if media_item.usertags:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id=tag.user.id,
                            tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                            context_account_id=item.owner.id,
                            context_post_url=post.url,
                            context_media_url=url,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            data=None
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url=f"https://www.instagram.com/{tag.user.username}/",
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump()
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        likes=[], comments=[], followers=[], suggested_accounts=[]
    )


def page_highlight_reels_to_entities(structure: HighlightsReelConnection) -> ExtractedEntitiesFlattened:
    extracted_posts: list[Post] = []
    extracted_accounts: list[Account] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    highlight = structure.edges[0].node if structure.edges else None
    if not highlight:
        return ExtractedEntitiesFlattened(
            accounts=[], posts=[], media=[], comments=[], likes=[], followers=[], suggested_accounts=[],
            tagged_accounts=[]
        )
    account = Account(
        id_on_platform=highlight.user.id,
        url=f"https://www.instagram.com/{highlight.user.username}/",
        display_name=None,
        bio=None,
        data=highlight.user.model_dump()
    )
    extracted_accounts.append(account)
    for reel in highlight.items:
        post = Post(
            id_on_platform=reel.id,
            url="https://www.instagram.com/p/" + media_id_to_shortcode(int(reel.pk)),
            account_id_on_platform=highlight.user.id,
            account_url=account.url,
            publication_date=datetime.fromtimestamp(reel.taken_at),
            caption=reel.caption,
            data=reel.model_dump()
        )
        extracted_posts.append(post)
        extracted_media.append(Media(
            id_on_platform=reel.id,
            url=canonical_cdn_url(
                reel.video_versions[0].url if reel.video_versions else reel.image_versions2.candidates[0].url),
            post_id_on_platform=post.id_on_platform,
            post_url=post.url,
            local_url=None,
            media_type="video" if reel.video_versions else "image",
            data=reel.model_dump()
        ))
        if reel.story_bloks_stickers:
            for sticker in reel.story_bloks_stickers:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id=None,
                    tagged_account_url=f"https://www.instagram.com/{sticker.bloks_sticker.sticker_data.ig_mention.username}/",
                    context_account_id=highlight.user.id,
                    context_post_url=post.url,
                    context_media_url=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    data=None
                ))
                extracted_accounts.append(Account(
                    id_on_platform=None,
                    url=f"https://www.instagram.com/{sticker.bloks_sticker.sticker_data.ig_mention.username}/",
                    display_name=sticker.bloks_sticker.sticker_data.ig_mention.full_name,
                    bio=None,
                    data=sticker.bloks_sticker.sticker_data.ig_mention.model_dump()
                ))
        if reel.carousel_media:
            for media_item in reel.carousel_media:
                media_url = media_item.video_versions[0].url if media_item.video_versions else \
                    media_item.image_versions2.candidates[0].url
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url=canonical_cdn_url(media_url),
                    post_id_on_platform=post.id_on_platform,
                    post_url=post.url,
                    local_url=None,
                    media_type="image" if media_item.media_type == 1 else "video",
                    data=media_item.model_dump()
                ))
                if media_item.usertags:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id=tag.user.id,
                            tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                            context_account_id=highlight.user.id,
                            context_post_url=post.url,
                            context_media_url=media_url,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            data=None
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url=f"https://www.instagram.com/{tag.user.username}/",
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump()
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], followers=[], suggested_accounts=[]
    )


def page_stories_to_entities(structure: StoriesFeed) -> ExtractedEntitiesFlattened:
    extracted_accounts: list[Account] = []
    extracted_posts: list[Post] = []
    extracted_media: list[Media] = []
    extracted_tagged_accounts: list[TaggedAccount] = []
    reels_media = structure.reels_media[0] if structure.reels_media and len(structure.reels_media) > 0 else None
    if not reels_media:
        return ExtractedEntitiesFlattened(
            accounts=[], posts=[], media=[], comments=[], likes=[], followers=[], suggested_accounts=[],
            tagged_accounts=[]
        )
    account = Account(
        id_on_platform=reels_media.user.id,
        url=f"https://www.instagram.com/{reels_media.user.username}/",
        display_name=None,
        bio=None,
        data=reels_media.user.model_dump()
    )
    extracted_accounts.append(account)
    for item in reels_media.items:
        post = Post(
            id_on_platform=item.id,
            url="https://www.instagram.com/p/" + media_id_to_shortcode(int(item.pk)),
            account_id_on_platform=reels_media.user.id,
            account_url=account.url,
            publication_date=datetime.fromtimestamp(item.taken_at),
            caption=item.caption.text if item.caption else None,
            data=item.model_dump()
        )
        extracted_posts.append(post)
        if item.story_bloks_stickers:
            for sticker in item.story_bloks_stickers:
                extracted_tagged_accounts.append(TaggedAccount(
                    tagged_account_id=None,
                    tagged_account_url=f"https://www.instagram.com/{sticker.bloks_sticker.sticker_data.ig_mention.username}/",
                    context_account_id=reels_media.user.id,
                    context_post_url=post.url,
                    context_media_url=None,
                    context_post_id_on_platform=post.id_on_platform,
                    context_media_id_on_platform=None,
                    data=None
                ))
                extracted_accounts.append(Account(
                    id_on_platform=None,
                    url=f"https://www.instagram.com/{sticker.bloks_sticker.sticker_data.ig_mention.username}/",
                    display_name=sticker.bloks_sticker.sticker_data.ig_mention.full_name,
                    bio=None,
                    data=sticker.bloks_sticker.sticker_data.ig_mention.model_dump()
                ))
        extracted_media.append(Media(
            id_on_platform=item.id,
            url=canonical_cdn_url(
                item.video_versions[0].url if item.video_versions else item.image_versions2.candidates[0].url),
            post_id_on_platform=post.id_on_platform,
            post_url=post.url,
            local_url=None,
            media_type="video" if item.video_versions else "image",
            data=item.model_dump()
        ))
        if item.carousel_media:
            for media_item in item.carousel_media:
                media_url = media_item.video_versions[0].url if media_item.video_versions else \
                    media_item.image_versions2.candidates[0].url
                extracted_media.append(Media(
                    id_on_platform=media_item.id,
                    url=canonical_cdn_url(media_url),
                    post_id_on_platform=post.id_on_platform,
                    post_url=post.url,
                    local_url=None,
                    media_type="image" if media_item.media_type == 1 else "video",
                    data=media_item.model_dump()
                ))
                if media_item.usertags:
                    for tag in media_item.usertags.in_field:
                        extracted_tagged_accounts.append(TaggedAccount(
                            tagged_account_id=tag.user.id,
                            tagged_account_url=f"https://www.instagram.com/{tag.user.username}/",
                            context_account_id=reels_media.user.id,
                            context_post_url=post.url,
                            context_media_url=media_url,
                            context_post_id_on_platform=post.id_on_platform,
                            context_media_id_on_platform=media_item.id,
                            data=None
                        ))
                        extracted_accounts.append(Account(
                            id_on_platform=tag.user.id,
                            url=f"https://www.instagram.com/{tag.user.username}/",
                            display_name=tag.user.full_name,
                            bio=None,
                            data=tag.user.model_dump()
                        ))
    return ExtractedEntitiesFlattened(
        accounts=extracted_accounts,
        posts=extracted_posts,
        media=extracted_media,
        tagged_accounts=extracted_tagged_accounts,
        comments=[], likes=[], followers=[], suggested_accounts=[]
    )


def page_comments_to_entities(comments_structure: CommentsConnection,
                              post_structure: MediaShortcode) -> ExtractedEntitiesFlattened:
    extracted_comments: list[Comment] = []
    extracted_accounts: list[Account] = []
    try:
        post_pk: Optional[str] = post_structure.items[0].pk
        post_url = f"https://www.instagram.com/p/{media_id_to_shortcode(int(post_pk))}/" if post_pk else None
        for e in comments_structure.edges:
            c = e.node
            account = Account(
                id_on_platform=c.user.pk if c.user else None,
                url=f"https://www.instagram.com/{c.user.username}/" if c.user else None,
                data=c.user.model_dump(),
                display_name=None, bio=None
            )
            extracted_accounts.append(account)
            comment = Comment(
                id_on_platform=c.pk,
                url=f"{post_url}c/{c.pk}/" if post_url else None,
                post_id_on_platform=post_pk,
                post_url=post_url,
                account_id_on_platform=account.id_on_platform,
                account_url=account.url,
                text=c.text,
                publication_date=datetime.fromtimestamp(c.created_at) if c.created_at else None,
                data=c.model_dump()
            )
            extracted_comments.append(comment)
    except Exception as ex:
        print(f"Error extracting comments from page: {ex}")
    return ExtractedEntitiesFlattened(
        comments=extracted_comments,
        accounts=extracted_accounts,
        likes=[], followers=[], suggested_accounts=[], tagged_accounts=[], media=[], posts=[]
    )


def canonical_cdn_url(url: str) -> str:
    insta_filename = url.split("?")[0].split("/")[-1]
    return f"https://scontent.cdninstagram.com/v/{insta_filename}"


def media_id_to_shortcode(media_id: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    shortcode = ''
    while media_id > 0:
        media_id, remainder = divmod(media_id, 64)
        shortcode = alphabet[remainder] + shortcode
    return shortcode


T = TypeVar("T")


def deduplicate_list_by_multiple_keys(
        entries: list[T],
        key_fields: list[Callable[[T], Optional[str]]],
        merge_function: Callable[[T, T], T] = None
) -> list[T]:
    # Filter down the set of entries such that no two entries have the same values for *any* of the key fields, unless the value is None
    unique_entries: list[T] = []
    entries_key_map: dict[tuple, int] = dict()
    for entry in entries:
        existing_copy: Optional[int] = None
        for key_index in range(len(key_fields)):
            key_field = key_fields[key_index]
            key_value = key_field(entry)
            if key_value is not None:
                key = (key_index, key_value)
                if key in entries_key_map:
                    existing_copy = entries_key_map[key]
                    break
        if existing_copy is None:
            unique_entries.append(entry)
            existing_copy = len(unique_entries) - 1
        else:
            unique_entries[existing_copy] = merge_function(unique_entries[existing_copy], entry) if merge_function else \
                unique_entries[existing_copy]
        for key_index in range(len(key_fields)):
            key_field = key_fields[key_index]
            key_value = key_field(entry)
            if key_value is not None:
                key = (key_index, key_value)
                entries_key_map[key] = entry if existing_copy is None else existing_copy
    return unique_entries


def deduplicate_entities(entities: ExtractedEntitiesFlattened) -> ExtractedEntitiesFlattened:
    return ExtractedEntitiesFlattened(
        accounts=deduplicate_list_by_multiple_keys(
            entities.accounts,
            [
                lambda x: x.id_on_platform,
                lambda x: x.url
            ],
            reconcile_accounts
        ),
        posts=deduplicate_list_by_multiple_keys(
            entities.posts,
            [
                lambda x: x.id_on_platform,
                lambda x: x.url
            ],
            reconcile_posts
        ),
        media=deduplicate_list_by_multiple_keys(
            entities.media,
            [
                lambda x: x.id_on_platform,
                lambda x: x.url
            ],
            reconcile_media
        ),
        comments=deduplicate_list_by_multiple_keys(entities.comments, [
            lambda x: x.id_on_platform,
            lambda x: x.url
        ]),
        likes=deduplicate_list_by_multiple_keys(entities.likes, [
            lambda x: "_".join([x.post_id_on_platform,
                                x.account_id_on_platform]) if x.post_id_on_platform and x.account_id_on_platform else None,
            lambda x: "_".join([x.post_url, x.account_url]) if x.post_url and x.account_url else None
        ]),
        followers=deduplicate_list_by_multiple_keys(entities.followers, [
            lambda x: "_".join([x.follower_account_id,
                                x.following_account_id]) if x.follower_account_id and x.following_account_id else None,
            lambda x: "_".join([x.follower_account_url,
                                x.following_account_url]) if x.follower_account_url and x.following_account_url else None
        ]),
        suggested_accounts=deduplicate_list_by_multiple_keys(entities.suggested_accounts, [
            lambda x: "_".join([x.context_account_id,
                                x.suggested_account_id]) if x.context_account_id and x.suggested_account_id else None
        ]),
        tagged_accounts=deduplicate_list_by_multiple_keys(entities.tagged_accounts, [
            lambda x: "_".join([
                x.tagged_account_id or "",
                x.context_post_id_on_platform or "",
                x.context_media_id_on_platform or ""
            ]) if x.tagged_account_id and (x.context_post_id_on_platform or x.context_media_id_on_platform) else None,
            lambda x: "_".join([
                x.tagged_account_url or "",
                x.context_post_url or "",
                x.context_media_url or ""
            ]) if x.tagged_account_url and (x.context_post_url or x.context_media_url) else None
        ])
    )


def manual_entity_extraction():
    # Provide the path to your .har file and desired output folder
    har_file = input("Input path to HAR file: ")  # Replace with your actual HAR file
    # Strip leading and trailing whitespace as well as " " or " from the input
    har_file = har_file.strip().strip('"').strip("'")
    har_path = Path(har_file)
    entities = extract_entities_from_har(
        har_path,
        VideoAcquisitionConfig(
            download_missing=False,
            download_media_not_in_structures=False,
            download_unfetched_media=False,
            download_full_versions_of_fetched_media=False,
            download_highest_quality_assets_from_structures=False
        ),
        PhotoAcquisitionConfig(
            download_missing=False,
            download_media_not_in_structures=False,
            download_unfetched_media=False,
            download_highest_quality_assets_from_structures=False
        )
    )
    pyperclip.copy(entities.model_dump_json(indent=2))


if __name__ == '__main__':
    manual_entity_extraction()
