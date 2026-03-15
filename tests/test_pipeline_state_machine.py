"""
Tests for the pipeline state machine (statuses.py).

Verifies allowed and forbidden transitions, terminal states,
and the happy-path / edge-case sequences.
"""
from __future__ import annotations

import pytest

from app.domain.statuses import ALLOWED_TRANSITIONS, PipelineStatus, validate_transition


# ---------------------------------------------------------------------------
# Happy path: full review cycle
# ---------------------------------------------------------------------------


def test_happy_path_transitions():
    """
    A chart entry that has a YouTube link and passes manual review should
    traverse: discovered → youtube_found → metadata_fetched →
    ready_for_manual_review → in_manual_review → approved.
    """
    path = [
        (PipelineStatus.discovered, PipelineStatus.youtube_found),
        (PipelineStatus.youtube_found, PipelineStatus.metadata_fetched),
        (PipelineStatus.metadata_fetched, PipelineStatus.ready_for_manual_review),
        (PipelineStatus.ready_for_manual_review, PipelineStatus.in_manual_review),
        (PipelineStatus.in_manual_review, PipelineStatus.approved),
    ]
    for from_s, to_s in path:
        validate_transition(from_s, to_s)  # must not raise


def test_no_youtube_path():
    """
    An entry without a YouTube URL transitions: discovered → youtube_missing.
    """
    validate_transition(PipelineStatus.discovered, PipelineStatus.youtube_missing)


def test_metadata_failed_path():
    """
    A metadata fetch failure transitions: youtube_found → metadata_failed.
    """
    validate_transition(PipelineStatus.youtube_found, PipelineStatus.metadata_failed)


def test_metadata_failed_retry_path():
    """
    After metadata_failed the entry can be reset to youtube_found for retry.
    """
    validate_transition(PipelineStatus.metadata_failed, PipelineStatus.youtube_found)


def test_operator_release_path():
    """
    An operator can release a task back to ready_for_manual_review from in_manual_review.
    """
    validate_transition(
        PipelineStatus.in_manual_review,
        PipelineStatus.ready_for_manual_review,
    )


def test_rejected_path():
    """An entry can be rejected from in_manual_review."""
    validate_transition(PipelineStatus.in_manual_review, PipelineStatus.rejected)


def test_no_useful_text_path():
    """An entry can be marked no_useful_text from in_manual_review."""
    validate_transition(PipelineStatus.in_manual_review, PipelineStatus.no_useful_text)


def test_approved_with_edits_path():
    """An entry can be approved_with_edits from in_manual_review."""
    validate_transition(PipelineStatus.in_manual_review, PipelineStatus.approved_with_edits)


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


def test_invalid_transition_blocked():
    """
    A direct jump from discovered → approved must raise ValueError.
    """
    with pytest.raises(ValueError, match="Invalid pipeline status transition"):
        validate_transition(PipelineStatus.discovered, PipelineStatus.approved)


def test_invalid_skipping_metadata():
    """
    Skipping the metadata step (youtube_found → ready_for_manual_review) is not allowed.
    """
    with pytest.raises(ValueError):
        validate_transition(
            PipelineStatus.youtube_found, PipelineStatus.ready_for_manual_review
        )


def test_invalid_jump_from_discovered_to_review():
    """discovered → in_manual_review is not a valid transition."""
    with pytest.raises(ValueError):
        validate_transition(PipelineStatus.discovered, PipelineStatus.in_manual_review)


# ---------------------------------------------------------------------------
# Terminal states
# ---------------------------------------------------------------------------


def test_approved_is_final_state():
    """
    Once approved, no further transition is valid.
    """
    final = PipelineStatus.approved
    assert ALLOWED_TRANSITIONS[final] == frozenset()
    for target in PipelineStatus:
        if target != final:
            with pytest.raises(ValueError):
                validate_transition(final, target)


def test_rejected_is_final_state():
    """
    Once rejected, no further transition is valid.
    """
    final = PipelineStatus.rejected
    assert ALLOWED_TRANSITIONS[final] == frozenset()
    for target in PipelineStatus:
        if target != final:
            with pytest.raises(ValueError):
                validate_transition(final, target)


def test_youtube_missing_is_final_state():
    """youtube_missing is a terminal state — no onwards transitions."""
    final = PipelineStatus.youtube_missing
    assert ALLOWED_TRANSITIONS[final] == frozenset()
    for target in PipelineStatus:
        with pytest.raises(ValueError):
            validate_transition(final, target)


def test_approved_with_edits_is_final_state():
    """approved_with_edits is terminal."""
    final = PipelineStatus.approved_with_edits
    assert ALLOWED_TRANSITIONS[final] == frozenset()


def test_no_useful_text_is_final_state():
    """no_useful_text is terminal."""
    final = PipelineStatus.no_useful_text
    assert ALLOWED_TRANSITIONS[final] == frozenset()


# ---------------------------------------------------------------------------
# Error recovery
# ---------------------------------------------------------------------------


def test_error_allows_reset_to_discovered():
    """An entry stuck in error can be reset to discovered for re-processing."""
    validate_transition(PipelineStatus.error, PipelineStatus.discovered)


def test_all_non_terminal_states_have_allowed_transitions():
    """Every non-terminal status has at least one valid next state."""
    terminal = {
        PipelineStatus.approved,
        PipelineStatus.approved_with_edits,
        PipelineStatus.rejected,
        PipelineStatus.no_useful_text,
        PipelineStatus.youtube_missing,
    }
    for status in PipelineStatus:
        if status not in terminal:
            assert len(ALLOWED_TRANSITIONS[status]) > 0, (
                f"{status.value} has no allowed transitions but is not terminal"
            )
