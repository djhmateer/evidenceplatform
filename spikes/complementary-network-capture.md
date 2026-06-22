# Complementary network capture — findings & design

**Status:** design agreed; implementation not started (this doc supersedes the
old `THREADS_HAR_ISSUE.md`, which covered only the problem stage).

**Branch:** `capture-open-ended-streams`
**Spike artifact:** `spikes/pcap_protocol_probe.py` (the protocol probe described
below). Capture output lands under `spikes/pcap_probe_out/` (git-ignored).

---

## 1. Why this feature exists — the gap in HAR capture

The archiver records each session as a browser-recorded **HAR** (Playwright
Firefox, `record_har_content="attach"`). That captures structural metadata,
captions, images, and GraphQL/JSON fine. It **cannot capture Threads post
video bodies**, and the reason is structural, not a bug we can patch in the HAR
layer.

### Root cause

Threads (`www.threads.com`, Meta codename "Barcelona") requests post video as an
**open-ended HTTP range**: `Range: bytes=0-`. The server answers `206` and
streams the *entire* file in one response straight into the browser's `<video>`
media pipeline (decoder + media cache). That body is consumed by the media stack
and **never surfaced to the HAR recorder**:

- In the HAR the entry has full network metadata — `status: 206`,
  `Content-Range: bytes 0-16444064/16444065`, `_transferSize: 16444755` — but
  `content.size: -1` and **no body** (`text`/`_file` absent). The bytes crossed
  the wire; the recorder just never received them.
- It is **not** a timing/at-close race (a lost full response completed minutes
  before session end) and **not** fiber-starvation (every non-media body is
  captured 100%).

### Why it's browser-agnostic

A HAR recorded directly with **Chrome DevTools** (no Playwright) shows the
**identical** result: zero `video/mp4` bodies. Chrome's CDP `getResponseBody`
fails the same way for media/MSE/range-streamed resources. So switching
Firefox → Chromium does not fix it, and there is no `record_har_content` / cache
/ pref setting that fixes it.

### Why Instagram worked but Threads doesn't

Instagram fetches video as **bounded** chunk requests with the byte range in the
**URL** (`bytestart=…&byteend=…`). Those complete as discrete, cacheable
resources whose bodies the recorder *does* capture, so IG videos could be
reassembled from HAR segments. Threads uses **header-based open-ended ranges**
fed to the media element, which the recorder cannot capture. Same Meta CDN
(`*.cdninstagram.com`), different fetch mechanism — and the mechanism is what
breaks HAR capture.

### What was ruled out (don't retry)

- **Disabling Firefox cache** (`media.cache_size=0`, `browser.cache.*=false`):
  strictly **worse**. Firefox fired hundreds of tiny overlapping range requests
  (177 vs ~10), playback glitched, and **none** captured a body. Reverted.
- **Switching browsers**: ruled out by the Chrome DevTools HAR above.
- **Reassembling from HAR segments**: impossible — the head bytes (`bytes=0-`,
  incl. the moov atom) are exactly what's dropped; only occasional seek-range
  tails survive, and tails alone can't be assembled.

### Current workaround (already in the pipeline) and its limit

The extractor **re-acquires videos from the CDN** at finalization using each
video's `full_asset` URL (`video_versions[0]`), a normal progressive MP4 that
downloads fully. Supporting fixes already merged:

- **`requested_in_session` flag** (`extractors/extract_videos.py`) — "fetched
  during the session" now means *"a `.mp4` request for it appears in the HAR"*
  (the `bytes=0-` request proves the operator loaded it), not "a body was
  captured" (a Threads video never has one). Posts never opened still have no
  request → still skipped.
- **Carousel cover-image fix** (`extractors/threads/structures_to_entities.py`)
  — a carousel parent carries its own `image_versions2` (the cover) even when
  every slide is a video; the mapper no longer emits a top-level `Media` for
  carousels, so the cover JPG no longer masquerades as the first asset.
- **Header-based byte-range handling** (`extractors/extract_videos.py`,
  `structures_from_wacz.py`) — when a Threads media body *is* captured (e.g. a
  seek-range tail), its offset comes from the `Content-Range`/`Range` headers,
  not the URL; the accumulator reads the offset from headers (URL params still
  win when present) so a captured tail lands at the correct offset.

**Evidentiary caveat that motivates this feature:** CDN re-acquisition is bytes
fetched *shortly after* capture, not captured on the wire. The HAR proves the
video's URL, response headers, size, and timestamp were observed during the
session, but the Meta CDN `etag` is **not** a content hash (verified: `etag` ≠
SHA-256 of a fresh full download, though the byte count matches `Content-Range`
exactly), so the re-downloaded bytes **cannot be cryptographically tied to the
capture-time bytes**. Closing that gap is the point of complementary network
capture.

---

## 2. Spike findings (`pcap_protocol_probe.py`)

Goal: settle whether the video crosses the wire as TCP/HTTP-2 or UDP/QUIC, and
whether a passive capture + `SSLKEYLOGFILE` can actually recover it — *without* a
MITM proxy (which would replace Meta's genuine TLS cert chain and destroy the
chain-of-custody argument).

Test: capture **both** `tcp port 443 or udp port 443` via Wireshark's `dumpcap`,
set `SSLKEYLOGFILE`, drive the archiver's Firefox stack to the 3-video carousel
post `DQgOjSajOsJ`, play it through, then analyze.

| Question | Result |
|---|---|
| Video transport: TCP/HTTP-2 or UDP/QUIC? | **QUIC / HTTP-3.** 85.3 MB UDP/443 vs 1.46 MB TCP/443. |
| Would a `tcp port 443`-only filter (as a naive design would use) work? | **No** — captures ~nothing but API/page chrome. Both-protocols filter is mandatory. |
| Does Playwright's bundled Firefox honor `SSLKEYLOGFILE`? | **Yes** — 72 secrets logged (Firefox 150.0.2). No stock Firefox needed. |
| Does the QUIC/HTTP-3 traffic decrypt with those keys? | **Yes** — `tshark` with the keylog yields plaintext request lines, incl. the post page (`157.240.196.63 GET /@…/post/DQgOjSajOsJ`) and all three carousel video GETs (`…/o1/v/t16/f2/m69/….mp4`, `…/o1/v/t2/f2/…`). |
| Are the actual video bytes present in the capture? | **Yes** — 84 MB of decryptable QUIC payload to the CDN hosts, consistent with the three full video bodies. |

Side findings:

- **The video served from `212.199.140.x`, an in-ISP Meta edge cache (FNA / Meta
  Network Appliance), not a Meta-owned IP.** Normal Meta CDN behavior; SNI is
  still `*.cdninstagram.com`/`fbcdn.net`, so the genuine-cert argument is intact
  (the cache presents Meta's real certificate). API/page traffic went to Meta's
  own ranges (`57.144.x`, `157.240.x`).
- **`tshark --export-objects` has no HTTP/3 support** — it silently exported 0
  objects. tshark *decrypts* HTTP/3 fine, but automated body extraction via the
  CLI export tap does not work for H3; reassembly must be custom (see §5).

**Conclusion:** the passive-capture + `SSLKEYLOGFILE` paradigm is confirmed
viable for this exact case. The remaining work is (a) a capture mechanism that
deploys automatically, and (b) an HTTP/3 (and HTTP/2) reassembler.

---

## 3. Guiding decision — preserve all raw data, refine the extractor over time

This capture is **complementary to the HAR, never a replacement.** But its scope
is deliberately broader than "just the missing video bytes":

- **Keep everything captured, not only the video.** Admissibility favors more
  corroborating metadata. The HAR runs locally on the operator's personal
  laptop, which is already an evidentiary disadvantage; any additional,
  independent monitoring artifact that corroborates the session strengthens the
  record. So we store the **entire** captured stream/packet record, not a
  video-only subset.
- **Mirror the HAR philosophy: freeze the raw capture, evolve the extractor.**
  The HAR capture mechanism has barely changed in a year; the value came from
  months of refining the *extraction* algorithm against a stable raw artifact.
  We adopt the same split here — get a complete, stable raw capture stored now,
  and improve the reassembler incrementally as we hit edge cases. The reassembler
  not being perfect on day one is acceptable **as long as the raw bytes are fully
  preserved** so a better reassembler can be re-run over old archives later.

### Phasing

- **Phase 1 (build now):** capture and store the raw monitoring artifact in the
  archive directory alongside the HAR. **No extraction integration yet.**
- **Phase 2 (later):** feed the reassembled streams into the structures/media
  extraction pipeline (`extractors/`, `db_loaders/`), so captured video bytes can
  be cryptographically tied to the session and supersede/augment CDN
  re-acquisition.

---

## 4. Design — two operator-selectable capture modes

Capture is **opt-in per session** and offered in two fidelity tiers. Neither runs
by default (the HAR path is unaffected when capture is off).

### Mode selection UX

At launch, the operator indicates the capture mode in the **profile selection
dialog** via a sentinel input:

- (no sentinel) → **no network capture** (current behavior).
- `^` → **regular mode** (pure-Python pass-through relay). The relay starts, and
  the dialog then **awaits the normal profile-selection input as the next
  step** (the `^` only sets the mode; profile selection proceeds as usual).
- `^^` → **max-fidelity mode** (pktmon). The archiver **relaunches itself
  elevated** (admin) and uses pktmon for passive packet capture.

The chosen mode determines which **affidavit caveats** are appended (see §6).

### Mode A — regular: pure-Python pass-through relay (`^`)

A small in-process **localhost CONNECT proxy** that the Playwright **browser
context** is routed through (`proxy=` at context level, so only the archiver's
browser is affected). It **terminates nothing** — for each `CONNECT host:443`
it opens an upstream socket and forwards bytes verbatim, tee-ing each direction
to disk.

- **Deploys with zero friction:** pure Python, no driver, no admin, no external
  binary, cross-platform. Directly satisfies the "auto-install like
  ffmpeg/par2/openssl, no manual Wireshark" requirement — there is nothing to
  install at all.
- **Captures the whole session**, not just media (per §3): every TLS stream the
  browser opens is recorded.
- **Genuine end-to-end TLS preserved:** the relay never decrypts; the browser
  authenticates Meta's real certificate directly. The genuine cert chain is
  recoverable offline from the captured handshake + keylog (and the archiver
  already independently records cert chains via a post-session re-handshake in
  `archive.py::get_tls_certs_for_domains`).
- **Forced HTTP/2 (the one deviation):** routing through a CONNECT proxy makes
  the browser **drop QUIC/HTTP-3 and fall back to HTTP/2 over TCP** (QUIC can't
  traverse a CONNECT tunnel). This is a *content-neutral* transport change — the
  resource bytes are identical — and it makes Phase-2 reassembly much simpler
  (H2-over-TLS vs QUIC). It is a smaller, disclosed deviation than the CDN
  re-acquisition already in use. **Must be disclosed in the affidavit.**
- **Risk:** when enabled, the *whole* session's traffic flows through the relay,
  so a relay fault could disrupt the session (and thus the HAR). Mitigated by
  keeping the mode opt-in/flag-gated and the relay robust; a future refinement
  could route only CDN/media hosts through it (e.g. a Firefox PAC that returns
  `PROXY` for `*.cdninstagram.com`/`*.fbcdn.net` and `DIRECT` otherwise), leaving
  the HAR-critical GraphQL/page path untouched.

**Raw artifact (Phase 1):** a `network_capture/` subdir in the archive holding,
per upstream connection, the raw client→server / server→client byte dumps, a
`connections.jsonl` index (host, port, timestamps, byte counts), and the
`sslkeys.txt` keylog. Clean, ordered, complete per-connection streams — no
IP/TCP reassembly or packet-loss handling needed downstream.

### Mode B — max-fidelity: pktmon passive packet capture (`^^`)

Windows' built-in `pktmon` (Win10 1809+/11; **no install**) captures all packets
at the NDIS layer to `.etl`, converted to `.pcapng`. Requires **admin**, so the
archiver relaunches itself elevated when `^^` is chosen.

- **Strongest forensic posture — purely passive, zero alteration.** The browser
  talks to Meta exactly as it would with no tooling present: real QUIC/HTTP-3,
  real IP endpoints, original timing, genuine handshake. The capture injects and
  modifies nothing.
- **Self-validating chain of custody:** the `.pcapng` contains the genuine
  handshake; with the `SSLKEYLOGFILE` keys an auditor decrypts the same artifact
  whose payload they're recovering and sees Meta's real cert chain — proving zero
  mediation. (`SSLKEYLOGFILE` is key material recorded "from the inside," but
  it's self-validating: the keys are trusted precisely because they decrypt
  ciphertext whose handshake carries Meta's authentic cert. Same mechanism all
  Wireshark TLS decryption relies on.)
- **Admin friction** (one UAC prompt at relaunch) is accepted for this mode, and
  is likely further reducible within Windows (e.g. a pre-authorized elevated
  Task Scheduler task). Windows-only.

**Raw artifact (Phase 1):** the `.pcapng` (+ converted-from `.etl` if relevant)
and the `sslkeys.txt` keylog, stored in `network_capture/`. Capture **drop
counters must be checked** and a lossy capture flagged (see §5).

---

## 5. Reconstruction (Phase 2) — challenges per mode

Both modes store raw now and reconstruct later. The reassembler is expected to
mature over time against the frozen raw artifact (per §3).

### Regular mode (relay → TLS-over-TCP, HTTP/2)

Comparatively tractable:

1. Decrypt TLS 1.3 records per connection using the keylog (matched by
   `client_random` from the cleartext ClientHello in each captured stream).
2. Reassemble HTTP/2 (HPACK header decode + stream frames) — well-trodden,
   library support exists.
3. Strip H2 framing to recover response bodies.

No packet loss / reordering / IP reassembly — the relay already yields clean,
ordered, complete per-connection byte streams.

### Max-fidelity mode (pktmon → pcap, QUIC/HTTP-3)

Genuinely harder; **no off-the-shelf automated extractor** (tshark decrypts H3
but `--export-objects` has no H3 support, and the GUI export path is ruled out by
the no-manual-steps requirement). A **custom QUIC→HTTP-3 reassembler** must, per
connection: track QUIC across **Connection-ID migration**; derive per-encryption-
level packet keys from the keylog; remove **header protection** (separate cipher
pass) before payload decryption; reassemble **stream data by offset** handling
frame-level **retransmission/de-dup**; **QPACK-decode** the stateful HTTP/3
headers; strip DATA-frame framing for the body. `aioquic` provides QUIC crypto
primitives but not a pcap-replay decoder — the pipeline is bespoke and somewhat
fragile against QUIC version drift (Meta tracks recent QUIC). Additionally,
kernel capture can **drop packets under load** (85 MB in a burst is load), so
capture completeness must be verified (pktmon reports drop counts) and a lossy
capture treated as failed.

This complexity is accepted (per §3) because the raw `.pcapng` is preserved and
the reassembler can be improved iteratively.

---

## 6. Affidavit caveats (mode-dependent)

`archive.py::affidavit_from_metadata` currently asserts a direct connection and
no third-party file-system access. Capture mode changes the wording:

- **No capture:** unchanged.
- **Regular (relay):** disclose that, for this session, the archiver's browser
  traffic was routed through a **local pass-through relay operated by the
  archiver itself** (no third party), which terminates no TLS and modifies no
  content, and that routing through the relay caused the browser to use **HTTP/2
  instead of HTTP/3** (a content-neutral transport change). Disclose that raw
  per-connection TLS streams and the session TLS keylog were stored in the
  archive.
- **Max-fidelity (pktmon):** disclose that a **passive OS-level packet capture**
  ran during the session (no traffic alteration), and that the raw `.pcapng` and
  session TLS keylog were stored in the archive.

---

## 7. Constraints & open items

- **VPN (active by default):** `archive.py` gates sessions on
  `ensure_vpn_connection()`, so traffic normally runs through a VPN tunnel
  (observed: NordVPN — NordLynx/WireGuard or OpenVPN DCO adapter). Implications:
  - *Relay:* indifferent to the VPN — it's an application-level proxy; the OS
    routes its upstream sockets through the tunnel transparently.
  - *pktmon:* must capture the **decapsulated** traffic on the *tunnel* adapter,
    not the physical adapter (which sees only the encrypted tunnel). Where
    pktmon's NDIS hook sits relative to the VPN virtual adapter must be
    validated. The spike confirmed the protocol question with VPN **off**;
    capture-point selection under VPN is an open item for pktmon.
- **`SSLKEYLOGFILE` is sensitive** but storing it in the archive is required and
  intended (it's the means to decrypt the captured ciphertext later). It is
  scoped to the archiver's browser process.
- **Hashing/PAR2 integration:** for forensic consistency the `network_capture/`
  artifacts should eventually join the per-asset manifest / `manifests.json` /
  OpenTimestamps anchoring used for the HAR and media. Not required for Phase 1
  storage, but a natural follow-up.
- **No browser injection** remains inviolable (memory: no JS injected into the
  session; the affidavit must be able to assert no injected code). Neither mode
  injects anything into the page — both observe transport only.

---

## 8. References

- Spike script: `spikes/pcap_protocol_probe.py` (run from project root via
  `uv run`; see its docstring).
- Relevant code: `archiver/archive.py` (launch, HAR merge, TLS cert capture,
  affidavit), `extractors/extract_videos.py`,
  `extractors/threads/structures_to_entities.py`,
  `extractors/structures_from_wacz.py`.
- Target post used throughout: Threads carousel `DQgOjSajOsJ` (3 videos).
