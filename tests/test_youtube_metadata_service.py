"""
Tests for youtube_metadata_service — URL parsing and canonicalisation.

No database, no yt-dlp calls, no network.
"""
from __future__ import annotations

import pytest

from app.services.youtube_metadata_service import (
    canonicalize_url,
    extract_video_id,
)

# ---------------------------------------------------------------------------
# extract_video_id
# ---------------------------------------------------------------------------


def test_extract_video_id_watch_url():
    """Standard watch?v= URL returns the 11-char video ID."""
    result = extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_short_url():
    """youtu.be/ short URL returns the video ID."""
    result = extract_video_id("https://youtu.be/dQw4w9WgXcQ")
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_embed_url():
    """Embed URL format returns the video ID."""
    result = extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_shorts_url():
    """YouTube Shorts URL returns the video ID."""
    result = extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_v_url():
    """Old /v/ URL format returns the video ID."""
    result = extract_video_id("https://www.youtube.com/v/dQw4w9WgXcQ")
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_invalid():
    """Non-YouTube URL returns None."""
    result = extract_video_id("https://www.spotify.com/track/abc")
    assert result is None


def test_extract_video_id_invalid_domain():
    """Plausible-looking but wrong domain returns None."""
    result = extract_video_id("https://www.notytube.com/watch?v=dQw4w9WgXcQ")
    assert result is None


def test_extract_video_id_with_extra_params():
    """Extra query parameters are ignored; video ID is still extracted."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234&index=5&si=abcdef"
    result = extract_video_id(url)
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_youtu_be_with_si_param():
    """youtu.be URL with ?si= tracking param returns correct ID."""
    result = extract_video_id("https://youtu.be/dQw4w9WgXcQ?si=TRACKERID")
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_no_www():
    """Works without the www subdomain."""
    result = extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert result == "dQw4w9WgXcQ"


def test_extract_video_id_empty_string():
    """Empty string returns None."""
    assert extract_video_id("") is None


def test_extract_video_id_none_like():
    """None input returns None (not raise)."""
    assert extract_video_id(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# canonicalize_url
# ---------------------------------------------------------------------------


def test_canonicalize_url():
    """Returns the standard canonical watch URL."""
    url = canonicalize_url("dQw4w9WgXcQ")
    assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_canonicalize_url_contains_video_id():
    """Canonical URL always contains the video ID."""
    vid = "ABCDE12345F"
    assert vid in canonicalize_url(vid)


def test_canonicalize_url_prefix():
    """Canonical URL starts with the standard YouTube HTTPS prefix."""
    url = canonicalize_url("ABCDE12345F")
    assert url.startswith("https://www.youtube.com/watch?v=")


# ---------------------------------------------------------------------------
# Non-retryable error scenarios (ValueError on invalid input)
# ---------------------------------------------------------------------------


def test_non_retryable_invalid_url():
    """
    Passing a URL that yields no video ID should cause fetch_metadata to
    raise a ValueError immediately (tested without a real session by checking
    the extract_video_id helper returns None, which is the trigger).
    """
    vid = extract_video_id("https://www.spotify.com/track/xyz")
    assert vid is None, "No video ID should be extracted from a Spotify URL"


def test_non_retryable_missing_video_id():
    """
    An empty string produces no video ID, which would trigger ValueError in
    fetch_metadata.  Verify the helper returns None for an empty/blank input.
    """
    assert extract_video_id("") is None
    assert extract_video_id("   ") is None
