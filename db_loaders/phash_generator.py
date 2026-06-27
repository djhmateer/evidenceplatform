"""
Perceptual-Hash Generator - Evidence Platform
==============================================

PURPOSE:
    Computes perceptual hashes (pHash + dHash, 64-bit each) for every media item so the browsing
    platform can do exact / near-duplicate *reverse image search*: upload a photo (or a screenshot
    of a video) and find the media row(s) it matches. This is Part E of the archive loading
    pipeline in archives_db_loader.py — it runs after D-THUMBNAILS.

HOW IT WORKS:
    1. Selects media rows where phash_status = 'pending' (status-gated, so it is resumable and
       incremental — mirrors thumbnail_generator.py).
    2. For each media item:
       - image  → one hash row (the whole image).
       - video  → MANY hash rows, one per *kept representative frame* (see VIDEO INDEXING below),
                  so the video is findable from a screenshot of ANY moment, not just the first
                  frame.
       - audio  → marked 'not_needed' (nothing visual to hash).
    3. Writes the hashes into the media_hash side table (one media → many rows) and flips
       media.phash_status to 'generated' (or 'error').

VIDEO INDEXING (lightweight, no shot-detection ML):
    A video is decoded ONCE by ffmpeg at a fixed cadence (≈1 frame/sec, bounded to
    [MIN_FRAMES, MAX_FRAMES] across the clip's duration). We then *collapse* near-identical
    consecutive frames: a sampled frame is kept only if its pHash differs from the last kept
    frame by more than COLLAPSE_HAMMING bits. Static clips collapse to a handful of hashes;
    dynamic clips keep more — a free "poor-man's shot detector" that reuses the pHash we already
    compute. No per-frame DB hashing of the whole video, no optical flow, no histogram cuts.

STORAGE (see migration V045):
    media.phash_status  enum('pending','generated','not_needed','error')
    media_hash(media_id, frame_time, phash BIGINT, dhash BIGINT)
    64-bit hashes are stored signed (two's-complement) so they fit MySQL's signed BIGINT; read
    them back as uint64 for Hamming popcount (see _to_signed64 / image_search.py).

PROFILING:
    generate_missing_hashes() returns a PhashStats object recording per-item timing (decode vs.
    hash ms, frames decoded vs. kept) and logs an aggregate summary. project_runtime() extrapolates
    a dev-DB sample to an arbitrary production corpus size, and dump_profile() writes the raw
    per-item timings to logs/ as JSON for offline analysis. This answers "how long would indexing
    take over the full production DB?" from a small local run.

USAGE:
    As Part E of the full pipeline:           uv run db_loaders/archives_db_loader.py full
    Standalone (status-gated, resumable):     uv run db_loaders/archives_db_loader.py phash
    Profiling / extrapolation:
        uv run db_loaders/archives_db_loader.py phash --limit 500 \
            --project-images 1500000 --project-videos 1500000
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Callable, Optional

import imagehash
from PIL import Image

from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS
from extractors.entity_types import Media
from root_anchor import ROOT_DIR, ROOT_ARCHIVES
from utils import db

logger = logging.getLogger(__name__)

# --- Batch / concurrency (mirrors thumbnail_generator) ---
BATCH_SIZE = 1000
MAX_CONCURRENT = 8

# --- Video frame sampling (tunable) ---
# Denser sampling is nearly free: ffmpeg decodes the whole clip regardless of the output frame rate,
# so a higher rate only adds cheap pHash computes + a few rows, not decode time. We sample ~2/sec and
# let the near-duplicate collapse below discard redundant frames — static clips collapse to a few
# hashes, high-motion clips keep more (bounded by MAX_FRAMES), which is what lifts screenshot recall.
DESIRED_INTERVAL_SEC = 0.5   # target ~2 sampled frames per second of video
MIN_FRAMES = 3               # always sample at least this many frames (short clips)
MAX_FRAMES = 60              # never store more than this many hashes per video (also a runaway guard)
COLLAPSE_HAMMING = 4         # drop a sampled frame within this Hamming distance of the last kept one
FRAME_SCALE = 64             # ffmpeg downscales frames to NxN before hashing (verified bit-identical
                             # to hashing full-res: imagehash resizes to 32x32 internally either way)
VIDEO_TIMEOUT_SEC = 120      # hard wall-clock cap on a single ffmpeg decode (subprocess is killable)


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def _to_signed64(v: Optional[int]) -> Optional[int]:
    """Map an unsigned 64-bit hash into MySQL signed BIGINT range (two's-complement)."""
    if v is None:
        return None
    return v - (1 << 64) if v >= (1 << 63) else v


def _phash_int(img: Image.Image) -> int:
    """imagehash.phash (8x8 DCT → 64 bits) as an unsigned int."""
    return int(str(imagehash.phash(img)), 16)


def _dhash_int(img: Image.Image) -> int:
    return int(str(imagehash.dhash(img)), 16)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------------------
# Image / video hashing (CPU work — run inside asyncio.to_thread)
# ---------------------------------------------------------------------------

def _hash_image_file(path: str) -> tuple[int, int]:
    """Open an image file and compute (phash, dhash). Runs in a thread."""
    with Image.open(path) as img:
        img.load()
        return _phash_int(img), _dhash_int(img)


def _probe_duration(path: str) -> Optional[float]:
    """Video duration in seconds via ffprobe (None if it can't be determined). Runs in a thread."""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _sample_interval(duration: Optional[float]) -> float:
    """Seconds between sampled frames, chosen so the clip yields [MIN_FRAMES, MAX_FRAMES] frames."""
    if not duration or duration <= 0:
        return DESIRED_INTERVAL_SEC  # unknown duration → fall back to 1 frame/sec (capped by -frames:v)
    n = round(duration / DESIRED_INTERVAL_SEC)
    n = max(MIN_FRAMES, min(MAX_FRAMES, n))
    return duration / n


async def _extract_frames(path: str, interval: float, out_dir: str) -> None:
    """Single ffmpeg decode pass: emit downscaled JPEG frames at 1/interval fps into out_dir.
    Killable on timeout (unlike the cv2 thread the thumbnail generator uses)."""
    proc = await asyncio.create_subprocess_exec(
        'ffmpeg', '-y', '-nostdin', '-i', path,
        '-vf', f'fps=1/{interval},scale={FRAME_SCALE}:{FRAME_SCALE}',
        '-frames:v', str(MAX_FRAMES),  # belt-and-suspenders cap on output frames
        '-f', 'image2', os.path.join(out_dir, 'f_%05d.jpg'),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=VIDEO_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise Exception(f"ffmpeg frame extraction timed out after {VIDEO_TIMEOUT_SEC}s")
    if proc.returncode != 0:
        raise Exception(f"ffmpeg frame extraction failed (exit {proc.returncode})")


def _collapse_frames(out_dir: str, interval: float) -> tuple[list[tuple[float, int, int]], int]:
    """Hash sampled frames in order, keeping only those that differ from the last kept frame by
    more than COLLAPSE_HAMMING bits. Returns (kept=[(frame_time, phash, dhash)], frames_decoded).
    Runs in a thread."""
    frame_paths = sorted(Path(out_dir).glob("f_*.jpg"))
    kept: list[tuple[float, int, int]] = []
    last_kept_phash: Optional[int] = None
    decoded = 0
    for idx, fp in enumerate(frame_paths):
        with Image.open(fp) as img:
            img.load()
            ph = _phash_int(img)
            decoded += 1
            if last_kept_phash is None or _hamming(ph, last_kept_phash) > COLLAPSE_HAMMING:
                dh = _dhash_int(img)
                kept.append((round(idx * interval, 3), ph, dh))
                last_kept_phash = ph
    return kept, decoded


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------

@dataclass
class MediaTiming:
    media_id: int
    media_type: str
    status: str                     # 'generated' | 'not_needed' | 'error'
    duration: Optional[float] = None
    frames_decoded: int = 0
    frames_kept: int = 0
    decode_ms: float = 0.0          # video: ffprobe + ffmpeg decode
    hash_ms: float = 0.0            # pHash/dHash compute (+ collapse)
    total_ms: float = 0.0


@dataclass
class PhashStats:
    items: list[MediaTiming] = field(default_factory=list)
    wall_clock_s: float = 0.0

    def add(self, t: MediaTiming) -> None:
        self.items.append(t)

    def _generated(self, media_type: str) -> list[MediaTiming]:
        return [t for t in self.items if t.media_type == media_type and t.status == 'generated']

    def summary(self) -> dict:
        imgs = self._generated('image')
        vids = self._generated('video')
        by_status: dict[str, int] = {}
        for t in self.items:
            by_status[t.status] = by_status.get(t.status, 0) + 1

        def _avg(xs: list[float]) -> float:
            return sum(xs) / len(xs) if xs else 0.0

        avg_img_ms = _avg([t.total_ms for t in imgs])
        avg_vid_ms = _avg([t.total_ms for t in vids])
        vid_decoded = sum(t.frames_decoded for t in vids)
        vid_proc_ms = sum(t.decode_ms + t.hash_ms for t in vids)
        return {
            "total_media": len(self.items),
            "by_status": by_status,
            "wall_clock_s": round(self.wall_clock_s, 2),
            "max_concurrent": MAX_CONCURRENT,
            "images_generated": len(imgs),
            "videos_generated": len(vids),
            "avg_image_ms": round(avg_img_ms, 1),
            "images_per_sec_serial": round(1000.0 / avg_img_ms, 1) if avg_img_ms else None,
            "avg_video_ms": round(avg_vid_ms, 1),
            "avg_frames_decoded_per_video": round(_avg([t.frames_decoded for t in vids]), 1),
            "avg_frames_kept_per_video": round(_avg([t.frames_kept for t in vids]), 1),
            "avg_ms_per_decoded_frame": round(vid_proc_ms / vid_decoded, 2) if vid_decoded else None,
            "total_hashes_stored": sum(t.frames_kept for t in self.items),
        }


def _log_summary(stats: PhashStats, emit: Optional[Callable[[str], None]]) -> None:
    s = stats.summary()
    lines = [
        "Part E — perceptual-hash indexing summary:",
        f"  processed {s['total_media']} media in {s['wall_clock_s']}s "
        f"({MAX_CONCURRENT} workers); status={s['by_status']}",
        f"  images:  {s['images_generated']} @ {s['avg_image_ms']} ms/img avg "
        f"({s['images_per_sec_serial']} img/s per worker)",
        f"  videos:  {s['videos_generated']} @ {s['avg_video_ms']} ms/vid avg; "
        f"frames decoded~{s['avg_frames_decoded_per_video']}, kept~{s['avg_frames_kept_per_video']}, "
        f"{s['avg_ms_per_decoded_frame']} ms/decoded-frame",
        f"  hashes stored: {s['total_hashes_stored']}",
    ]
    msg = "\n".join(lines)
    logger.info(msg)
    if emit:
        emit(msg)


def project_runtime(stats: PhashStats, n_images: int, n_videos: int) -> dict:
    """Extrapolate the per-type averages measured on this run to a production corpus of
    n_images + n_videos media. Returns serial and N-worker wall-clock estimates."""
    s = stats.summary()
    avg_img_s = (s["avg_image_ms"] or 0.0) / 1000.0
    avg_vid_s = (s["avg_video_ms"] or 0.0) / 1000.0
    serial_s = n_images * avg_img_s + n_videos * avg_vid_s
    return {
        "projected_images": n_images,
        "projected_videos": n_videos,
        "basis_avg_image_ms": s["avg_image_ms"],
        "basis_avg_video_ms": s["avg_video_ms"],
        "est_serial_hours": round(serial_s / 3600.0, 2),
        "est_parallel_hours": round(serial_s / MAX_CONCURRENT / 3600.0, 2),
        "note": (
            "Parallel estimate assumes near-linear scaling across MAX_CONCURRENT workers. Hashing "
            "is CPU-bound, so a CPU box with >= MAX_CONCURRENT cores approaches this; a rented GPU "
            "box does NOT speed pHash up (no neural model). Scale workers to the box's core count."
        ),
    }


def dump_profile(stats: PhashStats, projection: Optional[dict] = None) -> Path:
    """Write per-item timings + aggregates to logs/phash_profile_<ts>.json for offline analysis."""
    logs_dir = Path(ROOT_DIR) / "logs"
    logs_dir.mkdir(exist_ok=True)
    out_path = logs_dir / f"phash_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "summary": stats.summary(),
        "projection": projection,
        "items": [asdict(t) for t in stats.items],
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Per-media worker
# ---------------------------------------------------------------------------

def _is_deadlock(e: Exception) -> bool:
    """MySQL deadlock / lock-wait-timeout — transient, safe to retry per the server's own advice."""
    return getattr(e, "errno", None) in (1213, 1205) or "1213" in str(e) or "Deadlock" in str(e)


# Concurrent workers do DELETE+INSERT on the media_hash.media_id index for adjacent media_ids
# (batches fetch sequential ids), whose gap / insert-intention locks form lock cycles → InnoDB
# deadlocks one transaction. Retrying is cheap: the hashes are already computed and passed in, so a
# retry re-runs only the fast DB writes, never the decode/hash work.
PERSIST_MAX_ATTEMPTS = 10


def _persist_hashes(media_id: int, hashes: list[tuple[Optional[float], int, int]]) -> None:
    """Replace this media's hash rows and mark it generated, in one transaction (idempotent).
    Retries on transient deadlock with desynchronising backoff."""
    for attempt in range(1, PERSIST_MAX_ATTEMPTS + 1):
        try:
            with db.transaction_batch():
                db.execute_query("DELETE FROM media_hash WHERE media_id = %(id)s",
                                 {"id": media_id}, "none")
                for frame_time, ph, dh in hashes:
                    db.execute_query(
                        "INSERT INTO media_hash (media_id, frame_time, phash, dhash) "
                        "VALUES (%(m)s, %(ft)s, %(ph)s, %(dh)s)",
                        {"m": media_id, "ft": frame_time, "ph": _to_signed64(ph), "dh": _to_signed64(dh)},
                        "none",
                    )
                db.execute_query("UPDATE media SET phash_status = 'generated' WHERE id = %(id)s",
                                 {"id": media_id}, "none")
            return
        except Exception as e:
            if _is_deadlock(e) and attempt < PERSIST_MAX_ATTEMPTS:
                # Back off, staggered per media_id so the contending workers don't re-collide.
                sleep(0.02 * attempt + (media_id % 13) * 0.002)
                continue
            raise


async def process_one_media(
    media_row: dict,
    semaphore: asyncio.Semaphore,
    emit: Optional[Callable[[str], None]],
    stats: PhashStats,
) -> bool:
    """Compute and persist perceptual hash(es) for one media item. Returns True on success."""
    async with semaphore:
        media = Media(**media_row)
        t0 = perf_counter()
        decode_ms = hash_ms = 0.0
        frames_decoded = frames_kept = 0
        duration: Optional[float] = None
        try:
            if media.media_type == 'audio':
                db.execute_query("UPDATE media SET phash_status = 'not_needed' WHERE id = %(id)s",
                                 {"id": media.id}, "none")
                stats.add(MediaTiming(media.id, 'audio', 'not_needed',
                                      total_ms=(perf_counter() - t0) * 1000))
                return True

            if not media.local_url:
                # No downloaded file to hash — distinct from a real failure, so don't mark 'error'.
                db.execute_query("UPDATE media SET phash_status = 'not_needed' WHERE id = %(id)s",
                                 {"id": media.id}, "none")
                stats.add(MediaTiming(media.id, media.media_type, 'not_needed',
                                      total_ms=(perf_counter() - t0) * 1000))
                return True
            local_path = ROOT_ARCHIVES / media.local_url.split(f'{LOCAL_ARCHIVES_DIR_ALIAS}/')[1]

            if media.media_type == 'image':
                th0 = perf_counter()
                ph, dh = await asyncio.to_thread(_hash_image_file, str(local_path))
                hash_ms = (perf_counter() - th0) * 1000
                hashes: list[tuple[Optional[float], int, int]] = [(None, ph, dh)]
                frames_decoded = frames_kept = 1

            elif media.media_type == 'video':
                td0 = perf_counter()
                duration = await asyncio.to_thread(_probe_duration, str(local_path))
                interval = _sample_interval(duration)
                tmp_dir = tempfile.mkdtemp(prefix="phash_")
                try:
                    await _extract_frames(str(local_path), interval, tmp_dir)
                    decode_ms = (perf_counter() - td0) * 1000
                    th0 = perf_counter()
                    kept, decoded = await asyncio.to_thread(_collapse_frames, tmp_dir, interval)
                    hash_ms = (perf_counter() - th0) * 1000
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                if not kept:
                    raise Exception("no frames could be extracted/hashed from video")
                hashes = kept
                frames_decoded = decoded
                frames_kept = len(kept)
            else:
                raise Exception(f"Unsupported media type for hashing: {media.media_type}")

            await asyncio.to_thread(_persist_hashes, media.id, hashes)
            stats.add(MediaTiming(media.id, media.media_type, 'generated', duration,
                                  frames_decoded, frames_kept, decode_ms, hash_ms,
                                  (perf_counter() - t0) * 1000))
            if emit:
                emit(f"Part E — hashed media {media.id} ({media.media_type}, {frames_kept} hash(es))")
            return True

        except Exception as e:
            logger.error(f"Error hashing media ID {media.id} (type={media.media_type}): {e}")
            if emit:
                emit(f"Part E — error hashing media {media.id}: {e}")
            try:
                db.execute_query("UPDATE media SET phash_status = 'error' WHERE id = %(id)s",
                                 {"id": media.id}, "none")
            except Exception as db_err:
                logger.error(f"Failed to persist error status for media {media.id}: {db_err}")
            stats.add(MediaTiming(media.id, media.media_type, 'error', duration,
                                  frames_decoded, frames_kept, decode_ms, hash_ms,
                                  (perf_counter() - t0) * 1000))
            return False


async def generate_missing_hashes(
    limit: int | None = None,
    cancel_check=None,
    emit: Optional[Callable[[str], None]] = None,
) -> PhashStats:
    """Status-gated, resumable pass that hashes all media with phash_status='pending'.
    Mirrors generate_missing_thumbnails(). Returns a PhashStats with timing for extrapolation."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    stats = PhashStats()
    wall0 = perf_counter()
    processed = 0
    while True:
        if cancel_check and cancel_check():
            raise InterruptedError("Cancelled by user")

        fetch_count = BATCH_SIZE if limit is None else min(BATCH_SIZE, limit - processed)
        if fetch_count <= 0:
            break

        rows = db.execute_query(
            f"SELECT * FROM media WHERE phash_status = 'pending' LIMIT {fetch_count}",
            {}, return_type="rows"
        ) or []
        if not rows:
            break

        results = await asyncio.gather(
            *[process_one_media(row, semaphore, emit, stats) for row in rows],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Unhandled exception in process_one_media: {r}")
        processed += len(rows)

        if len(rows) < fetch_count:
            break

    stats.wall_clock_s = perf_counter() - wall0
    if stats.items:
        _log_summary(stats, emit)
    return stats
