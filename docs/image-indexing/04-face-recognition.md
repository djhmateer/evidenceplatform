# Feature 4 — Face Detection + Recognition

> See `00-architecture.md` for the shared pipeline (S1), model runtime (S2), vector storage (S3),
> and request flow (S4) referenced below.

**Verdict: plausible; the most involved (new table + clustering + labeling UX). Local open models,
CPU-safe queries, no lock-in.** Build last; gate behind the ethics/consent review below.

## Goal

Google-Photos-style: index every face in the corpus, cluster them into provisional people, and let
a researcher find a person from a few sample faces (query-by-example), with precision improving as
they confirm samples.

## Model

**InsightFace** `buffalo_l` / `buffalo_s` — already ONNX-based (S2): **SCRFD** detector + **ArcFace**
512-d embedder. Runs on CPU (~100 ms/image); fast on the rented GPU for the bulk pass. Open models
stored locally; pinned by `model_version`.

## Pipeline

1. **Detect** faces per media item → for each face store one row.
2. **Embed** each face (ArcFace 512-d, L2-normalized).
3. **Cluster** embeddings (HDBSCAN or agglomerative on cosine) into **provisional persons**.
4. **Query-by-example:** user selects/uploads a face → embed locally on CPU → ANN over face vectors
   → ranked **candidate** matches.

## Storage (S3)

```
face(
  id           INT AUTO_INCREMENT PRIMARY KEY,
  media_id     INT NOT NULL,         -- FK -> media.id
  bbox         VARCHAR(100) NOT NULL,-- detection box
  det_score    FLOAT NOT NULL,
  vector       BLOB NOT NULL,        -- float32, L2-normalized ArcFace embedding
  model_version VARCHAR(64) NOT NULL,
  person_id    INT NULL              -- provisional/confirmed person cluster
)
```

Plus `face_status` on `media` (S1 status enum). A dedicated **HNSW** index (S3) is built over the
face vectors.

**Scale note:** 3M media may yield **5–10M faces** → this index is *larger* than the media
embedding index; budget RAM accordingly (5–10M × 512-d float32 ≈ 10–20 GB raw — consider a
quantized FAISS variant if RAM is tight).

## Indexing pass (S1)

`generate_missing_faces()` worker → pipeline stage **H-FACES**. Detection+embedding runs in bulk on
the rented GPU; incremental batches run locally on CPU. Clustering is a separate periodic job over
the accumulated `face` vectors.

## API + UI (S4)

- Query-by-example endpoint: upload/select a face → embed locally → ANN search → scored candidates.
- New **faces/person browsing UI** (the largest frontend addition of the four): person pages, a
  face grid per media item, and the "confirm N samples to define a person" labeling flow.

## Human-in-the-loop + ethics (must address before shipping)

- Recognition is **probabilistic** — present **scored candidate matches, never assertions**.
- Support the **confirm-N-samples** pattern to raise precision/recall for a target person.
- Face vectors are **biometric data**. For an evidence platform this carries **consent/legal**
  obligations — flag this explicitly, gate the feature behind appropriate access controls, and
  decide retention/redaction policy before enabling.

## Effort

`face` table + detect/embed worker + clustering job + face ANN index + faces/person browsing UI.
Reuses the ONNX runtime (S2) and ANN lifecycle (S3) established by Feature 2.

## Verification

Shared checklist in `00-architecture.md`: index a small sample with known people, confirm
query-by-example returns the same person's other photos as top candidates with sensible scores,
confirm clustering groups them, and confirm the query path runs on CPU with the GPU provider
disabled.
