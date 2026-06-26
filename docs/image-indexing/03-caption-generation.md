# Feature 3 — Caption Generation + Text Search

> See `00-architecture.md` for the shared pipeline (S1), model runtime (S2), vector storage (S3),
> and request flow (S4) referenced below.

**Verdict: plausible; heaviest of the embedding features; build after Features 1 & 2.** CLIP
text→image search (Feature 2) already covers much of the "find beach photos" need, so this feature's
distinct value is **human-readable, keyword/boolean-searchable, auditable** descriptions.

## Goal

Auto-describe each image so researchers can find media with plain keywords/boolean queries through
the **existing** search, and so each item carries a readable summary of its contents.

## Model

A small open VLM — **Florence-2-base**, BLIP-2, or Moondream2 (open weights, local, ONNX per S2).
Florence-2 additionally yields **dense region captions / tags**, which materially improve keyword
recall.

## Storage + search (reuses existing fulltext)

Add a caption column and fold it into the search that already exists:

```
media.caption TEXT NULL          -- (or a media_caption side table with model_version)
caption_status ENUM('pending','generated','not_needed','error') NOT NULL DEFAULT 'pending'
```

Then **extend the existing media FULLTEXT index** from `(annotation)` to `(annotation, caption)` —
a migration plus a one-line change to the `MATCH(...)` clause in
`browsing_platform/server/services/search.py`. **No new search subsystem**; it reuses your
`… IN BOOLEAN MODE` fulltext as-is.

Optional: also embed captions with **Feature 2's text encoder** to add semantic text matching over
captions for free.

## Compute split

- **Captioning** is the only genuinely heavy step → run in **bulk on the rented GPU**; incremental
  batches run on CPU slowly or are shipped out periodically (S1).
- **Query side is plain text → no model at query time, fully CPU-safe.**

## Indexing pass (S1)

`generate_missing_captions()` worker → pipeline stage **G-CAPTION**. Selects `caption_status =
'pending'`, runs the VLM, writes `media.caption`, marks `generated`.

## Evidence caveat (surface in the UI)

Generated captions **can hallucinate**. They are **search aids, not evidence** — label them clearly
as machine-generated, store the `model_version`, and never present them as asserted fact in exports
or affidavits.

## Effort

Caption worker + migration + extend the fulltext columns + a small UI affordance to display the
(clearly-labeled) caption.

## Verification

Shared checklist in `00-architecture.md`: caption a small sample, confirm keyword queries (e.g.
"beach", "car +night") surface the right media through the existing search endpoint, and confirm the
machine-generated label renders. Confirm the query path needs no model loaded.
