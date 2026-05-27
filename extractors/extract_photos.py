# python
# File: extractors/extract_photos.py
import base64
import os
from hashlib import md5
from pathlib import Path
from typing import Literal, Optional
from urllib import parse as urllib_parse

import ijson
import requests
from pydantic import BaseModel

from archiver.summarizers import download_log as dl
from extractors.structures_extraction import StructureType
from extractors.structures_extraction import structures_from_har
from extractors.structures_extraction_api_v1 import ApiV1Response
from extractors.structures_extraction_graphql import GraphQLResponse
from extractors.structures_extraction_html import PageResponse
from utils.integrity import FileIntegrity, protect_file, prune_orphan_sidecars

OnLoggedMissingPhoto = Literal["use_har_bytes_only", "skip", "redownload"]


def _safe_id(identifier: str, max_len: int = 60) -> str:
    """Return identifier truncated to max_len, using an md5 suffix to stay unique."""
    if len(identifier) <= max_len:
        return identifier
    return identifier[:max_len - 9] + '_' + md5(identifier.encode()).hexdigest()[:8]

# Supported image extensions
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'heif'}

# ---------- Models ----------

class Photo(BaseModel):
    asset_id: str
    url: str
    fetched_assets: Optional[dict[str, bytes]] = None
    full_asset: Optional[str] = None
    local_files: Optional[list[Path]] = None


class AssetSaveResult(BaseModel):
    success: bool = True
    location: Optional[Path] = None
    integrity: Optional[FileIntegrity] = None


class PhotoAcquisitionConfig(BaseModel):
    download_missing: bool = True
    download_media_not_in_structures: bool = True
    download_unfetched_media: bool = True
    download_highest_quality_assets_from_structures: bool = True
    # Mirrors VideoAcquisitionConfig.on_logged_missing. Photos have no
    # reassembly step (they're atomic), so "use_har_bytes_only" simply means
    # `save_fetched_photo` is permitted but no CDN fetch. The default keeps
    # user deletions sticky across re-extraction runs.
    on_logged_missing: OnLoggedMissingPhoto = "use_har_bytes_only"


# ---------- Helpers ----------

def extract_xpv_asset_id(url) -> Optional[str]:
    try:
        path = urllib_parse.urlparse(url).path
        filename = path.rsplit('/', 1)[-1]
        if not filename:
            return None
        filename = filename.split('?')[0]
        return filename
    except Exception:
        return None


def _is_image_request(url: str) -> bool:
    lower = url.lower()
    return any(lower.split('?')[0].endswith('.' + ext) for ext in IMAGE_EXTENSIONS)


def download_file(url: str) -> Optional[bytes]:
    try:
        print("Downloading file from:", url)
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp.content
        else:
            raise Exception(f"Failed to download file, status code: {resp.status_code}")
    except Exception as e:
        print(f"Error: {e}")
        return None


# ---------- HAR Extraction ----------

def extract_photo_maps(har_path: Path) -> list[Photo]:
    photos_dict: dict[int, Photo] = {}
    with open(har_path, 'rb') as f:
        for entry in ijson.items(f, 'log.entries.item'):
            try:
                url = entry['request']['url']
                if not _is_image_request(url):
                    continue
                content_obj = entry.get('response', {}).get('content', {})
                if 'text' not in content_obj:
                    continue
                raw_b64 = content_obj['text']
                try:
                    data = base64.b64decode(raw_b64)
                except Exception:
                    continue
                asset_id = extract_xpv_asset_id(url) or hash(url)
                filename = url.split('/')[-1].split('?')[0]
                if asset_id not in photos_dict:
                    photos_dict[asset_id] = Photo(asset_id=asset_id, fetched_assets={}, url=url)
                photos_dict[asset_id].fetched_assets[filename] = data
            except Exception:
                continue
    return list(photos_dict.values())


# ---------- Structure Extraction ----------

def extract_photos_from_structures(structures: list[StructureType]) -> list[Photo]:
    # We assume any media object that has image_versions2/candidates like Instagram JSON
    # Here we reuse existing traversal patterns similar to videos, but focusing on image URLs.
    photos: dict[str, Photo] = {}

    def register(pk: str, url: str):
        asset_id = extract_xpv_asset_id(url)
        if asset_id not in photos:
            photos[asset_id] = Photo(asset_id=asset_id, full_asset=url, url=url)
        else:
            # Prefer longer (likely higher quality) URL path length
            if photos[asset_id].full_asset and url and len(url) > len(photos[asset_id].full_asset):
                photos[asset_id].full_asset = url

    for s in structures or []:
        try:
            if isinstance(s, GraphQLResponse):
                # reels_media
                if s.reels_media:
                    for edge in s.reels_media.edges:
                        for item in edge.node.items:
                            if item.image_versions2 and item.image_versions2.candidates:
                                register(item.pk, item.image_versions2.candidates[0].url)
                            if item.carousel_media:
                                for c in item.carousel_media:
                                    if c.image_versions2 and c.image_versions2.candidates:
                                        register(c.pk, c.image_versions2.candidates[0].url)
                # stories_feed
                if s.stories_feed:
                    for edge in s.stories_feed.reels_media:
                        for item in edge.items:
                            if item.image_versions2 and item.image_versions2.candidates:
                                register(item.pk, item.image_versions2.candidates[0].url)
                            if item.carousel_media:
                                for c in item.carousel_media:
                                    if c.image_versions2 and c.image_versions2.candidates:
                                        register(c.pk, c.image_versions2.candidates[0].url)
                # profile timeline
                if s.profile_timeline:
                    for edge in s.profile_timeline.edges:
                        node = edge.node
                        if node.image_versions2 and node.image_versions2.candidates:
                            register(node.pk, node.image_versions2.candidates[0].url)
                        if node.carousel_media:
                            for c in node.carousel_media:
                                if c.image_versions2 and c.image_versions2.candidates:
                                    register(c.pk, c.image_versions2.candidates[0].url)
                # clips_user_connection (thumbnails)
                if s.clips_user_connection:
                    for edge in s.clips_user_connection.edges:
                        media = edge.node.media
                        if media.image_versions2 and media.image_versions2.candidates:
                            register(media.pk, media.image_versions2.candidates[0].url)
                # post_shortcode (single-post payload arriving via graphql)
                if s.post_shortcode:
                    for post in s.post_shortcode.items:
                        if post.image_versions2 and post.image_versions2.candidates:
                            register(post.pk, post.image_versions2.candidates[0].url)
                        if post.carousel_media:
                            for c in post.carousel_media:
                                if c.image_versions2 and c.image_versions2.candidates:
                                    register(c.pk, c.image_versions2.candidates[0].url)

            elif isinstance(s, ApiV1Response):
                if s.media_info:
                    for item in s.media_info.items:
                        if item.image_versions2 and item.image_versions2.candidates:
                            register(item.pk, item.image_versions2.candidates[0].url)
                        if item.carousel_media:
                            for c in item.carousel_media:
                                if c.image_versions2 and c.image_versions2.candidates:
                                    register(c.pk, c.image_versions2.candidates[0].url)

            elif isinstance(s, PageResponse):
                if s.posts:
                    for post in s.posts.items:
                        if post.image_versions2 and post.image_versions2.candidates:
                            register(post.pk, post.image_versions2.candidates[0].url)
                        if post.carousel_media:
                            for c in post.carousel_media:
                                if c.image_versions2 and c.image_versions2.candidates:
                                    register(c.pk, c.image_versions2.candidates[0].url)
                if s.stories:
                    for edge in s.stories.edges:
                        for item in edge.node.items:
                            if item.image_versions2 and item.image_versions2.candidates:
                                register(item.pk, item.image_versions2.candidates[0].url)
                            if item.carousel_media:
                                for c in item.carousel_media:
                                    if c.image_versions2 and c.image_versions2.candidates:
                                        register(c.pk, c.image_versions2.candidates[0].url)
                if s.stories_direct:
                    for reel in s.stories_direct.reels_media:
                        for item in reel.items:
                            if item.image_versions2 and item.image_versions2.candidates:
                                register(item.pk, item.image_versions2.candidates[0].url)
                            if item.carousel_media:
                                for c in item.carousel_media:
                                    if c.image_versions2 and c.image_versions2.candidates:
                                        register(c.pk, c.image_versions2.candidates[0].url)
                if s.highlight_reels:
                    for reel in s.highlight_reels.edges:
                        for item in reel.node.items:
                            if item.image_versions2 and item.image_versions2.candidates:
                                register(item.pk, item.image_versions2.candidates[0].url)
                            if item.carousel_media:
                                for c in item.carousel_media:
                                    if c.image_versions2 and c.image_versions2.candidates:
                                        register(c.pk, c.image_versions2.candidates[0].url)
                if s.timelines:
                    for item in s.timelines.items:
                        if item.image_versions2 and item.image_versions2.candidates:
                            register(item.pk, item.image_versions2.candidates[0].url)
                        if item.carousel_media:
                            for c in item.carousel_media:
                                if c.image_versions2 and c.image_versions2.candidates:
                                    register(c.pk, c.image_versions2.candidates[0].url)
        except Exception:
            continue
    return list(photos.values())


# ---------- Existing files ----------

def get_existing_photos(working_dir: Path) -> dict[str, Path]:
    """Return a dict mapping lowercased filename to Path for every image file in working_dir."""
    existing = {}
    for file in working_dir.iterdir():
        if not file.is_file():
            continue
        file_name = file.name.lower()
        if any(file_name.endswith('.' + ext) for ext in IMAGE_EXTENSIONS):
            if file_name not in existing or file.stat().st_size > existing[file_name].stat().st_size:
                existing[file_name] = file
    return existing


# ---------- Saving ----------

def save_fetched_photo(photo: Photo, output_dir: Path) -> AssetSaveResult:
    if not photo.fetched_assets:
        return AssetSaveResult(success=False)
    # choose largest (by bytes) fetched asset
    best_name, best_bytes = max(photo.fetched_assets.items(), key=lambda kv: len(kv[1]))
    out_name = f"photo_{_safe_id(str(photo.asset_id))}_{_safe_id(best_name)}"
    out_path = output_dir / out_name
    try:
        with open(out_path, 'wb') as f:
            f.write(best_bytes)
        protection = protect_file(out_path)
        return AssetSaveResult(
            success=True,
            location=out_path,
            integrity=protection.to_integrity(base_dir=output_dir),
        )
    except Exception:
        return AssetSaveResult(success=False)


def download_full_asset(photo: Photo, output_dir: Path) -> AssetSaveResult:
    if not photo.full_asset:
        return AssetSaveResult(success=False)
    data = download_file(photo.full_asset)
    if not data:
        return AssetSaveResult(success=False)
    out_name = f"photo_full_{_safe_id(str(photo.asset_id))}"
    out_path = output_dir / out_name
    try:
        with open(out_path, 'wb') as f:
            f.write(data)
        protection = protect_file(out_path)
        return AssetSaveResult(
            success=True,
            location=out_path,
            integrity=protection.to_integrity(base_dir=output_dir),
        )
    except Exception:
        return AssetSaveResult(success=False)


# ---------- Orchestration ----------

def acquire_photos(
    har_path: Path,
    output_dir: Path = Path('../temp_photos'),
    structures: Optional[list[StructureType]] = None,
    config: PhotoAcquisitionConfig = PhotoAcquisitionConfig(),
    har_photo_maps: Optional[list['Photo']] = None,
    download_log: Optional['dl.DownloadLog'] = None,
) -> list[Photo]:
    download_missing = config.download_missing
    download_media_not_in_structures = config.download_media_not_in_structures
    download_unfetched_media = config.download_unfetched_media
    download_full_assets_from_structures = config.download_highest_quality_assets_from_structures
    on_logged_missing = config.on_logged_missing

    os.makedirs(output_dir, exist_ok=True)
    prune_orphan_sidecars(Path(output_dir))

    existing = get_existing_photos(output_dir)
    har_photos = har_photo_maps if har_photo_maps is not None else extract_photo_maps(har_path)
    structure_photos = extract_photos_from_structures(structures or [])

    combined: dict[str, Photo] = {}
    for p in har_photos:
        combined[p.asset_id] = p
    for p in structure_photos:
        if p.asset_id in combined:
            if not combined[p.asset_id].full_asset:
                combined[p.asset_id].full_asset = p.full_asset
        else:
            combined[p.asset_id] = p

    for photo in combined.values():
        safe_asset = _safe_id(str(photo.asset_id)).lower()
        possible_names = {f"photo_full_{safe_asset}"}
        for fn in (photo.fetched_assets or {}):
            possible_names.add(f"photo_{safe_asset}_{_safe_id(fn).lower()}")

        matching = [existing[name] for name in possible_names if name in existing]
        if matching:
            print(f"Skipping image {photo.asset_id} as it already exists in the output directory.")
            photo.local_files = matching

    def _photo_source(result_location: Optional[Path], photo: Photo) -> dl.PhotoSource:
        if result_location is not None and result_location.name.startswith("photo_full_"):
            return "full_asset"
        return "har_image_bytes"

    for photo in combined.values():
        # File already on disk → link normally and refresh the log entry.
        if photo.local_files:
            if download_log is not None:
                dl.upsert_photo(
                    download_log,
                    str(photo.asset_id),
                    photo.local_files,
                    _photo_source(photo.local_files[0], photo),
                )
            continue

        # download_missing=False means read-only pass — skip every acquisition
        # branch, including HAR-bytes restoration.
        if not download_missing:
            continue

        logged = (
            download_log is not None
            and str(photo.asset_id) in download_log.photos
        )

        if logged and on_logged_missing == "skip":
            print(f"[log] Photo {photo.asset_id} is in the download log but missing on disk — skipping per on_logged_missing=skip.")
            continue
        if logged and on_logged_missing == "use_har_bytes_only":
            if not photo.fetched_assets:
                print(f"[log] Photo {photo.asset_id} is in the log but missing and no HAR bytes available — skipping (no CDN fetch under use_har_bytes_only).")
                continue
            print(f"[log] Photo {photo.asset_id} is in the log but missing — restoring from HAR bytes only (no CDN fetch).")
            result = save_fetched_photo(photo, output_dir)
            if result.location:
                photo.local_files = [result.location]
                if download_log is not None:
                    dl.upsert_photo(
                        download_log,
                        str(photo.asset_id),
                        photo.local_files,
                        _photo_source(result.location, photo),
                    )
            continue

        # Fresh acquisition path (not in log, or "redownload" override).
        skip = (
            (not download_media_not_in_structures and not photo.full_asset) or
            (not download_unfetched_media and not photo.fetched_assets)
        )
        if skip:
            continue
        result = AssetSaveResult(success=False)
        if download_full_assets_from_structures and photo.full_asset:
            result = download_full_asset(photo, output_dir)
        if (not result.success) and photo.fetched_assets:
            result = save_fetched_photo(photo, output_dir)
        if result.location:
            if photo.local_files is None:
                photo.local_files = []
            photo.local_files.append(result.location)
            if download_log is not None:
                dl.upsert_photo(
                    download_log,
                    str(photo.asset_id),
                    photo.local_files,
                    _photo_source(result.location, photo),
                )

    return [p for p in combined.values() if p.local_files]

if __name__ == '__main__':
    har_file = input("Input path to HAR file: ").strip().strip('"').strip("'")
    har_path_input = Path(har_file)
    har_structures = structures_from_har(har_path_input)
    acquire_photos(
        har_path=har_path_input,
        output_dir=har_path_input.parent / "photos",
        structures=har_structures
    )