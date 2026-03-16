"""
SQLAlchemy 2.0 ORM models for the OpenClaw Mako YouTube pipeline.

All models use the mapped_column() style introduced in SQLAlchemy 2.0.
An async engine and session factory are configured from the DATABASE_URL
environment variable (defaults to a local PostgreSQL URL if not set).
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Database URL & engine
# ---------------------------------------------------------------------------

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/openclaw_mako",
)

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            DATABASE_URL,
            echo=bool(os.environ.get("SA_ECHO", "")),
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


# Convenience accessor for backwards compatibility
def async_session_factory() -> AsyncSession:  # type: ignore[misc]
    return get_session_factory()()


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class ChartSnapshot(Base):
    __tablename__ = "chart_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    scraper_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    entries: Mapped[list["ChartEntry"]] = relationship(
        "ChartEntry", back_populates="snapshot", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ChartSnapshot id={self.id} date={self.snapshot_date} status={self.status!r}>"


class ChartEntry(Base):
    __tablename__ = "chart_entry"
    __table_args__ = (
        Index("idx_chart_entry_snapshot_id", "snapshot_id"),
        Index("idx_chart_entry_youtube_video_id", "youtube_video_id"),
        Index("idx_chart_entry_pipeline_status", "pipeline_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chart_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    chart_position: Mapped[int] = mapped_column(Integer, nullable=False)
    artist_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    song_title_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artist_norm: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    song_title_norm: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    youtube_video_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_youtube: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    pipeline_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="discovered"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    snapshot: Mapped["ChartSnapshot"] = relationship("ChartSnapshot", back_populates="entries")
    review_tasks: Mapped[list["ReviewTask"]] = relationship(
        "ReviewTask", back_populates="chart_entry", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<ChartEntry id={self.id} pos={self.chart_position} "
            f"status={self.pipeline_status!r}>"
        )


class YouTubeVideo(Base):
    __tablename__ = "youtube_video"
    __table_args__ = (
        Index("idx_youtube_video_fetch_status", "fetch_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    youtube_video_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    video_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    channel_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetch_status: Mapped[str] = mapped_column(Text, nullable=False)
    fetch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetcher_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    review_tasks: Mapped[list["ReviewTask"]] = relationship(
        "ReviewTask",
        foreign_keys="[ReviewTask.youtube_video_id_ref]",
        primaryjoin="YouTubeVideo.youtube_video_id == ReviewTask.youtube_video_id_ref",
        back_populates="youtube_video",
    )

    def __repr__(self) -> str:
        return f"<YouTubeVideo id={self.id} vid_id={self.youtube_video_id!r} status={self.fetch_status!r}>"


class ReviewTask(Base):
    __tablename__ = "review_task"
    __table_args__ = (
        Index("idx_review_task_status", "review_status"),
        Index("idx_review_task_chart_entry_id", "chart_entry_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chart_entry_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chart_entry.id", ondelete="CASCADE"), nullable=False
    )
    youtube_video_id_ref: Mapped[Optional[str]] = mapped_column(
        Text,
        ForeignKey("youtube_video.youtube_video_id", ondelete="SET NULL"),
        nullable=True,
    )
    review_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    assigned_to: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    chart_entry: Mapped["ChartEntry"] = relationship("ChartEntry", back_populates="review_tasks")
    youtube_video: Mapped[Optional["YouTubeVideo"]] = relationship(
        "YouTubeVideo",
        foreign_keys="[ReviewTask.youtube_video_id_ref]",
        primaryjoin="ReviewTask.youtube_video_id_ref == YouTubeVideo.youtube_video_id",
        back_populates="review_tasks",
        uselist=False,
    )
    result: Mapped[Optional["ReviewResult"]] = relationship(
        "ReviewResult", back_populates="task", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ReviewTask id={self.id} status={self.review_status!r}>"


class ReviewResult(Base):
    __tablename__ = "review_result"
    __table_args__ = (
        Index("idx_review_result_decision", "decision"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    review_task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("review_task.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    operator_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_artist: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_song_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_lyrics_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    task: Mapped["ReviewTask"] = relationship("ReviewTask", back_populates="result")

    def __repr__(self) -> str:
        return f"<ReviewResult id={self.id} decision={self.decision!r}>"


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("idx_audit_event_entity", "entity_type", "entity_id"),
        Index("idx_audit_event_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AuditEvent id={self.id} type={self.event_type!r} "
            f"entity={self.entity_type}:{self.entity_id}>"
        )
