# Feature 2 — Semantic Similarity + Text→Image Search

> See `00-architecture.md` for the shared pipeline (S1), model runtime (S2), vector storage (S3),
> and request flow (S4) referenced below.

**Verdict: very plausible, and the highest-leverage feature.** A single open CLIP model delivers
image→image similarity **and** text→image search in the *same* vector space — so it also covers
most of the practical value of Feature 3 ("beach" as a text query lands on beach images).

## Goal

- **Image→image:** from an example media item (or uploaded photo), find visually/conceptually
  similar media — similar architecture, activity, machinery, scene.
- **Text→image:** from a free-text query, find matching images even when no human caption exists.

## Model

OpenCLIP **`ViT-B/32`** (LAION) or **SigLIP** — open weights, exported to ONNX (S2) as **two**
encoders:

- **image encoder** — produces a 512–768-d vector per image,
- **text encoder** — produces a vector in the *same* space for a query string.

Vectors L2-normalized at write time (cosine == inner product). Weights stored locally and pinned by
`model_version`.

## Compute split

- **Image embeddings:** computed in **bulk on the rented GPU** for the 400K backlog;
  **incremental** embedding of new media runs locally on CPU (~50–150 ms/image — fine as a
  background batch, per S1).
- **Text encoder:** tiny — runs **at query time on local CPU in ~10–50 ms**. Text→image search
  therefore needs **no GPU ever**.

## Storage (S3)

```
media_embedding(
  media_id     INT NOT NULL,        -- FK -> media.id
  model_version VARCHAR(64) NOT NULL,
  vector       BLOB NOT NULL,       -- float32 bytes, L2-normalized
  PRIMARY KEY (media_id, model_version)
)
```

Plus `embed_status` on `media` (S1 status enum). `model_version` lets multiple models coexist and
enables zero-downtime re-indexing (write new vectors under a new version, swap the index, drop the
old). The **HNSW** ANN index (S3) is built from these BLOBs, persisted to disk, loaded at FastAPI
startup, and incrementally `add`-ed for new media.

## Indexing pass (S1)

`generate_missing_embeddings()` worker → pipeline stage **F-EMBED**. Selects `embed_status =
'pending'`, runs the image encoder (GPU in bulk / CPU incrementally), writes the BLOB, marks
`generated`, and appends the vector to the ANN index.

## Search (S4)

Query is an **image** (embed locally with the image encoder) *or* **text** (embed locally with the
text encoder) → HNSW top-K → existing `SearchResult` shape → `MediaSearchResults.tsx`. Text→image
folds naturally into the existing search flow; add an example-image upload mode to `SearchPanel.tsx`
for image→image.

## Effort

ONNX export of both encoders + embed worker + the **ANN index lifecycle** (build / load /
incremental-add / rebuild-from-BLOBs) + endpoint + UI mode. The ANN lifecycle is shared with
Feature 4, so building it here pays for both.

## Verification

Shared checklist in `00-architecture.md`: text "beach" → beach images; an example image of
machinery → other machinery shots; rebuild the HNSW index purely from BLOBs and confirm identical
top-K (lock-in drill). Confirm text→image works with the GPU provider disabled.
