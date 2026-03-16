"""
Pydantic v2 Data Transfer Objects for the OpenClaw Mako YouTube pipeline.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.domain.statuses import (
    Decision,
    FetchStatus,
    PipelineStatus,
    ReviewStatus,
)


# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------

class _BaseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Core entity DTOs
# ---------------------------------------------------------------------------

class ChartSnapshotDTO(_BaseDTO):
    id: int
    source_name: str
    source_url: str
    snapshot_date: date
    fetched_at: datetime
    status: str
    scraper_version: Optional[str] = None
    notes: Optional[str] = None


class ChartEntryDTO(_BaseDTO):
    id: int
    snapshot_id: int
    chart_position: int
    artist_raw: Optional[str] = None
    song_title_raw: Optional[str] = None
    artist_norm: Optional[str] = None
    song_title_norm: Optional[str] = None
    youtube_url: Optional[str] = None
    youtube_video_id: Optional[str] = None
    has_youtube: bool = False
    pipeline_status: PipelineStatus
    created_at: datetime
    updated_at: datetime


class YouTubeVideoDTO(_BaseDTO):
    id: int
    youtube_video_id: str
    canonical_url: str
    video_title: Optional[str] = None
    channel_title: Optional[str] = None
    description_raw: Optional[str] = None
    published_at: Optional[datetime] = None
    metadata_fetched_at: Optional[datetime] = None
    fetch_status: FetchStatus
    fetch_error: Optional[str] = None
    fetcher_version: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReviewTaskDTO(_BaseDTO):
    id: int
    chart_entry_id: int
    youtube_video_id_ref: Optional[str] = None
    review_status: ReviewStatus
    assigned_to: Optional[str] = None
    priority: int = 100
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ReviewResultDTO(_BaseDTO):
    id: int
    review_task_id: int
    operator_id: Optional[str] = None
    final_artist: Optional[str] = None
    final_song_title: Optional[str] = None
    final_lyrics_text: Optional[str] = None
    decision: Decision
    review_notes: Optional[str] = None
    reviewed_at: datetime


class AuditEventDTO(_BaseDTO):
    id: int
    entity_type: str
    entity_id: str
    event_type: str
    event_payload_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Request / Response DTOs
# ---------------------------------------------------------------------------

class FetchChartResponse(BaseModel):
    snapshot_id: int
    status: str
    entries_discovered: int


class ProcessSnapshotResponse(BaseModel):
    snapshot_id: int
    processed_entries: int
    youtube_found: int
    youtube_missing: int


class YouTubeMetadataRequest(BaseModel):
    youtube_url: str


class YouTubeMetadataResponse(BaseModel):
    youtube_video_id: str
    canonical_url: str
    video_title: Optional[str] = None
    channel_title: Optional[str] = None
    description_raw: Optional[str] = None
    published_at: Optional[datetime] = None
    fetch_status: FetchStatus


# ---------------------------------------------------------------------------
# Review task list / detail
# ---------------------------------------------------------------------------

class ReviewTaskSummary(BaseModel):
    """Lightweight summary used in list responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    chart_entry_id: int
    youtube_video_id_ref: Optional[str] = None
    review_status: ReviewStatus
    assigned_to: Optional[str] = None
    priority: int
    created_at: datetime

    # Denormalised fields from ChartEntry for convenience in the UI
    chart_position: Optional[int] = None
    artist_raw: Optional[str] = None
    song_title_raw: Optional[str] = None
    has_youtube: Optional[bool] = None


class ReviewTaskListResponse(BaseModel):
    items: List[ReviewTaskSummary]
    total: int = Field(default=0)


class ReviewDecisionRequest(BaseModel):
    """
    Body for approve / approve-edited / reject / no-useful-text endpoints.

    *operator_id* is the only required field.  The text fields are optional
    for reject/no_useful_text decisions but should be supplied for approve*.
    """
    operator_id: str
    final_artist: Optional[str] = None
    final_song_title: Optional[str] = None
    final_lyrics_text: Optional[str] = None
    review_notes: Optional[str] = None


class SetYouTubeRequest(BaseModel):
    """Body for the set-youtube endpoint."""
    youtube_url: str
    operator_id: str


class ReviewTaskDetailResponse(BaseModel):
    """Enriched task detail as per API contract §15.5."""
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    review_status: str
    chart_entry: Optional[ChartEntryDTO] = None
    youtube_video: Optional[YouTubeVideoDTO] = None
    latest_result: Optional[ReviewResultDTO] = None  # populated when task has been reviewed


class ExportItemDTO(BaseModel):
    """Lightweight DTO for unified Word export."""
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    chart_position: Optional[int] = None
    review_status: str
    final_artist: Optional[str] = None
    final_song_title: Optional[str] = None
    final_lyrics_text: Optional[str] = None


class ExportItemsResponse(BaseModel):
    items: List["ExportItemDTO"]
    total: int = 0

