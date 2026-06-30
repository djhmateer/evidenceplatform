"""Generic, platform-agnostic HAR -> structures -> entities orchestration.

Scans a HAR once (structures + media in a single pass), acquires media, converts
structures to abstract entities, dedups and (optionally) nests them. All
platform-specific detail lives in the per-platform packages
(``extractors.instagram`` / ``extractors.threads``): structure *detection* is
host-routed via ``extract_structure_from_entry``; structure -> entity *mapping*
is dispatched by structure type in ``convert_structure_to_entities``. A single
mixed-platform HAR therefore flows through here with no global pivot.
"""
import base64
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import ijson
from pydantic import BaseModel

from archiver.summarizers import download_log as dl
from extractors.entity_types import Account, Post, Media, \
    ExtractedEntitiesFlattened, ExtractedEntitiesNested, AccountAndAssociatedEntities, \
    PostAndAssociatedEntities, MediaAndAssociatedEntities
from extractors.extract_photos import acquire_photos, PhotoAcquisitionConfig, Photo, \
    _is_image_request, extract_xpv_asset_id as _extract_photo_asset_id
from extractors.extract_videos import acquire_videos, VideoAcquisitionConfig, Video, \
    accumulate_video_segment, reconcile_video_dicts, byte_range_from_har_entry
from extractors.extraction_helpers import canonical_cdn_url, extend_flattened_entities
from extractors.reconcile_entities import reconcile_accounts, reconcile_posts, reconcile_media
from extractors.structures_extraction import StructureType, extract_structure_from_entry
from extractors.instagram.structures_extraction_graphql import GraphQLResponse
from extractors.instagram.structures_extraction_api_v1 import ApiV1Response
from extractors.instagram.structures_extraction_html import PageResponse
from extractors.instagram import structures_to_entities as _ig
from extractors.threads.structures_extraction import ThreadsResponse
from extractors.threads import structures_to_entities as _th


class ExtractedHarData(BaseModel):
    structures: list[StructureType]
    videos: list[Video]
    photos: list[Photo]


def _scan_har_once(har_path: Path) -> tuple[list[StructureType], list[Video], list[Photo], set[str]]:
    """
    Single streaming pass over a HAR file that simultaneously extracts:
    - structures (GraphQL / API v1 / HTML responses)
    - video segment maps (.mp4 entries)
    - photo maps (image entries)
    - the set of every requested .mp4 URL (incl. bodyless ones), so acquire_videos
      can flag requested-in-session videos without a second HAR pass

    Replaces three separate ijson passes with one, roughly tripling parse speed.
    """
    structures: list[StructureType] = []
    real_xpv_dict: dict[str, Video] = {}
    fallback_dict: dict[str, Video] = {}
    filename_to_xpv: dict[str, str] = {}
    photos_dict: dict = {}  # keys are str (filename) or int (hash fallback)
    requested_mp4_urls: set[str] = set()

    with open(har_path, 'rb') as f:
        for entry in ijson.items(f, 'log.entries.item'):
            url: str = entry['request']['url']
            content: dict = entry['response']['content']
            mime: str = content.get('mimeType', '')

            if '.mp4' in url:
                requested_mp4_urls.add(url)

            # --- Structures (host-routed: Instagram, Threads, ...) ---
            try:
                structure = extract_structure_from_entry(entry)
                if structure:
                    structures.append(structure)
            except Exception as e:
                print(f"Error processing structures entry: {e}")
                traceback.print_exc()

            # --- Video segment maps (.mp4 entries with base64 content) ---
            try:
                if '.mp4' in url and 'text' in content:
                    body = base64.b64decode(content['text'])
                    accumulate_video_segment(url, body, real_xpv_dict, fallback_dict, filename_to_xpv,
                                             byte_range=byte_range_from_har_entry(entry))
            except Exception as e:
                print(f"Error processing video entry: {e}")
                traceback.print_exc()

            # --- Photo maps (image content entries) ---
            try:
                if _is_image_request(url) and 'text' in content:
                    try:
                        img_data = base64.b64decode(content['text'])
                    except Exception:
                        pass
                    else:
                        asset_id = _extract_photo_asset_id(url) or hash(url)
                        img_filename = url.split('/')[-1].split('?')[0]
                        if asset_id not in photos_dict:
                            photos_dict[asset_id] = Photo(asset_id=str(asset_id), fetched_assets={}, url=url)
                        photos_dict[asset_id].fetched_assets[img_filename] = img_data
            except Exception:
                pass

    reconcile_video_dicts(real_xpv_dict, fallback_dict, filename_to_xpv, structures=structures)
    return structures, list(real_xpv_dict.values()), list(photos_dict.values()), requested_mp4_urls


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

    structures, har_video_maps, har_photo_maps, requested_mp4_urls = _scan_har_once(har_path)

    # downloaded_media_log.json carries acquisition history across re-extraction
    # runs. Pass the live object into both acquire_* calls so they can both
    # consult and update it, then persist once at the end.
    download_log = dl.load(archive_dir)

    videos = acquire_videos(
        har_path,
        archive_dir / "videos",
        structures=structures,
        config=video_acquisition_config,
        har_video_maps=har_video_maps,
        download_log=download_log,
        requested_mp4_urls=requested_mp4_urls,
    )

    photos = acquire_photos(
        har_path,
        archive_dir / "photos",
        structures=structures,
        config=photo_acquisition_config,
        har_photo_maps=har_photo_maps,
        download_log=download_log,
    )

    dl.save(archive_dir, download_log)

    return ExtractedHarData(
        structures=structures,
        videos=videos,
        photos=photos
    )


def har_data_to_entities(
        archive_path: Path,
        structures: list[StructureType],
        videos: list[Video],
        photos: list[Photo],
) -> ExtractedEntitiesFlattened:
    archive_dir = archive_path.parent
    local_files_map = dict()
    for video in videos:
        if video.fetched_tracks:
            for track in video.fetched_tracks.values():
                if video.local_files and len(video.local_files):
                    local_files_map[canonical_cdn_url(track.base_url) + ".mp4"] = video.local_files[0]
        if video.full_asset and video.local_files and len(video.local_files):
            local_files_map[canonical_cdn_url(video.full_asset)] = video.local_files[0]
    for photo in photos:
        if photo.local_files and len(photo.local_files) > 0:
            local_files_map[canonical_cdn_url(photo.url)] = photo.local_files[0]

    entities = ExtractedEntitiesFlattened(
        accounts=[], posts=[], media=[], comments=[], likes=[], account_relations=[], tagged_accounts=[]
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

    # Maps are keyed by (platform, identifier): Instagram and Threads share the Meta
    # pk space, so two same-pk cross-platform entities in one mixed session must not
    # collide here (last-writer-wins would mis-nest one platform's children under the
    # other). Every extracted entity carries a platform, so lookups compose it too.
    account_suffix_map: dict[tuple, AccountAndAssociatedEntities] = {}
    account_id_map: dict[tuple, AccountAndAssociatedEntities] = {}
    for account in entities.accounts:
        account_entity = AccountAndAssociatedEntities(
            **account.model_dump(),
            account_posts=[],
            account_relations=[]
        )
        if account.url_suffix:
            account_suffix_map[(account.platform, account.url_suffix)] = account_entity
        if account.id_on_platform:
            account_id_map[(account.platform, account.id_on_platform)] = account_entity
        nested_accounts.append(account_entity)

    def _find_account(platform, url_suffix: Optional[str], id_on_platform: Optional[str]) -> Optional[AccountAndAssociatedEntities]:
        if url_suffix and (platform, url_suffix) in account_suffix_map:
            return account_suffix_map[(platform, url_suffix)]
        if id_on_platform and (platform, id_on_platform) in account_id_map:
            return account_id_map[(platform, id_on_platform)]
        return None

    post_map: dict[tuple, PostAndAssociatedEntities] = {}
    for post in entities.posts:
        post_entity = PostAndAssociatedEntities(
            **post.model_dump(),
            post_media=[],
            post_comments=[],
            post_likes=[],
            post_tagged_accounts=[],
            post_author=None
        )
        account_entity = _find_account(post.platform, post.account_url_suffix, post.account_id_on_platform)
        if account_entity is not None:
            post_entity.post_author = account_entity
            account_entity.account_posts.append(post_entity)
        else:
            orphaned_posts.append(post_entity)
        if post.id_on_platform is not None:
            post_map[(post.platform, post.id_on_platform)] = post_entity

    for media in entities.media:
        parent_key = (media.platform, media.post_id_on_platform)
        if media.post_id_on_platform is not None and parent_key in post_map:
            post_map[parent_key].post_media.append(MediaAndAssociatedEntities(
                **media.model_dump(),
                media_parent_post=post_map[parent_key]
            ))
        else:
            orphaned_media.append(MediaAndAssociatedEntities(
                **media.model_dump(),
                media_parent_post=None
            ))

    for comment in entities.comments:
        parent_key = (comment.platform, comment.post_id_on_platform)
        if comment.post_id_on_platform and parent_key in post_map:
            post_map[parent_key].post_comments.append(comment)

    for like in entities.likes:
        parent_key = (like.platform, like.post_id_on_platform)
        if like.post_id_on_platform and parent_key in post_map:
            post_map[parent_key].post_likes.append(like)

    for tagged in entities.tagged_accounts:
        parent_key = (tagged.platform, tagged.context_post_id_on_platform)
        if tagged.context_post_id_on_platform and parent_key in post_map:
            post_map[parent_key].post_tagged_accounts.append(tagged)

    for relation in entities.account_relations:
        account_entity = (
            _find_account(relation.platform, relation.follower_account_url_suffix, relation.follower_account_id_on_platform)
            or _find_account(relation.platform, relation.followed_account_url_suffix, relation.followed_account_id_on_platform)
        )
        if account_entity is not None:
            account_entity.account_relations.append(relation)

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
        clean_media_url = media.url_suffix
        if clean_media_url is not None and clean_media_url in local_files_map:
            local_media_url = local_files_map[clean_media_url]
            relative_path = local_media_url.relative_to(archive_dir)
            media.local_url = str(relative_path)
    # TODO: filter out media without local files?


def convert_structure_to_entities(structure: StructureType) -> ExtractedEntitiesFlattened:
    if isinstance(structure, GraphQLResponse):
        return _ig.graphql_to_entities(structure)
    elif isinstance(structure, ApiV1Response):
        return _ig.api_v1_to_entities(structure)
    elif isinstance(structure, PageResponse):
        return _ig.page_to_entities(structure)
    elif isinstance(structure, ThreadsResponse):
        return _th.threads_to_entities(structure)
    else:
        raise ValueError(f"Unsupported structure type: {type(structure)}")


T = TypeVar("T")


def deduplicate_list_by_multiple_keys(
        entries: list[T],
        key_fields: list[Callable[[T], Optional[str]]],
        merge_function: Callable[[T, T], T] = None
) -> list[T]:
    # Collapse entries that share any identifier — directly or transitively through
    # a third entry that bridges two otherwise-disjoint identifier sets. The previous
    # left-to-right algorithm could leave such bridged pairs separate when the third
    # entry arrived later, because already-stored entries were never re-evaluated.
    # Union-find over (key_index, key_value) pairs makes the equivalence transitive.
    if not entries:
        return []
    n = len(entries)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri == rj:
            return
        # Keep the smaller (earlier-encountered) index as root so result order
        # matches first-appearance order of each cluster.
        if ri < rj:
            parent[rj] = ri
        else:
            parent[ri] = rj

    for key_index, key_field in enumerate(key_fields):
        first_index_for_value: dict = {}
        for i, entry in enumerate(entries):
            value = key_field(entry)
            if value is None:
                continue
            if value in first_index_for_value:
                union(first_index_for_value[value], i)
            else:
                first_index_for_value[value] = i

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)

    result: list[T] = []
    # Iterate components in order of their root (= smallest member index), so the
    # output preserves the order entries were first seen.
    for root in sorted(components.keys()):
        member_indices = components[root]
        merged = entries[member_indices[0]]
        if merge_function is not None and len(member_indices) > 1:
            # Fold later entries into the accumulator in original order. This
            # matches the original semantics (merge_function(older, newer) — newer
            # wins on conflicts, older fills gaps), so later observations of the
            # same logical entity still take precedence.
            for idx in member_indices[1:]:
                merged = merge_function(merged, entries[idx])
        result.append(merged)
    return result


def deduplicate_entities(entities: ExtractedEntitiesFlattened) -> ExtractedEntitiesFlattened:
    # Identity is per-platform: Instagram and Threads share the Meta pk space, so
    # every identifier key is composed with platform as a tuple. The `url` keys are
    # already platform-distinct (reconstruct_url embeds the platform domain), EXCEPT
    # media.url, which resolves to the shared cdninstagram.com CDN for both platforms
    # and so must also be composed. Each key returns None (not a (platform, None)
    # tuple) when the identifier is absent, so the union-find never collapses
    # identifier-less entities of the same platform.
    return ExtractedEntitiesFlattened(
        accounts=deduplicate_list_by_multiple_keys(
            entities.accounts,
            [
                lambda x: (x.platform, x.id_on_platform) if x.id_on_platform else None,
                lambda x: x.url
            ],
            reconcile_accounts
        ),
        posts=deduplicate_list_by_multiple_keys(
            entities.posts,
            [
                lambda x: (x.platform, x.id_on_platform) if x.id_on_platform else None,
                lambda x: x.url
            ],
            reconcile_posts
        ),
        media=deduplicate_list_by_multiple_keys(
            entities.media,
            [
                lambda x: (x.platform, x.id_on_platform) if x.id_on_platform else None,
                lambda x: (x.platform, x.url) if x.url else None
            ],
            reconcile_media
        ),
        comments=deduplicate_list_by_multiple_keys(entities.comments, [
            lambda x: (x.platform, x.id_on_platform) if x.id_on_platform else None,
            lambda x: x.url
        ]),
        likes=deduplicate_list_by_multiple_keys(entities.likes, [
            lambda x: (x.platform, x.id_on_platform) if x.id_on_platform else None,
        ]),
        account_relations=deduplicate_list_by_multiple_keys(entities.account_relations, [
            lambda x: (x.platform, x.id_on_platform) if x.id_on_platform else None,
        ]),
        tagged_accounts=deduplicate_list_by_multiple_keys(entities.tagged_accounts, [
            lambda x: (x.platform, x.id_on_platform) if x.id_on_platform else None,
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
        video_acquisition_config=VideoAcquisitionConfig(
            download_missing=False,
            download_media_not_in_structures=False,
            download_unfetched_media=False,
            download_full_versions_of_fetched_media=False,
            download_highest_quality_assets_from_structures=False
        ),
        photo_acquisition_config=PhotoAcquisitionConfig(
            download_missing=False,
            download_media_not_in_structures=False,
            download_unfetched_media=False,
            download_highest_quality_assets_from_structures=False
        )
    )
    print(entities)


if __name__ == '__main__':
    manual_entity_extraction()
