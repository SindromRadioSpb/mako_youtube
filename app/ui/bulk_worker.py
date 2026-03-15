"""
Bulk review worker for the OpenClaw Mako YouTube pipeline.

Executes item-level API calls sequentially in a background thread,
supports cancellation, and reports progress via a callback.

No Tkinter imports — pure logic layer, safe to test without a display.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

_TERMINAL_STATUSES = frozenset(
    ("approved", "approved_with_edits", "rejected", "no_useful_text")
)
_ACTIONABLE_STATUSES = frozenset(("pending", "in_review"))


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------


@dataclass
class BulkOptions:
    """Options that govern how the bulk worker processes each task."""

    # Which bulk action to run
    action: str = "fill_approve"
    # "reopen"           — reopen terminal tasks only
    # "approve"          — approve with raw chart data (no lyrics)
    # "approve_with_edits" — approve_with_edits with raw chart data
    # "fill_approve"     — fill lyrics from description + approve_with_edits

    # Safety options (relevant for fill_approve)
    reopen_terminal: bool = True       # reopen terminal tasks before acting
    fill_only_empty: bool = True       # fill lyrics only if field is currently empty
    overwrite_lyrics: bool = False     # overwrite existing lyrics (off by default)
    skip_empty_desc: bool = True       # skip tasks whose description_raw is empty


@dataclass
class BulkItemResult:
    """Per-task result produced by the worker."""

    task_id: int
    artist: str = ""
    title: str = ""
    status: str = "ok"          # "ok" | "skipped" | "failed" | "cancelled"
    reason: str = ""            # human-readable skip/fail reason
    actions_taken: List[str] = field(default_factory=list)
    # e.g. ["reopened", "filled", "approved"]


@dataclass
class BulkSummary:
    """Aggregate results returned after a bulk run completes."""

    total: int = 0
    processed: int = 0
    reopened: int = 0
    filled: int = 0
    approved: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: int = 0
    results: List[BulkItemResult] = field(default_factory=list)


# Callback signature: (current_index, total, last_result)
ProgressCallback = Callable[[int, int, BulkItemResult], None]


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class BulkWorker:
    """
    Processes a list of tasks sequentially using item-level REST calls.

    Usage::

        worker = BulkWorker(tasks, options, operator_id)
        worker.set_progress_callback(my_callback)
        summary = worker.run()   # blocking — call from a background thread
    """

    def __init__(
        self,
        tasks: List[Dict[str, Any]],
        options: BulkOptions,
        operator_id: str,
        api_base_url: str = API_BASE_URL,
    ) -> None:
        self._tasks = tasks
        self._options = options
        self._operator_id = operator_id
        self._api_base_url = api_base_url
        self._cancel_event = threading.Event()
        self._progress_cb: Optional[ProgressCallback] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_progress_callback(self, cb: ProgressCallback) -> None:
        self._progress_cb = cb

    def cancel(self) -> None:
        """Signal the worker to stop after the current item."""
        self._cancel_event.set()

    def run(self) -> BulkSummary:
        """Run all tasks. Blocking — must be called from a background thread."""
        summary = BulkSummary(total=len(self._tasks))

        with httpx.Client(base_url=self._api_base_url, timeout=20.0) as client:
            for i, task in enumerate(self._tasks):
                if self._cancel_event.is_set():
                    # Mark all remaining tasks as cancelled
                    for t in self._tasks[i:]:
                        r = BulkItemResult(
                            task_id=t["id"],
                            artist=t.get("artist_raw", ""),
                            title=t.get("song_title_raw", ""),
                            status="cancelled",
                            reason="Cancelled by operator",
                        )
                        summary.results.append(r)
                        summary.cancelled += 1
                    break

                result = self._process_one(client, task)
                summary.results.append(result)
                summary.processed += 1

                if result.status == "ok":
                    if "reopened" in result.actions_taken:
                        summary.reopened += 1
                    if "filled" in result.actions_taken:
                        summary.filled += 1
                    if "approved" in result.actions_taken:
                        summary.approved += 1
                elif result.status == "skipped":
                    summary.skipped += 1
                elif result.status == "failed":
                    summary.failed += 1

                if self._progress_cb:
                    self._progress_cb(i + 1, len(self._tasks), result)

        return summary

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _process_one(
        self, client: httpx.Client, task: Dict[str, Any]
    ) -> BulkItemResult:
        result = BulkItemResult(
            task_id=task["id"],
            artist=task.get("artist_raw", ""),
            title=task.get("song_title_raw", ""),
        )
        try:
            action = self._options.action
            if action == "reopen":
                return self._do_reopen(client, task, result)
            elif action == "approve":
                return self._do_approve(client, task, result)
            elif action == "approve_with_edits":
                return self._do_approve_with_edits(client, task, result)
            elif action == "fill_approve":
                return self._do_fill_approve(client, task, result)
            else:
                result.status = "failed"
                result.reason = f"Unknown action: {action!r}"
                return result
        except httpx.HTTPStatusError as exc:
            result.status = "failed"
            try:
                detail = exc.response.json().get("detail", exc.response.text[:300])
            except Exception:
                detail = exc.response.text[:300]
            result.reason = f"HTTP {exc.response.status_code}: {detail}"
            return result
        except Exception as exc:
            result.status = "failed"
            result.reason = str(exc)
            return result

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _do_reopen(
        self,
        client: httpx.Client,
        task: Dict[str, Any],
        result: BulkItemResult,
    ) -> BulkItemResult:
        if task.get("review_status") not in _TERMINAL_STATUSES:
            result.status = "skipped"
            result.reason = (
                f"Not in terminal state (status: {task.get('review_status')!r})"
            )
            return result
        r = client.post(
            f"/api/review/tasks/{task['id']}/reopen",
            json={"operator_id": self._operator_id},
        )
        r.raise_for_status()
        result.actions_taken.append("reopened")
        return result

    def _do_approve(
        self,
        client: httpx.Client,
        task: Dict[str, Any],
        result: BulkItemResult,
    ) -> BulkItemResult:
        status = task.get("review_status", "pending")
        if status in _TERMINAL_STATUSES:
            result.status = "skipped"
            result.reason = f"Already terminal (status: {status!r})"
            return result
        if status == "pending":
            r = client.post(
                f"/api/review/tasks/{task['id']}/start",
                json={"operator_id": self._operator_id},
            )
            r.raise_for_status()
        r = client.post(
            f"/api/review/tasks/{task['id']}/approve",
            json={
                "operator_id": self._operator_id,
                "final_artist": task.get("artist_raw"),
                "final_song_title": task.get("song_title_raw"),
            },
        )
        r.raise_for_status()
        result.actions_taken.append("approved")
        return result

    def _do_approve_with_edits(
        self,
        client: httpx.Client,
        task: Dict[str, Any],
        result: BulkItemResult,
    ) -> BulkItemResult:
        status = task.get("review_status", "pending")
        if status in _TERMINAL_STATUSES:
            result.status = "skipped"
            result.reason = f"Already terminal (status: {status!r})"
            return result
        if status == "pending":
            r = client.post(
                f"/api/review/tasks/{task['id']}/start",
                json={"operator_id": self._operator_id},
            )
            r.raise_for_status()
        r = client.post(
            f"/api/review/tasks/{task['id']}/approve-edited",
            json={
                "operator_id": self._operator_id,
                "final_artist": task.get("artist_raw"),
                "final_song_title": task.get("song_title_raw"),
            },
        )
        r.raise_for_status()
        result.actions_taken.append("approved")
        return result

    def _do_fill_approve(
        self,
        client: httpx.Client,
        task: Dict[str, Any],
        result: BulkItemResult,
    ) -> BulkItemResult:
        opts = self._options
        status = task.get("review_status", "pending")

        # Step 1 — ensure task is actionable (start or reopen as needed)
        if status in _TERMINAL_STATUSES:
            if not opts.reopen_terminal:
                result.status = "skipped"
                result.reason = "Terminal task and reopen_terminal is disabled"
                return result
            r = client.post(
                f"/api/review/tasks/{task['id']}/reopen",
                json={"operator_id": self._operator_id},
            )
            r.raise_for_status()
            result.actions_taken.append("reopened")
        elif status == "pending":
            r = client.post(
                f"/api/review/tasks/{task['id']}/start",
                json={"operator_id": self._operator_id},
            )
            r.raise_for_status()

        # Step 2 — fetch full detail to access description_raw
        r = client.get(f"/api/review/tasks/{task['id']}")
        r.raise_for_status()
        detail = r.json()

        yt = detail.get("youtube_video") or {}
        description_raw = (yt.get("description_raw") or "").strip()

        # Step 3 — check empty description guard
        if opts.skip_empty_desc and not description_raw:
            result.status = "skipped"
            result.reason = "Description is empty (skip_empty_desc is on)"
            return result

        # Step 4 — check existing lyrics guard
        lr = detail.get("latest_result") or {}
        existing_lyrics = (lr.get("final_lyrics_text") or "").strip()

        if existing_lyrics:
            if opts.fill_only_empty and not opts.overwrite_lyrics:
                result.status = "skipped"
                result.reason = "Lyrics already exist (fill_only_empty on, overwrite off)"
                return result

        # Use description as lyrics; fall back to existing if description empty
        lyrics_to_use = description_raw if description_raw else existing_lyrics
        result.actions_taken.append("filled")

        # Step 5 — approve with edits
        ce = detail.get("chart_entry") or {}
        r = client.post(
            f"/api/review/tasks/{task['id']}/approve-edited",
            json={
                "operator_id": self._operator_id,
                "final_artist": ce.get("artist_raw") or task.get("artist_raw"),
                "final_song_title": ce.get("song_title_raw") or task.get("song_title_raw"),
                "final_lyrics_text": lyrics_to_use or None,
            },
        )
        r.raise_for_status()
        result.actions_taken.append("approved")
        return result
