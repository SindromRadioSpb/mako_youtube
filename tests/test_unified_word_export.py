"""
Tests for unified_word_export_service.

Covers:
  - filter_and_sort policy (status filter, skip_empty_lyrics)
  - summary counts
  - section heading format: "Position N. Artist - Title"
  - build_document returns a Document with expected content
  - existing single-item word_export_service is not broken
"""
from __future__ import annotations

import pytest

from app.services.unified_word_export_service import (
    ExportItem,
    ExportPolicy,
    ExportSummary,
    _section_heading,
    filter_and_sort,
)


def _item(
    task_id: int = 1,
    chart_position: int = 1,
    final_artist: str = "Test Artist",
    final_song_title: str = "Test Song",
    final_lyrics_text: str = "Line 1\nLine 2",
    review_status: str = "approved",
) -> ExportItem:
    return ExportItem(
        task_id=task_id,
        chart_position=chart_position,
        final_artist=final_artist,
        final_song_title=final_song_title,
        final_lyrics_text=final_lyrics_text,
        review_status=review_status,
    )


# ---------------------------------------------------------------------------
# _section_heading
# ---------------------------------------------------------------------------


def test_section_heading_format():
    item = _item(chart_position=17, final_artist="Omer Adam", final_song_title="Lev Sheli")
    assert _section_heading(item) == "Position 17. Omer Adam - Lev Sheli"


def test_section_heading_none_position():
    item = _item(chart_position=None, final_artist="X", final_song_title="Y")
    item.chart_position = None
    assert _section_heading(item) == "Position ?. X - Y"


def test_section_heading_hebrew():
    item = _item(chart_position=1, final_artist="עומר אדם", final_song_title="לב שלי")
    heading = _section_heading(item)
    assert "עומר אדם" in heading
    assert "לב שלי" in heading
    assert heading.startswith("Position 1.")


# ---------------------------------------------------------------------------
# filter_and_sort — status filtering
# ---------------------------------------------------------------------------


def test_default_policy_includes_approved():
    items = [
        _item(1, review_status="approved"),
        _item(2, review_status="approved_with_edits"),
    ]
    policy = ExportPolicy()
    included, summary = filter_and_sort(items, policy)
    assert len(included) == 2
    assert summary.exported == 2
    assert summary.skipped == 0


def test_default_policy_excludes_pending():
    items = [
        _item(1, review_status="pending"),
        _item(2, review_status="in_review"),
        _item(3, review_status="rejected"),
        _item(4, review_status="no_useful_text"),
    ]
    policy = ExportPolicy()
    included, summary = filter_and_sort(items, policy)
    assert len(included) == 0
    assert summary.skipped == 4
    assert summary.skipped_status == 4


def test_custom_policy_includes_rejected():
    items = [_item(1, review_status="rejected"), _item(2, review_status="approved")]
    policy = ExportPolicy(included_statuses={"approved", "rejected"})
    included, summary = filter_and_sort(items, policy)
    assert len(included) == 2


# ---------------------------------------------------------------------------
# filter_and_sort — skip_empty_lyrics
# ---------------------------------------------------------------------------


def test_skip_empty_lyrics_on():
    items = [
        _item(1, final_lyrics_text="some lyrics", review_status="approved"),
        _item(2, final_lyrics_text="", review_status="approved"),
        _item(3, final_lyrics_text="   ", review_status="approved"),
    ]
    policy = ExportPolicy(skip_empty_lyrics=True)
    included, summary = filter_and_sort(items, policy)
    assert len(included) == 1
    assert included[0].task_id == 1
    assert summary.skipped_empty == 2


def test_skip_empty_lyrics_off():
    items = [
        _item(1, final_lyrics_text="", review_status="approved"),
        _item(2, final_lyrics_text="words", review_status="approved"),
    ]
    policy = ExportPolicy(skip_empty_lyrics=False)
    included, summary = filter_and_sort(items, policy)
    assert len(included) == 2
    assert summary.skipped_empty == 0


# ---------------------------------------------------------------------------
# filter_and_sort — sorting
# ---------------------------------------------------------------------------


def test_sort_by_position():
    items = [
        _item(1, chart_position=5, review_status="approved"),
        _item(2, chart_position=1, review_status="approved"),
        _item(3, chart_position=3, review_status="approved"),
    ]
    policy = ExportPolicy(sort_by_position=True)
    included, _ = filter_and_sort(items, policy)
    positions = [i.chart_position for i in included]
    assert positions == [1, 3, 5]


def test_no_sort_preserves_order():
    items = [
        _item(1, chart_position=5, review_status="approved"),
        _item(2, chart_position=1, review_status="approved"),
    ]
    policy = ExportPolicy(sort_by_position=False)
    included, _ = filter_and_sort(items, policy)
    assert [i.task_id for i in included] == [1, 2]


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


def test_summary_counts_mixed():
    items = [
        _item(1, final_lyrics_text="ok", review_status="approved"),
        _item(2, final_lyrics_text="", review_status="approved"),       # empty lyrics
        _item(3, final_lyrics_text="ok", review_status="pending"),      # wrong status
    ]
    policy = ExportPolicy()
    _, summary = filter_and_sort(items, policy)
    assert summary.total_input == 3
    assert summary.exported == 1
    assert summary.skipped == 2
    assert summary.skipped_empty == 1
    assert summary.skipped_status == 1


# ---------------------------------------------------------------------------
# build_document (smoke test — no disk I/O)
# ---------------------------------------------------------------------------


def test_build_document_returns_docx():
    pytest.importorskip("docx")
    from app.services.unified_word_export_service import build_document

    items = [
        _item(1, chart_position=1, final_artist="Omer Adam", final_song_title="Lev Sheli",
              final_lyrics_text="שיר יפה\nLine 2"),
        _item(2, chart_position=2, final_artist="Dave", final_song_title="Raindance",
              final_lyrics_text="English lyrics"),
    ]
    policy = ExportPolicy()
    doc = build_document(items, policy)

    # Verify it has paragraphs (duck-type check — Document factory returns a Document instance)
    assert doc is not None
    assert hasattr(doc, "paragraphs")
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Position 1." in full_text
    assert "Omer Adam" in full_text
    assert "Lev Sheli" in full_text
    assert "שיר יפה" in full_text  # Hebrew preserved
    assert "Table of Contents" in full_text


# ---------------------------------------------------------------------------
# Existing single-item export not broken
# ---------------------------------------------------------------------------


def test_single_item_export_still_works():
    pytest.importorskip("docx")
    from app.services.word_export_service import build_document as single_build

    doc = single_build(
        task_id=42,
        review_status="approved",
        chart_entry={"chart_position": 1, "artist_raw": "Test"},
        final_artist="Test Artist",
        final_title="Test Title",
        final_lyrics_text="Some lyrics",
    )
    assert doc is not None
    assert hasattr(doc, "paragraphs")
