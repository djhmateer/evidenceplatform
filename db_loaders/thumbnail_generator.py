"""
Thumbnail Generator - Evidence Platform
========================================

PURPOSE:
    Generates preview thumbnails for media items (images and videos) stored in the database.
    This is Part D of the archive loading pipeline in archives_db_loader.py.

HOW IT WORKS:
    1. Queries the database for media records where thumbnail_path IS NULL
    2. For each media item:
       - Images: Opens with PIL and resizes
       - Videos: Extracts first frame using OpenCV, falls back to later frames if needed
    3. Saves thumbnail as JPEG in thumbnails/ directory
    4. Updates the media record with the thumbnail path

THUMBNAIL NAMING:
    Thumbnails are named using MD5 hash: {md5(id_on_platform + size)}.jpg
    This provides deduplication - same media won't generate duplicate thumbnails.

STORAGE:
    - Thumbnails are stored in: {ROOT_DIR}/thumbnails/
    - Database stores relative path: local_thumbnails/{filename}.jpg
    - Default size: 128x128 pixels

ERROR HANDLING:
    - Failed thumbnails store "error: {message}" in thumbnail_path field
    - This prevents infinite retry loops on broken media
    - To retry failed thumbnails, clear the error:
      UPDATE media SET thumbnail_path = NULL WHERE thumbnail_path LIKE 'error:%';

VIDEO FRAME EXTRACTION:
    - Uses OpenCV (cv2) to read video files
    - Validates file size and metadata to detect truncated/corrupt files
    - Tries frames 0, 1, 10, 30 if earlier frames fail
    - 10 second timeout per video to prevent hangs

USAGE:
    Usually called as Part D of the full pipeline:
        uv run db_loaders/archives_db_loader.py full

    Can also be run standalone:
        python -c "import asyncio; from db_loaders.thumbnail_generator import generate_missing_thumbnails; asyncio.run(generate_missing_thumbnails())"

    With limit (process only N thumbnails):
        asyncio.run(generate_missing_thumbnails(limit=10))

DEPENDENCIES:
    - PIL/Pillow for image processing
    - OpenCV (cv2) for video frame extraction
    - MySQL database with media table
"""

import asyncio
import logging
import os
from hashlib import md5
from pathlib import Path
from typing import Callable, Optional

import cv2
from PIL import Image

from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS
from extractors.entity_types import Media
from root_anchor import ROOT_DIR, ROOT_ARCHIVES
from utils import db

logger = logging.getLogger(__name__)

ROOT_THUMBNAILS = Path(ROOT_DIR) / "thumbnails"
LOCAL_THUMBNAILS_DIR_ALIAS = 'local_thumbnails'


def _read_video_frame(path: str) -> Image.Image:
    """Extract the first frame from a video file for use as a thumbnail."""
    import os

    # Check file exists and get size
    if not os.path.exists(path):
        raise Exception(f"Video file does not exist: {path}")

    file_size = os.path.getsize(path)
    logger.debug(f"Opening video: {path} (size: {file_size / 1024:.1f} KB)")

    # Quick sanity check - a valid video should be at least a few KB
    if file_size < 5000:  # Less than 5KB
        raise Exception(
            f"Video file too small ({file_size / 1024:.1f} KB) - "
            f"file is likely truncated or incomplete"
        )

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise Exception(f"Could not open video - file may be corrupted or in unsupported format (size: {file_size / 1024:.1f} KB)")

        # Get video properties for diagnostics
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)]) if fourcc else "unknown"
        backend = cap.getBackendName()

        logger.debug(
            f"Video properties: {frame_count} frames, {width}x{height} @ {fps:.1f}fps, "
            f"codec={codec}, backend={backend}, size={file_size / 1024:.1f} KB"
        )

        # Detect truncated files: metadata looks valid but file is too small
        # A rough estimate: even highly compressed video needs ~100 bytes per frame minimum
        if frame_count > 0 and width > 0 and height > 0:
            # Estimate minimum reasonable size: at least 50 bytes per frame for compressed video
            min_expected_size = frame_count * 50
            if file_size < min_expected_size:
                raise Exception(
                    f"Video file appears truncated - "
                    f"metadata reports {frame_count} frames ({width}x{height} @ {fps:.1f}fps) "
                    f"but file is only {file_size / 1024:.1f} KB "
                    f"(expected at least {min_expected_size / 1024:.1f} KB)"
                )

            # Also detect absurd fps which indicates corrupt metadata
            if fps > 1000:
                raise Exception(
                    f"Video has invalid metadata - "
                    f"fps={fps:.1f} is unrealistic, file is likely corrupted or truncated "
                    f"(size: {file_size / 1024:.1f} KB)"
                )

        # Try to seek to first frame explicitly
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        success, frame = cap.read()
        if not success:
            # Try a few more frames in case first frame is corrupt
            for try_frame in [1, 10, 30]:
                if try_frame < frame_count:
                    logger.debug(f"First frame failed, trying frame {try_frame}")
                    cap.set(cv2.CAP_PROP_POS_FRAMES, try_frame)
                    success, frame = cap.read()
                    if success:
                        logger.debug(f"Successfully read frame {try_frame}")
                        break

        if not success:
            raise Exception(
                f"Could not read any video frame - "
                f"video reports {frame_count} frames, {width}x{height} @ {fps:.1f}fps, "
                f"codec={codec}, backend={backend}, file_size={file_size / 1024:.1f} KB. "
                f"Codec may not be supported by OpenCV"
            )

        logger.debug(f"Successfully extracted frame: shape={frame.shape}")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        cap.release()


BATCH_SIZE = 1000
MAX_CONCURRENT = 8


def load_image_and_thumbnail(path: str, size: tuple) -> Image.Image:
    """Open an image file and resize it in-place. Runs in a thread."""
    img = Image.open(path)
    img.thumbnail(size)
    return img


def save_image(img: Image.Image, out_path: Path) -> None:
    """Save a PIL image to disk. Runs in a thread."""
    os.makedirs(out_path.parent, exist_ok=True)
    img.save(out_path, "JPEG")


async def process_one_media(
    media_row: dict,
    thumbnail_size: tuple,
    semaphore: asyncio.Semaphore,
    emit: Optional[Callable[[str], None]],
) -> bool:
    """Generate and persist a thumbnail for one media item. Returns True on success."""
    async with semaphore:
        media = Media(**media_row)
        local_path = ROOT_ARCHIVES / media.local_url.split(f'{LOCAL_ARCHIVES_DIR_ALIAS}/')[1]
        try:
            logger.info(f"Generating thumbnail for media ID {media.id} at {local_path}")
            if media.media_type == 'image':
                img = await asyncio.to_thread(load_image_and_thumbnail, str(local_path), thumbnail_size)
            elif media.media_type == 'video':
                # TODO: asyncio.wait_for cancels the asyncio task on timeout but cannot stop the
                # underlying thread — the cv2.VideoCapture call keeps running, slowly consuming
                # ThreadPoolExecutor slots. Fix by replacing _read_video_frame with an
                # asyncio.create_subprocess_exec call to ffmpeg, which can be killed on timeout.
                img = await asyncio.wait_for(asyncio.to_thread(_read_video_frame, str(local_path)), timeout=10)
                img.thumbnail(thumbnail_size)
            else:
                raise Exception("Unsupported media type for thumbnail generation")

            hash_input = f"{media.id_on_platform}_{thumbnail_size[0]}x{thumbnail_size[1]}".encode('utf-8')
            thumbnail_filename = f"{md5(hash_input).hexdigest()}.jpg"
            out_path = ROOT_THUMBNAILS / thumbnail_filename
            await asyncio.to_thread(save_image, img, out_path)
        except Exception as e:
            logger.error(f"Error generating thumbnail for media ID {media.id} (type={media.media_type}, path={local_path}): {e}")
            if emit:
                emit(f"Part D — error generating thumbnail for media {media.id}: {e}")
            try:
                error_msg = f"error: {str(e)}"[:200]
                db.execute_query(
                    "UPDATE media SET thumbnail_path = %(p)s, thumbnail_status = 'error' WHERE id = %(id)s",
                    {"p": error_msg, "id": media.id}, "none"
                )
            except Exception as db_err:
                logger.error(f"Failed to persist error status for media {media.id}: {db_err}")
            return False

        aspect_ratio = img.width / img.height if img.height > 0 else None
        relative_path = f"{LOCAL_THUMBNAILS_DIR_ALIAS}/{thumbnail_filename}"
        db.execute_query(
            "UPDATE media SET thumbnail_path = %(p)s, thumbnail_status = 'generated', aspect_ratio = %(ar)s WHERE id = %(id)s",
            {"p": relative_path, "ar": aspect_ratio, "id": media.id}, "none"
        )
        if emit:
            emit(f"Part D — generated thumbnail for media {media.id}")
        return True


async def generate_missing_thumbnails(thumbnail_size=(128, 128), limit: int | None = None, cancel_check=None, emit: Optional[Callable[[str], None]] = None):
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    generated_count = 0
    while True:
        if cancel_check and cancel_check():
            raise InterruptedError("Cancelled by user")

        fetch_count = BATCH_SIZE if limit is None else min(BATCH_SIZE, limit - generated_count)
        if fetch_count <= 0:
            break

        rows = db.execute_query(
            f"SELECT * FROM media WHERE thumbnail_status = 'pending' LIMIT {fetch_count}",
            {}, return_type="rows"
        ) or []
        if not rows:
            break

        results = await asyncio.gather(
            *[process_one_media(row, thumbnail_size, semaphore, emit) for row in rows],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Unhandled exception in process_one_media: {r}")
        generated_count += sum(1 for r in results if r is True)

        if len(rows) < fetch_count:
            # Received fewer rows than requested — no more pending items remain
            break

    if generated_count:
        logger.info(f"Part D - Generated {generated_count} thumbnails")


if __name__ == "__main__":
    asyncio.run(generate_missing_thumbnails())