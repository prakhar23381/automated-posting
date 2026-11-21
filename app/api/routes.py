"""HTTP routes."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request

from app.errors import AppError
from app.schemas import (
    ErrorDetail,
    ErrorResponse,
    PlatformInfo,
    PostingResponse,
    PostRequest,
)
from app.services.posting_service import PostingService

router = APIRouter()


def get_posting_service(request: Request) -> PostingService:
    return request.app.state.posting_service


ServiceDep = Annotated[PostingService, Depends(get_posting_service)]


async def _ensure_link_reachable(request: Request, link: str) -> None:
    """Optional check (VERIFY_LINK_REACHABLE=true): the CTA link must answer a HEAD/GET."""
    client: httpx.AsyncClient = request.app.state.public_client
    try:
        response = await client.head(link, follow_redirects=True, timeout=5.0)
        if response.status_code == 405:
            response = await client.get(link, follow_redirects=True, timeout=5.0)
        reachable = response.status_code < 400
    except httpx.HTTPError:
        reachable = False
    if not reachable:
        message = "CTA link is not reachable"
        detail = ErrorDetail(field="message", message=message, type="link_unreachable")
        raise AppError(422, "validation_error", message, [detail])


@router.post(
    "/posting",
    response_model=PostingResponse,
    summary="Publish a message to every configured platform",
    description=(
        "Validates the message (max 200 characters, exactly one http(s) CTA link), then "
        "publishes it to all configured platforms concurrently. One platform failing never "
        "stops the others. Returns 200 with per-platform results whenever the request is "
        "valid; `success` is true when at least one platform succeeded."
    ),
    responses={422: {"model": ErrorResponse, "description": "Invalid message"}},
    tags=["posting"],
)
async def create_posting(
    body: PostRequest,
    request: Request,
    service: ServiceDep,
) -> PostingResponse:
    link = body.cta_link
    if service.settings.verify_link_reachable:
        await _ensure_link_reachable(request, link)
    return await service.post(body.message, link)


@router.get(
    "/platforms",
    response_model=list[PlatformInfo],
    summary="List integrated platforms and whether each has credentials",
    tags=["posting"],
)
async def list_platforms(
    service: ServiceDep,
) -> list[PlatformInfo]:
    return service.describe_platforms()


@router.get("/health", summary="Liveness check", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
