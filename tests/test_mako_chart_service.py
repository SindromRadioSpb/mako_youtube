"""
Tests for mako_chart_service — pure-logic functions only.

No database, no network calls required.
"""
from __future__ import annotations

import pytest

from app.services.mako_chart_service import (
    _extract_youtube_url,
    _normalize_text,
    _parse_redux_storage,
)


# ---------------------------------------------------------------------------
# _extract_youtube_url
# ---------------------------------------------------------------------------


def test_extract_youtube_url_from_links():
    """Returns the YouTube URL when mixed with other streaming service URLs."""
    links = [
        "https://open.spotify.com/track/abc123",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.apple.com/il/album/never-gonna",
    ]
    result = _extract_youtube_url(links)
    assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_extract_youtube_url_none():
    """Returns None when no YouTube URL is present."""
    links = [
        "https://open.spotify.com/track/abc123",
        "https://music.apple.com/il/album/something",
        "https://www.soundcloud.com/artist/track",
    ]
    result = _extract_youtube_url(links)
    assert result is None


def test_extract_youtube_url_empty_list():
    """Returns None for an empty link list."""
    assert _extract_youtube_url([]) is None


def test_extract_youtube_url_youtu_be():
    """Accepts youtu.be short-form URLs."""
    links = ["https://youtu.be/dQw4w9WgXcQ"]
    result = _extract_youtube_url(links)
    assert result == "https://youtu.be/dQw4w9WgXcQ"


def test_youtube_only_no_spotify():
    """Spotify URL is ignored; only YouTube is returned."""
    links = [
        "https://open.spotify.com/track/zzz",
        "https://www.youtube.com/watch?v=ABCDE12345F",
    ]
    result = _extract_youtube_url(links)
    assert result is not None
    assert "youtube.com" in result
    assert "spotify.com" not in result


def test_youtube_only_no_apple_music():
    """Apple Music URL is ignored; only YouTube is returned."""
    links = [
        "https://music.apple.com/album/xyz",
        "https://youtu.be/ABCDE12345F",
    ]
    result = _extract_youtube_url(links)
    assert result is not None
    assert "youtu.be" in result
    assert "apple.com" not in result


def test_extract_youtube_url_returns_first_match():
    """When multiple YouTube URLs are present, the first one is returned."""
    links = [
        "https://www.youtube.com/watch?v=first11111",
        "https://www.youtube.com/watch?v=second2222",
    ]
    result = _extract_youtube_url(links)
    assert result == "https://www.youtube.com/watch?v=first11111"


# ---------------------------------------------------------------------------
# _normalize_text
# ---------------------------------------------------------------------------


def test_normalize_text_strips_whitespace():
    """Strips leading/trailing whitespace."""
    assert _normalize_text("  hello  ") == "hello"


def test_normalize_text_lowercases():
    """Converts to lowercase."""
    assert _normalize_text("STING") == "sting"


def test_normalize_text_strip_and_lower_combined():
    """Both stripping and lowercasing work together."""
    assert _normalize_text("  The Beatles  ") == "the beatles"


def test_normalize_text_unicode_nfc():
    """Unicode NFC normalization is applied."""
    # café — precomposed vs decomposed should normalise to the same string
    composed = "\u00e9"       # é precomposed
    decomposed = "e\u0301"    # e + combining acute
    assert _normalize_text(decomposed) == _normalize_text(composed)


def test_normalize_text_empty_string():
    """Empty string stays empty."""
    assert _normalize_text("") == ""


# ---------------------------------------------------------------------------
# _parse_redux_storage — real Mako page format
# ---------------------------------------------------------------------------

import json


def _make_redux_html(items: list) -> str:
    """Wrap items into the window['__REDUX_STORAGE'] script format."""
    payload = json.dumps({"chart": {"items": items}})
    return f"<html><body><script>window['__REDUX_STORAGE'] = {payload};</script></body></html>"


_SAMPLE_ITEMS = [
    {
        "position": 1,
        "altArtist": "Omer Adam",
        "altTitle": "Lev Sheli",
        "youtubeUrl": "https://www.youtube.com/watch?v=ABC1234567D",
        "spotifyUrl": "https://open.spotify.com/track/xyz",
    },
    {
        "position": 2,
        "altArtist": "Noa Kirel",
        "altTitle": "Unicorn",
        "youtubeUrl": None,
        "spotifyUrl": "https://open.spotify.com/track/aaa",
    },
    {
        "position": 3,
        "altArtist": "Eyal Golan",
        "altTitle": "Salsa",
        "youtubeUrl": "https://youtu.be/XYZ9876543A",
    },
]


def test_chart_position_parsing():
    """Position values are correctly extracted from Redux storage."""
    entries = _parse_redux_storage(_make_redux_html(_SAMPLE_ITEMS))
    assert len(entries) == 3
    assert [e["position"] for e in entries] == [1, 2, 3]


def test_full_chart_row_parsing_first_entry():
    """Artist, title, and YouTube URL extracted correctly from first item."""
    entries = _parse_redux_storage(_make_redux_html(_SAMPLE_ITEMS))
    first = entries[0]
    assert first["artist_raw"] == "Omer Adam"
    assert first["song_title_raw"] == "Lev Sheli"
    assert first["youtube_url"] == "https://www.youtube.com/watch?v=ABC1234567D"


def test_full_chart_row_parsing_no_youtube():
    """Entry with null youtubeUrl has youtube_url=None."""
    entries = _parse_redux_storage(_make_redux_html(_SAMPLE_ITEMS))
    assert entries[1]["youtube_url"] is None


def test_full_chart_row_parsing_youtu_be():
    """youtu.be short URLs are accepted as valid YouTube URLs."""
    entries = _parse_redux_storage(_make_redux_html(_SAMPLE_ITEMS))
    assert entries[2]["youtube_url"] == "https://youtu.be/XYZ9876543A"


def test_parse_redux_storage_missing_marker():
    """Returns empty list when __REDUX_STORAGE is absent."""
    entries = _parse_redux_storage("<html><body>no data</body></html>")
    assert entries == []


def test_parse_redux_storage_spotify_url_not_kept():
    """Spotify URLs in youtubeUrl field are rejected."""
    items = [{"position": 1, "altArtist": "X", "altTitle": "Y",
              "youtubeUrl": "https://open.spotify.com/track/abc"}]
    entries = _parse_redux_storage(_make_redux_html(items))
    assert entries[0]["youtube_url"] is None


def test_parse_redux_storage_empty_items():
    """Returns empty list when chart.items is empty."""
    html = "<html><script>window['__REDUX_STORAGE'] = {\"chart\":{\"items\":[]}};</script></html>"
    assert _parse_redux_storage(html) == []


def test_parse_redux_storage_fallback_artist_title():
    """Falls back to 'artist'/'title' when 'altArtist'/'altTitle' are absent/None."""
    items = [{"position": 1, "altArtist": None, "altTitle": None,
              "artist": "Bad Bunny", "title": "NUEVAYoL", "youtubeUrl": None}]
    entries = _parse_redux_storage(_make_redux_html(items))
    assert entries[0]["artist_raw"] == "Bad Bunny"
    assert entries[0]["song_title_raw"] == "NUEVAYoL"


def test_parse_redux_storage_alt_takes_priority_over_fallback():
    """'altArtist'/'altTitle' take priority over 'artist'/'title' when both present."""
    items = [{"position": 1, "altArtist": "Alt Artist", "altTitle": "Alt Title",
              "artist": "Base Artist", "title": "Base Title", "youtubeUrl": None}]
    entries = _parse_redux_storage(_make_redux_html(items))
    assert entries[0]["artist_raw"] == "Alt Artist"
    assert entries[0]["song_title_raw"] == "Alt Title"
