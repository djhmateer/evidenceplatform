-- V039 — fix media_type based on file extension in url_suffix
--
-- Rows inserted before the multi-signal video detection fix may have
-- media_type='image' for DASH-only video carousel items (video_versions null,
-- only video_dash_manifest present). The file extension in url_suffix is the
-- authoritative fallback: it is derived from the CDN filename and cannot be
-- misclassified by HAR response ordering.
--
-- Both `media` (canonical) and `media_archive` (per-session staging) are corrected.
-- thumbnail_status is reset to 'pending' for canonical rows whose type changes
-- (either direction) so the thumbnail pipeline regenerates a correct frame.
--
-- Instagram video formats: mp4, mov, m4v, mkv, webm, avi
-- Instagram photo formats: jpg, jpeg, png, webp, heic, heif

-- 1. Promote image → video where url_suffix ends with a known video extension
UPDATE media
SET media_type       = 'video',
    thumbnail_status = 'pending'
WHERE media_type = 'image'
  AND LOWER(url_suffix) REGEXP '\\.(mp4|mov|m4v|mkv|webm|avi)$';

UPDATE media_archive
SET media_type = 'video'
WHERE media_type = 'image'
  AND LOWER(url_suffix) REGEXP '\\.(mp4|mov|m4v|mkv|webm|avi)$';

-- 2. Demote video → image where url_suffix ends with a known photo extension
--    (defensive: guards against any inverse misclassification)
UPDATE media
SET media_type       = 'image',
    thumbnail_status = 'pending'
WHERE media_type = 'video'
  AND LOWER(url_suffix) REGEXP '\\.(jpg|jpeg|png|webp|heic|heif)$';

UPDATE media_archive
SET media_type = 'image'
WHERE media_type = 'video'
  AND LOWER(url_suffix) REGEXP '\\.(jpg|jpeg|png|webp|heic|heif)$';
