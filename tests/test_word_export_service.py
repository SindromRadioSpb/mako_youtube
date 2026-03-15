"""Tests for word_export_service — document structure and content."""
from __future__ import annotations
import pytest

CHART_ENTRY = {
    "chart_position": 3,
    "artist_raw": "עומר אדם",
    "song_title_raw": "בן 32",
    "youtube_url": "https://www.youtube.com/watch?v=7PE611GuMAk",
}

YOUTUBE_VIDEO = {
    "youtube_video_id": "7PE611GuMAk",
    "canonical_url": "https://www.youtube.com/watch?v=7PE611GuMAk",
    "video_title": "עומר אדם - בן 32",
    "channel_title": "עומר אדם - הערוץ הרשמי",
    "description_raw": "Hebrew description text\nמילים ולחן: טל קסטיאל",
    "published_at": "2026-02-18T00:00:00Z",
}


def _get_text(doc) -> str:
    """Concatenate all paragraph text in document."""
    return "\n".join(p.text for p in doc.paragraphs)


def test_build_document_imports_ok():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=42, review_status="pending")
    assert doc is not None


def test_build_document_contains_task_id():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=99, review_status="pending")
    text = _get_text(doc)
    assert "99" in text


def test_build_document_contains_review_status():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=1, review_status="in_review")
    assert "in_review" in _get_text(doc)


def test_build_document_contains_chart_data():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=1, review_status="pending", chart_entry=CHART_ENTRY)
    text = _get_text(doc)
    assert "עומר אדם" in text
    assert "בן 32" in text
    assert "3" in text  # position


def test_build_document_contains_youtube_metadata():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=1, review_status="pending", youtube_video=YOUTUBE_VIDEO)
    text = _get_text(doc)
    assert "7PE611GuMAk" in text
    assert "עומר אדם - בן 32" in text


def test_build_document_contains_description():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=1, review_status="pending", youtube_video=YOUTUBE_VIDEO)
    text = _get_text(doc)
    assert "Hebrew description text" in text
    assert "טל קסטיאל" in text


def test_build_document_contains_final_fields():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(
        task_id=1, review_status="pending",
        final_artist="Final Artist", final_title="Final Title",
        final_lyrics_text="test lyrics"
    )
    text = _get_text(doc)
    assert "Final Artist" in text
    assert "Final Title" in text
    assert "test lyrics" in text


def test_build_document_missing_fields_no_crash():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=5, review_status="pending", chart_entry={}, youtube_video={})
    assert doc is not None
    assert "—" in _get_text(doc)  # fallback placeholder


def test_build_document_hebrew_text_preserved():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    hebrew = "שיר ישראלי"
    doc = build_document(task_id=1, review_status="pending", final_lyrics_text=hebrew)
    assert hebrew in _get_text(doc)


def test_build_document_contains_not_source_of_truth_notice():
    pytest.importorskip("docx", reason="python-docx not installed")
    from app.services.word_export_service import build_document
    doc = build_document(task_id=1, review_status="pending")
    text = _get_text(doc)
    assert "NOT a source of truth" in text


def test_get_export_path_safe_filename():
    from app.services.word_export_service import get_export_path
    path = get_export_path(42)
    assert "review_task_42.docx" == path.name
    assert str(path.parent).endswith("tmp")


def test_get_export_path_different_ids():
    from app.services.word_export_service import get_export_path
    p1 = get_export_path(1)
    p2 = get_export_path(2)
    assert p1 != p2
    assert "1" in p1.name
    assert "2" in p2.name
