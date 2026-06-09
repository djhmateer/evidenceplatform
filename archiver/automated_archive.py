import datetime
import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

from archiver.archive import (
    ArchiveSessionMetadata,
    StorageConfig,
    finish_recording,
    get_tls_cert_info,
    screen_record,
)
from archiver.automated_scripts.instagram_followers_scraper import run_followers_automation
from archiver.dialogs import (
    DialogForm,
    FormFieldBool,
    FormFieldText,
    FormSection,
    show_dialog_form,
)
from archiver.profile_registration import Profile
from root_anchor import ROOT_DIR
from utils.commit_tracker.git_helper import ensure_committed
from utils.ffmpeg_installer import ensure_ffmpeg_installed
from utils.misc import ensure_vpn_connection, get_my_public_ip, get_system_info
from utils.par2_installer import ensure_par2_installed

load_dotenv()


class SessionConfig(BaseModel):
    scrape_followers: bool
    scrape_following: bool
    storage_config: StorageConfig


def _load_profiles_map() -> list[Profile]:
    map_path = Path(ROOT_DIR) / "archiver" / "profiles" / "map.json"
    if not map_path.exists():
        return []
    with open(map_path, "r") as f:
        return [Profile(**p) for p in json.load(f)]


def _resolve_profile(identifier: str, profiles: list[Profile]) -> Optional[Profile]:
    identifier = identifier.strip()
    if identifier.isdigit():
        idx = int(identifier)
        if 0 <= idx < len(profiles):
            return profiles[idx]
        return None
    for p in profiles:
        if p.name == identifier:
            return p
    return None


def _username_from_url(url: str) -> str:
    url = url.strip().split("?")[0].rstrip("/")
    path = urlparse(url).path
    return path.strip("/").split("/")[0]


def read_targets_from_terminal() -> list[tuple[Profile, str]]:
    """Read profile+URL pairs from the terminal as CSV lines and return (Profile, username) pairs."""
    profiles = _load_profiles_map()
    if not profiles:
        print("No profiles found. Please register a profile first (run archiver/profile_registration.py).")
        sys.exit(1)

    print("\nAvailable profiles:")
    for idx, p in enumerate(profiles):
        print(f"  {idx}  {p.name}  (Instagram: @{p.insta_username})")

    print("\nEnter targets as CSV lines: profile_identifier,account_url")
    print("Profile identifier can be the profile name or its index number.")
    print("Enter a blank line when done.\n")

    targets: list[tuple[Profile, str]] = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        parts = line.split(",", 1)
        if len(parts) != 2:
            print(f"  Skipping malformed line (expected 'identifier,url'): {line}")
            continue
        profile_id, url = parts[0].strip(), parts[1].strip()
        profile = _resolve_profile(profile_id, profiles)
        if profile is None:
            print(f"  Skipping unknown profile identifier: '{profile_id}'")
            continue
        username = _username_from_url(url)
        if not username:
            print(f"  Skipping — could not extract username from URL: '{url}'")
            continue
        targets.append((profile, username))
        print(f"  Added: @{username} using profile '{profile.name}'")

    if not targets:
        print("No valid targets entered — nothing to do.")
        sys.exit(0)

    return targets


def get_session_config() -> Optional[SessionConfig]:
    default_signature = os.getenv("DEFAULT_SIGNATURE", "")

    print("\nPress Enter to use default settings, or type 'config' to customize: ", end="", flush=True)
    if input().strip().lower() != "config":
        return SessionConfig(
            scrape_followers=True,
            scrape_following=True,
            storage_config=StorageConfig(
                signature=default_signature,
                notes="",
                v_download_media_not_in_structures=False,
                v_download_unfetched_media=False,
                v_download_full_versions_of_fetched_media=False,
                v_download_highest_quality_assets_from_structures=False,
                p_download_media_not_in_structures=False,
                p_download_unfetched_media=False,
                p_download_highest_quality_assets_from_structures=False,
            ),
        )

    raw = show_dialog_form(
        DialogForm(
            title="Automated Follower Scraper — Configuration",
            submit_button_text="Start",
            sections=[
                FormSection(
                    title="Scraping",
                    fields=[
                        FormFieldBool(
                            title="Scrape followers",
                            key="scrape_followers",
                            default_value=True,
                        ),
                        FormFieldBool(
                            title="Scrape following",
                            key="scrape_following",
                            default_value=True,
                        ),
                    ],
                ),
                FormSection(
                    title="Summary",
                    fields=[
                        FormFieldText(
                            title="Signature (Full Name)",
                            key="signature",
                            default_value=default_signature,
                        ),
                        FormFieldText(
                            title="Notes about the content",
                            key="notes",
                            default_value="",
                        ),
                    ],
                ),
                FormSection(
                    title="Video Downloading Configuration",
                    fields=[
                        FormFieldBool(
                            title="Download Auxiliary Media (profile pictures of other users, thumbnails, etc.)",
                            key="v_download_media_not_in_structures",
                            default_value=False,
                        ),
                        FormFieldBool(
                            title="Download Related Media that Hasn't Been Fetched During the Session",
                            key="v_download_unfetched_media",
                            default_value=False,
                        ),
                        FormFieldBool(
                            title="Download Full Versions of Fetched Media",
                            key="v_download_full_versions_of_fetched_media",
                            default_value=False,
                        ),
                        FormFieldBool(
                            title="Download Highest Quality Assets from Structures",
                            key="v_download_highest_quality_assets_from_structures",
                            default_value=False,
                        ),
                    ],
                ),
                FormSection(
                    title="Photo Downloading Configuration",
                    fields=[
                        FormFieldBool(
                            title="Download Auxiliary Media (profile pictures of other users, thumbnails, etc.)",
                            key="p_download_media_not_in_structures",
                            default_value=False,
                        ),
                        FormFieldBool(
                            title="Download Related Media that Hasn't Been Fetched During the Session",
                            key="p_download_unfetched_media",
                            default_value=False,
                        ),
                        FormFieldBool(
                            title="Download Highest Quality Assets from Structures",
                            key="p_download_highest_quality_assets_from_structures",
                            default_value=False,
                        ),
                    ],
                ),
            ],
        )
    )

    if raw is None:
        return None

    return SessionConfig(
        scrape_followers=raw["scrape_followers"],
        scrape_following=raw["scrape_following"],
        storage_config=StorageConfig(
            signature=raw["signature"],
            notes=raw["notes"],
            v_download_media_not_in_structures=raw["v_download_media_not_in_structures"],
            v_download_unfetched_media=raw["v_download_unfetched_media"],
            v_download_full_versions_of_fetched_media=raw["v_download_full_versions_of_fetched_media"],
            v_download_highest_quality_assets_from_structures=raw["v_download_highest_quality_assets_from_structures"],
            p_download_media_not_in_structures=raw["p_download_media_not_in_structures"],
            p_download_unfetched_media=raw["p_download_unfetched_media"],
            p_download_highest_quality_assets_from_structures=raw["p_download_highest_quality_assets_from_structures"],
        ),
    )


def archive_followers_session(
    profile: Profile,
    username: str,
    commit_id: Optional[str],
    branch: Optional[str],
    config: SessionConfig,
) -> None:
    profiles_dir = Path(ROOT_DIR) / "archiver" / "profiles"
    profile_path = profiles_dir / profile.name

    if not profile_path.exists() or not (profile_path / "state.json").exists():
        print(f"Profile '{profile.name}' not found. Please register it first.")
        return

    target_url = f"https://www.instagram.com/{username}/"

    archiving_start_time = datetime.datetime.now()
    archiving_start_timestamp = archiving_start_time.isoformat()
    archive_dir = (
        Path(ROOT_DIR)
        / "archives"
        / f"{profile.name}_{username}_{archiving_start_time.strftime('%Y%m%d_%H%M%S')}"
    )
    archive_dir.mkdir(parents=True, exist_ok=True)

    my_public_ip = get_my_public_ip()
    tls_cert = get_tls_cert_info("www.instagram.com")

    with open(profile_path / "state.json", "r") as f:
        storage_state = json.load(f)

    stop_event = threading.Event()
    recording_thread = None
    video_path = archive_dir / "screen_recording.mp4"
    metadata = ArchiveSessionMetadata(
        commit_id=commit_id,
        branch=branch,
        profile_name=profile.insta_username,
        target_url=target_url,
        archiving_start_timestamp=archiving_start_timestamp,
        recording_start_timestamp=datetime.datetime.now().isoformat(),
        archiving_timezone=datetime.datetime.now().astimezone().tzname(),
        har_archive=archive_dir / "har_workspace" / "archive.har",
        my_ip=my_public_ip,
        platform=get_system_info(),
        tls_cert=tls_cert,
    )

    try:
        with sync_playwright() as p:
            # Force 1 device-pixel per CSS-pixel via the Firefox-native
            # layout.css.devPixelsPerPx pref. Without this, the operator's OS
            # display scaling (e.g. Windows 125%) leaks into devicePixelRatio
            # in headed mode, so the page renders into a larger backing surface
            # while the built-in video recorder only captures the top-left
            # device-px region -> cropped video. Playwright's device_scale_factor
            # context option does NOT fix this: Firefox ignores it
            # (microsoft/playwright#36628).
            browser = p.firefox.launch(
                headless=False,
                firefox_user_prefs={"layout.css.devPixelsPerPx": "1.0"},
            )
            browser_build_id = f"{browser.browser_type.name}_{browser.version}"
            metadata.browser_build_id = browser_build_id
            context = browser.new_context(
                storage_state=storage_state,
                record_har_path=metadata.har_archive,
                record_har_content="attach",
                record_video_dir=archive_dir / "screen_recordings",
            )

            page = context.new_page()
            frame_hashes_path = archive_dir / "frame_hashes.jsonl"
            recording_thread = threading.Thread(
                target=screen_record,
                args=(str(video_path), stop_event, str(frame_hashes_path)),
            )
            recording_thread.start()

            try:
                print(f"Starting automated followers scrape for @{username}")
                run_followers_automation(
                    page,
                    username,
                    config.scrape_followers,
                    config.scrape_following,
                )
                print(f"Automation complete for @{username}")
            except Exception as e:
                if "Target closed" in str(e) or "browser has disconnected" in str(e).lower():
                    print("Browser shutdown detected, wrapping up archiving session...")
                else:
                    print(f"Error during automated archiving of @{username}: {e}")
            finally:
                try:
                    context.close()
                except Exception as e:
                    print(f"Warning: context.close() raised an error: {e}")
                try:
                    browser.close()
                except Exception as e:
                    print(f"Warning: browser.close() raised an error: {e}")
    except Exception as e:
        print(f"Playwright session ended with an error: {e}")

    finish_recording(
        recording_thread,
        archive_dir,
        metadata,
        stop_event,
        storage_config=config.storage_config,
    )


if __name__ == "__main__":
    commit_id, branch = ensure_committed()
    ensure_vpn_connection()
    ensure_ffmpeg_installed()
    ensure_par2_installed()
    targets = read_targets_from_terminal()
    config = get_session_config()
    if config is None:
        sys.exit(0)
    for profile, username in targets:
        archive_followers_session(profile, username, commit_id, branch, config)
    sys.exit(0)
