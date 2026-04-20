# OpenClaw Mako YouTube Pipeline

## Overview

The OpenClaw Mako YouTube Pipeline is a semi-automatic music data ingestion and manual curation system. It scrapes the Mako Hitlist chart (https://hitlist.mako.co.il/), extracts YouTube URLs for chart entries, fetches YouTube metadata from the watch page HTML (with `yt-dlp` kept as a fallback path), and routes items requiring curation through a structured manual review workflow.

The system is designed to be run on a schedule (e.g., daily), with operators reviewing flagged items through a Tkinter desktop UI or REST API.

---

## Pipeline Stages

### Stage A — Chart Fetch

**Trigger:** `POST /api/chart/fetch`

1. Creates a `chart_snapshot` record with `status = "fetching"`.
2. Sends an HTTP GET to `https://hitlist.mako.co.il/` using `httpx`.
3. Parses the HTML with BeautifulSoup, extracting chart position, artist, song title, and outbound links.
4. Stores raw entry data as JSON in `chart_snapshot.raw_payload_json`.
5. Updates snapshot `status` to `"ok"` on success, `"failed"` on error.
6. Logs `chart_fetch_started` and `chart_fetch_completed` audit events.

**Output:** `FetchChartResponse { snapshot_id, status, entries_discovered }`

---

### Stage B — Snapshot Processing

**Trigger:** `POST /api/chart/{snapshot_id}/process`

1. Reads raw payload from the snapshot.
2. For each raw entry: creates a `chart_entry` record.
3. Runs `_extract_youtube_url()` over outbound links — only `youtube.com` / `youtu.be` URLs are accepted; Spotify, Apple Music, etc. are ignored.
4. Sets `has_youtube = True/False` and `pipeline_status`:
   - `youtube_found` if a YouTube URL was extracted.
   - `youtube_missing` if no YouTube URL found (terminal state).
5. Logs `chart_entry_discovered`, `youtube_url_found`, or `youtube_url_missing` audit events.

**Output:** `ProcessSnapshotResponse { snapshot_id, processed_entries, youtube_found, youtube_missing, metadata_ok, metadata_failed, tasks_created }`

---

### Stage C — YouTube Metadata Fetch

**Trigger:** `POST /api/youtube/fetch-metadata` or called programmatically for each `youtube_found` entry.

1. Extracts the video ID from the URL.
2. Deduplicates: if a `youtube_video` record with `fetch_status = "ok"` already exists, returns it immediately.
3. Fetches metadata in a background thread. The primary strategy is to parse `ytInitialPlayerResponse` directly from the YouTube watch page HTML so the pipeline does not depend on media-format resolution.
4. Falls back to `yt-dlp` only if the watch-page parser stops producing usable metadata.
5. Stores: `video_title`, `channel_title`, `description_raw`, `published_at`.
6. Retry logic: up to 3 attempts with 2s/4s exponential backoff for transient errors.
7. Non-retryable errors (404, private video, invalid URL) fail immediately and set `fetch_status = "failed"`.
8. Updates `chart_entry.pipeline_status`:
   - `metadata_fetched` on success.
   - `metadata_failed` on permanent failure (entry can be reprocessed via `POST /api/admin/reprocess/{id}`).

---

### Stage D — Review Task Creation

Triggered automatically during snapshot processing.

1. `review_queue_service.create_review_task()` is called.
2. If metadata was fetched successfully, the task is linked to `youtube_video.youtube_video_id`.
3. Dedup check: if a `review_task` already exists for this `youtube_video_id`, the new task is skipped.
4. Entries without a usable YouTube metadata record can still create a manual review task; these rely on chart data only.
5. A `review_task` record is created with `review_status = "pending"`.
6. `chart_entry.pipeline_status` is updated to `ready_for_manual_review`.

---

### Stage E — Manual Review

Operators use the Tkinter UI (`ReviewQueuePanel` → `ReviewItemDialog`) or REST API to claim and process tasks.

See `docs/MANUAL_REVIEW_WORKFLOW.md` for the detailed operator process.

---

### Stage F — Decision Recording

When the operator submits a decision:

1. `ReviewResult` is created with `decision`, `final_artist`, `final_song_title`, `final_lyrics_text`, `review_notes`.
2. `review_task.review_status` is updated to the matching terminal status.
3. `chart_entry.pipeline_status` is updated to the matching terminal status.
4. Audit event is logged.

---

### Stage G — Admin & Metrics

`GET /api/admin/metrics` returns aggregate counts across all pipeline stages, suitable for dashboards and monitoring.

`POST /api/admin/reprocess/{chart_entry_id}` triggers a re-fetch of YouTube metadata for entries stuck in `metadata_failed`.

---

## How to Run

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Install dependencies: `pip install -r requirements.txt`
- Install Playwright browsers (optional, for extended scraping): `playwright install chromium`

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/openclaw_mako` | Async PostgreSQL DSN |
| `SA_ECHO` | (empty) | Set to any value to enable SQLAlchemy query logging |

### Database Setup

Apply the migration:
```bash
psql -U postgres -d openclaw_mako -f app/migrations/001_mako_youtube_review_init.sql
```

Or let the FastAPI lifespan handler create tables automatically on first startup (development only).

### Start the API Server

```bash
uvicorn main:app --reload --port 8000
```

### Run Tests

```bash
pytest tests/ -v
```

### Launch the Desktop UI

```bash
python -m app.ui.review_queue_panel
```

---

## Workflow Config Reference

| Setting | Location | Description |
|---|---|---|
| `SCRAPER_VERSION` | `mako_chart_service.py` | Incremented when scraper logic changes |
| `FETCHER_VERSION` | `youtube_metadata_service.py` | Incremented when metadata extraction logic changes |
| `MAKO_HITLIST_URL` | `mako_chart_service.py` | Target scrape URL |
| `max_attempts` (retry) | `youtube_metadata_service.py` | Max retry count for metadata fetch (default 3) |
| `pool_size` | `sa_models.py` | SQLAlchemy async engine pool size (default 10) |
| `priority` | `create_review_task()` | Default review task priority (default 100, lower = higher priority) |
