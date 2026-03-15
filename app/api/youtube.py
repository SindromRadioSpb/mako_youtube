"""
YouTube metadata API router.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dto import YouTubeMetadataRequest, YouTubeMetadataResponse
from app.domain.statuses import FetchStatus
from app.infra.sa_models import async_session_factory
from app.services import youtube_metadata_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_session() -> AsyncSession:  # type: ignore[return]
    async with async_session_factory() as session:
        async with session.begin():
            yield session


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/fetch-metadata",
    response_model=YouTubeMetadataResponse,
    summary="Fetch and cache YouTube video metadata",
)
async def fetch_youtube_metadata(
    body: YouTubeMetadataRequest,
    session: AsyncSession = Depends(get_session),
) -> YouTubeMetadataResponse:
    """
    Extract the YouTube video ID from the provided URL, fetch metadata via
    yt-dlp, and persist / return the result.  Idempotent — subsequent calls
    for the same video ID return the cached record without re-fetching.
    """
    try:
        video = await youtube_metadata_service.fetch_metadata(session, body.youtube_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RuntimeError as exc:
        log.error(
            "fetch_youtube_metadata_endpoint_error",
            youtube_url=body.youtube_url,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Metadata fetch failed: {exc}",
        )

    return YouTubeMetadataResponse(
        youtube_video_id=video.youtube_video_id,
        canonical_url=video.canonical_url,
        video_title=video.video_title,
        channel_title=video.channel_title,
        description_raw=video.description_raw,
        published_at=video.published_at,
        fetch_status=FetchStatus(video.fetch_status),
    )
