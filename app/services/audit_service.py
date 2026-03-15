"""
Audit service for the OpenClaw Mako YouTube pipeline.

Provides structured logging via structlog and persistence of audit events
into the audit_event table for every significant pipeline action.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.sa_models import AuditEvent

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Core persistence helper
# ---------------------------------------------------------------------------


async def log_event(
    session: AsyncSession,
    entity_type: str,
    entity_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> AuditEvent:
    """
    Persist an audit event to the database and emit a structlog log entry.

    Args:
        session:      The active async SQLAlchemy session.
        entity_type:  Logical entity category (e.g. "chart_entry", "review_task").
        entity_id:    String representation of the entity's primary key / identifier.
        event_type:   Symbolic event name (e.g. "chart_fetch_started").
        payload:      Optional dict of additional structured data.
        actor_type:   "system", "operator", etc.
        actor_id:     Identifier of the actor (operator username, service name, …).

    Returns:
        The persisted AuditEvent ORM instance (not yet committed — the caller
        is responsible for committing the enclosing transaction).
    """
    event = AuditEvent(
        entity_type=entity_type,
        entity_id=str(entity_id),
        event_type=event_type,
        event_payload_json=payload,
        created_at=datetime.now(tz=timezone.utc),
        actor_type=actor_type,
        actor_id=actor_id,
    )
    session.add(event)

    log.info(
        event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type=actor_type,
        actor_id=actor_id,
        payload=payload,
    )

    return event


# ---------------------------------------------------------------------------
# Typed helpers — one per pipeline event kind
# ---------------------------------------------------------------------------


async def chart_fetch_started(
    session: AsyncSession,
    source_name: str,
    source_url: str,
    actor_id: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="chart_snapshot",
        entity_id="pending",
        event_type="chart_fetch_started",
        payload={"source_name": source_name, "source_url": source_url},
        actor_type="system",
        actor_id=actor_id,
    )


async def chart_fetch_completed(
    session: AsyncSession,
    snapshot_id: int,
    entries_discovered: int,
    actor_id: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="chart_snapshot",
        entity_id=str(snapshot_id),
        event_type="chart_fetch_completed",
        payload={"entries_discovered": entries_discovered},
        actor_type="system",
        actor_id=actor_id,
    )


async def chart_entry_discovered(
    session: AsyncSession,
    entry_id: int,
    snapshot_id: int,
    chart_position: int,
    artist_raw: Optional[str] = None,
    song_title_raw: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="chart_entry",
        entity_id=str(entry_id),
        event_type="chart_entry_discovered",
        payload={
            "snapshot_id": snapshot_id,
            "chart_position": chart_position,
            "artist_raw": artist_raw,
            "song_title_raw": song_title_raw,
        },
        actor_type="system",
    )


async def youtube_url_found(
    session: AsyncSession,
    entry_id: int,
    youtube_url: str,
    youtube_video_id: str,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="chart_entry",
        entity_id=str(entry_id),
        event_type="youtube_url_found",
        payload={"youtube_url": youtube_url, "youtube_video_id": youtube_video_id},
        actor_type="system",
    )


async def youtube_url_missing(
    session: AsyncSession,
    entry_id: int,
    chart_position: int,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="chart_entry",
        entity_id=str(entry_id),
        event_type="youtube_url_missing",
        payload={"chart_position": chart_position},
        actor_type="system",
    )


async def youtube_metadata_fetch_started(
    session: AsyncSession,
    youtube_video_id: str,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="youtube_video",
        entity_id=youtube_video_id,
        event_type="youtube_metadata_fetch_started",
        actor_type="system",
    )


async def youtube_metadata_fetch_completed(
    session: AsyncSession,
    youtube_video_id: str,
    video_title: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="youtube_video",
        entity_id=youtube_video_id,
        event_type="youtube_metadata_fetch_completed",
        payload={"video_title": video_title},
        actor_type="system",
    )


async def youtube_metadata_fetch_failed(
    session: AsyncSession,
    youtube_video_id: str,
    error: str,
    attempt: int = 1,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="youtube_video",
        entity_id=youtube_video_id,
        event_type="youtube_metadata_fetch_failed",
        payload={"error": error, "attempt": attempt},
        actor_type="system",
    )


async def review_task_created(
    session: AsyncSession,
    task_id: int,
    chart_entry_id: int,
    youtube_video_id_ref: str,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="review_task",
        entity_id=str(task_id),
        event_type="review_task_created",
        payload={
            "chart_entry_id": chart_entry_id,
            "youtube_video_id_ref": youtube_video_id_ref,
        },
        actor_type="system",
    )


async def review_started(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="review_task",
        entity_id=str(task_id),
        event_type="review_started",
        payload={"operator_id": operator_id},
        actor_type="operator",
        actor_id=operator_id,
    )


async def review_approved(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    final_artist: Optional[str] = None,
    final_song_title: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="review_task",
        entity_id=str(task_id),
        event_type="review_approved",
        payload={"final_artist": final_artist, "final_song_title": final_song_title},
        actor_type="operator",
        actor_id=operator_id,
    )


async def review_approved_with_edits(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    final_artist: Optional[str] = None,
    final_song_title: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="review_task",
        entity_id=str(task_id),
        event_type="review_approved_with_edits",
        payload={"final_artist": final_artist, "final_song_title": final_song_title},
        actor_type="operator",
        actor_id=operator_id,
    )


async def review_rejected(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    review_notes: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="review_task",
        entity_id=str(task_id),
        event_type="review_rejected",
        payload={"review_notes": review_notes},
        actor_type="operator",
        actor_id=operator_id,
    )


async def review_reopened(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    previous_status: str,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="review_task",
        entity_id=str(task_id),
        event_type="review_reopened",
        payload={"previous_status": previous_status},
        actor_type="operator",
        actor_id=operator_id,
    )


async def review_no_useful_text(
    session: AsyncSession,
    task_id: int,
    operator_id: str,
    review_notes: Optional[str] = None,
) -> AuditEvent:
    return await log_event(
        session,
        entity_type="review_task",
        entity_id=str(task_id),
        event_type="review_no_useful_text",
        payload={"review_notes": review_notes},
        actor_type="operator",
        actor_id=operator_id,
    )
