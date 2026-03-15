# Data Model — OpenClaw Mako YouTube Pipeline

## Entity Overview

The data model consists of six database tables corresponding to six ORM models:

```
chart_snapshot
    └── chart_entry  (1:N)
            └── review_task  (1:N, via chart_entry_id)
                    └── review_result (1:1, via review_task_id)

youtube_video
    └── review_task  (1:N, via youtube_video_id_ref)

audit_event  (append-only log, references any entity)
```

---

## Entities

### 1. `chart_snapshot`

Represents a single scrape of the Mako Hitlist chart page.

| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | Auto-incremented primary key |
| `source_name` | TEXT NOT NULL | Human-readable source label (e.g. `"mako_hitlist"`) |
| `source_url` | TEXT NOT NULL | The URL that was scraped |
| `snapshot_date` | DATE NOT NULL | Calendar date of the snapshot |
| `fetched_at` | TIMESTAMPTZ | When the scrape was executed |
| `status` | TEXT NOT NULL | `"fetching"`, `"ok"`, `"failed"` |
| `raw_payload_json` | JSONB | Full raw scrape payload |
| `scraper_version` | TEXT | Version of the scraper that produced this snapshot |
| `notes` | TEXT | Error message or human notes |

---

### 2. `chart_entry`

One row per song position in a snapshot.

| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `snapshot_id` | BIGINT FK → `chart_snapshot.id` | Parent snapshot |
| `chart_position` | INTEGER | Position on the chart (1-based) |
| `artist_raw` | TEXT | Artist as scraped (unmodified) |
| `song_title_raw` | TEXT | Song title as scraped |
| `artist_norm` | TEXT | Normalised artist (lowercase, NFC) |
| `song_title_norm` | TEXT | Normalised song title |
| `youtube_url` | TEXT | Full YouTube URL (if found) |
| `youtube_video_id` | TEXT | Extracted 11-char video ID |
| `has_youtube` | BOOLEAN | Whether a YouTube URL was extracted |
| `pipeline_status` | TEXT | See Pipeline Status State Machine |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Indexes:** `snapshot_id`, `youtube_video_id`, `pipeline_status`

---

### 3. `youtube_video`

Deduplicated YouTube video metadata. One row per unique `youtube_video_id`.

| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `youtube_video_id` | TEXT UNIQUE | 11-character YouTube video ID |
| `canonical_url` | TEXT | `https://www.youtube.com/watch?v={id}` |
| `video_title` | TEXT | Video title from yt-dlp |
| `channel_title` | TEXT | Channel / uploader name |
| `description_raw` | TEXT | Full video description text |
| `published_at` | TIMESTAMPTZ | Video upload date |
| `metadata_fetched_at` | TIMESTAMPTZ | When metadata was last fetched |
| `fetch_status` | TEXT | `"ok"`, `"failed"`, `"retrying"` |
| `fetch_error` | TEXT | Last error message |
| `fetcher_version` | TEXT | Version of the fetcher that populated this row |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Index:** `fetch_status`

---

### 4. `review_task`

One review task per `chart_entry` / `youtube_video` pair that needs human curation.

| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `chart_entry_id` | BIGINT FK → `chart_entry.id` | |
| `youtube_video_id_ref` | TEXT FK → `youtube_video.youtube_video_id` | |
| `review_status` | TEXT | See Review Status |
| `assigned_to` | TEXT | Operator ID who claimed the task |
| `priority` | INTEGER | Lower = reviewed sooner (default 100) |
| `created_at` | TIMESTAMPTZ | |
| `started_at` | TIMESTAMPTZ | When operator claimed the task |
| `completed_at` | TIMESTAMPTZ | When a terminal decision was recorded |

**Indexes:** `review_status`, `chart_entry_id`

---

### 5. `review_result`

One result per completed review task. 1:1 with `review_task`.

| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `review_task_id` | BIGINT UNIQUE FK → `review_task.id` | |
| `operator_id` | TEXT | Operator who submitted the decision |
| `final_artist` | TEXT | Curated artist name |
| `final_song_title` | TEXT | Curated song title |
| `final_lyrics_text` | TEXT | Extracted / curated lyrics |
| `decision` | TEXT NOT NULL | `approved`, `approved_with_edits`, `rejected`, `no_useful_text` |
| `review_notes` | TEXT | Operator's notes |
| `reviewed_at` | TIMESTAMPTZ | When the decision was submitted |

**Index:** `decision`

---

### 6. `audit_event`

Append-only structured event log. Every significant pipeline action writes a row here.

| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `entity_type` | TEXT NOT NULL | `"chart_snapshot"`, `"chart_entry"`, `"youtube_video"`, `"review_task"` |
| `entity_id` | TEXT NOT NULL | String form of the entity's primary key |
| `event_type` | TEXT NOT NULL | Symbolic event name (see below) |
| `event_payload_json` | JSONB | Additional structured context |
| `created_at` | TIMESTAMPTZ | |
| `actor_type` | TEXT | `"system"` or `"operator"` |
| `actor_id` | TEXT | Service name or operator ID |

**Indexes:** `(entity_type, entity_id)`, `event_type`

**Known event types:**
`chart_fetch_started`, `chart_fetch_completed`, `chart_entry_discovered`,
`youtube_url_found`, `youtube_url_missing`,
`youtube_metadata_fetch_started`, `youtube_metadata_fetch_completed`, `youtube_metadata_fetch_failed`,
`review_task_created`, `review_started`,
`review_approved`, `review_approved_with_edits`, `review_rejected`, `review_no_useful_text`

---

## Pipeline Status State Machine

```
                        ┌─────────────────────────────────────────┐
                        │               discovered                 │
                        └───────────────┬─────────────────────────┘
                                        │
                     ┌──────────────────┴─────────────┐
                     ▼                                  ▼
            ┌──────────────────┐            ┌──────────────────────┐
            │  youtube_found   │            │  youtube_missing      │ (terminal)
            └────────┬─────────┘            └──────────────────────┘
                     │
          ┌──────────┴───────────┐
          ▼                      ▼
  ┌────────────────┐   ┌───────────────────┐
  │metadata_fetched│   │  metadata_failed  │ ──► youtube_found (retry)
  └───────┬────────┘   └───────────────────┘
          │
          ▼
  ┌────────────────────────────┐
  │  ready_for_manual_review   │
  └──────────────┬─────────────┘
                 │
                 ▼
       ┌──────────────────┐
       │  in_manual_review│
       └──┬───────┬───────┴────────────────────┐
          │       │                            │
          ▼       ▼                            ▼
    ┌──────────┐ ┌────────────────────┐ ┌───────────────┐ ┌──────────────────┐
    │ approved │ │approved_with_edits │ │   rejected    │ │ no_useful_text   │
    │(terminal)│ │   (terminal)       │ │  (terminal)   │ │   (terminal)     │
    └──────────┘ └────────────────────┘ └───────────────┘ └──────────────────┘

error state can transition back to → discovered (re-process)
```

---

## Business Rules

1. **Deduplication:** A `review_task` is never created for a `youtube_video_id` that already has an `approved` or `approved_with_edits` result. The same video appearing in multiple chart snapshots generates at most one approved result.

2. **Terminal states:** `youtube_missing`, `approved`, `approved_with_edits`, `rejected`, `no_useful_text` are all terminal. Once a `chart_entry` reaches one of these states, no further pipeline status transitions are permitted.

3. **Concurrency:** A `review_task` in `in_review` state is locked to the operator who claimed it. A second operator attempting to start the same task receives a 409 Conflict.

4. **Metadata dedup:** `youtube_video` rows are keyed on `youtube_video_id` (UNIQUE). If the same YouTube video appears in multiple chart entries across different snapshots, only one `youtube_video` row is stored and reused.

5. **Audit trail:** Every state transition and review decision is recorded in `audit_event`. The audit log is append-only and must never be modified or deleted.

6. **Re-processing:** Entries stuck in `metadata_failed` can be re-processed via `POST /api/admin/reprocess/{chart_entry_id}`. This re-runs the yt-dlp fetch and updates the existing `youtube_video` record in place.
