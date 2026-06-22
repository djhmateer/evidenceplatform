# Threads video bodies are not capturable from a browser HAR

## Summary

Threads (`www.threads.com`, Meta codename "Barcelona") serves post **videos** in a
way that **no browser-recorded HAR can capture the response body** — confirmed
across both the Playwright-driven Firefox archiver and a hand-recorded Chrome
DevTools HAR. The structural metadata, captions, images, and GraphQL/JSON are
captured fine; only `video/mp4` bodies are lost.

Because the bytes can't be captured during the session, Threads videos are
**re-acquired from the CDN** at archive-finalization time using the `full_asset`
URL parsed from the page structures. This document explains why capture fails,
what was ruled out, and how the pipeline now recovers the videos.

## Symptom

For a 3-video carousel post (`DQgOjSajOsJ`), the extractor produced no usable
videos: either it emitted the carousel's still **cover image** instead of the
videos, or — once that was fixed — reported every video as "not fetched" and
downloaded none.

## Root cause

Threads requests video as an **open-ended HTTP range**: `Range: bytes=0-`. The
server answers `206` and streams the *entire* file in one response straight into
the browser's `<video>` media pipeline (decoder + media cache). That body is
consumed by the media stack and **never surfaced to the HAR recorder**:

- In the HAR the entry has full network metadata — `status: 206`,
  `Content-Range: bytes 0-16444064/16444065`, `_transferSize: 16444755` — but
  `content.size: -1` and **no body** (`text`/`_file` absent). The bytes crossed
  the wire; the recorder just never received them.
- This is **not** a timing/at-close race (a lost full response completed minutes
  before the session ended) and **not** fiber-starvation (every non-media body
  is captured 100%).

### Why this is browser-agnostic

A HAR recorded directly with **Chrome DevTools** (no Playwright involved) shows
the **identical** result: zero `video/mp4` bodies. Chrome's CDP `getResponseBody`
fails the same way for media/MSE/range-streamed resources. So:

- Switching Firefox → Chromium does **not** fix it.
- There is no `record_har_content` / cache / pref setting that fixes it (see
  "What was ruled out").

### Why Instagram worked but Threads doesn't

Instagram fetches video as **bounded** chunk requests with the byte range in the
**URL** (`bytestart=…&byteend=…`). Those complete as discrete, cacheable
resources whose bodies the recorder *does* capture, so IG videos could be
reassembled from HAR segments. Threads uses **header-based** open-ended ranges
fed to the media element, which the recorder cannot capture. Same Meta CDN
(`*.cdninstagram.com`), different fetch mechanism — and the mechanism is what
breaks HAR capture.

## What was ruled out (don't retry these)

- **Disabling Firefox cache** (`media.cache_size=0`, `browser.cache.*=false`):
  made it strictly **worse**. With no media buffer, Firefox fired hundreds of
  tiny overlapping range requests (177 vs ~10), playback went glitchy, and
  **none** of the fragments captured a body. Reverted.
- **Switching browsers**: ruled out by the Chrome DevTools HAR above.
- **Reassembling from HAR segments**: impossible for these posts — the
  head bytes (`bytes=0-`, incl. the moov atom) are exactly what's dropped; only
  occasional seek-range tails survive, and tails alone can't be assembled.

## What was fixed (and why it works)

1. **Re-acquire videos from the CDN.** The parsed structures expose each video's
   `full_asset` URL (`video_versions[0]`), a normal progressive MP4 that
   downloads fully. The archiver already runs acquisition at finalization, so
   videos are fetched seconds after the session. *(Verified: all 3 carousel
   videos download, byte-for-byte the sizes the HAR recorded.)*

2. **`requested_in_session` flag** (`extractors/extract_videos.py`). The bug that
   made it look unfixable: `acquire_videos` used `fetched_tracks` ("did we
   capture a body?") as the proxy for "was this fetched during the session." A
   Threads video never has a body, so it was classed **unfetched** and skipped
   before the CDN download could run (under the default
   `download_unfetched_media=False`). Fix: "fetched during the session" now means
   **"a `.mp4` request for it appears in the HAR"** (the `bytes=0-` request proves
   the operator loaded it), collected during the existing single HAR pass. Posts
   never opened still have no request → still skipped (no over-collection).

3. **Carousel cover-image fix** (`extractors/threads/structures_to_entities.py`).
   A carousel parent carries its own `image_versions2` (the cover) even when every
   slide is a video. The mapper no longer emits a top-level `Media` for carousels,
   so the cover JPG no longer masquerades as the post's first asset.

4. **Header-based byte-range handling** (`extractors/extract_videos.py`,
   `structures_from_wacz.py`). When a Threads media body *is* captured (e.g. a
   seek-range tail), its offset comes from the `Content-Range`/`Range` headers,
   not the URL. The accumulator now reads the offset from headers (URL params
   still win when present), so a captured tail lands at the correct offset
   instead of being misfiled at byte 0 and corrupting the file.

## Evidentiary caveat

CDN re-acquisition is bytes fetched *shortly after* capture, not captured on the
wire. The HAR proves the video's URL, response headers, size, and timestamp were
observed during the session, but the Meta CDN `etag` is **not** a content hash
(tested: `etag` ≠ SHA-256 of a fresh full download, though the byte count matches
`Content-Range` exactly), so the re-downloaded bytes can't be *cryptographically*
tied to the capture-time bytes.

## The only way to capture the real bytes: a network-level proxy

To get the actual transmitted video bytes into the timestamped archive, capture
**below** the browser media pipeline with a local MITM proxy that Playwright
routes the browser through (`proxy=` per browser context, so only the archiver's
browser is intercepted — observes traffic, injects nothing into the page).
Tradeoff: the proxy re-presents its own CA, replacing the genuine server TLS
certificate chain the archiver currently records — weakening that evidence. It's
a larger, double-edged change, deferred unless CDN re-acquisition proves
insufficient.

## Operator notes

- Run with `v_download_highest_quality_assets_from_structures=True` (the archiver
  default) so videos are re-acquired from the CDN. `v_download_unfetched_media`
  can stay `False`; watched videos are now recognized via `requested_in_session`.
- The HAR merge prints a `WARNING: HAR body capture: N response(s) … NO body
  recorded` line (by MIME type) when bodies are dropped — watch for it. Capture
  output to a file (`archiver.bat > archive_log.txt 2>&1`) since the console
  closes on exit.
