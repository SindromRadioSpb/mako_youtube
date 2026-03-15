"""
Admin API router — metrics and operational tooling.
"""
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.statuses import Decision, PipelineStatus
from app.infra.sa_models import (
    ChartEntry,
    ChartSnapshot,
    ReviewResult,
    ReviewTask,
    YouTubeVideo,
    async_session_factory,
)
from app.services import youtube_metadata_service
from app.services import mako_chart_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_session() -> AsyncSession:  # type: ignore[return]
    async with async_session_factory() as session:
        async with session.begin():
            yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _count(session: AsyncSession, model: Any, where=None) -> int:
    stmt = select(func.count()).select_from(model)
    if where is not None:
        stmt = stmt.where(where)
    result = await session.execute(stmt)
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/metrics",
    summary="Pipeline metrics and review queue counts",
)
async def get_metrics(session: AsyncSession = Depends(get_session)) -> Dict[str, Any]:
    """
    Returns aggregate pipeline metrics:
    - counts of snapshots, entries, YouTube presence rates
    - metadata fetch success rate
    - review queue breakdown
    """
    total_snapshots = await _count(session, ChartSnapshot)
    total_entries = await _count(session, ChartEntry)

    youtube_present = await _count(session, ChartEntry, ChartEntry.has_youtube.is_(True))
    youtube_missing = await _count(session, ChartEntry, ChartEntry.has_youtube.is_(False))

    total_videos = await _count(session, YouTubeVideo)
    metadata_ok = await _count(
        session, YouTubeVideo, YouTubeVideo.fetch_status == "ok"
    )
    metadata_failed = await _count(
        session, YouTubeVideo, YouTubeVideo.fetch_status == "failed"
    )

    pending_count = await _count(session, ReviewTask, ReviewTask.review_status == "pending")
    in_review_count = await _count(session, ReviewTask, ReviewTask.review_status == "in_review")

    approved_count = await _count(
        session, ReviewResult, ReviewResult.decision == Decision.approved.value
    )
    approved_edits_count = await _count(
        session, ReviewResult, ReviewResult.decision == Decision.approved_with_edits.value
    )
    rejected_count = await _count(
        session, ReviewResult, ReviewResult.decision == Decision.rejected.value
    )
    no_useful_text_count = await _count(
        session, ReviewResult, ReviewResult.decision == Decision.no_useful_text.value
    )

    youtube_present_rate = (
        round(youtube_present / total_entries, 4) if total_entries else 0.0
    )
    youtube_missing_rate = (
        round(youtube_missing / total_entries, 4) if total_entries else 0.0
    )
    metadata_success_rate = (
        round(metadata_ok / total_videos, 4) if total_videos else 0.0
    )

    return {
        "total_snapshots": total_snapshots,
        "total_entries": total_entries,
        "youtube_present": youtube_present,
        "youtube_missing": youtube_missing,
        "youtube_present_rate": youtube_present_rate,
        "youtube_missing_rate": youtube_missing_rate,
        "total_youtube_videos": total_videos,
        "metadata_fetch_ok": metadata_ok,
        "metadata_fetch_failed": metadata_failed,
        "metadata_fetch_success_rate": metadata_success_rate,
        "pending_count": pending_count,
        "in_review_count": in_review_count,
        "approved_count": approved_count,
        "approved_with_edits_count": approved_edits_count,
        "rejected_count": rejected_count,
        "no_useful_text_count": no_useful_text_count,
    }


@router.post(
    "/reprocess/{chart_entry_id}",
    summary="Re-fetch YouTube metadata for a chart entry",
)
async def reprocess_entry(
    chart_entry_id: int,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """
    Re-fetches YouTube metadata for a specific chart entry.  Useful when a
    previous fetch failed or returned stale data.

    Raises 404 if the chart entry does not exist or has no YouTube URL.
    """
    from sqlalchemy import select as sa_select
    result = await session.execute(
        sa_select(ChartEntry).where(ChartEntry.id == chart_entry_id)
    )
    entry: ChartEntry | None = result.scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ChartEntry {chart_entry_id} not found",
        )

    if not entry.has_youtube or not entry.youtube_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ChartEntry {chart_entry_id} has no YouTube URL",
        )

    try:
        video = await youtube_metadata_service.fetch_metadata(session, entry.youtube_url)
    except (ValueError, RuntimeError) as exc:
        log.error(
            "reprocess_entry_failed",
            chart_entry_id=chart_entry_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Metadata re-fetch failed: {exc}",
        )

    return {
        "chart_entry_id": chart_entry_id,
        "youtube_video_id": video.youtube_video_id,
        "fetch_status": video.fetch_status,
        "video_title": video.video_title,
    }
