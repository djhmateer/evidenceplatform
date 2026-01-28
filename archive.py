# archive.py
import os
import sys
import pygetwindow as gw
import time
import json
import datetime
from hashlib import md5
from typing import Literal, Optional

from archiver.dialogs import show_dialog_form, DialogForm, FormFieldText, FormFieldBool, FormSection
from extractors.extract_photos import PhotoAcquisitionConfig
from extractors.extract_videos import VideoAcquisitionConfig
from utils.ffmpeg_installer import ensure_ffmpeg_installed
from utils.git_helper import ensure_committed

import cv2
import pyautogui
import threading
import shutil

from pydantic import BaseModel
from har2warc.har2warc import har2warc
import numpy as np
from pathlib import Path
from playwright.sync_api import sync_playwright, Browser, BrowserContext
from dotenv import load_dotenv

from archiver.profile_selection import select_profile
from utils.timestamper import timestamp_file
from archiver.profile_registration import Profile
from summarizers.entities_summary_generator import generate_entities_summary

from utils.misc import get_my_public_ip, get_system_info

SCREEN_SIZE = tuple(pyautogui.size())
commit_id = None
load_dotenv()

def store_archive_as_warc(archive_dir: Path):
    har_file = archive_dir / "archive.har"
    if har_file.exists():
        try:
            warc_file = archive_dir / "archive.warc.gz"
            har2warc(str(har_file), str(warc_file))
            print(f"WARC file generated at: {warc_file}")
        except Exception as e:
            print(f"Error converting HAR to WARC: {e}")
    else:
        print("HAR file was not saved successfully.")

class InstagramObject(BaseModel):
    type: Literal["post", "story", "reel", "highlight", "profile"]
    username: Optional[str] = None
    url: str
    id: str

def get_instagram_object_type(item_url: str, username: Optional[str] = None) -> InstagramObject:
    item_url = item_url.strip()
    item_url = item_url.split("?")[0]  # Remove query parameters if any
    item_url = item_url.rstrip("/")  # Remove trailing slash if any
    item_url = item_url.replace("www.", "")  # Remove www. if present
    item_url = item_url.split("://")[-1]  # Remove protocol if present
    url_components = item_url.split("/")
    if url_components[1] == "p":
        return InstagramObject(type="post", url=item_url, id=item_url.split("/")[2], username=username)
    elif url_components[1] == "reel":
        return InstagramObject(type="reel", url=item_url, id=item_url.split("/")[2], username=username)
    elif url_components[1] == "stories":
        if len(url_components) > 3 and url_components[2] == "highlights":
            return InstagramObject(type="highlight", url=item_url, id=item_url.split("/")[4], username=username)
        else:
            return InstagramObject(type="story", url=item_url, id=item_url.split("/")[2], username=username)
    if username is None:
        username = url_components[1]
        url_stripped_of_username = item_url.replace(f"/{username}", "")
        if len(url_stripped_of_username.split("/")) > 2:
            return get_instagram_object_type(url_stripped_of_username, username=username)
        else:
            return InstagramObject(type="profile", url=item_url, id=username, username=username)
    else:
        return InstagramObject(type="profile", url=item_url, id=username, username=username)


class ArchiveSessionMetadata(BaseModel):
    profile_name: str
    target_url: str
    archiving_start_timestamp: str
    recording_start_timestamp: str
    archiving_finished_timestamp: Optional[str] = None
    archiving_timezone: Optional[str] = None
    har_archive: Path
    warc_archive: Optional[Path] = None
    my_ip: Optional[str] = None
    platform: Optional[str] = None
    har_hash: Optional[str] = None
    sanitized_har_hash: Optional[str] = None
    browser_build_id: Optional[str] = None
    commit_id: Optional[str] = None
    signature: Optional[str] = None
    notes: Optional[str] = None


def screen_record(output_path, stop_event):
    # Screen recording using OpenCV, only capturing the Playwright browser window
    for attempt in range(5):
        time.sleep(5)
        windows = [w for w in gw.getAllWindows() if "Nightly" in w.title]
        if windows:
            break
    else:
        print("Could not find the Firefox browser window for screen recording.")
        return
    browser_window = windows[0]
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    fps = 20.0
    width, height = browser_window.width, browser_window.height
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    while not stop_event.is_set():
        try:
            img = pyautogui.screenshot(region=(browser_window.left, browser_window.top, width, height))
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            out.write(frame)
        except Exception as _:
            pass
        time.sleep(1 / fps)  # Control FPS

    out.release()
    print(f"Screen recording saved to {output_path}")


def affidavit_from_metadata(metadata: ArchiveSessionMetadata) -> str:
    affidavit = f"""I, {metadata.signature}, have archived the Instagram content from {metadata.target_url} using the profile '{metadata.profile_name}'.
The archiving process started at {metadata.archiving_start_timestamp} and was completed at {metadata.archiving_finished_timestamp} (timezone: {datetime.datetime.now().astimezone().tzname()}, UTC {datetime.datetime.now().astimezone().utcoffset()}).
Archiving was carried out from the IP address {metadata.my_ip}, and was done through the use of a custom Python script.
The script launches a Playwright-controlled Firefox browser ({metadata.browser_build_id}), which is used to navigate to the target URL, and allows the user to manually interact with the page (including scrolling, clicking, and navigating to other pages).
The script records the screen during this process, and also saves a HAR file of the network traffic. The screen recording is saved as a video file. Server requests for video content from the Instagram servers during the sessions are identified through analysis of the HAR file, and the full media files are downloaded and saved to the archive directory (these tracks may include data that does not appear in the HAR, since it only includes byte-range segments which don't necessarily cover the entire duration of the video).
None of the HAR's content has been altered or modified in any way, and no third party has been granted access to the file system. The code used for this process is available on GitHub at https://github.com/yanivcogan/InstagramArchiver (commit {metadata.commit_id})
MD5 hash of the HAR file: {metadata.har_hash}
OS and hardware details: {metadata.platform}
Additional Notes: {metadata.notes}"""
    return affidavit


class StorageConfig(BaseModel):
    signature: str
    notes: str
    v_download_media_not_in_structures: bool
    v_download_unfetched_media: bool
    v_download_full_versions_of_fetched_media: bool
    v_download_highest_quality_assets_from_structures: bool
    p_download_media_not_in_structures: bool
    p_download_unfetched_media: bool
    p_download_highest_quality_assets_from_structures: bool


def get_storage_config() -> Optional[StorageConfig]:
    default_signature = os.getenv("DEFAULT_SIGNATURE", "")
    storage_config_dict = show_dialog_form(
        DialogForm(
            title="Finish Archiving",
            submit_button_text="Save Archive",
            sections=[
                FormSection(
                    title="Summary",
                    fields=[
                        FormFieldText(
                            title="Signature (Full Name)",
                            key="signature",
                            default_value=default_signature
                        ),
                        FormFieldText(
                            title="Notes about the content",
                            key="notes",
                            default_value=""
                        )
                    ]
                ),
                FormSection(
                    title="Video Downloading Configuration",
                    fields=[
                        FormFieldBool(
                            title="Download Auxiliary Media (profile pictures of other users, thumbnails, etc.)",
                            key="v_download_media_not_in_structures",
                            default_value=False
                        ),
                        FormFieldBool(
                            title="Download Related Media that Hasn't Been Fetched During the Session (e.g. videos from a post that wasn't opened)",
                            key="v_download_unfetched_media",
                            default_value=False
                        ),
                        FormFieldBool(
                            title="Download Full Versions of Fetched Media (if set to false, videos which were only partially played might be corrupted)",
                            key="v_download_full_versions_of_fetched_media",
                            default_value=True
                        ),
                        FormFieldBool(
                            title="Download Highest Quality Assets from Structures (if set to false, the videos will be downloaded in the quality they were displayed in during the session)",
                            key="v_download_highest_quality_assets_from_structures",
                            default_value=True
                        )
                    ]
                ),
                FormSection(
                    title="Photo Downloading Configuration",
                    fields=[
                        FormFieldBool(
                            title="Download Auxiliary Media (profile pictures of other users, thumbnails, etc.)",
                            key="p_download_media_not_in_structures",
                            default_value=False
                        ),
                        FormFieldBool(
                            title="Download Related Media that Hasn't Been Fetched During the Session (e.g. videos from a post that wasn't opened)",
                            key="p_download_unfetched_media",
                            default_value=False
                        ),
                        FormFieldBool(
                            title="Download Highest Quality Assets from Structures (if set to false, the videos will be downloaded in the quality they were displayed in during the session)",
                            key="p_download_highest_quality_assets_from_structures",
                            default_value=True
                        )
                    ]
                ),
            ]
        )
    )
    if storage_config_dict is None:
        return None
    return StorageConfig(**storage_config_dict)


def finish_recording(recording_thread: threading.Thread, browser: Browser, context: BrowserContext, archive_dir: Path, metadata: ArchiveSessionMetadata, stop_event=None):
    context.close()
    browser.close()

    if stop_event is not None:
        stop_event.set()
    if recording_thread.is_alive():
        recording_thread.join()
        print("Recording finished.")

    archiving_finished_timestamp = datetime.datetime.now().isoformat()
    metadata.archiving_finished_timestamp = archiving_finished_timestamp

    storage_config = get_storage_config()

    if storage_config is None:
        print("Archiving cancelled by user. Deleting archive directory.")
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        return

    # video downloading configuration
    v_download_missing: bool = True
    v_download_media_not_in_structures: bool = storage_config.v_download_media_not_in_structures
    v_download_unfetched_media: bool = storage_config.v_download_unfetched_media
    v_download_full_versions_of_fetched_media: bool = storage_config.v_download_full_versions_of_fetched_media
    v_download_highest_quality_assets_from_structures: bool = storage_config.p_download_highest_quality_assets_from_structures

    # photo downloading configuration
    p_download_missing: bool = True
    p_download_media_not_in_structures: bool = storage_config.p_download_media_not_in_structures
    p_download_unfetched_media: bool = storage_config.p_download_unfetched_media
    p_download_highest_quality_assets_from_structures: bool = storage_config.p_download_highest_quality_assets_from_structures


    metadata.signature = storage_config.signature
    metadata.notes = storage_config.notes

    har_path = metadata.har_archive
    # sanitized_har_path = archive_dir / "sanitized.har"

    # sanitize_har(har_path, sanitized_har_path)

    with open(har_path, 'rb') as file:
        har_content = file.read()
        har_hash = md5(har_content).hexdigest()
        metadata.har_hash = har_hash

    har_hash_path = archive_dir / "har_hash.txt"
    with open(har_hash_path, 'w', encoding='utf-8') as f:
        f.write(metadata.har_hash)

    try:
        timestamp_file(har_hash_path)
    except Exception as e:
        print(f"❌ Error timestamping HAR hash file: {e}")

    # with open(sanitized_har_path, 'rb') as file:
    #     sanitized_har_content = file.read()
    #     sanitized_har_hash = md5(sanitized_har_content).hexdigest()
    #     metadata.sanitized_har_hash = sanitized_har_hash

    with open(archive_dir / "metadata.json", "w", encoding="utf-8") as f:
        metadata_dict = metadata.model_dump()
        json.dump(metadata_dict, f, indent=2, default=str)

    with open(archive_dir / "affidavit.txt", "w", encoding="utf-8") as f:
        f.write(affidavit_from_metadata(metadata))

    # try:
    #     generate_summary(har_path, archive_dir, metadata_dict, download_full_video=True)
    # except Exception:
    #     pass
    try:
        generate_entities_summary(
            har_path,
            archive_dir,
            metadata_dict,
            VideoAcquisitionConfig(
                download_missing=v_download_missing,
                download_media_not_in_structures=v_download_media_not_in_structures,
                download_unfetched_media=v_download_unfetched_media,
                download_full_versions_of_fetched_media=v_download_full_versions_of_fetched_media,
                download_highest_quality_assets_from_structures=v_download_highest_quality_assets_from_structures
            ),
            PhotoAcquisitionConfig(
                download_missing=p_download_missing,
                download_media_not_in_structures=p_download_media_not_in_structures,
                download_unfetched_media=p_download_unfetched_media,
                download_highest_quality_assets_from_structures=p_download_highest_quality_assets_from_structures
            )
        )
    except Exception:
        pass

    print(f"Content archived successfully in {archive_dir}")

    return


def archive_instagram_content(profile: Profile, target_url: str):
    profiles_dir = Path("profiles")
    profile_name = profile.name
    profile_path = profiles_dir / profile_name

    if not profile_path.exists() or not (profile_path / "state.json").exists():
        print(f"Profile '{profile_name}' not found. Please register it first.")
        return

    # Create archive directory with timestamp
    archiving_start_time = datetime.datetime.now()
    archiving_start_timestamp = archiving_start_time.isoformat()
    archive_dir = Path("archives") / f"{profile_name}_{archiving_start_time.strftime('%Y%m%d_%H%M%S')}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    my_public_ip = get_my_public_ip()

    with open(profile_path / "state.json", "r") as f:
        storage_state = json.load(f)

    with sync_playwright() as p:
        # Start screen recording in a separate thread
        video_path = archive_dir / "screen_recording.avi"
        stop_event = threading.Event()
        recording_thread = threading.Thread(
            target=screen_record,
            args=(str(video_path), stop_event)
        )
        recording_thread.start()
        recording_start_timestamp = datetime.datetime.now().isoformat()
        metadata = ArchiveSessionMetadata(
            commit_id=commit_id,
            profile_name=profile.insta_username,
            target_url=target_url,
            archiving_start_timestamp=archiving_start_timestamp,
            recording_start_timestamp=recording_start_timestamp,
            archiving_timezone=datetime.datetime.now().astimezone().tzname(),
            har_archive=archive_dir / "archive.har",
            my_ip=my_public_ip,
            platform=get_system_info()
        )
        # Launch browser with the saved state
        browser = p.firefox.launch(headless=False)
        browser_build_id = f"{browser.browser_type.name}_{browser.version}"
        metadata.browser_build_id = browser_build_id
        context = browser.new_context(
            storage_state=storage_state,
            record_har_path=metadata.har_archive,
            record_video_dir=archive_dir / "screen_recordings",
        )

        page = context.new_page()

        try:
            # Navigate to the target URL
            page.goto(target_url)

            # Allow user to do whatever they want
            print(f"Archiving content from {target_url}")
            page.wait_for_event("close", timeout=0)
        except Exception as e:
            if "Target closed" in str(e) or "browser has disconnected" in str(e).lower():
                print("Browser shutdown detected, wrapping up archiving session...")
            else:
                print(f"Error during archiving: {e}")
        finally:
            finish_recording(recording_thread, browser, context, archive_dir, metadata, stop_event)



if __name__ == "__main__":
    commit_id = ensure_committed()
    ensure_ffmpeg_installed()
    profile = select_profile()
    url = input("Enter the Instagram URL to archive: ")
    url = url.split("?igsh=")[0].strip().split("&igsh=")[0].strip()

    archive_instagram_content(profile, url)
    sys.exit(0)