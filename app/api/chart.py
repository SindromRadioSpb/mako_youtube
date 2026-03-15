"""
Chart API router — fetch and process Mako Hitlist chart snapshots.
"""
from __future__ import annotations

from typing import List

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dto import ChartSnapshotDTO, FetchChartResponse, ProcessSnapshotResponse
from app.infra.sa_models import ChartSnapshot, async_session_factory
from app.services import mako_chart_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/chart", tags=["chart"])


# ---------------------------------------------------------------------------
# Dependency: database session
# ---------------------------------------------------------------------------


async def get_session() -> AsyncSession:  # type: ignore[return]
    async with async_session_factory() as session:
        async with session.begin():
            yield session


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/fetch",
    response_model=FetchChartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fetch a new chart snapshot from the Mako Hitlist",
)
async def fetch_chart(session: AsyncSession = Depends(get_session)) -> FetchChartResponse:
    """
    Triggers a live scrape of the Mako Hitlist page, stores the snapshot and
    raw entry payloads, and returns a summary.
    """
    try:
        snapshot = await mako_chart_service.fetch_chart_snapshot(session)
    except Exception as exc:
        log.error("fetch_chart_endpoint_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch chart: {exc}",
        )

    entries_count: int = (
        snapshot.raw_payload_json.get("count", 0)
        if snapshot.raw_payload_json
        else 0
    )
    return FetchChartResponse(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        entries_discovered=entries_count,
    )


@router.post(
    "/{snapshot_id}/process",
    response_model=ProcessSnapshotResponse,
    summary="Process a chart snapshot and create ChartEntry records",
)
async def process_snapshot(
    snapshot_id: int,
    session: AsyncSession = Depends(get_session),
) -> ProcessSnapshotResponse:
    """
    Iterates the raw payload of a snapshot, creates or updates ChartEntry
    records, and extracts YouTube URLs.
    """
    try:
        result = await mako_chart_service.process_snapshot(session, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        log.error("process_snapshot_endpoint_error", snapshot_id=snapshot_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process snapshot: {exc}",
        )

    return ProcessSnapshotResponse(**result)


@router.get(
    "/snapshots",
    response_model=List[ChartSnapshotDTO],
    summary="List all chart snapshots",
)
async def list_snapshots(
    session: AsyncSession = Depends(get_session),
) -> List[ChartSnapshotDTO]:
    """
    Returns all chart snapshots ordered by snapshot_date descending.
    """
    result = await session.execute(
        select(ChartSnapshot).order_by(ChartSnapshot.snapshot_date.desc())
    )
    snapshots = result.scalars().all()
    return [ChartSnapshotDTO.model_validate(s) for s in snapshots]
