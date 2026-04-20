"""
YouTube metadata fetching service using yt-dlp.

Extracts video IDs from various YouTube URL formats, canonicalises URLs,
deduplicates by video ID (upsert), and fetches metadata via the yt-dlp
Python API.  Transient network errors are retried up to 3 times with
exponential backoff.  Non-retryable errors (invalid URL, missing video ID,
video not found) raise immediately.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.statuses import FetchStatus
from app.infra.sa_models import YouTubeVideo
from app.services import audit_service

log = structlog.get_logger(__name__)

FETCHER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"(?:youtube\.com/(?:watch\?.*v=|embed/|v/|shorts/)|youtu\.be/)"
    r"([a-zA-Z0-9_-]{11})",
    re.IGNORECASE,
)

_DOMAIN_RE = re.compile(r"^(www\.)?(youtube\.com|youtu\.be)$", re.IGNORECASE)

# Errors that should NOT be retried
_NON_RETRYABLE_FRAGMENTS = (
    "Video unavailable",
    "Private video",
    "This video has been removed",
    "HTTP Error 404",
    "not available",
)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract an 11-character YouTube video ID from any recognised YouTube URL
    format, or return None if the URL is not a YouTube URL.

    Supports:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://www.youtube.com/watch?v=VIDEO_ID&list=...
        - https://youtu.be/VIDEO_ID
        - https://youtu.be/VIDEO_ID?si=...
        - https://www.youtube.com/embed/VIDEO_ID
        - https://www.youtube.com/v/VIDEO_ID
        - https://www.youtube.com/shorts/VIDEO_ID
    """
    if not url:
        return None

    # Fast path via regex
    m = YOUTUBE_URL_PATTERN.search(url)
    if m:
        return m.group(1)

    # Fallback: manual parse for query-string-based URLs
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not _DOMAIN_RE.match(host):
            return None

        qs = parse_qs(parsed.query)
        v_values = qs.get("v", [])
        if v_values:
            vid = v_values[0]
            if re.fullmatch(r"[a-zA-Z0-9_-]{11}", vid):
                return vid
    except Exception:
        pass

    return None


def canonicalize_url(video_id: str) -> str:
    """
    Return the canonical watch URL for a given video ID.
    """
    return f"https://www.youtube.com/watch?v={video_id}"


# ---------------------------------------------------------------------------
# Main fetch entry point
# ---------------------------------------------------------------------------


async def fetch_metadata(session: AsyncSession, youtube_url: str) -> YouTubeVideo:
    """
    Fetch YouTube video metadata for *youtube_url*, persist/upsert the result,
    and return the YouTubeVideo ORM object.

    Raises:
        ValueError: for non-retryable errors (invalid URL, missing video ID).
    """
    if not youtube_url or not youtube_url.strip():
        raise ValueError("youtube_url must not be empty")

    video_id = extract_video_id(youtube_url)
    if not video_id:
        raise ValueError(f"Cannot extract a valid YouTube video ID from URL: {youtube_url!r}")

    canonical = canonicalize_url(video_id)

    # Dedup check — reuse existing record if present
    existing = await _get_existing(session, video_id)
    if existing is not None and existing.fetch_status == FetchStatus.ok.value:
        log.info(
            "youtube_metadata_cache_hit",
            youtube_video_id=video_id,
            video_id=existing.id,
        )
        return existing

    await audit_service.youtube_metadata_fetch_started(session, youtube_video_id=video_id)

    record = existing or YouTubeVideo(
        youtube_video_id=video_id,
        canonical_url=canonical,
        fetch_status=FetchStatus.retrying.value,
        fetcher_version=FETCHER_VERSION,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    if existing is None:
        session.add(record)
    await session.flush()

    max_attempts = 3
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            record.fetch_status = FetchStatus.retrying.value
            raw = await _fetch_raw_metadata(video_id)

            record.video_title = raw.get("video_title")
            record.channel_title = raw.get("channel_title")
            record.description_raw = raw.get("description_raw")
            record.published_at = raw.get("published_at")
            record.metadata_fetched_at = datetime.now(tz=timezone.utc)
            record.fetch_status = FetchStatus.ok.value
            record.fetch_error = None
            record.updated_at = datetime.now(tz=timezone.utc)

            await session.flush()
            await audit_service.youtube_metadata_fetch_completed(
                session,
                youtube_video_id=video_id,
                video_title=record.video_title,
            )
            log.info(
                "youtube_metadata_fetched",
                youtube_video_id=video_id,
                attempt=attempt,
                video_title=record.video_title,
            )
            return record

        except Exception as exc:
            last_error = exc
            error_msg = str(exc)

            # Non-retryable
            if _is_non_retryable(error_msg):
                record.fetch_status = FetchStatus.failed.value
                record.fetch_error = error_msg
                record.updated_at = datetime.now(tz=timezone.utc)
                await session.flush()
                await audit_service.youtube_metadata_fetch_failed(
                    session, youtube_video_id=video_id, error=error_msg, attempt=attempt
                )
                log.error(
                    "youtube_metadata_fetch_non_retryable",
                    youtube_video_id=video_id,
                    error=error_msg,
                )
                raise ValueError(f"Non-retryable error fetching metadata: {error_msg}") from exc

            log.warning(
                "youtube_metadata_fetch_retrying",
                youtube_video_id=video_id,
                attempt=attempt,
                error=error_msg,
            )
            await audit_service.youtube_metadata_fetch_failed(
                session, youtube_video_id=video_id, error=error_msg, attempt=attempt
            )

            if attempt < max_attempts:
                await asyncio.sleep(2 ** attempt)  # 2s, 4s backoff

    # All retries exhausted
    record.fetch_status = FetchStatus.failed.value
    record.fetch_error = str(last_error)
    record.updated_at = datetime.now(tz=timezone.utc)
    await session.flush()

    raise RuntimeError(
        f"Failed to fetch YouTube metadata for {video_id!r} after {max_attempts} attempts: "
        f"{last_error}"
    )


# ---------------------------------------------------------------------------
# yt-dlp backend
# ---------------------------------------------------------------------------


async def _fetch_raw_metadata(video_id: str) -> Dict[str, Any]:
    """
    Use the yt-dlp Python API to extract metadata for *video_id*.

    Runs synchronously in a thread pool executor to avoid blocking the
    event loop.

    Returns a dict with:
        video_title, channel_title, description_raw, published_at (datetime|None)
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_fetch_raw_metadata, video_id)


def _sync_fetch_raw_metadata(video_id: str) -> Dict[str, Any]:
    """
    Fetch metadata without depending on media format selection.

    Primary path: parse ytInitialPlayerResponse from the watch page HTML.
    Fallback path: invoke yt-dlp if the page structure changes.
    """
    last_error: Optional[Exception] = None

    for fetcher in (_fetch_raw_metadata_from_watch_page, _fetch_raw_metadata_with_ytdlp):
        try:
            return fetcher(video_id)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Unable to fetch metadata for {video_id}: {last_error}")


def _fetch_raw_metadata_from_watch_page(video_id: str) -> Dict[str, Any]:
    """
    Fetch metadata directly from the YouTube watch page HTML.

    This avoids yt-dlp failures related to unavailable media formats while still
    giving us the fields needed by the review pipeline.
    """
    url = canonicalize_url(video_id)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()

    return _parse_watch_html_metadata(response.text)


def _parse_watch_html_metadata(html: str) -> Dict[str, Any]:
    """Parse title/channel/description/publishDate from ytInitialPlayerResponse."""
    payload = _extract_json_object_from_html(html, "ytInitialPlayerResponse = ")
    video_details = payload.get("videoDetails", {}) or {}
    microformat = payload.get("microformat", {}) or {}
    player_microformat = microformat.get("playerMicroformatRenderer", {}) or {}

    title = video_details.get("title") or player_microformat.get("title", {}).get("simpleText")
    channel_title = (
        video_details.get("author")
        or player_microformat.get("ownerChannelName")
    )
    description_raw = (
        video_details.get("shortDescription")
        or player_microformat.get("description", {}).get("simpleText")
    )

    published_at: Optional[datetime] = None
    publish_date = player_microformat.get("publishDate")
    if publish_date:
        try:
            published_at = datetime.fromisoformat(f"{publish_date}T00:00:00+00:00")
        except ValueError:
            published_at = None

    if not any([title, channel_title, description_raw, published_at]):
        raise RuntimeError("ytInitialPlayerResponse did not contain usable metadata")

    return {
        "video_title": title,
        "channel_title": channel_title,
        "description_raw": description_raw,
        "published_at": published_at,
    }


def _extract_json_object_from_html(html: str, marker: str) -> Dict[str, Any]:
    """
    Extract a JSON object that starts after *marker*.

    Uses brace counting instead of regex so quoted braces inside strings do not
    break parsing.
    """
    marker_index = html.find(marker)
    if marker_index < 0:
        raise RuntimeError(f"Marker not found: {marker!r}")

    start = html.find("{", marker_index)
    if start < 0:
        raise RuntimeError(f"JSON object start not found after marker: {marker!r}")

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(html)):
        ch = html[index]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start:index + 1])

    raise RuntimeError(f"JSON object for marker {marker!r} was not closed")


def _fetch_raw_metadata_with_ytdlp(video_id: str) -> Dict[str, Any]:
    """
    Use yt-dlp as a subprocess with -j (JSON dump) to avoid Windows
    charmap encoding errors when yt-dlp writes Unicode to the console.
    """
    import subprocess
    import sys

    url = canonicalize_url(video_id)
    python_exe = sys.executable
    cmd = [
        python_exe, "-m", "yt_dlp",
        "--quiet", "--no-warnings", "--skip-download",
        "--socket-timeout", "20",
        "-j",  # dump JSON to stdout
        url,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or f"yt-dlp exited with code {result.returncode}")

    info: Dict[str, Any] = json.loads(result.stdout)

    # Parse upload_date: "YYYYMMDD"
    published_at: Optional[datetime] = None
    upload_date = info.get("upload_date")
    if upload_date and len(upload_date) == 8:
        try:
            published_at = datetime(
                int(upload_date[:4]),
                int(upload_date[4:6]),
                int(upload_date[6:8]),
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass

    return {
        "video_title": info.get("title") or info.get("fulltitle"),
        "channel_title": info.get("channel") or info.get("uploader"),
        "description_raw": info.get("description"),
        "published_at": published_at,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_existing(session: AsyncSession, video_id: str) -> Optional[YouTubeVideo]:
    result = await session.execute(
        select(YouTubeVideo).where(YouTubeVideo.youtube_video_id == video_id)
    )
    return result.scalar_one_or_none()


def _is_non_retryable(error_msg: str) -> bool:
    """Return True if the error message indicates a permanent failure."""
    for fragment in _NON_RETRYABLE_FRAGMENTS:
        if fragment.lower() in error_msg.lower():
            return True
    return False
