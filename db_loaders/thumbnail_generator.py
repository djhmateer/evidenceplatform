import asyncio
import logging
import os
from hashlib import md5
from pathlib import Path

import cv2
from PIL import Image

from db_loaders.db_intake import ROOT_ARCHIVES, LOCAL_ARCHIVES_DIR_ALIAS
from extractors.entity_types import Media
from root_anchor import ROOT_DIR
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


async def generate_missing_thumbnails(thumbnail_size=(128, 128)):
    while True:
        media = db.execute_query(
            """SELECT *
               FROM media
               WHERE thumbnail_path IS NULL
                 AND local_url IS NOT NULL
                 AND (media_type = 'image' OR media_type = 'video')
               LIMIT 1""",
            {}, return_type="single_row"
        )
        if media is None:
            break
        media = Media(**media)
        local_path = ROOT_ARCHIVES / media.local_url.split(f'{LOCAL_ARCHIVES_DIR_ALIAS}/')[1]
        # Generate thumbnail and store it under ROOT_THUMBNAILS/{md5_hash}_{thumbnail_size}.jpg

        try:
            logger.info(f"Generating thumbnail for media ID {media.id} at {local_path}")
            if media.media_type == 'image':
                img = Image.open(local_path)
            elif media.media_type == 'video':
                img = await asyncio.wait_for(asyncio.to_thread(_read_video_frame, str(local_path)), timeout=10)
            else:
                raise Exception("Unsupported media type for thumbnail generation")
            img.thumbnail(thumbnail_size)
            hash_input = f"{media.id_on_platform}_{thumbnail_size[0]}x{thumbnail_size[1]}".encode('utf-8')
            thumbnail_filename = f"{md5(hash_input).hexdigest()}.jpg"
            thumbnail_path = ROOT_THUMBNAILS / thumbnail_filename
            os.makedirs(ROOT_THUMBNAILS, exist_ok=True)
            img.save(thumbnail_path, "JPEG")
        except Exception as e:
            logger.error(f"Error generating thumbnail for media ID {media.id} (type={media.media_type}, path={local_path}): {e}")
            db.execute_query(f'''
                        UPDATE media
                        SET thumbnail_path = %(thumbnail_path)s
                        WHERE id = %(id)s
                    ''', {
                "thumbnail_path": f"error: {str(e)}",
                "id": media.id
            }, "none")
            continue
        # Update database with thumbnail path
        relative_thumbnail_path = f"{LOCAL_THUMBNAILS_DIR_ALIAS}/{thumbnail_filename}"
        db.execute_query(f'''
            UPDATE media
            SET thumbnail_path = %(thumbnail_path)s
            WHERE id = %(id)s
        ''', {
            "thumbnail_path": relative_thumbnail_path,
            "id": media.id
        }, "none")


if __name__ == "__main__":
    asyncio.run(generate_missing_thumbnails())