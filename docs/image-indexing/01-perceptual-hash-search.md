# Feature 1 — Exact / Near-Duplicate Reverse Image Search

> See `00-architecture.md` for the shared pipeline (S1), model runtime (S2), vector storage (S3),
> and request flow (S4) referenced below.

**Verdict: trivially plausible. Zero ML, zero lock-in, CPU-only end-to-end. Build first.**

## Goal

Given an uploaded photo, find the `media` row(s) it matches — robust to resize, recompression,
mild color shifts, and small overlaid labels. Distance 0 ⇒ same image after recompression;
small Hamming distance ⇒ near-duplicate.

## Technique

Perceptual hashing via the **`imagehash`** library (pure Python on Pillow, already a dependency):

- **pHash** (DCT-based, 64-bit) — primary; robust to the modifications above.
- **dHash** (gradient, 64-bit) — secondary, cheap tie-breaker / cross-check.

No neural model, no GPU, no external service — so there is nothing to deprecate.

## Storage

Add two indexed columns to `media` (or a small `media_hash` side table), as 64-bit integers:

```
phash BIGINT NULL,
dhash BIGINT NULL,
phash_status ENUM('pending','generated','not_needed','error') NOT NULL DEFAULT 'pending'
```

New migration in `infra/migrations/` (next `V0NN`). For **video**, hash the existing thumbnail
frame (`media.thumbnail_path`) per S1.

## Indexing pass (S1)

`generate_missing_hashes()` mirroring `generate_missing_thumbnails()`: select `phash_status =
'pending'`, open the image (or thumbnail frame), compute pHash + dHash, store as ints, mark
`generated`. Wire as pipeline stage **E-PHASH** in `db_loaders/archives_db_loader.py`. Runs locally
on CPU at full scale — no cloud step needed even for the 400K bulk pass.

## Search

Compute the query image's pHash, then **brute-force Hamming distance** (`XOR` + popcount over the
column, vectorized in NumPy):

- threshold `== 0`: exact match after recompression,
- threshold `≤ ~10/64`: near-duplicate.

Even at 3M rows this is tens of milliseconds — **no ANN index required**. If latency ever matters,
add a BK-tree or multi-index hashing; not needed initially.

## API + UI (S4)

New endpoint accepts an uploaded image, computes pHash locally, runs the Hamming scan, returns
results in the existing `SearchResult` shape → rendered by `MediaSearchResults.tsx`. Add the
upload/paste affordance to `SearchPanel.tsx`.

## Bonus

Instantly enables **cross-archive deduplication** and "is this exact image already in the archive?"
provenance checks across the whole corpus.

## Effort

~1 migration + one `generate_missing_hashes()` worker + one search endpoint + an upload box.
Smallest of the four; validates the indexing-stage and image-upload-search patterns for the rest.

## Verification

Per the shared checklist in `00-architecture.md`: upload an exact copy (expect distance 0), a
recompressed/relabeled/resized variant (expect near-dup within threshold), and an unrelated image
(expect no match). Confirm the indexing stage is resumable via `phash_status` gating.
