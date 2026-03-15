"""
Unit tests for BulkWorker.

All HTTP calls are mocked via unittest.mock — no real server required.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch

import pytest

from app.ui.bulk_worker import BulkItemResult, BulkOptions, BulkSummary, BulkWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    task_id: int = 1,
    status: str = "pending",
    artist: str = "Omer Adam",
    title: str = "Lev Sheli",
) -> Dict[str, Any]:
    return {
        "id": task_id,
        "review_status": status,
        "artist_raw": artist,
        "song_title_raw": title,
    }


def _detail(
    task_id: int = 1,
    description_raw: str = "Some lyrics here",
    existing_lyrics: str = "",
    artist_raw: str = "Omer Adam",
    song_title_raw: str = "Lev Sheli",
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "review_status": "in_review",
        "chart_entry": {"artist_raw": artist_raw, "song_title_raw": song_title_raw},
        "youtube_video": {"description_raw": description_raw},
        "latest_result": {"final_lyrics_text": existing_lyrics} if existing_lyrics else None,
    }


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx
            req = MagicMock()
            exc = httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=req,
                response=MagicMock(
                    status_code=self.status_code,
                    text=str(self._json),
                    json=lambda: {"detail": str(self._json)},
                ),
            )
            raise exc

    def json(self) -> Any:
        return self._json


def _make_client(responses: List[_FakeResponse]) -> MagicMock:
    """Return a mock httpx.Client that yields responses in order."""
    client = MagicMock()
    client.__enter__ = lambda s: client
    client.__exit__ = MagicMock(return_value=False)
    resp_iter = iter(responses)

    def _next(*_a, **_kw):
        return next(resp_iter)

    client.post = MagicMock(side_effect=_next)
    client.get  = MagicMock(side_effect=_next)
    return client


def _run(tasks, opts, responses) -> BulkSummary:
    worker = BulkWorker(tasks, opts, operator_id="tester", api_base_url="http://test")
    with patch("app.ui.bulk_worker.httpx.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value.__enter__ = lambda s: mock_client
        MockClient.return_value.__exit__  = MagicMock(return_value=False)
        resp_iter = iter(responses)

        def _next_resp(*_a, **_kw):
            return next(resp_iter)

        mock_client.post = MagicMock(side_effect=_next_resp)
        mock_client.get  = MagicMock(side_effect=_next_resp)
        return worker.run()


# ---------------------------------------------------------------------------
# REOPEN
# ---------------------------------------------------------------------------

def test_reopen_terminal_task_succeeds():
    tasks = [_task(status="approved")]
    opts = BulkOptions(action="reopen")
    summary = _run(tasks, opts, [_FakeResponse(200)])
    assert summary.processed == 1
    assert summary.reopened == 1
    assert summary.results[0].status == "ok"
    assert "reopened" in summary.results[0].actions_taken


def test_reopen_nonterminal_task_skipped():
    tasks = [_task(status="pending")]
    opts = BulkOptions(action="reopen")
    summary = _run(tasks, opts, [])   # no HTTP calls expected
    assert summary.skipped == 1
    assert summary.results[0].status == "skipped"


# ---------------------------------------------------------------------------
# APPROVE
# ---------------------------------------------------------------------------

def test_approve_pending_task_starts_then_approves():
    tasks = [_task(status="pending")]
    opts = BulkOptions(action="approve")
    # Expects: POST /start, POST /approve
    summary = _run(tasks, opts, [_FakeResponse(200), _FakeResponse(200)])
    assert summary.approved == 1
    assert summary.results[0].status == "ok"


def test_approve_in_review_task_approves_directly():
    tasks = [_task(status="in_review")]
    opts = BulkOptions(action="approve")
    summary = _run(tasks, opts, [_FakeResponse(200)])
    assert summary.approved == 1


def test_approve_terminal_task_skipped():
    tasks = [_task(status="rejected")]
    opts = BulkOptions(action="approve")
    summary = _run(tasks, opts, [])
    assert summary.skipped == 1
    assert summary.results[0].status == "skipped"


# ---------------------------------------------------------------------------
# APPROVE WITH EDITS
# ---------------------------------------------------------------------------

def test_approve_with_edits_pending_task():
    tasks = [_task(status="pending")]
    opts = BulkOptions(action="approve_with_edits")
    summary = _run(tasks, opts, [_FakeResponse(200), _FakeResponse(200)])
    assert summary.approved == 1


# ---------------------------------------------------------------------------
# FILL + APPROVE (macro)
# ---------------------------------------------------------------------------

def test_fill_approve_happy_path_pending():
    """Pending → start → get detail → approve_with_edits."""
    tasks = [_task(status="pending")]
    opts = BulkOptions(action="fill_approve")
    detail = _detail(description_raw="great lyrics")
    # POST /start, GET /detail, POST /approve-edited
    summary = _run(tasks, opts, [
        _FakeResponse(200),           # start
        _FakeResponse(200, detail),   # get detail
        _FakeResponse(200),           # approve-edited
    ])
    assert summary.filled == 1
    assert summary.approved == 1
    assert "filled" in summary.results[0].actions_taken
    assert "approved" in summary.results[0].actions_taken


def test_fill_approve_empty_description_skipped():
    tasks = [_task(status="pending")]
    opts = BulkOptions(action="fill_approve", skip_empty_desc=True)
    detail = _detail(description_raw="")
    summary = _run(tasks, opts, [
        _FakeResponse(200),           # start
        _FakeResponse(200, detail),   # get detail
    ])
    assert summary.skipped == 1
    assert "empty" in summary.results[0].reason.lower()


def test_fill_approve_existing_lyrics_fill_only_empty_skipped():
    tasks = [_task(status="in_review")]
    opts = BulkOptions(
        action="fill_approve",
        fill_only_empty=True,
        overwrite_lyrics=False,
        skip_empty_desc=True,
    )
    detail = _detail(description_raw="description text", existing_lyrics="already has lyrics")
    summary = _run(tasks, opts, [
        _FakeResponse(200, detail),   # get detail (no start needed — already in_review)
    ])
    assert summary.skipped == 1
    assert "fill_only_empty" in summary.results[0].reason or "Lyrics already" in summary.results[0].reason


def test_fill_approve_existing_lyrics_overwrite_enabled():
    tasks = [_task(status="in_review")]
    opts = BulkOptions(
        action="fill_approve",
        fill_only_empty=True,
        overwrite_lyrics=True,
        skip_empty_desc=True,
    )
    detail = _detail(description_raw="new description", existing_lyrics="old lyrics")
    summary = _run(tasks, opts, [
        _FakeResponse(200, detail),   # get detail
        _FakeResponse(200),           # approve-edited
    ])
    assert summary.filled == 1
    assert summary.approved == 1


def test_fill_approve_terminal_with_reopen():
    tasks = [_task(status="approved")]
    opts = BulkOptions(action="fill_approve", reopen_terminal=True)
    detail = _detail(description_raw="lyrics content")
    summary = _run(tasks, opts, [
        _FakeResponse(200),           # reopen
        _FakeResponse(200, detail),   # get detail
        _FakeResponse(200),           # approve-edited
    ])
    assert "reopened" in summary.results[0].actions_taken
    assert summary.reopened == 1
    assert summary.filled == 1
    assert summary.approved == 1


def test_fill_approve_terminal_reopen_disabled_skipped():
    tasks = [_task(status="approved")]
    opts = BulkOptions(action="fill_approve", reopen_terminal=False)
    summary = _run(tasks, opts, [])
    assert summary.skipped == 1
    assert "reopen_terminal" in summary.results[0].reason or "terminal" in summary.results[0].reason.lower()


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------

def test_partial_failure_continues_remaining():
    """One task 500s — worker continues to process remaining tasks."""
    tasks = [_task(task_id=1, status="in_review"), _task(task_id=2, status="in_review")]
    opts = BulkOptions(action="approve")
    summary = _run(tasks, opts, [
        _FakeResponse(500, {"detail": "Internal Error"}),  # task 1 fails
        _FakeResponse(200),                                 # task 2 succeeds
    ])
    assert summary.failed == 1
    assert summary.approved == 1
    assert summary.results[0].status == "failed"
    assert summary.results[1].status == "ok"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def test_cancel_stops_remaining_tasks():
    tasks = [_task(task_id=i, status="in_review") for i in range(1, 6)]
    opts = BulkOptions(action="approve")
    worker = BulkWorker(tasks, opts, operator_id="tester", api_base_url="http://test")

    call_count = 0

    def _progress(current, total, result):
        nonlocal call_count
        call_count += 1
        if current == 2:
            worker.cancel()  # cancel after second task

    worker.set_progress_callback(_progress)

    with patch("app.ui.bulk_worker.httpx.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value.__enter__ = lambda s: mock_client
        MockClient.return_value.__exit__  = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=_FakeResponse(200))
        summary = worker.run()

    assert summary.cancelled >= 1
    assert summary.approved <= 2   # at most 2 processed before cancel


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

def test_progress_callback_called_for_each_task():
    tasks = [_task(task_id=i, status="in_review") for i in range(1, 4)]
    opts = BulkOptions(action="approve")
    progress_calls = []

    worker = BulkWorker(tasks, opts, operator_id="tester", api_base_url="http://test")
    worker.set_progress_callback(lambda c, t, r: progress_calls.append((c, t, r.status)))

    with patch("app.ui.bulk_worker.httpx.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value.__enter__ = lambda s: mock_client
        MockClient.return_value.__exit__  = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=_FakeResponse(200))
        worker.run()

    assert len(progress_calls) == 3
    assert [c for c, _, _ in progress_calls] == [1, 2, 3]
