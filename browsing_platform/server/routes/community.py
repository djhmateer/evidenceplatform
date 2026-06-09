from fastapi import APIRouter, Depends, HTTPException, Request

from browsing_platform.server.routes.fast_api_request_processor import extract_search_results_config
from browsing_platform.server.services.community import (
    CommunityCandidatesRequest,
    CommunityCandidatesResponse,
    TagDismissalsRequest,
    TagKernelResponse,
    compute_candidates,
    compute_kernel_scores,
    get_tag_kernel_accounts,
    set_tag_dismissals,
)
from browsing_platform.server.services.permissions import auth_user_access

router = APIRouter(
    prefix="/community",
    tags=["community"],
    dependencies=[Depends(auth_user_access)],
    responses={404: {"description": "Not found"}},
)


@router.post("/candidates/")
async def get_community_candidates(
        req: CommunityCandidatesRequest,
        request: Request,
) -> CommunityCandidatesResponse:
    if not req.kernel_ids:
        raise HTTPException(status_code=422, detail="kernel_ids must not be empty")
    transform = extract_search_results_config(request)
    return compute_candidates(req, transform)


@router.post("/kernel-details/")
async def get_kernel_details(
        req: CommunityCandidatesRequest,
        request: Request,
) -> CommunityCandidatesResponse:
    if not req.kernel_ids:
        return CommunityCandidatesResponse(candidates=[])
    transform = extract_search_results_config(request)
    return compute_kernel_scores(req, transform)


@router.get("/tag-kernel/{tag_id}")
async def get_tag_kernel(tag_id: int, request: Request) -> TagKernelResponse:
    transform = extract_search_results_config(request)
    return get_tag_kernel_accounts(tag_id, transform)


@router.put("/tag/{tag_id}/dismissals")
async def put_tag_dismissals(tag_id: int, req: TagDismissalsRequest) -> dict:
    """Overwrite the saved candidate dismissals for a tag (tag-bound mode)."""
    set_tag_dismissals(tag_id, req.dismissals)
    return {"status": "ok"}
