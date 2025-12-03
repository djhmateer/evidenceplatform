from pathlib import Path

from pydantic import BaseModel, Field


class SessionAttachments(BaseModel):
    screen_recordings: list[str] = Field(default_factory=list)
    screen_shots: list[str] = Field(default_factory=list)
    wacz_archives: list[str] = Field(default_factory=list)
    har_archives: list[str] = Field(default_factory=list)
    hash_files: list[str] = Field(default_factory=list)
    timestamp_files: list[str] = Field(default_factory=list)
    other_files: list[str] = Field(default_factory=list)


def get_session_attachments(archive_location: Path) -> SessionAttachments:
    attachments = SessionAttachments()
    if not archive_location.exists() or not archive_location.is_dir():
        return attachments

    # screen recordings
    # search for main screen recording (screen_recording.avi in root)
    main_screen_recording = archive_location / "screen_recording.avi"
    if main_screen_recording.exists() and main_screen_recording.is_file():
        attachments.screen_recordings.append(main_screen_recording.relative_to(archive_location).as_posix())

    # search for other screen recordings in screen_recordings/ subdir, keep the largest one
    screen_recordings_dir = archive_location / "screen_recordings"
    if screen_recordings_dir.exists() and screen_recordings_dir.is_dir():
        screen_recording_files = [f for f in screen_recordings_dir.iterdir() if f.is_file() and f.suffix.lower() in {".avi", ".mp4", ".mkv", ".mov", ".webm"}]
        if screen_recording_files:
            largest_screen_recording = max(screen_recording_files, key=lambda f: f.stat().st_size)
            attachments.screen_recordings.append(largest_screen_recording.relative_to(archive_location).as_posix())

    # har archive
    har_path = archive_location / "archive.har"
    if har_path.exists() and har_path.is_file():
        attachments.har_archives.append(har_path.relative_to(archive_location).as_posix())

    # har hash
    har_hash_path = archive_location / "har_hash.txt"
    if har_hash_path.exists() and har_hash_path.is_file():
        attachments.hash_files.append(har_hash_path.relative_to(archive_location).as_posix())

    # timestamp file
    timestamp_path = archive_location / "har_hash.txt.tsr"
    if timestamp_path.exists() and timestamp_path.is_file():
        attachments.timestamp_files.append(timestamp_path.relative_to(archive_location).as_posix())

    # media hashes and timestamps
    # photos
    photos_dir = archive_location / "photos"
    if photos_dir.exists() and photos_dir.is_dir():
        photo_hash_files = [f for f in photos_dir.iterdir() if f.is_file() and (f.suffix.lower() == ".txt" or f.suffix.lower() == ".json")]
        for phf in photo_hash_files:
            attachments.hash_files.append(phf.relative_to(archive_location).as_posix())
        photo_timestamp_files = [f for f in photos_dir.iterdir() if f.is_file() and f.suffix.lower() == ".tsr"]
        for ptf in photo_timestamp_files:
            attachments.timestamp_files.append(ptf.relative_to(archive_location).as_posix())
    # videos
    videos_dir = archive_location / "videos"
    if videos_dir.exists() and videos_dir.is_dir():
        video_hash_files = [f for f in videos_dir.iterdir() if f.is_file() and (f.suffix.lower() == ".txt" or f.suffix.lower() == ".json")]
        for vhf in video_hash_files:
            attachments.hash_files.append(vhf.relative_to(archive_location).as_posix())
        video_timestamp_files = [f for f in videos_dir.iterdir() if f.is_file() and f.suffix.lower() == ".tsr"]
        for vtf in video_timestamp_files:
            attachments.timestamp_files.append(vtf.relative_to(archive_location).as_posix())

    return attachments


if __name__ == "__main__":
    archive_path = input("Input path to archive: ")  # Replace with your actual HAR file
    archive_path = archive_path.strip().strip('"').strip("'")
    attachments = get_session_attachments(Path(archive_path))
    print(attachments.model_dump_json(indent=2))