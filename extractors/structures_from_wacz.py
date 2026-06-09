import gzip
import json
import traceback
import zipfile
from pathlib import Path
from typing import Optional

from warcio.archiveiterator import ArchiveIterator

from extractors.extract_photos import Photo, extract_xpv_asset_id as _extract_photo_asset_id
from extractors.extract_videos import (
    Video, save_fetched_asset,
    accumulate_video_segment, reconcile_video_dicts,
)
from extractors.models_har import HarRequest
from extractors.structures_extraction import StructureType
from extractors.structures_extraction_api_v1 import extract_data_from_api_v1_entry
from extractors.structures_extraction_graphql import extract_graphql_from_response, is_graphql_url
from extractors.structures_extraction_html import extract_data_from_html_entry


def _make_minimal_har_request(url: str) -> HarRequest:
    """Construct the minimal HarRequest needed by existing entry parsers (only url is used)."""
    return HarRequest(
        method='GET',
        url=url,
        httpVersion='HTTP/1.1',
        cookies=[],
        headers=[],
        queryString=[],
        postData=None,
        headersSize=-1,
        bodySize=-1,
    )


def _decode_response_body(record) -> Optional[bytes]:
    """Read and decompress the HTTP response body from a WARC record."""
    try:
        body = record.content_stream().read()
        content_encoding = record.http_headers.get_header('Content-Encoding', '')
        if content_encoding and 'gzip' in content_encoding.lower():
            try:
                body = gzip.decompress(body)
            except Exception:
                pass  # already decompressed or not actually gzip
        return body
    except Exception as e:
        print(f"[wacz] Error reading response body: {e}")
        return None


def scan_wacz(wacz_path: Path, output_dir: Path) -> tuple[list[StructureType], list[Video], list[Photo]]:
    """
    Single pass over all WARC records in a WACZ file, simultaneously extracting:
    - structures (GraphQL / API v1 / HTML responses)
    - video segment maps (.mp4 entries by bytestart/byteend)
    - photo maps (image/* responses)

    Video segments are assembled and saved to output_dir/videos/.
    Photos are saved to output_dir/photos/.

    Returns (structures, videos, photos) — same types as _scan_har_once() in structures_to_entities.py.
    """
    structures: list[StructureType] = []
    real_xpv_dict: dict[str, Video] = {}
    fallback_dict: dict[str, Video] = {}
    filename_to_xpv: dict[str, str] = {}
    photos_dict: dict[str, Photo] = {}

    videos_dir = output_dir / "videos"
    photos_dir = output_dir / "photos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    photos_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(wacz_path) as zf:
        # Webrecorder stores WARCs under archive/ (wacz 1.x) or data/ (older)
        warc_names = [
            n for n in zf.namelist()
            if (n.startswith('archive/') or n.startswith('data/'))
            and (n.endswith('.warc') or n.endswith('.warc.gz'))
        ]

        for warc_name in warc_names:
            print(f"[wacz] Processing {warc_name}")
            with zf.open(warc_name) as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type != 'response':
                        continue

                    url: str = record.rec_headers.get_header('WARC-Target-URI', '')
                    if not url or url.startswith('urn:'):
                        continue

                    ct: str = record.http_headers.get_header('Content-Type', '') or ''
                    status_code = record.http_headers.get_statuscode()
                    if status_code and str(status_code) not in ('200', '206'):
                        continue

                    # Webrecorder encodes POST requests as GET with ?__wb_method=POST&...
                    # Strip that prefix to restore the original URL for matching.
                    clean_url = url.split('?__wb_method=')[0] if '?__wb_method=' in url else url

                    # --- Structures (GraphQL, API v1, HTML) ---
                    try:
                        if is_graphql_url(clean_url):
                            body = _decode_response_body(record)
                            if body:
                                try:
                                    structure = extract_graphql_from_response(json.loads(body))
                                    if structure:
                                        structures.append(structure)
                                except Exception as e:
                                    print(f"[wacz] GraphQL parse error for {clean_url}: {e}")

                        elif 'instagram.com/api/v1/media/' in clean_url and not ct.startswith('text/html'):
                            body = _decode_response_body(record)
                            if body:
                                try:
                                    structure = extract_data_from_api_v1_entry(
                                        json.loads(body), _make_minimal_har_request(clean_url)
                                    )
                                    if structure:
                                        structures.append(structure)
                                except Exception as e:
                                    print(f"[wacz] API v1 parse error for {clean_url}: {e}")

                        elif ct.startswith('text/html'):
                            body = _decode_response_body(record)
                            if body:
                                try:
                                    structure = extract_data_from_html_entry(
                                        body.decode('utf-8', errors='replace'),
                                        _make_minimal_har_request(clean_url),
                                    )
                                    if structure:
                                        structures.append(structure)
                                except Exception as e:
                                    print(f"[wacz] HTML parse error for {clean_url}: {e}")
                    except Exception as e:
                        print(f"[wacz] Structure processing error for {clean_url}: {e}")
                        traceback.print_exc()

                    # --- Video segments (.mp4 with video/mp4 content-type) ---
                    try:
                        if '.mp4' in url and ct.startswith('video/'):
                            body = _decode_response_body(record)
                            if body:
                                accumulate_video_segment(
                                    url, body, real_xpv_dict, fallback_dict, filename_to_xpv
                                )
                    except Exception as e:
                        print(f"[wacz] Video segment error for {url}: {e}")
                        traceback.print_exc()

                    # --- Images (image/* content-type; CDN URLs have no extension) ---
                    try:
                        if ct.startswith('image/'):
                            body = _decode_response_body(record)
                            if body:
                                asset_id = _extract_photo_asset_id(url) or url.split('/')[-1].split('?')[0]
                                img_filename = url.split('/')[-1].split('?')[0]
                                if asset_id not in photos_dict:
                                    photos_dict[asset_id] = Photo(
                                        asset_id=str(asset_id), url=url, fetched_assets={}
                                    )
                                photos_dict[asset_id].fetched_assets[img_filename] = body
                    except Exception as e:
                        print(f"[wacz] Image error for {url}: {e}")

    # --- Reconcile filename-keyed video entries (cascade steps 2-3) ---
    reconcile_video_dicts(real_xpv_dict, fallback_dict, filename_to_xpv, structures=structures)

    # --- Assemble video segments and save to disk ---
    videos = list(real_xpv_dict.values())
    for video in videos:
        if video.fetched_tracks:
            result = save_fetched_asset(video, videos_dir, download_full_track=False)
            if result.success and result.location:
                video.local_files = [result.location]
                print(f"[wacz] Saved video: {result.location.name}")

    # --- Save photo files to disk ---
    photos = list(photos_dict.values())
    for photo in photos:
        if photo.fetched_assets:
            # Pick the largest fetched asset (proxy for highest quality)
            best_filename, best_data = max(photo.fetched_assets.items(), key=lambda x: len(x[1]))
            save_path = photos_dir / best_filename
            try:
                save_path.write_bytes(best_data)
                photo.local_files = [save_path]
            except Exception as e:
                print(f"[wacz] Error saving photo {best_filename}: {e}")

    print(f"[wacz] Scan complete: {len(structures)} structures, "
          f"{len(videos)} videos, {len(photos)} photos")
    return structures, videos, photos
