"""
Domain status enums and pipeline state machine for the OpenClaw Mako YouTube pipeline.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class PipelineStatus(str, Enum):
    discovered = "discovered"
    youtube_found = "youtube_found"
    youtube_missing = "youtube_missing"
    metadata_fetched = "metadata_fetched"
    metadata_failed = "metadata_failed"
    ready_for_manual_review = "ready_for_manual_review"
    in_manual_review = "in_manual_review"
    approved = "approved"
    approved_with_edits = "approved_with_edits"
    rejected = "rejected"
    no_useful_text = "no_useful_text"
    error = "error"


class ReviewStatus(str, Enum):
    pending = "pending"
    in_review = "in_review"
    approved = "approved"
    approved_with_edits = "approved_with_edits"
    rejected = "rejected"
    no_useful_text = "no_useful_text"


class FetchStatus(str, Enum):
    ok = "ok"
    failed = "failed"
    retrying = "retrying"


class Decision(str, Enum):
    approved = "approved"
    approved_with_edits = "approved_with_edits"
    rejected = "rejected"
    no_useful_text = "no_useful_text"


# State machine: maps each status to the set of valid next statuses.
# Terminal states (approved, approved_with_edits, rejected, no_useful_text, youtube_missing)
# map to empty sets — no further transitions are permitted.
ALLOWED_TRANSITIONS: Dict[PipelineStatus, FrozenSet[PipelineStatus]] = {
    PipelineStatus.discovered: frozenset({
        PipelineStatus.youtube_found,
        PipelineStatus.youtube_missing,
        PipelineStatus.error,
    }),
    PipelineStatus.youtube_found: frozenset({
        PipelineStatus.metadata_fetched,
        PipelineStatus.metadata_failed,
        PipelineStatus.error,
    }),
    PipelineStatus.youtube_missing: frozenset(),  # terminal
    PipelineStatus.metadata_fetched: frozenset({
        PipelineStatus.ready_for_manual_review,
        PipelineStatus.error,
    }),
    PipelineStatus.metadata_failed: frozenset({
        PipelineStatus.youtube_found,  # retry
        PipelineStatus.error,
    }),
    PipelineStatus.ready_for_manual_review: frozenset({
        PipelineStatus.in_manual_review,
        PipelineStatus.error,
    }),
    PipelineStatus.in_manual_review: frozenset({
        PipelineStatus.approved,
        PipelineStatus.approved_with_edits,
        PipelineStatus.rejected,
        PipelineStatus.no_useful_text,
        PipelineStatus.ready_for_manual_review,  # operator release
        PipelineStatus.error,
    }),
    PipelineStatus.approved: frozenset(),          # terminal
    PipelineStatus.approved_with_edits: frozenset(),  # terminal
    PipelineStatus.rejected: frozenset(),           # terminal
    PipelineStatus.no_useful_text: frozenset(),     # terminal
    PipelineStatus.error: frozenset({
        PipelineStatus.discovered,  # allow reset / re-process
    }),
}


def validate_transition(
    from_status: PipelineStatus,
    to_status: PipelineStatus,
) -> None:
    """
    Validate that a pipeline status transition is allowed.

    Raises:
        ValueError: if the transition from *from_status* to *to_status* is not
                    defined in ALLOWED_TRANSITIONS.
    """
    allowed = ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValueError(
            f"Invalid pipeline status transition: {from_status.value!r} → {to_status.value!r}. "
            f"Allowed next states: {sorted(s.value for s in allowed) or '(none — terminal state)'}"
        )
