"""
Resume a crashed archiving session.

`archive.py`'s `finish_recording` does a fairly long sequence of post-recording
work (HAR merge, integrity protection, metadata.json + affidavit, media
download via `generate_entities_summary`, optional curation, seal). If the
script crashes anywhere in there, this module picks up wherever it left off
and finishes the job — re-using `archive.py`'s building blocks so behaviour
stays identical to a clean run.

What gets auto-detected from disk:
  - HAR merge: if `archive.har` is missing but `har_workspace/archive.har`
    exists, the merge step is run.
  - Browser build id: from the HAR's `log.browser` header.
  - Archiving start time: from the archive folder's `_YYYYMMDD_HHMMSS` suffix.
  - Profile insta_username: from `archiver/profiles/map.json` keyed off the
    folder's name prefix.
  - Target URL: from the HAR's first entry's request URL.
  - Commit id / branch: from current git state via `ensure_committed`.
  - Platform: via `get_system_info`.
  - Existing video integrity / frame-hashes / metadata: preserved if present.

What's prompted for (since it can't be derived):
  - Confirmation / override for the auto-detected target URL.
  - The same "Finish Archiving" dialog the user normally sees, supplying
    signature, notes, video/photo acquisition config and curation preference.

Caveats:
  - TLS cert + public IP are RE-CAPTURED at recovery time, not at session
    time. The notes field records that this archive was recovered.
"""
import datetime
import hashlib
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Optional

import ijson

from archiver.archive import (
    ArchiveSessionMetadata,
    StorageConfig,
    affidavit_from_metadata,
    get_storage_config,
    get_tls_cert_info,
    merge_har_attachments,
    resolve_har_domains,
)
from archiver.summarizers.finalize_archive import finalize_archive
from archiver.summarizers.har_summary_generator import generate_entities_summary
from extractors.extract_photos import PhotoAcquisitionConfig
from extractors.extract_videos import VideoAcquisitionConfig
from root_anchor import ROOT_DIR
from utils.commit_tracker.git_helper import ensure_committed
from utils.integrity import FileIntegrity, protect_file
from utils.misc import get_my_public_ip, get_system_info


FOLDER_NAME_RE = re.compile(r"^(?P<name>.+)_(?P<ts>\d{8}_\d{6})$")


def parse_folder_name(archive_dir: Path) -> tuple[Optional[str], Optional[datetime.datetime]]:
    """Split 'profilename_YYYYMMDD_HHMMSS' into (profile_name, start_dt_local)."""
    m = FOLDER_NAME_RE.match(archive_dir.name)
    if not m:
        return None, None
    name = m.group("name")
    try:
        start_dt = datetime.datetime.strptime(m.group("ts"), "%Y%m%d_%H%M%S").astimezone()
    except ValueError:
        start_dt = None
    return name, start_dt


def lookup_insta_username(profile_name: str) -> Optional[str]:
    map_path = Path(ROOT_DIR) / "archiver" / "profiles" / "map.json"
    if not map_path.exists():
        return None
    try:
        entries = json.loads(map_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for e in entries:
        if e.get("name") == profile_name:
            return e.get("insta_username")
    return None


def har_browser_build_id(har_path: Path) -> Optional[str]:
    try:
        with open(har_path, "rb") as f:
            browser = next(ijson.items(f, "log.browser", use_float=True), None)
    except Exception:
        return None
    if not browser:
        return None
    name = browser.get("name", "")
    version = browser.get("version", "")
    if name and version:
        return f"{name}_{version}"
    return name or None


def har_first_request_url(har_path: Path) -> Optional[str]:
    try:
        with open(har_path, "rb") as f:
            entry = next(ijson.items(f, "log.entries.item", use_float=True), None)
    except Exception:
        return None
    if not entry:
        return None
    return entry.get("request", {}).get("url")


def prompt(text: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{text}{suffix}: ").strip()
    return val or (default or "")


def load_video_integrity(archive_dir: Path) -> Optional[FileIntegrity]:
    """Reuse the pre-crash screen_recording.mp4.manifest.json if present.

    Recomputes manifest_hash by hashing the manifest file's bytes — matches
    what write_manifest did originally (sha256 of the serialized payload that
    was written to disk).
    """
    manifest_path = archive_dir / "screen_recording.mp4.manifest.json"
    if not manifest_path.exists():
        return None
    raw = manifest_path.read_bytes()
    try:
        m = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    whole = m.get("whole_file_sha256")
    if not whole:
        return None
    manifest_hash = hashlib.sha256(raw).hexdigest()
    par2_index = archive_dir / "screen_recording.mp4.par2"
    return FileIntegrity(
        algorithm="sha256",
        whole_file_hash=whole,
        manifest_path=str(manifest_path.relative_to(archive_dir)),
        manifest_hash=manifest_hash,
        par2_index_path=str(par2_index.relative_to(archive_dir)) if par2_index.exists() else None,
    )


def ensure_har_merged(archive_dir: Path) -> Path:
    """Make sure the self-contained archive.har is at the archive root."""
    final = archive_dir / "archive.har"
    if final.exists():
        return final
    workspace_har = archive_dir / "har_workspace" / "archive.har"
    if not workspace_har.exists():
        raise FileNotFoundError(
            f"Neither {final} nor {workspace_har} exists — nothing to recover."
        )
    print(f"Merging HAR attachments from {workspace_har.parent}...")
    merge_har_attachments(workspace_har)
    if not final.exists():
        raise RuntimeError(f"merge produced no file at {final}")
    return final


def resume_archive(archive_dir: Path) -> None:
    if not archive_dir.is_dir():
        raise FileNotFoundError(f"Not a directory: {archive_dir}")

    har_path = ensure_har_merged(archive_dir)

    profile_name, start_dt = parse_folder_name(archive_dir)
    insta_username_default = lookup_insta_username(profile_name) if profile_name else None
    browser_build_id = har_browser_build_id(har_path)
    target_url_default = har_first_request_url(har_path) or ""

    print()
    print("Auto-detected from archive folder + HAR:")
    print(f"  archive_dir       = {archive_dir}")
    print(f"  profile_name      = {profile_name}")
    print(f"  insta_username    = {insta_username_default}")
    print(f"  start_timestamp   = {start_dt.isoformat() if start_dt else '<unknown>'}")
    print(f"  target_url        = {target_url_default}")
    print(f"  browser_build_id  = {browser_build_id}")
    print()

    insta_username = prompt("Confirm/override Instagram username", insta_username_default or "")
    target_url = prompt("Confirm/override target URL", target_url_default)

    if not insta_username:
        print("⚠️  Instagram username left blank.")
    if not target_url:
        print("⚠️  Target URL left blank.")

    print()
    print("Opening the standard 'Finish Archiving' dialog for the rest...")
    storage_config: Optional[StorageConfig] = get_storage_config()
    if storage_config is None:
        print("Aborted — dialog cancelled. No changes written.")
        return

    commit_id, branch = ensure_committed()

    print("Re-capturing TLS cert + public IP (POST-session — not session-time values).")
    tls_cert = get_tls_cert_info("www.instagram.com")
    my_ip = get_my_public_ip()

    recovery_note = (
        "Archive recovered post-crash via archiver/resume_archive.py. "
        "TLS cert and public IP shown here were captured at recovery time, "
        "not during the original recording."
    )
    notes_combined = (
        f"{storage_config.notes}\n\n[RECOVERY] {recovery_note}"
        if storage_config.notes else f"[RECOVERY] {recovery_note}"
    )

    start_iso = start_dt.isoformat() if start_dt else datetime.datetime.now().isoformat()
    metadata = ArchiveSessionMetadata(
        commit_id=commit_id,
        branch=branch,
        profile_name=insta_username,
        target_url=target_url,
        archiving_start_timestamp=start_iso,
        recording_start_timestamp=start_iso,
        archiving_timezone=(start_dt or datetime.datetime.now().astimezone()).tzname(),
        har_archive=har_path,
        my_ip=my_ip,
        platform=get_system_info(),
        tls_cert=tls_cert,
        browser_build_id=browser_build_id,
        signature=storage_config.signature,
        notes=notes_combined,
        video_integrity=load_video_integrity(archive_dir),
    )

    print("Resolving HAR domains...")
    metadata.domain_resolutions = resolve_har_domains(har_path)
    metadata.archiving_finished_timestamp = datetime.datetime.now().isoformat()

    print("Protecting HAR (chunked hash + PAR2 + OTS)...")
    try:
        # timestamp=True: standalone per-asset OTS proof for the HAR, matching
        # the main archive.py path. The archive-level seal still runs later via
        # finalize_archive().
        har_protection = protect_file(har_path, timestamp=True)
        metadata.har_integrity = har_protection.to_integrity(base_dir=archive_dir)
    except Exception as e:
        traceback.print_exc()
        print(f"HAR integrity protection failed: {e}")

    metadata_dict = metadata.model_dump()
    (archive_dir / "metadata.json").write_text(
        json.dumps(metadata_dict, indent=2, default=str), encoding="utf-8"
    )
    print(f"Wrote {archive_dir / 'metadata.json'}")

    (archive_dir / "affidavit.txt").write_text(
        affidavit_from_metadata(metadata), encoding="utf-8"
    )
    print(f"Wrote {archive_dir / 'affidavit.txt'}")

    video_config = VideoAcquisitionConfig(
        download_missing=True,
        download_media_not_in_structures=storage_config.v_download_media_not_in_structures,
        download_unfetched_media=storage_config.v_download_unfetched_media,
        download_full_versions_of_fetched_media=storage_config.v_download_full_versions_of_fetched_media,
        download_highest_quality_assets_from_structures=storage_config.v_download_highest_quality_assets_from_structures,
    )
    photo_config = PhotoAcquisitionConfig(
        download_missing=True,
        download_media_not_in_structures=storage_config.p_download_media_not_in_structures,
        download_unfetched_media=storage_config.p_download_unfetched_media,
        download_highest_quality_assets_from_structures=storage_config.p_download_highest_quality_assets_from_structures,
    )

    print("Running generate_entities_summary (downloads media)...")
    try:
        generate_entities_summary(har_path, archive_dir, metadata_dict, video_config, photo_config)
    except Exception:
        traceback.print_exc()

    # Hand off to finalize_archive for the curation + re-render + seal stage.
    # finalize_archive already encapsulates exactly that flow.
    finalize_archive(har_path, pause_for_curation=storage_config.manually_curate_assets)

    print(f"Content archived successfully in {archive_dir}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path(input("Path to the archive directory to resume: ").strip().strip('"').strip("'"))
    resume_archive(target.resolve())