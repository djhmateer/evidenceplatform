"""
Finalize an existing archive directory: optionally pause for manual curation,
re-render the entities summary against what's currently on disk, prune orphan
manifest/par2 sidecars, protect the download log, and run seal_archive.

Use cases:
- Recovery from a crashed or killed `archive.py` run that produced the HAR and
  downloaded media but never reached `seal_archive`.
- Re-finalizing an archive after deleting more files by hand at any point in
  the future — the curation decisions become sticky via
  `downloaded_media_log.json` and the new seal commits only to files actually
  present on disk.

Acquisition is run with `download_missing=False`, so no CDN fetches happen —
this script never adds anything new to the archive. It only reconciles what's
already there, anchors the curation decisions, and seals.
"""

import json
from pathlib import Path

from archiver.archive import (
    _read_only_photo_config,
    _read_only_video_config,
    protect_log_and_seal,
    run_curation_pause,
)
from archiver.summarizers.har_summary_generator import generate_entities_summary


def finalize_archive(har_path: Path, *, pause_for_curation: bool = True) -> None:
    archive_dir = har_path.parent

    metadata_path = archive_dir / "metadata.json"
    metadata: dict = {}
    if metadata_path.exists():
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        print(f"⚠️  No metadata.json at {metadata_path} — proceeding with empty metadata.")

    if pause_for_curation:
        run_curation_pause(archive_dir)

    print("Re-rendering entities summary against current files on disk...")
    generate_entities_summary(
        har_path,
        archive_dir,
        metadata,
        _read_only_video_config(),
        _read_only_photo_config(),
    )

    protect_log_and_seal(archive_dir)


if __name__ == "__main__":
    har_file = input("Input path to HAR file: ").strip().strip('"').strip("'")
    finalize_archive(Path(har_file))
