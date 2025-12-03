import asyncio
import os
from hashlib import md5
from pathlib import Path

import cv2
from PIL import Image

from db_loaders.db_intake import ROOT_ARCHIVES, LOCAL_ARCHIVES_DIR_ALIAS
from extractors.entity_types import Media
from root_anchor import ROOT_DIR
from utils import db

ROOT_THUMBNAILS = Path(ROOT_DIR) / "thumbnails"
LOCAL_THUMBNAILS_DIR_ALIAS = 'local_thumbnails'


def _read_video_frame(path: str) -> Image.Image:
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise Exception("Could not open video")
        success, frame = cap.read()
        if not success:
            raise Exception("Could not read video frame")
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
            print(f"Generating thumbnail for media ID {media.id} at {local_path}")
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
            print(f"Error generating thumbnail for media ID {media.id}: {e}")
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