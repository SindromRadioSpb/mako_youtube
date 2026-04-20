# Bulk Review Workflow

> Covers: multi-select, bulk toolbar, bulk actions, Fill+Approve macro, safety model.

---

## Overview

The bulk processing layer sits **on top of** the existing single-item review lifecycle.
It reuses the same REST endpoints and DB-first architecture — there are no new backend
batch endpoints. All decisions are submitted individually through the standard API.

---

## Selecting Tasks

| Action | Result |
|--------|--------|
| Click a row | Single selection |
| Ctrl+Click | Add/remove one row |
| Shift+Click | Range selection |
| Ctrl+A | Select all currently visible rows |
| Click empty area | Clear selection |

The status bar shows total tasks and a per-status count breakdown.
The bulk toolbar shows the selection count and enables bulk buttons when 2+ rows are selected.

---

## Bulk Toolbar

The contextual toolbar appears between the main toolbar and the task list.

**Left side — operates on SELECTED tasks** (enabled when 2+ selected):

| Button | Action |
|--------|--------|
| ↺ Reopen | Return terminal tasks to in_review |
| ✓ Approve | Approve using raw chart data |
| ✎ Approve w/ Edits | Approve-with-edits using raw chart data |
| ★ Fill+Approve | Macro: fill lyrics from description → approve-with-edits |

**Right side — always enabled:**

| Control | Action |
|---------|--------|
| All filtered (N) → | Dropdown: apply any bulk action to ALL filtered tasks |

---

## Bulk Actions in Detail

### ↺ Reopen

- Only affects tasks in terminal state (`approved`, `approved_with_edits`, `rejected`, `no_useful_text`)
- Pending and in_review tasks are skipped with a reason
- After reopen the task returns to `in_review` and can be re-processed

### ✓ Approve

- Approves each task with `final_artist = artist_raw`, `final_song_title = song_title_raw`
- Pending tasks are automatically started before approving
- Terminal tasks are skipped unless "Also reopen terminal tasks" is checked in the options dialog

### ✎ Approve w/ Edits

- Same as Approve but submits as `approved_with_edits` decision
- Pending tasks are started automatically
- Terminal tasks skipped by default

### ★ Fill+Approve (macro)

This is the primary high-ROI bulk scenario.

**Per-task logic:**

```
if status = pending:
    POST /start
if status = terminal and reopen_terminal = ON:
    POST /reopen
GET /tasks/{id}                        ← fetch description_raw
if description empty and skip_empty_desc = ON:
    → skip
if lyrics already exist and fill_only_empty = ON and overwrite = OFF:
    → skip
POST /approve-edited  with final_lyrics_text = description_raw
```

**Safety options (shown in options dialog before run):**

| Option | Default | Meaning |
|--------|---------|---------|
| Reopen terminal tasks automatically | ON | Terminal tasks are reopened before processing |
| Fill only if Lyrics Text is empty | ON | Skip tasks that already have lyrics |
| Overwrite existing lyrics | OFF | Replace existing lyrics with description (⚠ destructive) |
| Skip tasks with empty description | ON | Skip tasks where description_raw is blank |

> **Safe defaults prevent accidental overwrite of already-edited lyrics.**
> The operator must explicitly enable "Overwrite existing lyrics" and confirm the warning.

---

## Selected vs All Filtered

This distinction is explicit and intentional:

- **Selected tasks**: use the selection (Ctrl+Click / Shift+Click / Ctrl+A), then click a left-side bulk button
- **All filtered tasks**: use the "All filtered (N) →" dropdown on the right, regardless of current selection

The options/preview dialog shows the target count before any run.

---

## Options Dialog

Shown before every bulk run. Contains:
- Description of the action
- Task statistics (pending / in_review / terminal counts)
- Safety option checkboxes (context-dependent)
- Confirm / Cancel

Enabling "Overwrite existing lyrics" shows a confirmation warning.

---

## Progress Dialog

Shown during the run:
- Progress bar and `X / Y` counter
- Current task identity (ID, artist, title)
- Running counters: Succeeded / Skipped / Failed
- **Cancel remaining** button — stops processing after the current item

The UI remains **fully responsive** during a bulk run (worker runs in a daemon thread).

---

## Result Summary

Shown after each bulk run:
- Aggregate counts (total / processed / approved / reopened / filled / skipped / failed / cancelled)
- Table of skipped / failed / cancelled items with reason
- **Copy summary** button — copies plain-text report to clipboard
- Close button

---

## Partial Failure Handling

If a single task fails (API error, stale state, network issue):
- The worker logs the failure with a reason
- Processing continues for all remaining tasks
- Failed items appear in the result summary with their error detail
- The whole run is **never aborted** due to a single item failure

---

## What Bulk Does NOT Do

- Does **not** open individual review dialogs per task
- Does **not** use Word export
- Does **not** require manual per-task editing of final fields (use single-item flow for that)
- Does **not** add new backend batch endpoints — all calls use existing item-level API
- Does **not** auto-refresh selection after the queue reloads (selection is cleared on reload)

---

## Recommended Operator Scenarios

### Scenario A: Fast-approve a set of simple tasks
1. Filter by `pending`
2. Ctrl+A to select all
3. Click **✓ Approve**
4. Confirm in options dialog

### Scenario B: Fill lyrics from description for selected tracks
1. Select 5–10 tasks (Ctrl+Click or Shift+Click)
2. Click **★ Fill+Approve**
3. Review options (keep safe defaults)
4. Confirm → monitor progress → review summary

### Scenario C: Mixed-status batch (include terminal tasks)
1. Filter by `all` or specific status
2. Select target tasks
3. Click **★ Fill+Approve**
4. Enable "Reopen terminal tasks automatically" in options dialog
5. Run

### Scenario D: Re-process previously rejected tasks
1. Filter by `rejected`
2. Ctrl+A to select all
3. Click **↺ Reopen** (returns them to in_review)
4. Then run **★ Fill+Approve** on the same selection

---

## Smoke-Check Commands (PowerShell)

```powershell
# Start backend
cd E:\projects\Project_Vibe\openclaw_mako_youtube
.\start.bat

# Launch UI
$env:API_BASE_URL = "http://localhost:8000"
python ui_launcher.py

# Run all tests
python -m pytest tests/ -v

# Run bulk worker tests only
python -m pytest tests/test_bulk_worker.py -v

# Import check
python -c "from app.ui.bulk_worker import BulkWorker; from app.ui.bulk_dialogs import BulkOptionsDialog; print('OK')"
```

---

## Files

| File | Role |
|------|------|
| `app/ui/review_queue_panel.py` | Multi-select, bulk toolbar, action dispatch |
| `app/ui/bulk_worker.py` | Worker logic — sequential API calls, cancellation, summary |
| `app/ui/bulk_dialogs.py` | Options, Progress, and Summary dialogs |
| `tests/test_bulk_worker.py` | Unit tests for worker logic |
