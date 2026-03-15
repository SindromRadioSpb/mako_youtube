"""
Review queue API router.
"""
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dto import (
    ChartEntryDTO,
    ReviewDecisionRequest,
    ReviewResultDTO,
    ReviewTaskDTO,
    ReviewTaskDetailResponse,
    ReviewTaskListResponse,
    ReviewTaskSummary,
    YouTubeVideoDTO,
)
from app.infra.sa_models import ChartEntry, ReviewTask, YouTubeVideo, async_session_factory
from app.services import review_queue_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/review", tags=["review"])


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


async def _enrich_task_summary(session: AsyncSession, task: ReviewTask) -> ReviewTaskSummary:
    """Build a ReviewTaskSummary by joining with ChartEntry data."""
    entry_result = await session.execute(
        select(ChartEntry).where(ChartEntry.id == task.chart_entry_id)
    )
    entry: Optional[ChartEntry] = entry_result.scalar_one_or_none()

    return ReviewTaskSummary(
        id=task.id,
        chart_entry_id=task.chart_entry_id,
        youtube_video_id_ref=task.youtube_video_id_ref,
        review_status=task.review_status,  # type: ignore[arg-type]
        assigned_to=task.assigned_to,
        priority=task.priority,
        created_at=task.created_at,
        chart_position=entry.chart_position if entry else None,
        artist_raw=entry.artist_raw if entry else None,
        song_title_raw=entry.song_title_raw if entry else None,
        has_youtube=entry.has_youtube if entry else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/tasks",
    response_model=ReviewTaskListResponse,
    summary="List review tasks, optionally filtered by status",
)
async def list_tasks(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
) -> ReviewTaskListResponse:
    tasks = await review_queue_service.list_tasks(session, status=status_filter)
    summaries = [await _enrich_task_summary(session, t) for t in tasks]
    return ReviewTaskListResponse(items=summaries, total=len(summaries))


@router.get(
    "/tasks/{task_id}",
    response_model=ReviewTaskDetailResponse,
    summary="Get a single review task with full detail",
)
async def get_task(
    task_id: int,
    session: AsyncSession = Depends(get_session),
) -> ReviewTaskDetailResponse:
    task = await review_queue_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    entry_result = await session.execute(
        select(ChartEntry).where(ChartEntry.id == task.chart_entry_id)
    )
    entry = entry_result.scalar_one_or_none()

    yt_result = await session.execute(
        select(YouTubeVideo).where(YouTubeVideo.youtube_video_id == task.youtube_video_id_ref)
    )
    yt_video = yt_result.scalar_one_or_none()

    return ReviewTaskDetailResponse(
        task_id=task.id,
        review_status=task.review_status,
        chart_entry=ChartEntryDTO.model_validate(entry) if entry else None,
        youtube_video=YouTubeVideoDTO.model_validate(yt_video) if yt_video else None,
    )


@router.post(
    "/tasks/{task_id}/start",
    response_model=ReviewTaskDTO,
    summary="Start reviewing a task (claim it for an operator)",
)
async def start_review(
    task_id: int,
    body: dict,  # {operator_id: str}
    session: AsyncSession = Depends(get_session),
) -> ReviewTaskDTO:
    operator_id: str = body.get("operator_id", "")
    if not operator_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="operator_id is required",
        )
    try:
        task = await review_queue_service.start_review(session, task_id, operator_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return ReviewTaskDTO.model_validate(task)


@router.post(
    "/tasks/{task_id}/approve",
    response_model=ReviewResultDTO,
    summary="Approve a review task",
)
async def approve_task(
    task_id: int,
    body: ReviewDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResultDTO:
    try:
        result = await review_queue_service.approve(
            session,
            task_id=task_id,
            operator_id=body.operator_id,
            final_artist=body.final_artist,
            final_song_title=body.final_song_title,
            final_lyrics_text=body.final_lyrics_text,
            review_notes=body.review_notes,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return ReviewResultDTO.model_validate(result)


@router.post(
    "/tasks/{task_id}/approve-edited",
    response_model=ReviewResultDTO,
    summary="Approve a review task with edits",
)
async def approve_task_with_edits(
    task_id: int,
    body: ReviewDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResultDTO:
    try:
        result = await review_queue_service.approve_with_edits(
            session,
            task_id=task_id,
            operator_id=body.operator_id,
            final_artist=body.final_artist,
            final_song_title=body.final_song_title,
            final_lyrics_text=body.final_lyrics_text,
            review_notes=body.review_notes,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return ReviewResultDTO.model_validate(result)


@router.post(
    "/tasks/{task_id}/reject",
    response_model=ReviewResultDTO,
    summary="Reject a review task",
)
async def reject_task(
    task_id: int,
    body: dict,  # {operator_id: str, review_notes: str|None}
    session: AsyncSession = Depends(get_session),
) -> ReviewResultDTO:
    operator_id: str = body.get("operator_id", "")
    if not operator_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="operator_id is required",
        )
    try:
        result = await review_queue_service.reject(
            session,
            task_id=task_id,
            operator_id=operator_id,
            review_notes=body.get("review_notes"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return ReviewResultDTO.model_validate(result)


@router.post(
    "/tasks/{task_id}/mark-no-useful-text",
    response_model=ReviewResultDTO,
    summary="Mark a review task as having no useful text",
)
async def mark_no_useful_text(
    task_id: int,
    body: dict,  # {operator_id: str, review_notes: str|None}
    session: AsyncSession = Depends(get_session),
) -> ReviewResultDTO:
    operator_id: str = body.get("operator_id", "")
    if not operator_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="operator_id is required",
        )
    try:
        result = await review_queue_service.no_useful_text(
            session,
            task_id=task_id,
            operator_id=operator_id,
            review_notes=body.get("review_notes"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return ReviewResultDTO.model_validate(result)
