"""
Mako Hitlist chart scraping service.

Fetches the Mako Hitlist page, parses chart entries (position, artist, title,
links), stores them in the database, and extracts YouTube URLs.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.statuses import PipelineStatus
from app.infra.sa_models import ChartEntry, ChartSnapshot
from app.services import audit_service

log = structlog.get_logger(__name__)

SCRAPER_VERSION = "1.0.0"
MAKO_HITLIST_URL = "https://hitlist.mako.co.il/"

_YOUTUBE_HOST_RE = re.compile(
    r"^(www\.)?(youtube\.com|youtu\.be)$", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_chart_snapshot(session: AsyncSession) -> ChartSnapshot:
    """
    Fetch the Mako Hitlist page, persist a ChartSnapshot record, and
    return it.  The snapshot status will be "ok" on success or "failed"
    if the scrape raises an exception.
    """
    await audit_service.chart_fetch_started(
        session,
        source_name="mako_hitlist",
        source_url=MAKO_HITLIST_URL,
        actor_id="system",
    )

    snapshot = ChartSnapshot(
        source_name="mako_hitlist",
        source_url=MAKO_HITLIST_URL,
        snapshot_date=date.today(),
        fetched_at=datetime.now(tz=timezone.utc),
        status="fetching",
        scraper_version=SCRAPER_VERSION,
    )
    session.add(snapshot)
    await session.flush()  # get the id

    try:
        raw_entries = await _scrape_mako_hitlist()
        snapshot.status = "ok"
        snapshot.raw_payload_json = {"entries": raw_entries, "count": len(raw_entries)}
        await session.flush()

        await audit_service.chart_fetch_completed(
            session,
            snapshot_id=snapshot.id,
            entries_discovered=len(raw_entries),
        )

        log.info(
            "chart_snapshot_created",
            snapshot_id=snapshot.id,
            entries_discovered=len(raw_entries),
        )
    except Exception as exc:
        snapshot.status = "failed"
        snapshot.notes = str(exc)
        await session.flush()
        log.error("chart_fetch_failed", error=str(exc), exc_info=exc)
        raise

    return snapshot


async def process_snapshot(session: AsyncSession, snapshot_id: int) -> Dict[str, Any]:
    """
    For each raw entry stored in a snapshot's raw_payload_json, create
    ChartEntry records and determine YouTube presence.

    Returns a dict with keys: snapshot_id, processed_entries,
    youtube_found, youtube_missing.
    """
    result = await session.execute(
        select(ChartSnapshot).where(ChartSnapshot.id == snapshot_id)
    )
    snapshot: Optional[ChartSnapshot] = result.scalar_one_or_none()
    if snapshot is None:
        raise ValueError(f"ChartSnapshot {snapshot_id} not found")

    raw_entries: List[Dict[str, Any]] = (
        snapshot.raw_payload_json.get("entries", [])
        if snapshot.raw_payload_json
        else []
    )

    from app.services import review_queue_service, youtube_metadata_service

    youtube_found = 0
    youtube_missing = 0
    metadata_ok = 0
    metadata_failed = 0
    tasks_created = 0
    processed = 0

    for raw in raw_entries:
        entry = await _parse_entry(session, snapshot_id, raw)
        processed += 1

        if not entry.has_youtube:
            youtube_missing += 1
            continue

        youtube_found += 1

        # Fetch YouTube metadata and create review task
        try:
            yt_video = await youtube_metadata_service.fetch_metadata(
                session, entry.youtube_url  # type: ignore[arg-type]
            )
            entry.pipeline_status = PipelineStatus.metadata_fetched.value
            entry.updated_at = datetime.now(tz=timezone.utc)
            metadata_ok += 1

            task = await review_queue_service.create_review_task(
                session,
                chart_entry_id=entry.id,
                youtube_video_id_ref=yt_video.youtube_video_id,
            )
            if task is not None:
                entry.pipeline_status = PipelineStatus.ready_for_manual_review.value
                entry.updated_at = datetime.now(tz=timezone.utc)
                tasks_created += 1

        except Exception as exc:
            entry.pipeline_status = PipelineStatus.metadata_failed.value
            entry.updated_at = datetime.now(tz=timezone.utc)
            metadata_failed += 1
            log.warning(
                "metadata_fetch_failed_during_process",
                chart_entry_id=entry.id,
                youtube_url=entry.youtube_url,
                error=str(exc),
            )

        await session.flush()

    return {
        "snapshot_id": snapshot_id,
        "processed_entries": processed,
        "youtube_found": youtube_found,
        "youtube_missing": youtube_missing,
        "metadata_ok": metadata_ok,
        "metadata_failed": metadata_failed,
        "tasks_created": tasks_created,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _scrape_mako_hitlist() -> List[Dict[str, Any]]:
    """
    HTTP GET the Mako Hitlist page and extract chart entries from the
    embedded ``window['__REDUX_STORAGE']`` JSON block.

    Each entry is a dict with:
        position (int), artist_raw (str), song_title_raw (str),
        youtube_url (str|None)
    """
    timeout = httpx.Timeout(30.0, connect=10.0)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
    }

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(MAKO_HITLIST_URL, headers=headers)
        response.raise_for_status()
        html = response.text

    return _parse_redux_storage(html)


def _parse_redux_storage(html: str) -> List[Dict[str, Any]]:
    """
    Extract chart items from the ``window['__REDUX_STORAGE']`` JSON
    block embedded in the page HTML.

    Structure:
        window['__REDUX_STORAGE'] = {
            "chart": {
                "items": [
                    {
                        "position": 1,
                        "altArtist": "...",
                        "altTitle": "...",
                        "youtubeUrl": "https://www.youtube.com/watch?v=...",
                        ...
                    },
                    ...
                ]
            }
        };
    """
    marker = "window['__REDUX_STORAGE']"
    idx = html.find(marker)
    if idx < 0:
        log.warning("redux_storage_not_found", url=MAKO_HITLIST_URL)
        return []

    eq = html.find("=", idx) + 1
    while eq < len(html) and html[eq] == " ":
        eq += 1

    end = html.find("</script>", eq)
    if end < 0:
        log.warning("redux_storage_script_end_not_found")
        return []

    raw_json = html[eq:end].rstrip().rstrip(";")
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        log.error("redux_storage_json_parse_failed", error=str(exc))
        return []

    items: List[Dict[str, Any]] = data.get("chart", {}).get("items", [])
    if not items:
        log.warning("redux_storage_items_empty")
        return []

    entries: List[Dict[str, Any]] = []
    for item in items:
        youtube_url: Optional[str] = item.get("youtubeUrl") or None
        # Only keep YouTube URLs; ignore Spotify / Apple Music
        if youtube_url and not _is_youtube_url(youtube_url):
            youtube_url = None

        entries.append(
            {
                "position": item.get("position", len(entries) + 1),
                "artist_raw": item.get("altArtist") or None,
                "song_title_raw": item.get("altTitle") or None,
                "youtube_url": youtube_url,
            }
        )

    return entries


async def _parse_entry(
    session: AsyncSession,
    snapshot_id: int,
    raw: Dict[str, Any],
) -> ChartEntry:
    """
    Convert a raw scrape dict into a persisted ChartEntry.
    """
    artist_raw: Optional[str] = raw.get("artist_raw")
    song_title_raw: Optional[str] = raw.get("song_title_raw")
    position: int = raw.get("position", 0)

    # Raw entry already has youtube_url resolved during scrape
    youtube_url: Optional[str] = raw.get("youtube_url") or None
    youtube_video_id: Optional[str] = None

    if youtube_url:
        # Lazy import to avoid circular
        from app.services.youtube_metadata_service import extract_video_id
        youtube_video_id = extract_video_id(youtube_url)

    has_youtube = youtube_url is not None

    pipeline_status = (
        PipelineStatus.youtube_found if has_youtube else PipelineStatus.youtube_missing
    )

    entry = ChartEntry(
        snapshot_id=snapshot_id,
        chart_position=position,
        artist_raw=artist_raw,
        song_title_raw=song_title_raw,
        artist_norm=_normalize_text(artist_raw) if artist_raw else None,
        song_title_norm=_normalize_text(song_title_raw) if song_title_raw else None,
        youtube_url=youtube_url,
        youtube_video_id=youtube_video_id,
        has_youtube=has_youtube,
        pipeline_status=pipeline_status.value,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    session.add(entry)
    await session.flush()

    if has_youtube:
        await audit_service.youtube_url_found(
            session,
            entry_id=entry.id,
            youtube_url=youtube_url,  # type: ignore[arg-type]
            youtube_video_id=youtube_video_id or "",
        )
    else:
        await audit_service.youtube_url_missing(
            session, entry_id=entry.id, chart_position=position
        )

    await audit_service.chart_entry_discovered(
        session,
        entry_id=entry.id,
        snapshot_id=snapshot_id,
        chart_position=position,
        artist_raw=artist_raw,
        song_title_raw=song_title_raw,
    )

    return entry


def _is_youtube_url(url: str) -> bool:
    """Return True if *url* is a YouTube URL (youtube.com or youtu.be)."""
    try:
        host = urlparse(url).netloc.lower()
        return bool(_YOUTUBE_HOST_RE.match(host))
    except Exception:
        return False


def _extract_youtube_url(links: List[str]) -> Optional[str]:
    """
    Return the first YouTube URL found in *links*, or None.
    Kept for backwards compatibility with tests.
    """
    for link in links:
        if _is_youtube_url(link):
            return link
    return None


def _normalize_text(text: str) -> str:
    """
    Basic Unicode-aware normalization: NFC, strip, lowercase.
    """
    return unicodedata.normalize("NFC", text).strip().lower()
