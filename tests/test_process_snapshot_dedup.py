"""
Unit tests for the cross-snapshot dedup logic in process_snapshot.

Covers:
  - Named entries (artist + title): deduplicated across snapshots by artist_norm/song_title_norm.
  - Empty slots (no artist, no title): deduplicated across snapshots by chart_position.
  - New entries (no prior task): task is always created.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.statuses import PipelineStatus
from app.infra.sa_models import ChartEntry, ChartSnapshot, ReviewTask


# ---------------------------------------------------------------------------
# Session factory for process_snapshot tests
# ---------------------------------------------------------------------------


def _make_chart_entry(
    entry_id: int = 1,
    snapshot_id: int = 10,
    chart_position: int = 1,
    artist_raw: str | None = "Omer Adam",
    song_title_raw: str | None = "Lev Sheli",
    artist_norm: str | None = "omer adam",
    song_title_norm: str | None = "lev sheli",
    youtube_url: str | None = None,
    has_youtube: bool = False,
) -> ChartEntry:
    e = MagicMock(spec=ChartEntry)
    e.id = entry_id
    e.snapshot_id = snapshot_id
    e.chart_position = chart_position
    e.artist_raw = artist_raw
    e.song_title_raw = song_title_raw
    e.artist_norm = artist_norm
    e.song_title_norm = song_title_norm
    e.youtube_url = youtube_url
    e.has_youtube = has_youtube
    e.pipeline_status = PipelineStatus.youtube_missing.value
    e.updated_at = datetime.now(tz=timezone.utc)
    return e


def _make_snapshot(snapshot_id: int = 10) -> ChartSnapshot:
    s = MagicMock(spec=ChartSnapshot)
    s.id = snapshot_id
    s.raw_payload_json = {
        "entries": [],
        "count": 0,
    }
    return s


def _session_for_process(
    snapshot: ChartSnapshot,
    existing_task: ReviewTask | None = None,
) -> AsyncMock:
    """Return a mock session wired for process_snapshot calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def _execute(stmt):
        mock_result = MagicMock()
        stmt_str = str(stmt).lower()
        if "chart_snapshot" in stmt_str:
            mock_result.scalar_one_or_none.return_value = snapshot
        elif "review_task" in stmt_str or "chart_entry" in stmt_str:
            mock_result.scalar_one_or_none.return_value = existing_task
            mock_result.scalars.return_value.all.return_value = (
                [existing_task] if existing_task else []
            )
        else:
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
        return mock_result

    session.execute = _execute
    return session


# ---------------------------------------------------------------------------
# Tests for the dedup helper paths in process_snapshot
# ---------------------------------------------------------------------------


_CHART_SVC = "app.services.mako_chart_service"
_RQS = "app.services.review_queue_service"
_YT_SVC = "app.services.youtube_metadata_service"


@pytest.mark.asyncio
async def test_named_entry_dedup_skips_when_task_exists():
    """
    When an entry with artist+title already has a ReviewTask across any snapshot,
    process_snapshot must NOT create a second task.
    """
    snapshot_id = 10
    raw_entry = {
        "position": 5,
        "artist_raw": "Omer Adam",
        "song_title_raw": "Lev Sheli",
        "youtube_url": None,
    }
    snapshot = _make_snapshot(snapshot_id)
    snapshot.raw_payload_json = {"entries": [raw_entry], "count": 1}

    entry = _make_chart_entry(
        entry_id=99,
        snapshot_id=snapshot_id,
        chart_position=5,
        artist_raw="Omer Adam",
        song_title_raw="Lev Sheli",
        artist_norm="omer adam",
        song_title_norm="lev sheli",
        has_youtube=False,
    )
    existing_task = MagicMock(spec=ReviewTask)
    existing_task.id = 42

    session = _session_for_process(snapshot=snapshot, existing_task=existing_task)

    with (
        patch(f"{_CHART_SVC}._parse_entry", new=AsyncMock(return_value=entry)),
        patch(f"{_CHART_SVC}.audit_service"),
        patch(f"{_RQS}.create_review_task", new=AsyncMock(return_value=None)) as mock_create,
        patch(f"{_YT_SVC}.fetch_metadata", new=AsyncMock(side_effect=Exception("no yt"))),
    ):
        from app.services.mako_chart_service import process_snapshot
        result = await process_snapshot(session, snapshot_id)

    # Task creation must NOT have been attempted (dedup fired first in process_snapshot)
    mock_create.assert_not_called()
    assert result["tasks_created"] == 0


@pytest.mark.asyncio
async def test_empty_slot_dedup_skips_when_task_exists():
    """
    When an empty slot (no artist, no title) already has a ReviewTask for that
    chart_position, process_snapshot must NOT create a second task.
    """
    snapshot_id = 10
    raw_entry = {
        "position": 32,
        "artist_raw": None,
        "song_title_raw": None,
        "youtube_url": None,
    }
    snapshot = _make_snapshot(snapshot_id)
    snapshot.raw_payload_json = {"entries": [raw_entry], "count": 1}

    entry = _make_chart_entry(
        entry_id=99,
        snapshot_id=snapshot_id,
        chart_position=32,
        artist_raw=None,
        song_title_raw=None,
        artist_norm=None,
        song_title_norm=None,
        has_youtube=False,
    )
    existing_task = MagicMock(spec=ReviewTask)
    existing_task.id = 77

    session = _session_for_process(snapshot=snapshot, existing_task=existing_task)

    with (
        patch(f"{_CHART_SVC}._parse_entry", new=AsyncMock(return_value=entry)),
        patch(f"{_CHART_SVC}.audit_service"),
        patch(f"{_RQS}.create_review_task", new=AsyncMock(return_value=None)) as mock_create,
        patch(f"{_YT_SVC}.fetch_metadata", new=AsyncMock(side_effect=Exception("no yt"))),
    ):
        from app.services.mako_chart_service import process_snapshot
        result = await process_snapshot(session, snapshot_id)

    mock_create.assert_not_called()
    assert result["tasks_created"] == 0


@pytest.mark.asyncio
async def test_empty_slot_creates_task_when_none_exists():
    """
    When an empty slot has NO existing task, process_snapshot creates one.
    """
    snapshot_id = 10
    raw_entry = {
        "position": 32,
        "artist_raw": None,
        "song_title_raw": None,
        "youtube_url": None,
    }
    snapshot = _make_snapshot(snapshot_id)
    snapshot.raw_payload_json = {"entries": [raw_entry], "count": 1}

    entry = _make_chart_entry(
        entry_id=99,
        snapshot_id=snapshot_id,
        chart_position=32,
        artist_raw=None,
        song_title_raw=None,
        artist_norm=None,
        song_title_norm=None,
        has_youtube=False,
    )
    new_task = MagicMock(spec=ReviewTask)
    new_task.id = 55

    session = _session_for_process(snapshot=snapshot, existing_task=None)

    with (
        patch(f"{_CHART_SVC}._parse_entry", new=AsyncMock(return_value=entry)),
        patch(f"{_CHART_SVC}.audit_service"),
        patch(f"{_RQS}.create_review_task", new=AsyncMock(return_value=new_task)) as mock_create,
        patch(f"{_YT_SVC}.fetch_metadata", new=AsyncMock(side_effect=Exception("no yt"))),
    ):
        from app.services.mako_chart_service import process_snapshot
        result = await process_snapshot(session, snapshot_id)

    mock_create.assert_called_once()
    assert result["tasks_created"] == 1
