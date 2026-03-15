"""
Tests for review_queue_service using mocked SQLAlchemy sessions.

All tests are fully isolated — no real DB, no real network calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.domain.statuses import Decision, PipelineStatus, ReviewStatus
from app.infra.sa_models import ChartEntry, ReviewResult, ReviewTask


# ---------------------------------------------------------------------------
# Helpers to build lightweight ORM-like objects
# ---------------------------------------------------------------------------


def _make_task(
    task_id: int = 1,
    chart_entry_id: int = 10,
    youtube_video_id_ref: str = "dQw4w9WgXcQ",
    review_status: str = ReviewStatus.pending.value,
    assigned_to: str | None = None,
) -> ReviewTask:
    task = MagicMock(spec=ReviewTask)
    task.id = task_id
    task.chart_entry_id = chart_entry_id
    task.youtube_video_id_ref = youtube_video_id_ref
    task.review_status = review_status
    task.assigned_to = assigned_to
    task.priority = 100
    task.created_at = datetime.now(tz=timezone.utc)
    task.started_at = None
    task.completed_at = None
    return task


def _make_entry(
    entry_id: int = 10,
    pipeline_status: str = PipelineStatus.ready_for_manual_review.value,
) -> ChartEntry:
    entry = MagicMock(spec=ChartEntry)
    entry.id = entry_id
    entry.pipeline_status = pipeline_status
    entry.has_youtube = True
    entry.chart_position = 1
    entry.updated_at = datetime.now(tz=timezone.utc)
    return entry


def _make_session(
    task: ReviewTask | None = None,
    entry: ChartEntry | None = None,
    existing_result: ReviewResult | None = None,
) -> AsyncMock:
    """Return a mock async session wired to return provided ORM objects."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def _execute(stmt):
        mock_result = MagicMock()
        # Determine what the query is for by inspecting the FROM clause.
        # Use "from review_result" to distinguish from queries that merely
        # reference the review_task_id column on review_result rows.
        stmt_str = str(stmt).lower()
        if "from review_result" in stmt_str:
            mock_result.scalar_one_or_none.return_value = existing_result
        elif "from review_task" in stmt_str and task is not None:
            mock_result.scalar_one_or_none.return_value = task
            mock_result.scalars.return_value.all.return_value = [task]
        elif "chart_entry" in stmt_str and entry is not None:
            mock_result.scalar_one_or_none.return_value = entry
        else:
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
        return mock_result

    session.execute = _execute
    return session


# ---------------------------------------------------------------------------
# Patch audit_service to avoid DB writes in tests
# ---------------------------------------------------------------------------

_AUDIT_PATCH = "app.services.review_queue_service.audit_service"


# ---------------------------------------------------------------------------
# test_create_review_task_creates_new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_review_task_creates_new():
    """
    When no approved result exists for the video, a new ReviewTask is created.
    """
    session = _make_session(existing_result=None)

    with patch(_AUDIT_PATCH) as mock_audit:
        mock_audit.review_task_created = AsyncMock()

        from app.services import review_queue_service

        result = await review_queue_service.create_review_task(
            session,
            chart_entry_id=10,
            youtube_video_id_ref="dQw4w9WgXcQ",
        )

    assert result is not None
    session.add.assert_called_once()
    session.flush.assert_called()


# ---------------------------------------------------------------------------
# test_create_review_task_skips_if_approved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_review_task_skips_if_approved():
    """
    When an approved result already exists for the video, returns None (skip).
    """
    existing = MagicMock(spec=ReviewResult)
    existing.decision = Decision.approved.value

    session = _make_session(existing_result=existing)

    with patch(_AUDIT_PATCH):
        from app.services import review_queue_service

        result = await review_queue_service.create_review_task(
            session,
            chart_entry_id=10,
            youtube_video_id_ref="dQw4w9WgXcQ",
        )

    assert result is None
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# test_start_review_sets_in_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_review_sets_in_review():
    """
    start_review sets review_status to in_review, assigned_to, and started_at.
    """
    task = _make_task(review_status=ReviewStatus.pending.value)
    entry = _make_entry()
    session = _make_session(task=task, entry=entry)

    with patch(_AUDIT_PATCH) as mock_audit:
        mock_audit.review_started = AsyncMock()

        from app.services import review_queue_service

        returned_task = await review_queue_service.start_review(
            session, task_id=1, operator_id="alice"
        )

    assert returned_task.review_status == ReviewStatus.in_review.value
    assert returned_task.assigned_to == "alice"
    assert returned_task.started_at is not None


# ---------------------------------------------------------------------------
# test_approve_creates_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_creates_result():
    """
    approve() creates a ReviewResult with decision 'approved'.
    """
    task = _make_task(review_status=ReviewStatus.in_review.value, assigned_to="alice")
    entry = _make_entry()
    session = _make_session(task=task, entry=entry)

    with patch(_AUDIT_PATCH) as mock_audit:
        mock_audit.review_approved = AsyncMock()

        from app.services import review_queue_service

        result = await review_queue_service.approve(
            session,
            task_id=1,
            operator_id="alice",
            final_artist="Omer Adam",
            final_song_title="Lev Sheli",
            final_lyrics_text="some lyrics",
        )

    assert result.decision == Decision.approved.value
    assert result.operator_id == "alice"
    assert result.final_artist == "Omer Adam"
    assert result.final_song_title == "Lev Sheli"
    session.add.assert_called()


# ---------------------------------------------------------------------------
# test_approve_with_edits_creates_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_with_edits_creates_result():
    """
    approve_with_edits() creates a ReviewResult with decision 'approved_with_edits'.
    """
    task = _make_task(review_status=ReviewStatus.in_review.value, assigned_to="bob")
    entry = _make_entry()
    session = _make_session(task=task, entry=entry)

    with patch(_AUDIT_PATCH) as mock_audit:
        mock_audit.review_approved_with_edits = AsyncMock()

        from app.services import review_queue_service

        result = await review_queue_service.approve_with_edits(
            session,
            task_id=1,
            operator_id="bob",
            final_artist="Noa Kirel",
            final_song_title="Unicorn (edited)",
            final_lyrics_text="edited lyrics",
        )

    assert result.decision == Decision.approved_with_edits.value
    assert result.operator_id == "bob"


# ---------------------------------------------------------------------------
# test_reject_creates_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_creates_result():
    """
    reject() creates a ReviewResult with decision 'rejected'.
    """
    task = _make_task(review_status=ReviewStatus.in_review.value)
    entry = _make_entry()
    session = _make_session(task=task, entry=entry)

    with patch(_AUDIT_PATCH) as mock_audit:
        mock_audit.review_rejected = AsyncMock()

        from app.services import review_queue_service

        result = await review_queue_service.reject(
            session,
            task_id=1,
            operator_id="charlie",
            review_notes="Not relevant",
        )

    assert result.decision == Decision.rejected.value
    assert result.review_notes == "Not relevant"


# ---------------------------------------------------------------------------
# test_no_useful_text_creates_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_useful_text_creates_result():
    """
    no_useful_text() creates a ReviewResult with decision 'no_useful_text'.
    """
    task = _make_task(review_status=ReviewStatus.pending.value)
    entry = _make_entry()
    session = _make_session(task=task, entry=entry)

    with patch(_AUDIT_PATCH) as mock_audit:
        mock_audit.review_no_useful_text = AsyncMock()

        from app.services import review_queue_service

        result = await review_queue_service.no_useful_text(
            session,
            task_id=1,
            operator_id="dave",
            review_notes="Description is promotional only",
        )

    assert result.decision == Decision.no_useful_text.value
    assert result.operator_id == "dave"
