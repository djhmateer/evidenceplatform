-- V040 — align media_type with the actual downloaded file (local_url)
--
-- Root cause: when an archive session was reprocessed after the DASH-only video detection
-- fix, the db_intake reprocessing path synthesised the canonical from a stale pre-loop
-- snapshot of media_archive instead of the freshly merged record (fixed in db_intake.py).
-- The symptom left in the data: media rows that are actually videos kept media_type='image'.
--
-- Why discriminate on local_url, not url_suffix:
-- The browsing platform renders an <img>/<video> tag chosen by media_type and sets its src
-- to local_url. The only gap that actually breaks rendering is media_type disagreeing with
-- the file local_url points at (e.g. <video src="...jpg"> or <img src="...mp4">). url_suffix
-- is the matching/identity key and is never rendered, so trusting it could even *introduce*
-- a gap (promote media_type to 'video' while local_url still points at the .jpg). local_url
-- is the authoritative, render-relevant signal, so we key off it and never rewrite it here.
--
-- Reliability: muxed/saved video files always end in '.mp4' (the extension is appended after
-- the filename is truncated, so it cannot be lost) — the image -> video promotion is exact.
-- Saved photo filenames usually keep their extension but can be truncated for very long CDN
-- names; the video -> image demotion is therefore best-effort and defensive (a genuine image
-- with an unrecognised local_url is simply left untouched — never falsely demoted).
--
-- Both `media` (canonical, rendered) and `media_archive` (per-session staging) are corrected:
-- leaving media_archive stale would let a future reprocessing run re-synthesise the canonical
-- back to the wrong media_type. thumbnail_status/thumbnail_path are reset on canonical rows
-- whose type changes so the thumbnail pipeline regenerates a correct frame.
--
-- Instagram video formats: mp4, mov, m4v, mkv, webm, avi
-- Instagram photo formats: jpg, jpeg, png, webp, heic, heif

-- 1. Promote image -> video where the downloaded file is a video container
UPDATE media
SET media_type       = 'video',
    thumbnail_status = 'pending',
    thumbnail_path   = NULL
WHERE media_type = 'image'
  AND local_url IS NOT NULL
  AND LOWER(local_url) REGEXP '\\.(mp4|mov|m4v|mkv|webm|avi)$';

UPDATE media_archive
SET media_type = 'video'
WHERE media_type = 'image'
  AND local_url IS NOT NULL
  AND LOWER(local_url) REGEXP '\\.(mp4|mov|m4v|mkv|webm|avi)$';

-- 2. Demote video -> image where the downloaded file is a still image (defensive)
UPDATE media
SET media_type       = 'image',
    thumbnail_status = 'pending',
    thumbnail_path   = NULL
WHERE media_type = 'video'
  AND local_url IS NOT NULL
  AND LOWER(local_url) REGEXP '\\.(jpg|jpeg|png|webp|heic|heif)$';

UPDATE media_archive
SET media_type = 'image'
WHERE media_type = 'video'
  AND local_url IS NOT NULL
  AND LOWER(local_url) REGEXP '\\.(jpg|jpeg|png|webp|heic|heif)$';
