# Image Indexing — Shared Architecture

Cross-cutting design shared by all four image-indexing features. Each feature doc
(`01`–`04`) references the sections (`S1`–`S4`) below rather than repeating them.

## Why these features are lock-in-proof

The platform already retains the **original media on disk**
(`archives/{archive_folder}/media/{images,videos}/…`, aliased by `media.local_url`). Every
indexing feature uses **open-weight models whose weights are stored as local files we own**.

Consequence: embeddings can **never be orphaned**. If a model is retired or we want a better one,
we re-run the (idempotent, resumable) indexing pass to rebuild them from the originals. The *only*
thing to avoid is a **cloud embedding API in the query path** — that is the single dependency whose
disappearance is unrecoverable. Renting GPUs to run *open weights* for the bulk first pass is fine:
that is compute, not a dependency.

## Scale assumptions

- ~400K media today; realistically heading to **1M–3M**.
- No local NVIDIA GPU. The **bulk first pass** may run on a **rented cloud GPU box**.
- **Incremental indexing of new media** and **all query-time embedding** must run **locally on
  CPU-only hardware**.

---

## S1 — Reuse the thumbnail-generator pattern for every indexing pass

`db_loaders/thumbnail_generator.py` is the template. Each `media` row carries a status enum
(`pending` / `generated` / `not_needed` / `error`); `generate_missing_thumbnails()` selects
`pending` rows, processes them under an `asyncio.Semaphore` with `cancel_check` + `emit` callbacks,
and writes status back. Each new feature adds:

- its own `*_status` column (or a status column on its side table),
- a `generate_missing_<feature>()` worker with the same batch / cancel / emit shape, and
- a new stage in `db_loaders/archives_db_loader.py` after **D-THUMBNAILS**
  (E-PHASH, F-EMBED, G-CAPTION, H-FACES).

Each stage is independently runnable, resumable, and incremental for free.

Media files resolve exactly as the thumbnail generator already does:
`ROOT_ARCHIVES / media.local_url.split('local_archive_har/')[1]`. For **video**, index the
already-extracted thumbnail frame (`media.thumbnail_path`) rather than re-decoding the video.

## S2 — ONNX Runtime as the single model abstraction (GPU-bulk, CPU-local)

Run **all** neural models through `onnxruntime`. The same `.onnx` weight file runs on the rented
box with `CUDAExecutionProvider` (bulk pass) and on the local server with `CPUExecutionProvider`
(incremental + query). This satisfies "bulk on cloud GPU, routine on local CPU" with **one** code
path and **no torch-on-the-server requirement**.

Weights are downloaded once and stored locally (managed like `utils/ffmpeg/` already is), and
pinned by a `model_version` string recorded alongside every vector/caption/face row.

## S3 — Vectors: DB is source of truth, ANN index is a rebuildable cache

At 1M–3M, brute-force cosine is too slow for interactive similarity search (brute-force stays fine
for *hashes* — see `01`). So:

- **Source of truth:** store each vector as a `float32` **BLOB** (+ `model_version`) in a
  per-feature table. We deliberately do **not** use MySQL's `VECTOR` type. It would require MySQL
  9.x (an *Innovation* release with a short support window), and even there the **Community** server
  only *stores* vectors — `DISTANCE()`, vector indexes, and ANN search are **HeatWave-only**. A plain
  `float32` BLOB is more portable (reads on any MySQL — including the 8.4 LTS line — or any other DB)
  and loses nothing here, because nearest-neighbor search runs in **FAISS** regardless. MySQL is just
  durable storage for the bytes.
- **Query index:** build an **HNSW** ANN index with **FAISS** (`IndexHNSWFlat`, wrapped in
  `IndexIDMap` so it returns `media_id`) from the BLOBs. Lifecycle: build once → `faiss.write_index`
  to disk → `faiss.read_index` at FastAPI startup → incremental `index.add(...)` for new media. The
  index is **resident in RAM at query time** — the disk file is a fast-reload snapshot, not off-disk
  search. 3M × 512-d `float32` ≈ 6 GB raw (~8–12 GB with HNSW graph links) — fits in server RAM;
  HNSW query is sub-10 ms on CPU. If the corpus ever outgrows RAM, FAISS Product Quantization
  (`IndexIVFPQ`, ~30–60× smaller) or memory-mapped IVF indexes extend the ceiling well before a
  dedicated vector database is warranted.
- Because the index is **derived** from the BLOBs, it can be rebuilt at any time (model swap,
  corruption, dimension change) — that rebuild is the **recovery/safety path**, not the routine
  startup cost (normal startup just loads the persisted snapshot). This is what makes the design
  lock-in-proof and operationally safe.

Normalize vectors (L2) at write time so cosine similarity == inner product.

## S4 — Image-search request flow (reuses existing search UI)

Add an "image search" mode to `browsing_platform/client/src/UIComponents/Search/SearchPanel.tsx`
(file upload / paste). A new backend endpoint accepts the uploaded image, computes the relevant
descriptor **locally on CPU** (pHash / CLIP image vector / face vector), runs Hamming or ANN
search, and returns results in the existing `SearchResult` shape so
`UIComponents/SearchResults/MediaSearchResults.tsx` renders them unchanged. Text→image and caption
search fold into the existing text search flow (`services/search.py`).

**Bulk-vs-local data movement:** the first pass over 400K media runs on the rented GPU box against
a copy of the media tree (extend `utils/data_transfers/`); it emits a vector/caption/face dump that
is imported into the local DB. Thereafter, new-media batches are small enough to index locally on
CPU (captioning and face detection are the only heavy ones — those batches can still be shipped out
periodically if desired).

---

## Build order

1. **`01` Perceptual hash** — smallest, immediate dedup/provenance value; validates the pipeline
   stage + image-upload search flow. **Buildable right now** on the current stack: no FAISS, no ONNX,
   no MySQL change — just an `imagehash` pass and a NumPy Hamming scan.
2. **`02` CLIP** — establishes the ONNX runtime (S2) and the ANN index lifecycle (S3) reused by `04`.
3. **`03` Captions** — reuses `02`'s text encoder and the existing fulltext search.
4. **`04` Faces** — reuses S2/S3; largest UI surface; gate behind the ethics/consent review.

## Verification (applies to every feature)

- **Correctness:** index a small known sample; run known-answer queries (exact copy → distance 0;
  recompressed/labeled variant → near-dup within threshold; text "beach" → beach images; known face
  → its other photos). Confirm results render via `MediaSearchResults.tsx`.
- **CPU-only query path:** disable the GPU provider and confirm every *query* endpoint returns
  correctly on `CPUExecutionProvider`.
- **Scale/latency:** load the ANN index with synthetic vectors at 1M and 3M; measure query latency
  and RAM; confirm HNSW stays sub-50 ms and fits memory.
- **Idempotency/resumability:** re-run each stage; confirm `*_status` gating skips done rows and a
  cancelled run resumes cleanly (mirrors the thumbnail generator).
- **Lock-in drill:** delete and rebuild an ANN index purely from the DB BLOBs; confirm parity —
  proves the index is a disposable cache and embeddings are recoverable.

## Settled decisions

- **Vector storage:** `float32` BLOB in MySQL; the MySQL `VECTOR` type is **not** used (see S3). The
  current MySQL version is therefore a non-issue for this work — no DB upgrade is required.
- **ANN library:** **FAISS** (`IndexHNSWFlat`); `hnswlib` was the alternative but FAISS wins on
  on-disk options and quantization (`IndexIVFPQ`) headroom at 3M+.

## Open items to confirm during execution

- Rented-GPU provider + the media→box→DB **data-transfer mechanics** (extends `utils/data_transfers/`).
