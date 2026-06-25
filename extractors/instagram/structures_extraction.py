"""Instagram per-entry structure-detection seam.

Consolidates the GraphQL / API-v1 / HTML branching that used to be duplicated
across ``structures_from_har``, ``keep_only_requests_*``, ``_scan_har_once`` and
the WACZ scanner. The generic top-level dispatcher
(``extractors.structures_extraction``) routes each HAR/WARC entry here by host.
"""
import json
from typing import Optional, Union

from extractors.models_har import HarRequest
from extractors.instagram.structures_extraction_api_v1 import ApiV1Response, extract_data_from_api_v1_entry
from extractors.instagram.structures_extraction_graphql import GraphQLResponse, extract_graphql_from_response, is_graphql_url
from extractors.instagram.structures_extraction_html import PageResponse, extract_data_from_html_entry

InstagramStructure = Union[GraphQLResponse, ApiV1Response, PageResponse]


def is_instagram_host(host: Optional[str]) -> bool:
    """True for instagram.com and its subdomains (www., i., etc.).

    Deliberately excludes the shared Meta media CDN (``*.cdninstagram.com``):
    ``"cdninstagram.com"`` has no ``.instagram.com`` boundary, so it never
    matches. CDN entries carry no structures — they are handled by the media
    accumulators, not here.
    """
    if not host:
        return False
    host = host.lower()
    return host == "instagram.com" or host.endswith(".instagram.com")


def extract_structure_from_entry(entry: dict) -> Optional[InstagramStructure]:
    """Detect and parse an Instagram structure from a single HAR/WARC entry.

    Mirrors the original inline branching: GraphQL responses (``graphql/query``
    and ``/api/graphql``), API-v1 media/friendships JSON, and bootstrapped HTML
    pages. Returns None when the entry carries no recognizable structure.
    """
    url: str = entry["request"]["url"]
    content: dict = entry["response"]["content"]
    mime: str = content.get("mimeType", "")
    if is_graphql_url(url):
        res_json = content.get("text")
        if not res_json:
            return None
        req = HarRequest(**entry["request"])
        ctx = {p["name"]: p["value"] for p in req.postData.params} if req.postData and req.postData.params else {}
        return extract_graphql_from_response(json.loads(res_json), context=ctx)
    if ("instagram.com/api/v1/media/" in url or "instagram.com/api/v1/friendships/" in url) \
            and not mime.startswith("text/html"):
        res_json = content.get("text")
        if not res_json:
            return None
        return extract_data_from_api_v1_entry(json.loads(res_json), HarRequest(**entry["request"]))
    if mime.startswith("text/html"):
        html_text = content.get("text")
        if not html_text:
            return None
        return extract_data_from_html_entry(html_text, HarRequest(**entry["request"]))
    return None
