"""
Reverse image search (Feature 01) — perceptual-hash query path.

Given an uploaded image (or a screenshot of a video), compute its pHash locally and brute-force the
Hamming distance against every stored hash in the media_hash table, returning the matching media in
the existing SearchResult shape so MediaSearchResults.tsx renders them unchanged.

Why a RAM cache: the popcount itself is the "tens of ms at 3M" the architecture doc cites — but
re-reading millions of hash rows from MySQL on every query is not. So the (media_id, phash) columns
are loaded once into two NumPy arrays resident in RAM (the DB stays the source of truth; the arrays
are a rebuildable cache, mirroring S3's philosophy for vectors). Call reload_hash_cache() after an
indexing run to pick up new hashes without restarting the server.

Video matching falls out for free: a video contributes many hash rows (one per kept frame), all
pointing at the same media_id, so a screenshot from any indexed moment matches that video.
"""

import io
import logging
import threading
from typing import Optional

import numpy as np
from PIL import Image

from browsing_platform.server.services.media import get_media_thumbnail_path
from browsing_platform.server.services.search import (
    SearchResult, SearchResultTransform, Thumbnail, apply_search_results_transform,
)
from db_loaders.phash_generator import _phash_int, _dhash_int  # identical hashes used at index time
from extractors.entity_types import reconstruct_url
from utils import db

logger = logging.getLogger(__name__)

# Fixed, deliberately generous Hamming tolerance (out of 64 bits). pHash already survives resize,
# recompression and small overlaid labels; this loose cut keeps those matches even when degraded.
# It is NOT user-tunable: results are returned nearest-first, so a few weak matches trailing the list
# cost nothing, while a knob would only invite confusion. (Crops need region hashing or CLIP — out of
# scope here.) We compare against BOTH pHash and dHash and take the smaller distance, since the two
# capture different structure and a true match that drifts on one often stays close on the other.
DEFAULT_THRESHOLD = 18

_cache_lock = threading.Lock()
_media_ids: Optional[np.ndarray] = None   # int64, parallel to _phashes / _dhashes
_phashes: Optional[np.ndarray] = None     # uint64
_dhashes: Optional[np.ndarray] = None     # uint64


def _load_cache() -> None:
    """Load (media_id, phash, dhash) from media_hash into NumPy arrays. Caller holds _cache_lock."""
    global _media_ids, _phashes, _dhashes
    rows = db.execute_query("SELECT media_id, phash, dhash FROM media_hash", {}, return_type="rows") or []
    if not rows:
        _media_ids = np.empty(0, dtype=np.int64)
        _phashes = np.empty(0, dtype=np.uint64)
        _dhashes = np.empty(0, dtype=np.uint64)
        return
    _media_ids = np.fromiter((r["media_id"] for r in rows), dtype=np.int64, count=len(rows))
    # Hashes are stored as signed BIGINTs (two's-complement); reinterpret the bits as uint64.
    # A NULL dhash falls back to the row's phash so min(d_phash, d_dhash) simply ignores it.
    _phashes = np.fromiter((r["phash"] for r in rows), dtype=np.int64, count=len(rows)).view(np.uint64)
    _dhashes = np.fromiter(((r["dhash"] if r["dhash"] is not None else r["phash"]) for r in rows),
                           dtype=np.int64, count=len(rows)).view(np.uint64)


def reload_hash_cache() -> int:
    """Rebuild the in-RAM hash cache from the DB. Returns the number of hashes loaded."""
    with _cache_lock:
        _load_cache()
        count = len(_phashes)
    logger.info(f"Image-search hash cache loaded: {count} hashes")
    return count


def _ensure_cache() -> None:
    if _phashes is None:
        with _cache_lock:
            if _phashes is None:
                _load_cache()


def _build_results_for_ids(
    id_dist: list[tuple[int, int]],
    transform: SearchResultTransform,
) -> list[SearchResult]:
    """Fetch media rows for the matched ids and build SearchResults (media-arm shape, no parts),
    carrying the matched Hamming distance in metadata. id_dist is pre-sorted best-first."""
    if not id_dist:
        return []
    dist_by_id = {mid: d for mid, d in id_dist}
    params = {f"id{i}": mid for i, (mid, _) in enumerate(id_dist)}
    placeholders = ", ".join(f"%(id{i})s" for i in range(len(id_dist)))
    rows = db.execute_query(
        f"""SELECT m.id, m.thumbnail_path, m.local_url, m.aspect_ratio, m.media_type,
                   m.publication_date,
                   a.display_name AS account_display_name, a.url_suffix AS account_url_suffix,
                   a.platform AS account_platform
            FROM media m
            LEFT JOIN account a ON m.account_id = a.id
            WHERE m.id IN ({placeholders})""",
        params, return_type="rows",
    ) or []

    results = []
    for row in rows:
        account_url = reconstruct_url(row["account_url_suffix"], row["account_platform"])
        metadata = {
            "publication_date": row["publication_date"].isoformat() if row["publication_date"] else None,
            "account_display_name": row["account_display_name"],
            "account_url": account_url,
            "media_type": row["media_type"],
            "match_distance": dist_by_id.get(row["id"]),
        }
        thumbnails = [Thumbnail(src=src, aspect_ratio=row.get("aspect_ratio")) for src in [
            get_media_thumbnail_path(row["thumbnail_path"], row["local_url"]),
            row["local_url"],
        ] if src]
        results.append(SearchResult(
            page="media",
            id=row["id"],
            title=account_url or "",
            details="",
            thumbnails=thumbnails,
            metadata=metadata,
        ))
    # IN (...) returns rows unordered; restore best-first (smallest Hamming distance) order.
    results.sort(key=lambda r: (r.metadata["match_distance"], r.id))
    return apply_search_results_transform(results, transform)


def search_by_image_bytes(
    file_bytes: bytes,
    page_number: int,
    page_size: int,
    transform: SearchResultTransform,
    threshold: int = DEFAULT_THRESHOLD,
) -> list[SearchResult]:
    """Decode the uploaded image, hash it, and return media within `threshold` Hamming bits (of the
    closer of its pHash/dHash), nearest first, paginated. Per media we keep its single best
    (smallest-distance) frame match."""
    _ensure_cache()
    if _phashes is None or len(_phashes) == 0:
        return []
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img.load()
            q_phash = np.uint64(_phash_int(img))
            q_dhash = np.uint64(_dhash_int(img))
    except Exception as e:
        raise ValueError(f"Could not decode uploaded image: {e}")

    # Distance to the closer of the two hashes — pHash and dHash capture different structure, so a
    # degraded match that drifts on one often stays near on the other.
    dist = np.minimum(np.bitwise_count(_phashes ^ q_phash),
                      np.bitwise_count(_dhashes ^ q_dhash))   # uint8 per row, 0..64
    mask = dist <= np.uint8(max(0, threshold))
    cand_ids = _media_ids[mask].tolist()
    cand_dist = dist[mask].tolist()

    best: dict[int, int] = {}
    for mid, d in zip(cand_ids, cand_dist):
        d = int(d)
        if mid not in best or d < best[mid]:
            best[mid] = d
    ordered = sorted(best.items(), key=lambda kv: (kv[1], kv[0]))

    start = max(0, (page_number - 1) * page_size)
    page = ordered[start:start + page_size]
    return _build_results_for_ids(page, transform)
