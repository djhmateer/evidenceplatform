from fastapi import APIRouter, Depends, File, Request, UploadFile

from browsing_platform.server.routes.fast_api_request_processor import extract_search_results_config
from browsing_platform.server.services.image_search import (
    reload_hash_cache, search_by_image_bytes,
)
from browsing_platform.server.services.permissions import auth_user_access
from browsing_platform.server.services.search import ISearchQuery, SearchResult, search_base

router = APIRouter(
    prefix="/search",
    tags=["search"],
    dependencies=[Depends(auth_user_access)],
    responses={404: {"description": "Not found"}},
)


@router.post("/", dependencies=[Depends(auth_user_access)])
async def search_data(query: ISearchQuery, req: Request) -> list[SearchResult]:
    return search_base(query, extract_search_results_config(req))


@router.post("/image", dependencies=[Depends(auth_user_access)])
async def search_image(
    req: Request,
    file: UploadFile = File(...),
    page_number: int = 1,
    page_size: int = 50,
) -> list[SearchResult]:
    """Reverse image search: upload a photo (or a video screenshot); returns matching media nearest
    first, in the same SearchResult shape as POST /search/. The match tolerance is fixed
    server-side (see image_search.DEFAULT_THRESHOLD) and intentionally not a request parameter."""
    file_bytes = await file.read()
    return search_by_image_bytes(
        file_bytes, page_number, page_size, extract_search_results_config(req))


@router.post("/image/reload", dependencies=[Depends(auth_user_access)])
async def reload_image_index() -> dict:
    """Rebuild the in-RAM perceptual-hash cache from the DB (call after an indexing run)."""
    return {"hashes_loaded": reload_hash_cache()}

