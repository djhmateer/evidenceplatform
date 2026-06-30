-- V043 — Give media_part its own thumbnails so parts can render as first-class,
-- media-like search results.
--
-- A MediaPart is a crop box (+ optional video time range) over a parent media
-- asset. Until now it had no preview image of its own; the search grid and the
-- focus modal had to fall back to the parent media's thumbnail, ignoring the
-- crop and (for video) the start frame. These columns mirror the same pair on
-- `media` (see create_db.sql) and are populated by
-- db_loaders/thumbnail_generator.generate_media_part_thumbnail, which seeks to
-- timestamp_range_start and crops to crop_area before resizing.

ALTER TABLE media_part
    ADD COLUMN thumbnail_path   varchar(200) NULL,
    ADD COLUMN thumbnail_status enum ('pending', 'generated', 'not_needed', 'error') DEFAULT 'pending' NOT NULL;

CREATE INDEX media_part_thumbnail_status_index ON media_part (thumbnail_status);
