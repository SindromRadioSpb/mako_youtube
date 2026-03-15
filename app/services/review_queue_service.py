"""
Review queue service for the OpenClaw Mako YouTube pipeline.

Manages ReviewTask and ReviewResult lifecycle, enforces dedup logic,
and coordinates pipeline status updates on ChartEntry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.statuses import Decision, PipelineStatus, ReviewStatus
from app.infra.sa_models import ChartEntry, ReviewResult, ReviewTask
from app.services import audit_service

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------


async def create_review_task(
    session: AsyncSession,
    chart_entry_id: int,
    youtube_video_id_ref: str,
    priority: int = 100,
) -> Optional[ReviewTask]:
    """
    Create a new ReviewTask for the given chart_entry_id / youtube_video_id_ref
    pair, unless an approved or approved_with_edits result already exists for
    this YouTube video — in which case the call is a no-op and returns None.

    Returns:
        The newly created ReviewTask, or None if skipped due to dedup.
    """
    # Dedup: check for an existing positive review result for this video
    dedup_result = await session.execute(
        select(ReviewResult)
        .join(ReviewTask, ReviewTask.id == ReviewResult.review_task_id)
        .where(ReviewTask.youtube_video_id_ref == youtube_video_id_ref)
        .where(
            ReviewResult.decision.in_(
                [Decision.approved.value, Decision.approved_with_edits.value]
            )
        )
        .limit(1)
    )
    if dedup_result.scalar_one_or_none() is not None:
        log.info(
            "review_task_skipped_dedup",
            chart_entry_id=chart_entry_id,
            youtube_video_id_ref=youtube_video_id_ref,
        )
        return None

    task = ReviewTask(
        chart_entry_id=chart_entry_id,
        youtube_video_id_ref=youtube_video_id_ref,
        review_status=ReviewStatus.pending.value,
        priority=priority,
        created_at=datetime.now(tz=timezone.utc),
    )
    session.add(task)
    await session.flush()

    await audit_service.review_task_created(
        session,
        task_id=task.id,
        chart_entry_id=chart_entry_id,
        youtube_video_id_ref=youtube_video_id_ref,
    )

    log.info(
        "review_task_created",
        task_id=task.id,
        chart_entry_id=chart_entry_id,
        youtube_video_id_ref=youtube_video_id_ref,
    )
    return task


# ---------------------------------------------------------------------------
# Task querying
# ---------------------------------------------------------------------------


async def list_tasks(
    session: AsyncSession,
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[ReviewTask]:
    """
    Return ReviewTask rows, optionally filtered by review_status.
    """
    stmt = select(ReviewTask).order_by(ReviewTask.priority.asc(), ReviewTask.created_at.asc())
    if status is not None:
        stmt = stmt.where(ReviewTask.review_status == status)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_task(session: AsyncSession, task_id: int) -> Optional[ReviewTask]:
    """Return a single ReviewTask by primary key, or None."""
    result = await session.execute(
        select(ReviewTask).where(ReviewTask.id == task_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Workflow transitions
# ---------------------------------------------------------------------------


async def start_review(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
) -> ReviewTask:
    """
    Claim a pending task for an operator.

    Raises:
        ValueError: if task not found, already claimed by another operator,
                    or not in a startable state.
    """
    task = await _get_task_or_raise(session, task_id)

    if task.review_status not in (ReviewStatus.pending.value, ReviewStatus.in_review.value):
        raise ValueError(
            f"Cannot start review for task {task_id}: "
            f"current status is {task.review_status!r}"
        )

    if (
        task.review_status == ReviewStatus.in_review.value
        and task.assigned_to
        and task.assigned_to != operator_id
    ):
        raise ValueError(
            f"Task {task_id} is already assigned to {task.assigned_to!r}"
        )

    task.review_status = ReviewStatus.in_review.value
    task.assigned_to = operator_id
    task.started_at = task.started_at or datetime.now(tz=timezone.utc)

    await _update_entry_status(session, task.chart_entry_id, PipelineStatus.in_manual_review)
    await session.flush()

    await audit_service.review_started(session, task_id=task_id, operator_id=operator_id)
    return task


async def approve(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    final_artist: Optional[str] = None,
    final_song_title: Optional[str] = None,
    final_lyrics_text: Optional[str] = None,
    review_notes: Optional[str] = None,
) -> ReviewResult:
    """Mark a task as approved and create a ReviewResult."""
    return await _complete_task(
        session,
        task_id=task_id,
        operator_id=operator_id,
        decision=Decision.approved,
        review_status=ReviewStatus.approved,
        pipeline_status=PipelineStatus.approved,
        final_artist=final_artist,
        final_song_title=final_song_title,
        final_lyrics_text=final_lyrics_text,
        review_notes=review_notes,
    )


async def approve_with_edits(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    final_artist: Optional[str] = None,
    final_song_title: Optional[str] = None,
    final_lyrics_text: Optional[str] = None,
    review_notes: Optional[str] = None,
) -> ReviewResult:
    """Mark a task as approved with edits and create a ReviewResult."""
    return await _complete_task(
        session,
        task_id=task_id,
        operator_id=operator_id,
        decision=Decision.approved_with_edits,
        review_status=ReviewStatus.approved_with_edits,
        pipeline_status=PipelineStatus.approved_with_edits,
        final_artist=final_artist,
        final_song_title=final_song_title,
        final_lyrics_text=final_lyrics_text,
        review_notes=review_notes,
    )


async def reject(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    review_notes: Optional[str] = None,
) -> ReviewResult:
    """Mark a task as rejected and create a ReviewResult."""
    return await _complete_task(
        session,
        task_id=task_id,
        operator_id=operator_id,
        decision=Decision.rejected,
        review_status=ReviewStatus.rejected,
        pipeline_status=PipelineStatus.rejected,
        review_notes=review_notes,
    )


async def no_useful_text(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    review_notes: Optional[str] = None,
) -> ReviewResult:
    """Mark a task as having no useful text and create a ReviewResult."""
    return await _complete_task(
        session,
        task_id=task_id,
        operator_id=operator_id,
        decision=Decision.no_useful_text,
        review_status=ReviewStatus.no_useful_text,
        pipeline_status=PipelineStatus.no_useful_text,
        review_notes=review_notes,
    )


async def reopen_task(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
) -> ReviewTask:
    """
    Reopen a terminal review task for re-editing.

    Transitions the task back to in_review and resets completed_at so the
    operator can submit a new decision.  The existing ReviewResult rows are
    preserved as audit history.

    Raises:
        LookupError: task not found.
        ValueError:  task is not in a terminal state.
    """
    task = await _get_task_or_raise(session, task_id)

    _TERMINAL = (
        ReviewStatus.approved.value,
        ReviewStatus.approved_with_edits.value,
        ReviewStatus.rejected.value,
        ReviewStatus.no_useful_text.value,
    )
    if task.review_status not in _TERMINAL:
        raise ValueError(
            f"Task {task_id} cannot be reopened: "
            f"current status is {task.review_status!r} (must be a terminal state)"
        )

    previous_status = task.review_status
    task.review_status = ReviewStatus.in_review.value
    task.assigned_to = operator_id
    task.completed_at = None

    await _update_entry_status(session, task.chart_entry_id, PipelineStatus.in_manual_review)
    await session.flush()

    await audit_service.review_reopened(
        session,
        task_id=task_id,
        operator_id=operator_id,
        previous_status=previous_status,
    )
    return task


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _complete_task(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    decision: Decision,
    review_status: ReviewStatus,
    pipeline_status: PipelineStatus,
    final_artist: Optional[str] = None,
    final_song_title: Optional[str] = None,
    final_lyrics_text: Optional[str] = None,
    review_notes: Optional[str] = None,
) -> ReviewResult:
    task = await _get_task_or_raise(session, task_id)

    if task.review_status not in (
        ReviewStatus.pending.value,
        ReviewStatus.in_review.value,
    ):
        raise ValueError(
            f"Task {task_id} cannot be completed: "
            f"current status is {task.review_status!r}"
        )

    task.review_status = review_status.value
    task.assigned_to = task.assigned_to or operator_id
    task.completed_at = datetime.now(tz=timezone.utc)

    result = ReviewResult(
        review_task_id=task_id,
        operator_id=operator_id,
        final_artist=final_artist,
        final_song_title=final_song_title,
        final_lyrics_text=final_lyrics_text,
        decision=decision.value,
        review_notes=review_notes,
        reviewed_at=datetime.now(tz=timezone.utc),
    )
    session.add(result)

    await _update_entry_status(session, task.chart_entry_id, pipeline_status)
    await session.flush()

    # Emit specific audit event based on decision
    if decision == Decision.approved:
        await audit_service.review_approved(
            session, task_id=task_id, operator_id=operator_id,
            final_artist=final_artist, final_song_title=final_song_title,
        )
    elif decision == Decision.approved_with_edits:
        await audit_service.review_approved_with_edits(
            session, task_id=task_id, operator_id=operator_id,
            final_artist=final_artist, final_song_title=final_song_title,
        )
    elif decision == Decision.rejected:
        await audit_service.review_rejected(
            session, task_id=task_id, operator_id=operator_id, review_notes=review_notes
        )
    elif decision == Decision.no_useful_text:
        await audit_service.review_no_useful_text(
            session, task_id=task_id, operator_id=operator_id, review_notes=review_notes
        )

    log.info(
        "review_task_completed",
        task_id=task_id,
        decision=decision.value,
        operator_id=operator_id,
    )
    return result


async def _get_task_or_raise(session: AsyncSession, task_id: int) -> ReviewTask:
    task = await get_task(session, task_id)
    if task is None:
        raise LookupError(f"ReviewTask {task_id} not found")
    return task


async def _update_entry_status(
    session: AsyncSession,
    chart_entry_id: int,
    new_status: PipelineStatus,
) -> None:
    result = await session.execute(
        select(ChartEntry).where(ChartEntry.id == chart_entry_id)
    )
    entry: Optional[ChartEntry] = result.scalar_one_or_none()
    if entry is not None:
        entry.pipeline_status = new_status.value
        entry.updated_at = datetime.now(tz=timezone.utc)
