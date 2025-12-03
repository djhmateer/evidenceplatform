# archive.py
import os
import sys
import pygetwindow as gw
import time
import json
import datetime
from hashlib import md5
from typing import Optional

from ffmpeg_installer import ensure_ffmpeg_installed
from git_helper import has_uncommitted_changes, get_current_commit_id, is_bundled, ensure_committed

import cv2
import pyautogui
import threading

from pydantic import BaseModel
import numpy as np  # For the screen recorder
from pathlib import Path
from playwright.sync_api import sync_playwright, Browser, BrowserContext
from dotenv import load_dotenv

from profile_selection import select_profile
from timestamper import timestamp_file
from profile_registration import Profile

from utils import get_my_public_ip, get_system_info

SCREEN_SIZE = tuple(pyautogui.size())
load_dotenv()
commit_id = None


class StoriesFeedArchiveSessionMetadata(BaseModel):
    profile_name: str
    archiving_start_timestamp: str
    recording_start_timestamp: str
    archiving_finished_timestamp: Optional[str] = None
    archiving_timezone: Optional[str] = None
    log_path: Path
    log_hash: Optional[str] = None
    my_ip: Optional[str] = None
    platform: Optional[str] = None
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


def affidavit_from_metadata(metadata: StoriesFeedArchiveSessionMetadata) -> str:
    affidavit = f"""I, {metadata.signature}, have viewed the Instagram stories feed for '{metadata.profile_name}' in order to send a subset of them for archiving.
The browsing session began at {metadata.archiving_start_timestamp} and was completed at {metadata.archiving_finished_timestamp} (timezone: {datetime.datetime.now().astimezone().tzname()}, UTC {datetime.datetime.now().astimezone().utcoffset()}).
Archiving was carried out from the IP address {metadata.my_ip}, and was done through the use of a custom Python script.
The script launches a Playwright-controlled Firefox browser ({metadata.browser_build_id}), which is used to navigate to the target URL, and allows the user to manually interact with the page (including scrolling, clicking, and navigating to other pages).
The script records the screen during this process. The screen recording is saved as a video file. Server requests fetching the metadata of the browsed stories from Instagram's graphql API are monitored and their details are output into a log file.
None of the log's content has been altered or modified in any way, and no third party has been granted access to the file system. The code used for this process is available on GitHub at https://github.com/yanivcogan/InstagramArchiver (commit {metadata.commit_id})
MD5 hash of the log file: {metadata.log_hash}
OS and hardware details: {metadata.platform}
Additional Notes: {metadata.notes}"""
    return affidavit


def finish_recording(recording_thread: threading.Thread, browser: Browser, context: BrowserContext, archive_dir: Path, metadata: StoriesFeedArchiveSessionMetadata, stop_event=None):
    context.close()
    browser.close()

    if stop_event is not None:
        stop_event.set()
    if recording_thread.is_alive():
        recording_thread.join()
        print("Recording finished.")

    archiving_finished_timestamp = datetime.datetime.now().isoformat()
    metadata.archiving_finished_timestamp = archiving_finished_timestamp

    while True:
        metadata.signature = os.getenv('DEFAULT_SIGNATURE') or input('Sign full name: ')
        print(f"Signed {metadata.signature}.")
        metadata.notes = input("Notes about the content (type 'reset' to reinput signature): ") or '-'
        if metadata.notes == "switch":
            metadata.notes = metadata.signature
            print(f"Notes set to {metadata.notes}.")
            metadata.signature = input('Sign full name: ')
        if not metadata.notes == "reset":
            break
    try:
        # timestamp_file(har_hash_path)
        pass
    except Exception as e:
        print(f"❌ Error timestamping HAR hash file: {e}")

    with open(archive_dir / "metadata.json", "w", encoding="utf-8") as f:
        metadata_dict = metadata.model_dump()
        json.dump(metadata_dict, f, indent=2, default=str)

    with open(archive_dir / "affidavit.txt", "w", encoding="utf-8") as f:
        f.write(affidavit_from_metadata(metadata))

    print(f"Content archived successfully in {archive_dir}")

    return


def archive_instagram_content(profile: Profile):
    profiles_dir = Path("profiles")
    profile_name = profile.name
    profile_path = profiles_dir / profile_name

    if not profile_path.exists() or not (profile_path / "state.json").exists():
        print(f"Profile '{profile_name}' not found. Please register it first.")
        return

    # Create archive directory with timestamp
    archiving_start_time = datetime.datetime.now()
    archiving_start_timestamp = archiving_start_time.isoformat()
    archive_dir = Path("archives") / f"{profile_name}_stories_{archiving_start_time.strftime('%Y%m%d_%H%M')}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    my_public_ip = get_my_public_ip()

    with open(profile_path / "state.json", "r") as f:
        storage_state = json.load(f)

    stories_to_keep = []

    def log_story_request(request):
        if (
                request.url.startswith("https://www.instagram.com/graphql/query")
                and request.headers.get("x-root-field-name") == "xdt_api__v1__feed__reels_media__connection"
        ):
            try:
                response = request.response()
                stories_to_keep.append({
                    "request": {
                        "url": request.url,
                        "headers": dict(request.headers),
                        "post_data": request.post_data
                    },
                    "response": {
                        "status": response.status,
                        "headers": dict(response.headers),
                        "body": response.body()
                    }
                })
            except Exception as e:
                print(f"Error saving request/response: {e}")


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
        metadata = StoriesFeedArchiveSessionMetadata(
            commit_id=commit_id,
            profile_name=profile.insta_username,
            archiving_start_timestamp=archiving_start_timestamp,
            recording_start_timestamp=recording_start_timestamp,
            archiving_timezone=datetime.datetime.now().astimezone().tzname(),
            my_ip=my_public_ip,
            platform=get_system_info(),
            log_path=archive_dir / "captured_stories.json"
        )
        # Launch browser with the saved state
        browser = p.firefox.launch(headless=False)
        browser_build_id = f"{browser.browser_type.name}_{browser.version}"
        metadata.browser_build_id = browser_build_id
        # browser.on("disconnected", lambda b: finish_recording(recording_thread, browser, context, archive_dir, metadata, stop_event))
        context = browser.new_context(
            storage_state=storage_state,
        )
        context.on("requestfinished", log_story_request)

        page = context.new_page()

        try:
            # Navigate to the target URL
            page.goto('https://www.instagram.com/')

            # Allow user to do whatever they want
            page.wait_for_event("close", timeout=0)
        except Exception as e:
            if "Target closed" in str(e) or "browser has disconnected" in str(e).lower():
                print("Browser shutdown detected, wrapping up archiving session...")
            else:
                print(f"Error during archiving: {e}")
        finally:
            try:
                with open(metadata.log_path, "w", encoding="utf-8") as f:
                    json.dump(stories_to_keep, f, indent=2, default=str)
            except Exception as e:
                pass
            finish_recording(recording_thread, browser, context, archive_dir, metadata, stop_event)



if __name__ == "__main__":
    commit_id = ensure_committed()
    print("Welcome to the Instagram Story Archiver!")
    ensure_ffmpeg_installed()
    profile = select_profile()
    archive_instagram_content(profile)
    sys.exit(0)