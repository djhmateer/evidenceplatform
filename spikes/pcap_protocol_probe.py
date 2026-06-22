"""Spike: settle whether the Threads video stream crosses the wire as
TCP/HTTP-2 or UDP/QUIC(HTTP-3).

Background: THREADS_HAR_ISSUE.md. The browser's HAR recorder never sees the
`bytes=0-` video body because it's consumed by the media pipeline. A passive
PCAP captures the bytes *below* that layer while the browser does a genuine,
untampered TLS handshake with Meta (no MITM proxy, so the real
DigiCert -> *.cdninstagram.com chain is preserved in the capture itself). Before
committing to that design we must answer ONE question:

    Does the ~16 MB video body travel over TCP/443 (HTTP/2) or UDP/443 (QUIC)?

That answer decides whether wire capture is a weekend prototype or a swamp:
the LLM-suggested `tcp port 443` filter would capture *nothing* if Meta's CDN
serves the video over HTTP/3.

This script:
  1. starts a passive capture of BOTH `tcp port 443 or udp port 443` (dumpcap),
  2. sets SSLKEYLOGFILE so the capture can be decrypted offline later,
  3. launches the same Firefox stack the archiver uses and lets you play the
     video manually,
  4. stops the capture and reports byte volume per protocol + top talkers.

PHASE 1 (byte volume) needs NO decryption and answers the TCP-vs-QUIC question
on its own: whichever protocol moved ~16 MB to a cdninstagram host carried the
video. PHASE 2 (optional, if the keylog is non-empty and tshark is present)
attempts decryption and an HTTP object export to prove the bytes are actually
recoverable.

PREREQUISITES
  - Wireshark installed WITH Npcap (the Npcap driver install needs admin once).
    Provides dumpcap.exe + tshark.exe, normally in C:\\Program Files\\Wireshark\\.
    Override with --wireshark-dir or the WIRESHARK_DIR env var.
  - Run from the project root so the bundled Playwright Firefox is found:
        uv run spikes/pcap_protocol_probe.py "https://www.threads.com/@user/post/XXXX"
  - Capturing requires the Npcap driver; if dumpcap reports no interfaces,
    re-run an elevated shell once or reinstall Npcap in "non-admin" mode.

NOTE: Playwright ships a custom Firefox build that may NOT honor SSLKEYLOGFILE.
If the keylog comes out empty, Phase 1 still answers the protocol question.
To get a decryptable capture, point --firefox-path at a stock Firefox install.
"""

import argparse
import os
import signal
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Match the archiver's recording dimensions / pref so the page behaves the same
# (see archiver/archive.py).
_VIEWPORT = {"width": 1280, "height": 720}
_FIREFOX_PREFS = {"layout.css.devPixelsPerPx": "1.0"}

_DEFAULT_WIRESHARK_DIRS = [
    Path(r"C:\Program Files\Wireshark"),
    Path(r"C:\Program Files (x86)\Wireshark"),
]


def find_wireshark_dir(override: str | None) -> Path:
    candidates = []
    if override:
        candidates.append(Path(override))
    if os.environ.get("WIRESHARK_DIR"):
        candidates.append(Path(os.environ["WIRESHARK_DIR"]))
    candidates.extend(_DEFAULT_WIRESHARK_DIRS)
    for d in candidates:
        if (d / "dumpcap.exe").exists():
            return d
    sys.exit(
        "Could not find dumpcap.exe. Install Wireshark (with Npcap) or pass "
        "--wireshark-dir. Looked in: " + ", ".join(str(c) for c in candidates)
    )


def list_interfaces(dumpcap: Path) -> str:
    """Return dumpcap's interface list (`-D`). On Windows interfaces are named
    \\Device\\NPF_{GUID}; the leading number is what we pass to `-i`."""
    out = subprocess.run(
        [str(dumpcap), "-D"], capture_output=True, text=True
    )
    return out.stdout or out.stderr


def start_capture(dumpcap: Path, iface: str, pcap_path: Path, max_seconds: int) -> subprocess.Popen:
    """Start dumpcap capturing both TCP and UDP on 443. CREATE_NEW_PROCESS_GROUP
    lets us send CTRL_BREAK for a clean flush instead of a hard kill."""
    cmd = [
        str(dumpcap),
        "-i", iface,
        "-f", "tcp port 443 or udp port 443",
        "-w", str(pcap_path),
        "-a", f"duration:{max_seconds}",   # safety auto-stop
    ]
    print("Starting capture:\n  " + " ".join(cmd))
    return subprocess.Popen(
        cmd,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_capture(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT)
        proc.wait(timeout=10)
    except Exception:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def drive_browser(target_url: str, keylog_path: Path, firefox_path: str | None) -> None:
    from playwright.sync_api import sync_playwright

    os.environ["SSLKEYLOGFILE"] = str(keylog_path)
    print(f"SSLKEYLOGFILE -> {keylog_path}")

    with sync_playwright() as p:
        launch_kwargs = {"headless": False, "firefox_user_prefs": _FIREFOX_PREFS}
        if firefox_path:
            launch_kwargs["executable_path"] = firefox_path
        browser = p.firefox.launch(**launch_kwargs)
        print(f"Launched {browser.browser_type.name} {browser.version}")
        context = browser.new_context(viewport=_VIEWPORT)
        page = context.new_page()
        print(f"Navigating to {target_url}")
        page.goto(target_url, wait_until="domcontentloaded")
        print(
            "\n>>> Play the video through to the end (let the full body stream).\n"
            ">>> Then press ENTER here to stop the capture and analyze."
        )
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        context.close()
        browser.close()


def _run_tshark(tshark: Path, args: list[str]) -> str:
    out = subprocess.run([str(tshark), *args], capture_output=True, text=True)
    return out.stdout


def analyze(tshark: Path | None, pcap_path: Path, keylog_path: Path, outdir: Path) -> None:
    print("\n" + "=" * 70)
    print("PHASE 1 — byte volume per protocol (no decryption needed)")
    print("=" * 70)
    if tshark is None:
        print("tshark.exe not found next to dumpcap; skipping analysis. Open the "
              f"pcap in Wireshark:\n  {pcap_path}")
        return

    # Per-packet: transport proto (6=TCP, 17=UDP), src, dst, frame length.
    fields = _run_tshark(
        tshark,
        ["-r", str(pcap_path), "-T", "fields",
         "-e", "ip.proto", "-e", "ip.src", "-e", "ip.dst", "-e", "frame.len",
         "-E", "separator=,"],
    )

    tcp_bytes = udp_bytes = 0
    conv = defaultdict(int)  # (proto, peer_ip) -> bytes
    for line in fields.splitlines():
        parts = line.split(",")
        if len(parts) != 4 or not parts[3]:
            continue
        proto, src, dst, length = parts
        try:
            n = int(length)
        except ValueError:
            continue
        if proto == "6":
            tcp_bytes += n
        elif proto == "17":
            udp_bytes += n
        # Attribute to the remote peer: the non-private address of the pair.
        peer = dst if src.startswith(("10.", "192.168.", "172.")) else src
        conv[(proto, peer)] += n

    mb = lambda b: f"{b / 1_048_576:.2f} MB"
    print(f"  TCP/443 (HTTP/1.1 or HTTP/2): {mb(tcp_bytes)}")
    print(f"  UDP/443 (QUIC / HTTP/3):      {mb(udp_bytes)}")
    print("\n  Top remote peers by bytes:")
    proto_name = {"6": "TCP", "17": "UDP"}
    for (proto, peer), b in sorted(conv.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {proto_name.get(proto, proto):>3} {peer:<20} {mb(b)}")

    verdict = "UDP/QUIC (HTTP/3)" if udp_bytes > tcp_bytes else "TCP (HTTP/2)"
    print(f"\n  >>> The bulk of port-443 traffic moved over: {verdict}")
    print("  >>> Whichever protocol carries ~the video size to a cdninstagram")
    print("      peer is the one a wire-capture design must target.")

    # Phase 2: only worthwhile if we have keys to decrypt with.
    keys = keylog_path.read_text() if keylog_path.exists() else ""
    print("\n" + "=" * 70)
    print("PHASE 2 — decryptability (needs a non-empty SSLKEYLOGFILE)")
    print("=" * 70)
    if not keys.strip():
        print("  SSLKEYLOGFILE is empty — this Firefox build did not log session")
        print("  keys. Re-run with --firefox-path pointing at a stock Firefox to")
        print("  produce a decryptable capture. (Phase 1 above is still valid.)")
        return

    print(f"  Keylog has {len(keys.splitlines())} secret line(s). Attempting "
          "HTTP object export...")
    export_dir = outdir / "exported_objects"
    export_dir.mkdir(exist_ok=True)
    # Try HTTP/2 (over TLS) and HTTP/3 (over QUIC) object export. tshark needs
    # the keylog wired in via -o for both TLS and QUIC dissectors.
    for proto in ("http", "http3"):
        _run_tshark(
            tshark,
            ["-r", str(pcap_path),
             "-o", f"tls.keylog_file:{keylog_path}",
             "-o", f"quic.keylog_file:{keylog_path}",
             "--export-objects", f"{proto},{export_dir / proto}"],
        )
    exported = sorted(export_dir.rglob("*"))
    media = [f for f in exported if f.is_file() and f.stat().st_size > 1_000_000]
    print(f"  Exported {sum(1 for f in exported if f.is_file())} object(s) to {export_dir}")
    if media:
        print("  Large objects (likely the video body) — wire recovery is FEASIBLE:")
        for f in media:
            print(f"    {f.name}: {f.stat().st_size / 1_048_576:.2f} MB")
    else:
        print("  No >1 MB object exported. If Phase 1 said UDP/QUIC, tshark's")
        print("  HTTP/3 reassembly/export may be incomplete — inspect manually in")
        print("  Wireshark (Edit > Preferences > Protocols > TLS/QUIC keylog).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target_url", nargs="?", help="Threads post URL with the video (e.g. .../post/DQgOjSajOsJ)")
    ap.add_argument("--iface", help="dumpcap interface number/name (run --list-interfaces to see them)")
    ap.add_argument("--list-interfaces", action="store_true", help="print capture interfaces and exit")
    ap.add_argument("--wireshark-dir", help="dir containing dumpcap.exe/tshark.exe")
    ap.add_argument("--firefox-path", help="path to a stock Firefox exe (for a decryptable keylog)")
    ap.add_argument("--outdir", default="spikes/pcap_probe_out", help="output dir for pcap/keylog/exports")
    ap.add_argument("--max-seconds", type=int, default=600, help="capture auto-stop safety (default 600)")
    args = ap.parse_args()

    ws_dir = find_wireshark_dir(args.wireshark_dir)
    dumpcap = ws_dir / "dumpcap.exe"
    tshark = ws_dir / "tshark.exe"
    tshark = tshark if tshark.exists() else None

    if args.list_interfaces:
        print(list_interfaces(dumpcap))
        return

    if not args.target_url:
        ap.error("target_url is required (omit only with --list-interfaces)")

    if not args.iface:
        print("No --iface given. Available interfaces:\n")
        print(list_interfaces(dumpcap))
        print("\nRe-run with --iface <number> (the number before the interface name).")
        return

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    pcap_path = outdir / "capture.pcapng"
    keylog_path = outdir / "sslkeys.txt"
    keylog_path.write_text("")  # truncate any prior keys

    cap = start_capture(dumpcap, args.iface, pcap_path, args.max_seconds)
    try:
        drive_browser(args.target_url, keylog_path, args.firefox_path)
    finally:
        print("Stopping capture...")
        stop_capture(cap)

    if not pcap_path.exists() or pcap_path.stat().st_size == 0:
        sys.exit(f"Capture file is empty — wrong --iface, or Npcap not capturing: {pcap_path}")
    print(f"Captured {pcap_path.stat().st_size / 1_048_576:.2f} MB -> {pcap_path}")
    analyze(tshark, pcap_path, keylog_path, outdir)


if __name__ == "__main__":
    main()
