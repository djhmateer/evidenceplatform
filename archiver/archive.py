# archive.py
import base64
import datetime
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import cv2
import ijson
import numpy as np
import pyautogui
import pygetwindow as gw
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

from archiver.dialogs import show_dialog_form, DialogForm, FormFieldText, FormFieldBool, FormSection
from archiver.profile_registration import Profile
from archiver.profile_selection import select_profile
from archiver.summarizers import download_log as dl
from archiver.summarizers.har_summary_generator import generate_entities_summary
from extractors.extract_photos import PhotoAcquisitionConfig
from extractors.extract_videos import VideoAcquisitionConfig
from root_anchor import ROOT_DIR
from utils.commit_tracker.git_helper import ensure_committed
from utils.ffmpeg_installer import ensure_ffmpeg_installed
from utils.integrity import FileIntegrity, protect_file, seal_archive
from utils.misc import get_my_public_ip, get_system_info
from utils.par2_installer import ensure_par2_installed

SCREEN_SIZE = tuple(pyautogui.size())
commit_id = None
branch = None
load_dotenv()


# Locking the recording dimensions deterministically so Playwright's per-page
# MP4 (and the network video frames it embeds) isn't cropped by whatever the
# context's default happens to be on a given Playwright/Firefox version.
_VIEWPORT = {"width": 1280, "height": 720}

# Navigating the main frame to this URL is the "safe finish" signal. It tells
# the archiver "I'm done; finalize the HAR now, while Firefox is still alive."
# Closing the Firefox window still works as a fallback, but has the rare
# (~5%) HAR-finalization race against the dying browser process — use the
# safe-finish URL when the archive matters.
#
# This is the single source of truth — _is_safe_finish_url derives its host
# and path check from this value, so changing the URL here is enough; nothing
# else needs editing. Pick a URL the operator can type from memory under
# pressure but that is unlikely to be hit accidentally by browser-internal
# requests during the session.
_SAFE_FINISH_URL = "https://www.google.com/"
_SAFE_FINISH_URL_PARSED = urlparse(_SAFE_FINISH_URL)


def _is_safe_finish_url(url: str) -> bool:
    """True iff `url` matches the configured safe-finish URL exactly.

    Anchoring on `(scheme, host, path)` equality — not prefix — stops two
    real false-positives a naive startswith match would accept:
      * lookalike hosts (anything ending in the configured host suffix);
      * other paths under the same host that can be reached from
        sponsored / wrapped / redirected links inside a recorded session
        (e.g. open-redirect endpoints, on-site search results, etc.) — a
        startswith match would treat any of these as a finish trigger and
        end the session mid-archive.

    An empty `parsed.path` (Firefox sometimes drops the trailing slash when
    auto-completing a bare host in the URL bar) is treated as equivalent to
    the configured path's "/" form.
    """
    parsed = urlparse(url)
    if parsed.scheme != _SAFE_FINISH_URL_PARSED.scheme:
        return False
    if parsed.netloc != _SAFE_FINISH_URL_PARSED.netloc:
        return False
    configured_path = _SAFE_FINISH_URL_PARSED.path or "/"
    actual_path = parsed.path or "/"
    return actual_path == configured_path



class TLSCertInfo(BaseModel):
    fingerprint_sha256: Optional[str] = None
    subject: Optional[dict] = None
    issuer: Optional[dict] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None


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
    har_integrity: Optional[FileIntegrity] = None
    video_integrity: Optional[FileIntegrity] = None
    domain_resolutions: Optional[dict] = None
    tls_cert: Optional[TLSCertInfo] = None
    browser_build_id: Optional[str] = None
    commit_id: Optional[str] = None
    branch: Optional[str] = None
    signature: Optional[str] = None
    notes: Optional[str] = None


def get_tls_cert_info(hostname: str) -> Optional[TLSCertInfo]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                cert_dict = ssock.getpeercert()
                info = TLSCertInfo(
                    fingerprint_sha256=hashlib.sha256(cert_der).hexdigest(),
                    subject=dict(item for rdn in cert_dict.get('subject', ()) for item in rdn),
                    issuer=dict(item for rdn in cert_dict.get('issuer', ()) for item in rdn),
                    valid_from=cert_dict.get('notBefore'),
                    valid_to=cert_dict.get('notAfter'),
                )
                print(f"TLS cert fingerprint for {hostname}: {info.fingerprint_sha256}")
                return info
    except Exception as e:
        print(f"TLS certificate capture failed for {hostname}: {e}")
        return None


def resolve_har_domains(har_path: Path) -> dict:
    """Parse all unique hostnames from HAR requests and resolve each to an IP."""
    resolutions = {}
    try:
        hostnames = set()
        with open(har_path, 'rb') as f:
            for entry in ijson.items(f, 'log.entries.item'):
                url = entry.get('request', {}).get('url', '')
                if url:
                    hostname = urlparse(url).hostname
                    if hostname:
                        hostnames.add(hostname)
        for hostname in sorted(hostnames):
            try:
                resolutions[hostname] = socket.getaddrinfo(hostname, None)[0][4][0]
            except Exception:
                resolutions[hostname] = None
        print(f"Resolved {len(resolutions)} domains from HAR.")
    except Exception as e:
        print(f"Error resolving HAR domains: {e}")
    return resolutions


def screen_record(output_path, stop_event, frame_hashes_path=None):
    # Screen recording using OpenCV, only capturing the Playwright browser window
    window_keywords = ("Nightly")
    browser_window = None
    for attempt in range(5):
        windows = [w for w in gw.getAllWindows() if any(k in w.title for k in window_keywords)]
        if windows:
            browser_window = windows[0]
            break
        time.sleep(5)
    else:
        print("Could not find the Firefox browser window for screen recording.")
        return

    fps = 20.0
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    raw_output_path = output_path.replace(".mp4", "_raw.mp4")
    out = None
    last_size = None
    frame_index = 0
    last_hash_time = None
    frame_hash_interval_seconds = 30

    while not stop_event.is_set():
        try:
            if browser_window.isMinimized:
                time.sleep(1 / fps)
                continue

            width, height = browser_window.width, browser_window.height
            if width <= 0 or height <= 0:
                time.sleep(1 / fps)
                continue

            current_size = (width, height)
            if out is None or current_size != last_size:
                if out is not None:
                    out.release()
                out = cv2.VideoWriter(raw_output_path, fourcc, fps, current_size)
                last_size = current_size

            img = pyautogui.screenshot(region=(browser_window.left, browser_window.top, width, height))
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            out.write(frame)

            now = time.time()
            if frame_hashes_path and (last_hash_time is None or now - last_hash_time >= frame_hash_interval_seconds):
                frame_hash = hashlib.sha256(frame.tobytes()).hexdigest()
                entry = json.dumps({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "frame_index": frame_index,
                    "sha256": frame_hash,
                })
                with open(frame_hashes_path, 'a', encoding='utf-8') as fh:
                    fh.write(entry + '\n')
                last_hash_time = now

            frame_index += 1
        except Exception:
            time.sleep(1 / fps)
            continue
        time.sleep(1 / fps)  # Control FPS

    if out is not None:
        out.release()
    print("Frame capture stopped.")


def affidavit_from_metadata(metadata: ArchiveSessionMetadata) -> str:
    affidavit = f"""I, {metadata.signature}, have archived the Instagram content from {metadata.target_url} using the profile '{metadata.profile_name}'.
The archiving process started at {metadata.archiving_start_timestamp} and was completed at {metadata.archiving_finished_timestamp} (timezone: {datetime.datetime.now().astimezone().tzname()}, UTC {datetime.datetime.now().astimezone().utcoffset()}).
Archiving was carried out from the IP address {metadata.my_ip}, and was done through the use of a custom Python script.
The script launches a Playwright-controlled Firefox browser ({metadata.browser_build_id}), which is used to navigate to the target URL, and allows the user to manually interact with the page (including scrolling, clicking, and navigating to other pages).
The script records the screen during this process, and also saves a HAR file of the network traffic. The screen recording is saved as a video file. Server requests for video content from the Instagram servers during the sessions are identified through analysis of the HAR file, and the full media files are downloaded and saved to the archive directory (these tracks may include data that does not appear in the HAR, since it only includes byte-range segments which don't necessarily cover the entire duration of the video).
None of the HAR's content has been altered or modified in any way, and no third party has been granted access to the file system. The code used for this process is available on GitHub at https://github.com/yanivcogan/InstagramArchiver (branch {metadata.branch}, commit {metadata.commit_id})
SHA-256 hash of the HAR file: {metadata.har_integrity.whole_file_hash if metadata.har_integrity else 'N/A'}
SHA-256 hash of the screen recording: {metadata.video_integrity.whole_file_hash if metadata.video_integrity else 'N/A'}
Each archived asset has a sidecar `<asset>.manifest.json` carrying its chunked-SHA-256 + PAR2 recovery metadata, and a sibling `<asset>.par2` recovery file (PAR2). A single archive-level `manifests.json` summary at the archive root commits to every per-asset manifest's SHA-256 and is OpenTimestamps-anchored at `manifests.json.ots` — that one timestamp transitively proves the existence of every chunk hash, whole-file hash, and PAR2 index hash in the archive at the time of sealing.
At the time of archiving, the following domains were contacted and resolved to the following IP addresses: {metadata.domain_resolutions}
The TLS certificate presented by www.instagram.com had SHA-256 fingerprint {metadata.tls_cert.fingerprint_sha256 if metadata.tls_cert else 'N/A'}, issued by {metadata.tls_cert.issuer if metadata.tls_cert else 'N/A'}, valid from {metadata.tls_cert.valid_from if metadata.tls_cert else 'N/A'} to {metadata.tls_cert.valid_to if metadata.tls_cert else 'N/A'}.
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
    manually_curate_assets: bool = False


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
                FormSection(
                    title="Post-Archiving Review",
                    fields=[
                        FormFieldBool(
                            title="Pause to let me review the downloaded media in Explorer before sealing (delete unwanted files in videos/ or photos/; they won't be re-downloaded on subsequent runs)",
                            key="manually_curate_assets",
                            default_value=False
                        )
                    ]
                ),
            ]
        )
    )
    if storage_config_dict is None:
        return None
    return StorageConfig(**storage_config_dict)


def merge_har_attachments(har_path: Path) -> Path:
    """
    Playwright's record_har_content="attach" mode writes each response body as
    a separate file (named by content hash) in the same directory as the HAR,
    and stores a "_file" reference in the HAR entry instead of an inline "text"
    field.  This function inlines those bodies back into the HAR to produce a
    standard self-contained file at har_path.parent.parent / "archive.har",
    then removes the entire har_path.parent workspace directory.
    Returns the path of the merged HAR.
    If the HAR contains no "_file" references it is moved as-is and the
    workspace is still removed.
    """
    workspace_dir = har_path.parent
    final_path = workspace_dir.parent / "archive.har"
    temp_path = workspace_dir / "archive.tmp.har"

    # Read small header fields via separate streaming passes.  These sections
    # are always tiny; only the entries array grows large.
    with open(har_path, 'rb') as f:
        version = next(ijson.items(f, 'log.version', use_float=True), '1.2')
    with open(har_path, 'rb') as f:
        creator = next(ijson.items(f, 'log.creator', use_float=True), {})
    with open(har_path, 'rb') as f:
        browser = next(ijson.items(f, 'log.browser', use_float=True), None)
    with open(har_path, 'rb') as f:
        pages = list(ijson.items(f, 'log.pages.item', use_float=True))

    # Stream entries one-by-one so neither reader nor writer needs the full
    # document in memory at once.
    attachment_count = 0
    missing_count = 0
    missing_by_mime: dict[str, int] = {}
    with open(har_path, 'rb') as har_f, \
         open(temp_path, 'w', encoding='utf-8') as out_f:

        out_f.write('{"log":{')
        out_f.write(f'"version":{json.dumps(version)}')
        out_f.write(f',"creator":{json.dumps(creator, ensure_ascii=False)}')
        if browser is not None:
            out_f.write(f',"browser":{json.dumps(browser, ensure_ascii=False)}')
        out_f.write(f',"pages":{json.dumps(pages, ensure_ascii=False)}')
        out_f.write(',"entries":[')

        first = True
        for entry in ijson.items(har_f, 'log.entries.item', use_float=True):
            content = entry.get('response', {}).get('content', {})
            file_ref = content.pop('_file', None)
            if file_ref is not None:
                attachment_count += 1
                attachment_path = workspace_dir / file_ref
                if attachment_path.exists():
                    body_bytes = attachment_path.read_bytes()
                    mime = content.get('mimeType', '')
                    is_text = (
                        mime.startswith('text/') or
                        'json' in mime or
                        'xml' in mime or
                        'javascript' in mime
                    )
                    if is_text:
                        try:
                            content['text'] = body_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            content['text'] = base64.b64encode(body_bytes).decode('ascii')
                            content['encoding'] = 'base64'
                    else:
                        content['text'] = base64.b64encode(body_bytes).decode('ascii')
                        content['encoding'] = 'base64'
                else:
                    # Playwright recorded a `_file` reference but the attachment
                    # was never written to disk — almost always means
                    # context.close() ran with this response's body still
                    # streaming. Tally it and surface a loud warning at the
                    # end of the merge; the worst outcome is silent body loss
                    # going unnoticed (see commit history for the post-mortem
                    # where ~91% of bodies were dropped without a single
                    # operator-visible signal).
                    missing_count += 1
                    mime_key = content.get('mimeType', '?').split(';')[0]
                    missing_by_mime[mime_key] = missing_by_mime.get(mime_key, 0) + 1

            if not first:
                out_f.write(',')
            out_f.write(json.dumps(entry, ensure_ascii=False))
            first = False

        out_f.write(']}}')

    # Move the merged HAR to the archive root and delete the whole workspace.
    if missing_count:
        pct_lost = missing_count * 100 // max(attachment_count, 1)
        print(f"⚠️  Merging HAR: {attachment_count} attachments referenced, "
              f"{missing_count} MISSING ({pct_lost}% of bodies lost).")
        print("    Missing by MIME type (top contributors):")
        for mime, n in sorted(missing_by_mime.items(), key=lambda kv: -kv[1])[:8]:
            print(f"      {n:>5}  {mime}")
        print("    This means Playwright finalized the HAR with `_file` "
              "references whose attachment files were never written — "
              "typically because context.close() ran while requests were "
              "still in flight (X-button close is the usual culprit).")
    else:
        print(f"Merging HAR attachments into self-contained HAR ({attachment_count} attachments)...")
    temp_path.rename(final_path)
    shutil.rmtree(workspace_dir)
    print("HAR merge complete.")
    return final_path


def _read_only_video_config() -> VideoAcquisitionConfig:
    """Acquisition config that links files already on disk but never downloads
    or reassembles anything. Used post-curation and from finalize_archive."""
    return VideoAcquisitionConfig(
        download_missing=False,
        download_media_not_in_structures=False,
        download_unfetched_media=False,
        download_full_versions_of_fetched_media=False,
        download_highest_quality_assets_from_structures=False,
    )


def _read_only_photo_config() -> PhotoAcquisitionConfig:
    return PhotoAcquisitionConfig(
        download_missing=False,
        download_media_not_in_structures=False,
        download_unfetched_media=False,
        download_highest_quality_assets_from_structures=False,
    )


def protect_log_and_seal(archive_dir: Path) -> None:
    """Protect downloaded_media_log.json (so the curation decisions are
    committed to the seal) and then seal the archive."""
    log_path = archive_dir / dl.LOG_FILENAME
    if log_path.exists():
        try:
            protect_file(log_path)
        except Exception as e:
            traceback.print_exc()
            print(f"❌ Error protecting download log: {e}")

    try:
        seal = seal_archive(archive_dir)
        print(
            f"Sealed archive: {seal.manifest_count} manifest(s), "
            f"summary={seal.summary_path.name}, "
            f"ots={'yes' if seal.ots_path else 'MISSING'}"
        )
    except Exception as e:
        traceback.print_exc()
        print(f"❌ Error sealing archive: {e}")


def run_curation_pause(archive_dir: Path) -> None:
    """
    Open Explorer at the archive root, then block on terminal input until the
    user signals they're done. Any files the user deletes from videos/ or
    photos/ during the pause will stick across subsequent extraction runs via
    downloaded_media_log.json.

    Plain terminal input is intentionally used here rather than a Tk modal:
    Tk windows opened immediately after os.startfile-launched Explorer tend
    to lose the z-order race on Windows, and the terminal is always reachable.
    """
    try:
        os.startfile(str(archive_dir))
    except Exception as e:
        print(f"⚠️  Could not auto-open archive folder ({archive_dir}): {e}")

    print()
    print("=" * 72)
    print("  MANUAL CURATION")
    print("=" * 72)
    print(f"  Archive: {archive_dir}")
    print()
    print("  1. Explorer has been opened at the archive root.")
    print("  2. Delete any files you don't want to keep from:")
    print(f"       {archive_dir / 'videos'}")
    print(f"       {archive_dir / 'photos'}")
    print("     They will NOT be re-downloaded on subsequent extraction runs")
    print("     (downloaded_media_log.json remembers what was already acquired).")
    print("  3. Return to this terminal and press Enter when finished.")
    print("=" * 72)
    try:
        input("  Press Enter to re-render the summary, prune orphans, and seal: ")
    except EOFError:
        # No interactive stdin (e.g. piped/automated run) — fall through and
        # finish sealing rather than getting stuck.
        print("  (stdin closed — proceeding without waiting)")
    print("Manual curation complete.")


def finish_recording(recording_thread: Optional[threading.Thread], archive_dir: Path, metadata: ArchiveSessionMetadata, stop_event=None, storage_config: Optional[StorageConfig] = None):
    # Stop the recording loop. The thread now exits quickly (no FFmpeg inside it).
    if stop_event is not None:
        stop_event.set()
    if recording_thread is not None and recording_thread.is_alive():
        recording_thread.join()

    # Show the dialog if no pre-supplied config (automated sessions pass config upfront).
    if storage_config is None:
        storage_config = get_storage_config()

    if storage_config is None:
        print("Archiving cancelled by user. Deleting archive directory.")
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        return

    metadata.signature = storage_config.signature
    metadata.notes = storage_config.notes

    # har_path may be updated by merge_har_attachments inside the try block below;
    # initialise here so it is always defined when generate_entities_summary runs.
    har_path = metadata.har_archive

    # video downloading configuration
    v_download_missing: bool = True
    v_download_media_not_in_structures: bool = storage_config.v_download_media_not_in_structures
    v_download_unfetched_media: bool = storage_config.v_download_unfetched_media
    v_download_full_versions_of_fetched_media: bool = storage_config.v_download_full_versions_of_fetched_media
    v_download_highest_quality_assets_from_structures: bool = storage_config.v_download_highest_quality_assets_from_structures

    # photo downloading configuration
    p_download_missing: bool = True
    p_download_media_not_in_structures: bool = storage_config.p_download_media_not_in_structures
    p_download_unfetched_media: bool = storage_config.p_download_unfetched_media
    p_download_highest_quality_assets_from_structures: bool = storage_config.p_download_highest_quality_assets_from_structures

    try:
        # Re-encode the raw screen recording to H.264 (was previously done inside
        # the recording thread; moved here so the dialog could appear sooner).
        video_path = archive_dir / "screen_recording.mp4"
        raw_video_path = archive_dir / "screen_recording_raw.mp4"
        if raw_video_path.exists():
            print("Re-encoding screen recording to H.264 for browser compatibility...")
            try:
                subprocess.run(
                    ["ffmpeg", "-i", str(raw_video_path), "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-y", str(video_path)],
                    check=True, capture_output=True
                )
                raw_video_path.unlink()
                print(f"Screen recording saved to {video_path}")
            except Exception as e:
                print(f"FFmpeg re-encode failed, keeping raw recording: {e}")
                shutil.move(str(raw_video_path), str(video_path))

        # Build chunked-hash manifest + PAR2 recovery + OTS for the screen recording.
        # timestamp=True writes a standalone <file>.manifest.json.ots proof for the
        # recording on top of the archive-level seal, so this key asset can be
        # independently timestamp-verified without the rest of the archive.
        if video_path.exists():
            try:
                video_protection = protect_file(video_path, timestamp=True)
                metadata.video_integrity = video_protection.to_integrity(base_dir=archive_dir)
            except Exception as e:
                traceback.print_exc()
                print(f"❌ Error protecting video file: {e}")

        # Build chunked-hash manifest + PAR2 + OTS for the frame hashes log
        frame_hashes_path = archive_dir / "frame_hashes.jsonl"
        if frame_hashes_path.exists():
            try:
                protect_file(frame_hashes_path)
            except Exception as e:
                traceback.print_exc()
                print(f"❌ Error protecting frame hashes file: {e}")

        # Inline response bodies from the har_workspace into a single self-contained
        # HAR at archive_dir / "archive.har", then remove the workspace directory.
        try:
            metadata.har_archive = merge_har_attachments(metadata.har_archive)
            har_path = metadata.har_archive
        except Exception as e:
            traceback.print_exc()
            print(f"❌ HAR merge failed, proceeding with unmerged HAR: {e}")

        # Resolve all domains contacted during the session
        metadata.domain_resolutions = resolve_har_domains(metadata.har_archive)

        metadata.archiving_finished_timestamp = datetime.datetime.now().isoformat()

        # timestamp=True writes a standalone <file>.manifest.json.ots proof for the
        # HAR on top of the archive-level seal — the HAR is the load-bearing
        # evidence file, so an independent per-asset timestamp is worth the extra cost.
        try:
            har_protection = protect_file(har_path, timestamp=True)
            metadata.har_integrity = har_protection.to_integrity(base_dir=archive_dir)
        except Exception as e:
            traceback.print_exc()
            print(f"❌ HAR integrity protection failed: {e}")

    except Exception as e:
        traceback.print_exc()
        print(f"❌ Error during post-processing (metadata.json will still be saved): {e}")
    finally:
        with open(archive_dir / "metadata.json", "w", encoding="utf-8") as f:
            metadata_dict = metadata.model_dump()
            json.dump(metadata_dict, f, indent=2, default=str)

    with open(archive_dir / "affidavit.txt", "w", encoding="utf-8") as f:
        f.write(affidavit_from_metadata(metadata))

    # try:
    #     generate_summary(har_path, archive_dir, metadata_dict, download_full_video=True)
    # except Exception:
    #     pass
    video_config = VideoAcquisitionConfig(
        download_missing=v_download_missing,
        download_media_not_in_structures=v_download_media_not_in_structures,
        download_unfetched_media=v_download_unfetched_media,
        download_full_versions_of_fetched_media=v_download_full_versions_of_fetched_media,
        download_highest_quality_assets_from_structures=v_download_highest_quality_assets_from_structures,
    )
    photo_config = PhotoAcquisitionConfig(
        download_missing=p_download_missing,
        download_media_not_in_structures=p_download_media_not_in_structures,
        download_unfetched_media=p_download_unfetched_media,
        download_highest_quality_assets_from_structures=p_download_highest_quality_assets_from_structures,
    )
    try:
        generate_entities_summary(
            har_path,
            archive_dir,
            metadata_dict,
            video_config,
            photo_config,
        )
    except Exception:
        traceback.print_exc()

    if storage_config.manually_curate_assets:
        try:
            run_curation_pause(archive_dir)
            # Read-only configs for the post-curation re-render: with
            # download_missing=False, acquire_* won't reassemble files the
            # user just deleted from HAR segments (which would silently undo
            # the curation). It just relinks what's still on disk.
            generate_entities_summary(
                har_path,
                archive_dir,
                metadata_dict,
                _read_only_video_config(),
                _read_only_photo_config(),
            )
        except Exception:
            traceback.print_exc()

    protect_log_and_seal(archive_dir)

    print(f"Content archived successfully in {archive_dir}")

    return


def archive_instagram_content(profile: Profile, target_url: str):
    profiles_dir = Path(ROOT_DIR) / "archiver" / "profiles"
    profile_name = profile.name
    profile_path = profiles_dir / profile_name

    if not profile_path.exists() or not (profile_path / "state.json").exists():
        print(f"Profile '{profile_name}' not found. Please register it first.")
        return

    # Create archive directory with timestamp
    archiving_start_time = datetime.datetime.now()
    archiving_start_timestamp = archiving_start_time.isoformat()
    archive_dir = Path(ROOT_DIR) / "archives" / f"{profile_name}_{archiving_start_time.strftime('%Y%m%d_%H%M%S')}"
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
            # Launch browser with the saved state
            browser = p.firefox.launch(headless=False)
            browser_build_id = f"{browser.browser_type.name}_{browser.version}"
            metadata.browser_build_id = browser_build_id
            context = browser.new_context(
                storage_state=storage_state,
                record_har_path=metadata.har_archive,
                record_har_content="attach",
                record_video_dir=archive_dir / "screen_recordings",
                viewport=_VIEWPORT,
                record_video_size=_VIEWPORT,
            )

            page = context.new_page()
            frame_hashes_path = archive_dir / "frame_hashes.jsonl"
            recording_thread = threading.Thread(
                target=screen_record,
                args=(str(video_path), stop_event, str(frame_hashes_path))
            )
            recording_thread.start()

            try:
                # Navigate to the target URL
                page.goto(target_url)

                # Allow user to do whatever they want. The session ends when
                # the user either:
                #   (a) navigates the main frame to the safe-finish URL
                #       (configured via _SAFE_FINISH_URL above) →
                #       wait_for_url returns cleanly. Firefox is still alive,
                #       so context.close() below finalizes the HAR without
                #       racing the dying browser process. Bonus: navigating
                #       away from instagram.com aborts any in-flight IG
                #       requests *before* context.close() runs, which makes
                #       attachment loss strictly less likely than the
                #       X-button path.
                #   (b) closes the Firefox window → wait_for_url raises
                #       "Target closed" / "Page closed", caught below. Same
                #       behaviour as the legacy single-page approach with
                #       the same residual ~5% HAR-finalization race.
                #
                # The whole session blocks inside one Playwright call, so the
                # dispatcher fiber is pumped continuously — there's no risk
                # of recreating the fiber-starvation body-loss bug we hit
                # with the polling-loop GUI approach.
                print(f"Archiving content from {target_url}")
                print(f"To finish SAFELY (recommended for important archives): "
                      f"navigate the browser to {_SAFE_FINISH_URL}")
                print("Or close the Firefox window to finish (slightly less "
                      "reliable — rare HAR-finalization race).")
                page.wait_for_url(_is_safe_finish_url, timeout=0)
                print(f"Safe-finish trigger detected ({_SAFE_FINISH_URL}); "
                      f"closing context cleanly...")
            except Exception as e:
                # Playwright raises TargetClosedError on browser/page close
                # with the message "Target page, context or browser has been
                # closed" (see playwright._impl._errors.TargetClosedError).
                # Match the substring that's actually present.
                msg = str(e)
                if "has been closed" in msg or "Target closed" in msg:
                    print("Browser shutdown detected, wrapping up archiving session...")
                else:
                    print(f"Error during archiving: {e}")
            finally:
                # Close browser inside the sync_playwright context. Both calls may fail
                # if the browser already disconnected — that's expected and safe.
                try:
                    context.close()
                except Exception as e:
                    print(f"Warning: context.close() raised an error (browser may have already closed): {e}")
                try:
                    browser.close()
                except Exception as e:
                    print(f"Warning: browser.close() raised an error (browser may have already closed): {e}")
    except Exception as e:
        # sync_playwright().__exit__ can raise if the Playwright server subprocess
        # crashed (e.g. due to an unhandled Node.js error during HAR flush). We
        # catch it here so that post-processing always runs.
        print(f"Playwright session ended with an error: {e}")

    finish_recording(recording_thread, archive_dir, metadata, stop_event)



if __name__ == "__main__":
    commit_id, branch = ensure_committed()
    ensure_ffmpeg_installed()
    ensure_par2_installed()
    selected_profile = select_profile()
    url = input("Enter the Instagram URL to archive: ")
    url = url.split("?igsh=")[0].strip().split("&igsh=")[0].strip()

    archive_instagram_content(selected_profile, url)
    sys.exit(0)