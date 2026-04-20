# Manual Review Workflow

## Overview

The manual review step is the human-in-the-loop stage of the OpenClaw Mako YouTube pipeline. Operators review chart entries that have been matched to YouTube videos and decide whether the video description contains usable lyrics text, whether it should be approved as-is, approved with corrections, rejected, or marked as having no useful text.

---

## UI Description

### Review Queue Panel (`ReviewQueuePanel`)

The main panel displays a filterable table of review tasks:

| Column | Description |
|---|---|
| Task ID | Internal review task identifier |
| Position | Chart position from the Mako Hitlist |
| Artist | Raw artist name as scraped |
| Song Title | Raw song title as scraped |
| YT? | Y/N — whether a YouTube URL was found |
| Status | Current review status of the task |
| Created | Timestamp when the task was created |
| Priority | Task priority (lower number = higher priority) |

**Filter dropdown** — filters tasks by status: `all`, `pending`, `in_review`, `approved`, `approved_with_edits`, `rejected`, `no_useful_text`.

**Refresh button** — reloads the task list from the API.

**Row colors:**
- Orange — `pending`
- Blue — `in_review`
- Green — `approved`
- Dark green — `approved_with_edits`
- Red — `rejected`
- Brown — `no_useful_text`

Double-clicking a row opens the `ReviewItemDialog`.

---

### Review Item Dialog (`ReviewItemDialog`)

The dialog has four sections:

#### 1. Source — Chart Entry
Displays the original chart data:
- Chart position
- Artist (raw, as scraped)
- Song title (raw, as scraped)

#### 2. YouTube Video
- Canonical URL — clickable, opens the video in the default browser
- Video title
- Channel name
- Published date

#### 3. Description (raw — read only)
A scrollable read-only text widget showing the full video description as fetched by the metadata service. The service first parses the YouTube watch page HTML and falls back to `yt-dlp` only if the page parser stops yielding usable metadata. Operators read this text to determine if it contains lyrics.

#### 4. Manual Finalization
Editable fields for the operator to fill in:
- **Final Artist** — corrected / normalised artist name
- **Final Title** — corrected / normalised song title
- **Lyrics Text** — the lyrics extracted from the description (paste or type)
- **Review Notes** — optional notes about the decision

---

## Step-by-Step Review Process

1. Open the Review Queue Panel.
2. Set the filter to `pending` to see unstarted tasks.
3. Double-click a row to open the Review Item Dialog.
4. Click **Start Review** and enter your operator ID. This claims the task (`in_review`) and prevents another operator from claiming the same task simultaneously.
5. Watch the YouTube video and read the raw description.
6. Fill in the **Manual Finalization** fields:
   - Correct artist and title if needed.
   - Paste extracted lyrics into the **Lyrics Text** field if present.
   - Add any notes in **Review Notes**.
7. Choose a decision (see Decision Types below).
8. The dialog closes automatically on success. The queue refreshes.

---

## Decision Types

| Decision | Button | Keyboard Shortcut | When to Use |
|---|---|---|---|
| **Approve** | Approve (Ctrl+↵) | `Ctrl+Enter` | Description contains lyrics; artist and title are correct as-is |
| **Approve With Edits** | Approve w/ Edits (Ctrl+Shift+↵) | `Ctrl+Shift+Enter` | Description contains lyrics; you have corrected the artist, title, or lyrics text |
| **Reject** | Reject | — | Video is wrong (wrong song, wrong artist, not music-related) |
| **No Useful Text** | No Useful Text | — | Video is correct but the description does not contain usable lyrics text |

Reject and No Useful Text show a confirmation dialog before submission.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Enter` | Approve |
| `Ctrl+Shift+Enter` | Approve With Edits |
| `Escape` | Close dialog (without submitting) |

---

## Deduplication Behaviour

The pipeline deduplicates review tasks at creation time. If an `approved` or `approved_with_edits` result already exists for a given YouTube video ID, a new review task for a different chart entry pointing to the same video will be skipped automatically. This avoids re-reviewing the same video across multiple chart snapshots.

---

## Pipeline Status Updates

Each operator decision updates the `chart_entry.pipeline_status` field:

| Decision | chart_entry.pipeline_status |
|---|---|
| Start Review | `in_manual_review` |
| Approve | `approved` |
| Approve With Edits | `approved_with_edits` |
| Reject | `rejected` |
| No Useful Text | `no_useful_text` |

Review decisions are terminal for the current submission, but the UI supports explicit reopening. Once a task reaches `approved`, `approved_with_edits`, `rejected`, or `no_useful_text`, the edit buttons are disabled and a **Reopen for Editing** action is shown instead.

---

## Open in Word (Optional Export)

### How It Works

The **Open in Word** button (bottom-right of the Review Item Dialog) generates a `.docx`
snapshot of the current task and opens it in Microsoft Word (or the system default `.docx`
handler). It is intended as a read-along aid while the operator reviews the raw description
or verifies Hebrew text.

**Operator flow:**
1. Open a task in the Review Item Dialog.
2. Click **Open in Word** at any time — before or after starting the review.
3. The export is generated in the background; the status bar shows progress.
4. Word (or compatible application) opens automatically.
5. All approve / reject decisions must still be made in the OpenClaw application.

### What Gets Exported

The `.docx` file contains the following sections:

| Section | Contents |
|---|---|
| Header | Task ID, review status, export timestamp (UTC) |
| Chart Source | Chart position, artist (raw), title (raw), YouTube URL |
| YouTube Metadata | Video ID, video title, channel, published date, canonical URL |
| Raw Description | Full `description_raw` text as fetched by the metadata service |
| Final Fields | Final artist, final title, lyrics text (as currently entered in the dialog), review notes |
| Footer notice | Warning that Word is not a source of truth |

### Where the File Is Saved

```
exports/tmp/review_task_{task_id}.docx
```

The file is overwritten on each export for the same task ID. The `exports/tmp/` directory
is tracked in git via a `.gitkeep` file but the `.docx` files themselves are excluded
(add `exports/tmp/*.docx` to `.gitignore` if not already present).

### What Word Is NOT

- Word is **not a source of truth** for any review decision.
- There is **no import from Word** — the application does not read back any changes made
  to the exported file.
- There is **no roundtrip** — edits made in Word have no effect on the database.
- Approve, Approve with Edits, Reject, and No Useful Text must always be performed
  through the OpenClaw application UI.

### Future Phases

- **Import from Word** and **version conflict handling** are planned for a future phase
  but are not yet implemented. The `build_document()` / `export_and_open()` separation
  in `word_export_service.py` is designed to make that integration straightforward.

### Tkinter RTL Limitations

Hebrew text displays correctly on Windows in all text and entry widgets (Segoe UI 10 font,
`justify="right"`). Cursor navigation within text fields follows LTR order — this is a
known Tkinter limitation on Windows and does not affect the content or correctness of
submitted data.

---

## Concurrent Review Safety

- `start_review` validates that the task is not already assigned to a different operator before claiming it.
- If two operators try to start the same task simultaneously, the second one receives a `409 Conflict` response from the API.
- An operator who has started a task but has not yet submitted a decision can release the task back to `ready_for_manual_review` by closing the dialog without acting (the task remains in `in_review` and must be released via the API or by an admin).
- Terminal tasks can be reopened explicitly through the UI or `POST /api/review/tasks/{task_id}/reopen`, which returns them to `in_review`.
