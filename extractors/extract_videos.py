import base64
import datetime
import json
import os
import subprocess
import traceback
from hashlib import md5
from pathlib import Path
from typing import Optional, Literal
from urllib import parse as urllib_parse

import ijson
import requests
from pydantic import BaseModel

from extractors.models import VideoVersion
from extractors.structures_extraction import StructureType, structures_from_har
from extractors.structures_extraction_api_v1 import ApiV1Response
from extractors.structures_extraction_graphql import GraphQLResponse
from extractors.structures_extraction_html import PageResponse
from utils.timestamper import timestamp_file


class MediaSegment(BaseModel):
    start: Optional[int]
    end: Optional[int]
    data: bytes


class MediaTrack(BaseModel):
    base_url: str
    full_url: str
    segments: list[MediaSegment]


class Video(BaseModel):
    xpv_asset_id: int
    fetched_tracks: Optional[dict[str, MediaTrack]]
    full_asset: Optional[str] = None
    local_files: Optional[list[Path]] = None


def extract_xpv_asset_id(url) -> Optional[int]:
    # Parse query string
    parsed_url = urllib_parse.urlparse(url)
    query_params = urllib_parse.parse_qs(parsed_url.query)

    # Get the `efg` parameter (it may be URL-encoded)
    efg_encoded = query_params.get('efg')
    if not efg_encoded:
        try:
            return int(md5(url.split(".mp4")[0].split("/")[-1].encode("utf-8")).hexdigest(), 16)
        except Exception:
            return None

    # Base64-decode the efg value
    try:
        efg_json = base64.urlsafe_b64decode(efg_encoded[0] + '==')  # Add padding if missing
        efg_data = json.loads(efg_json.decode('utf-8'))
        xpv_asset_id =efg_data.get('xpv_asset_id')
        if not xpv_asset_id:
            raise ValueError("xpv_asset_id not found in efg data")
        return xpv_asset_id
    except Exception as e:
        print(f"Error decoding efg: {e}")
        try:
            return int(md5(url.split(".mp4")[0].split("/")[-1].encode("utf-8")).hexdigest(), 16)
        except Exception:
            return None


def extract_video_maps(har_path: Path) -> list[Video]:
    """Extracts video segment data from the HAR file using streaming JSON parsing."""
    videos_dict: dict[int, Video] = dict()

    with open(har_path, 'rb') as file:
        for entry in ijson.items(file, 'log.entries.item'):
            try:
                if ".mp4" in entry['request']['url'] and "text" in entry['response']['content']:
                    url = entry['request']['url']
                    base_url = url.split(".mp4")[0]
                    full_url = str(urllib_parse.urlunparse(
                        urllib_parse.urlparse(url)._replace(
                            query="&".join(
                                f"{k}={v[0]}" if len(v) == 1 else "&".join(f"{k}={i}" for i in v)
                                for k, v in urllib_parse.parse_qs(urllib_parse.urlparse(url).query).items()
                                if k not in ("bytestart", "byteend")
                            )
                        )
                    ))
                    xpv_asset_id = extract_xpv_asset_id(url)
                    filename = base_url.split("/")[-1]
                    start = end = None
                    if "bytestart=" in url:
                        start = int(url.split("bytestart=")[1].split("&")[0])
                    if "byteend=" in url:
                        end = int(url.split("byteend=")[1].split("&")[0])
                    response_content = base64.b64decode(entry['response']['content']['text'])
                    if xpv_asset_id not in videos_dict:
                        videos_dict[xpv_asset_id] = Video(
                            xpv_asset_id=xpv_asset_id,
                            fetched_tracks=dict(),
                        )
                    if filename not in videos_dict[xpv_asset_id].fetched_tracks:
                        videos_dict[xpv_asset_id].fetched_tracks[filename] = MediaTrack(
                            base_url=base_url,
                            full_url=full_url,
                            segments=[]
                        )
                    videos_dict[xpv_asset_id].fetched_tracks[filename].segments.append(
                        MediaSegment(start=start, end=end, data=response_content))
            except Exception as e:
                print(f'Error processing entry: {e}')
                traceback.print_exc()
                continue
    videos = list(videos_dict.values())
    return videos


def clean_segments(files_to_delete):
    for file in files_to_delete:
        if os.path.exists(file):
            os.remove(file)
        else:
            print(f"File {file} does not exist, skipping deletion.")

def clean_corrupted_files(path_to_check: Path) -> bool:
    if not os.path.exists(path_to_check):
        print(f"File {path_to_check} does not exist, skipping check.")
        return False
    if os.path.getsize(path_to_check) < 1000:
        os.remove(path_to_check)
        return False
    try:
        # Use ffprobe to check if the file is a valid media file
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration,format_name', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', path_to_check],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            os.remove(path_to_check)  # Delete if ffprobe indicates corruption
            return False
        return True
    except Exception as e:
        print(f"Error checking file {path_to_check}: {e}")
        if os.path.exists(path_to_check):
            os.remove(path_to_check)
            return False
        return True

def merge_video_and_audio_tracks(video_path: Path, audio_path: Path, output_path: Path) -> bool:
    """Merge video and audio tracks into a single file."""
    try:
        # Use ffmpeg to merge video and audio
        subprocess.run(
            ['ffmpeg', '-y', '-i', video_path, '-i', audio_path, '-c:v', 'copy', '-c:a', 'aac', '-strict',
             'experimental',
             output_path],
            check=True
        )
        # Check if the merge was successful
        if os.path.exists(output_path):
            print(f"Merged video and audio into {output_path}")
            clean_segments([video_path, audio_path])
            return True
        else:
            print(f"Failed to create merged file at {output_path}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"Error merging video and audio: {e}")
        return False

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

class AssetSaveResult(BaseModel):
    success: bool = True
    location: Optional[Path] = None
    hashed_contents: Optional[str] = None

def save_fetched_asset(video: Video, output_dir: Path, download_full_track: bool) -> AssetSaveResult:
    temp_video_file: Optional[Path] = None
    temp_audio_file: Optional[Path] = None
    merged_file: Optional[Path] = None
    xpv_asset_id = video.xpv_asset_id
    for track_name, track in video.fetched_tracks.items():
        track_data: Optional[bytes] = None
        download_type: Optional[Literal["har_segments", "full_track"]] = None
        if download_full_track:
            # Download the full track as a single file
            track_data = download_file(track.full_url)
            if track_data is not None:
                print("Downloaded full track data for", track_name)
                download_type = "full_track"
        if track_data is None:
            # Attempt to compose the track from segments
            # sort the segments by start byte
            track.segments.sort(key=lambda s: s.start)
            # compose a full file out of the segments.
            # Determine the total length needed for the track
            max_end = max((segment.end for segment in track.segments if segment.end is not None), default=0)
            track_data = bytearray(max_end)

            for segment in track.segments:
                if segment.start is None:
                    # If no start, append at the end (rare, fallback)
                    track_data = segment.data
                else:
                    # Overwrite the region with this segment's data
                    track_data[segment.start:segment.end] = segment.data
            download_type = "har_segments"

        source_type = "har_segments" if download_type == "har_segments" else "full_track"
        single_track_file = f"track_{xpv_asset_id}_{track_name}_{source_type}.mp4"
        if track_data is not None and len(track_data) > 0:
            with open(output_dir / single_track_file, 'wb') as f:
                f.write(track_data)

        valid_file = clean_corrupted_files(output_dir / single_track_file)
        if not valid_file:
            print(f"File {output_dir / single_track_file} is corrupted, skipping.")
            clean_segments([output_dir / single_track_file])
            continue

        if valid_file:
            # determine whether the file is audio or video using ffprobe
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of',
                 'default=noprint_wrappers=1:nokey=1',
                 str(output_dir / single_track_file)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if 'audio' in result.stdout:
                # keep track of the largest audio file
                new_file = output_dir / single_track_file
                if temp_audio_file is not None:
                    if os.path.getsize(new_file) > os.path.getsize(temp_audio_file):
                        temp_audio_file = new_file
                        # delete the smaller file
                        if os.path.exists(temp_audio_file):
                            os.remove(temp_audio_file)
                else:
                    temp_audio_file = new_file
            else:
                # keep track of the largest video file
                new_file = output_dir / single_track_file
                if temp_video_file is not None:
                    if os.path.getsize(new_file) > os.path.getsize(temp_video_file):
                        temp_video_file = new_file
                        # delete the smaller file
                        if os.path.exists(temp_video_file):
                            os.remove(temp_video_file)
                else:
                    temp_video_file = new_file

    if temp_audio_file is not None and temp_video_file is not None:
        merged_file_path = output_dir / f"xpv_{video.xpv_asset_id}.mp4"
        merge_success = merge_video_and_audio_tracks(
            temp_video_file,
            temp_audio_file,
            merged_file_path
        )
        if merge_success:
            merged_file = merged_file_path

    most_complete_version = merged_file or temp_video_file or temp_audio_file or None

    if most_complete_version is None:
        print(f"No valid video segments found for xpv_asset_id {video.xpv_asset_id}.")
        return AssetSaveResult(success=False)

    try:
        hashed_contents = md5(open(most_complete_version, 'rb').read()).hexdigest()
        return AssetSaveResult(
            success=True,
            location=most_complete_version,
            hashed_contents=hashed_contents
        )
    except Exception as e:
        print(f"Error hashing file {most_complete_version}: {e}")
        return AssetSaveResult(success=False)


def extract_videos_from_structures(structures: list[StructureType]) -> list[Video]:
    pk_video_versions_dict: dict[str, list[VideoVersion]] = dict()
    for s in structures:
        if isinstance(s, GraphQLResponse):
            if s.reels_media:
                for edge in s.reels_media.edges:
                    for item in edge.node.items:
                        if item.video_versions:
                            pk_video_versions_dict[item.pk] = item.video_versions
                        if item.carousel_media:
                            for carousel_item in item.carousel_media:
                                if carousel_item.video_versions:
                                    pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
            if s.stories_feed:
                for edge in s.stories_feed.reels_media:
                    for item in edge.items:
                        if item.video_versions:
                            pk_video_versions_dict[item.pk] = item.video_versions
                        if item.carousel_media:
                            for carousel_item in item.carousel_media:
                                if carousel_item.video_versions:
                                    pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
            if s.profile_timeline:
                for edge in s.profile_timeline.edges:
                    if edge.node.video_versions:
                        pk_video_versions_dict[edge.node.pk] = edge.node.video_versions
                    if edge.node.carousel_media:
                        for carousel_item in edge.node.carousel_media:
                            if carousel_item.video_versions:
                                pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
            if s.clips_user_connection:
                for edge in s.clips_user_connection.edges:
                    if edge.node.media.video_versions:
                        pk_video_versions_dict[edge.node.media.pk] = edge.node.media.video_versions
        elif isinstance(s, ApiV1Response):
            if s.media_info:
                for item in s.media_info.items:
                    if item.video_versions:
                        pk_video_versions_dict[item.pk] = item.video_versions
        elif isinstance(s, PageResponse):
            if s.posts:
                for post in s.posts.items:
                    if post.video_versions:
                        pk_video_versions_dict[post.pk] = post.video_versions
                    if post.carousel_media:
                        for carousel_item in post.carousel_media:
                            if carousel_item.video_versions:
                                pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
            if s.stories:
                for edge in s.stories.edges:
                    for item in edge.node.items:
                        if item.video_versions:
                            pk_video_versions_dict[item.pk] = item.video_versions
                        if item.carousel_media:
                            for carousel_item in item.carousel_media:
                                if carousel_item.video_versions:
                                    pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
            if s.highlight_reels:
                for reel in s.highlight_reels.edges:
                    for item in reel.node.items:
                        if item.video_versions:
                            pk_video_versions_dict[item.pk] = item.video_versions
                        if item.carousel_media:
                            for carousel_item in item.carousel_media:
                                if carousel_item.video_versions:
                                    pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
            if s.stories_direct:
                for story in s.stories_direct.reels_media:
                    for item in story.items:
                        if item.video_versions:
                            pk_video_versions_dict[item.pk] = item.video_versions
                        if item.carousel_media:
                            for carousel_item in item.carousel_media:
                                if carousel_item.video_versions:
                                    pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
            if s.timelines:
                for item in s.timelines.items:
                    if item.video_versions:
                        pk_video_versions_dict[item.pk] = item.video_versions
                    if item.carousel_media:
                        for carousel_item in item.carousel_media:
                            if carousel_item.video_versions:
                                pk_video_versions_dict[carousel_item.pk] = carousel_item.video_versions
    videos: dict[int, Video] = dict()
    for pk, video_versions in pk_video_versions_dict.items():
        if video_versions:
            try:
                xpv_asset_id = extract_xpv_asset_id(video_versions[0].url)
                video = Video(
                    xpv_asset_id=xpv_asset_id,
                    full_asset=video_versions[0].url,
                    fetched_tracks=None
                )
                videos[xpv_asset_id] = video
            except Exception as e:
                print(f"Error extracting xpv_asset_id from video version URL {video_versions[0].url}: {e}")
                continue
    return list(videos.values())


def get_existing_videos(working_dir: Path) -> dict[str, Path]:
    # Existing files in the output directory
    existing_files_name_size_tuples = [
        (file.name, file.stat().st_size) for file in working_dir.iterdir() if file.is_file()
    ]

    largest_version_of_files: dict[str, tuple[str, int]] = dict()

    for file_name, file_size in existing_files_name_size_tuples:
        print(f"Extracting {file_name}...")
        asset_id = file_name
        try:
            asset_id = asset_id.split('track_')[1] if 'track_' in asset_id else asset_id
            asset_id = asset_id.split('xpv_')[1] if 'xpv_' in asset_id else asset_id
            asset_id = asset_id.split('_')[0] if '_' in asset_id else asset_id
            asset_id = asset_id.split('.mp4')[0] if '.mp4' in asset_id else asset_id
        except IndexError:
            pass
        if (
                asset_id not in largest_version_of_files or
                file_size > largest_version_of_files[asset_id][1]
        ):
            largest_version_of_files[asset_id] = (file_name, file_size)

    return {track_name: Path(working_dir / file_name) for track_name, (file_name, _) in
            largest_version_of_files.items()}


def download_full_asset(video: Video, output_dir: Path) -> AssetSaveResult:
    if not video.full_asset:
        return AssetSaveResult(success=False)
    try:
        download_result = download_file(video.full_asset)
        if download_result is not None:
            hashed_contents = md5(download_result).hexdigest()
            file_name = f"xpv_{video.xpv_asset_id}_full.mp4"
            file_path = output_dir / file_name
            with open(file_path, 'wb') as f:
                f.write(download_result)
            return AssetSaveResult(
                success=True,
                location=file_path,
                hashed_contents=hashed_contents
            )
        else:
            raise Exception(f"Failed to download full asset")
    except Exception as e:
        print(f"Error downloading full asset {video.full_asset}: {e}")
        return AssetSaveResult(success=False)


def timestamp_downloaded_contents(downloaded_video_hashes: dict[int, str], output_dir: Path):
    if not downloaded_video_hashes or len(downloaded_video_hashes.items()) == 0:
        return
    try:
        now_timestamp = int(datetime.datetime.timestamp(datetime.datetime.now()))
        full_track_hashes_path = output_dir / f"full_track_hashes_{now_timestamp}.json"
        full_track_hashes_str = json.dumps(downloaded_video_hashes, indent=2, sort_keys=True)
        with open(full_track_hashes_path, "w", encoding="utf-8") as f:
            f.write(full_track_hashes_str)
        full_track_hashes_md5 = md5(full_track_hashes_str.encode("utf-8")).hexdigest()
        full_track_hashes_hash_path = output_dir / f"full_track_hashes_hash_{now_timestamp}.txt"
        with open(full_track_hashes_hash_path, "w") as f:
            f.write(full_track_hashes_md5)
        timestamp_file(full_track_hashes_hash_path)
    except Exception as e:
        print(f"Error saving full track hashes: {e}")


class VideoAcquisitionConfig(BaseModel):
    download_missing: bool = True,
    download_media_not_in_structures: bool = True,
    download_unfetched_media: bool = True,
    download_full_versions_of_fetched_media: bool = True,
    download_highest_quality_assets_from_structures: bool = True,


def acquire_videos(
        har_path: Path,
        output_dir: Path = Path('../temp_video_segments'),
        structures: Optional[list[StructureType]] = None,
        config: VideoAcquisitionConfig = VideoAcquisitionConfig()
) -> list[Video]:
    # unpack the config
    download_missing = config.download_missing
    download_media_not_in_structures = config.download_media_not_in_structures
    download_unfetched_media = config.download_unfetched_media
    download_full_versions_of_fetched_media = config.download_full_versions_of_fetched_media
    download_highest_quality_assets_from_structures = config.download_highest_quality_assets_from_structures

    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    existing_videos = get_existing_videos(output_dir)

    har_videos = extract_video_maps(har_path)
    structures_videos = extract_videos_from_structures(structures)

    combined_videos_dict: dict[int, Video] = dict()

    for video in har_videos:
        if video.xpv_asset_id in combined_videos_dict:
            combined_videos_dict[video.xpv_asset_id].fetched_tracks = video.fetched_tracks
        else:
            combined_videos_dict[video.xpv_asset_id] = video

    for video in structures_videos:
        if video.xpv_asset_id in combined_videos_dict:
            combined_videos_dict[video.xpv_asset_id].full_asset = video.full_asset
        else:
            combined_videos_dict[video.xpv_asset_id] = video

    combined_videos = list(combined_videos_dict.values())
    # attach existing local files to the videos
    for video in combined_videos:
        # check if any of the tracks, xpv_asset_ids, or full_asset urls are already in existing_videos
        possible_asset_ids = [f"{video.xpv_asset_id}"]
        try:
            possible_asset_ids.append(video.full_asset.split(".mp4")[0].split("/")[-1])
        except Exception:
            pass
        if video.fetched_tracks:
            for track_name in video.fetched_tracks:
                try:
                    possible_asset_ids.append(track_name.split(".mp4")[0].split("/")[-1])
                except Exception:
                    pass

        if any(asset_id in existing_videos for asset_id in possible_asset_ids):
            print(f"Skipping video {video.xpv_asset_id} as it already exists in the output directory.")
            video.local_files = [
                existing_videos[asset_id] for asset_id in possible_asset_ids if asset_id in existing_videos
            ]
            continue

    downloaded_video_hashes: dict[int, str] = dict()
    for video in combined_videos:
        if video.local_files is None or len(video.local_files) == 0:
            if download_missing:
                download_result = AssetSaveResult(success=False)
                skip_video = (
                        (not download_media_not_in_structures and not video.full_asset) or
                        (not download_unfetched_media and not video.fetched_tracks)
                )
                if skip_video:
                    continue
                if (
                        (not download_result.success) and
                        download_highest_quality_assets_from_structures and
                        video.full_asset
                ):
                    download_result = download_full_asset(video, output_dir)
                if (
                        (not download_result.success) and video.fetched_tracks
                ):
                    download_result = save_fetched_asset(video, output_dir, download_full_track=download_full_versions_of_fetched_media)
            else:
                continue
            if download_result.hashed_contents is not None:
                downloaded_video_hashes[video.xpv_asset_id] = download_result.hashed_contents
            if download_result.location is not None:
                if video.local_files is None:
                    video.local_files = []
                video.local_files.append(download_result.location)
    
    timestamp_downloaded_contents(downloaded_video_hashes, output_dir)
    
    stored_videos = []
    for video in combined_videos:
        if video.local_files is None or len(video.local_files) == 0:
            print(f"Video {video.xpv_asset_id} not downloaded.")
            continue
        stored_videos.append(video)
    return stored_videos


if __name__ == '__main__':
    # Provide the path to your .har file and desired output folder
    har_file = input("Input path to HAR file: ")  # Replace with your actual HAR file
    har_file = har_file.strip().strip('"').strip("'")
    har_file_path = Path(har_file)
    har_structures = structures_from_har(har_file_path)
    acquire_videos(
        har_file_path,
        output_dir=har_file_path.parent / "videos",
        structures=har_structures
    )
