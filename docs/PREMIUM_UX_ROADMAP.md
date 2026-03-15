# Premium UX Roadmap — OpenClaw Mako YouTube Review UI

> Generated: 2026-03-15
> Scope: Incremental premiumization of the Tkinter review workflow.
> Principle: operator-first, DB-first, progressive enhancement.

---

## 1. Repo Audit Findings

### Files participating in the review UI flow

| File | Role |
|------|------|
| `app/ui/review_queue_panel.py` | Queue Treeview, filter combobox, status bar |
| `app/ui/review_item_dialog.py` | Detail dialog: all sections, action buttons, prefill logic |
| `app/services/word_export_service.py` | Word export: `build_document()` + `export_and_open()` |
| `app/api/review.py` | REST endpoints: list/get/start/approve/approve-edited/reject/reopen/no-useful-text |
| `app/services/review_queue_service.py` | Business logic: task lifecycle, upsert ReviewResult |
| `app/domain/dto.py` | `ReviewTaskDetailResponse` with `latest_result` |
| `app/infra/sa_models.py` | ORM models: ReviewTask, ReviewResult, ChartEntry, YouTubeVideo |

### Existing strong points (already implemented)

- Scrollable canvas layout with fixed status bar + button bar
- Status badge colour-coded per state
- Readonly description text (selectable, Ctrl+C, Ctrl+A, right-click menu)
- Context menu on all editable fields
- Multiline Review Notes (3-row Text)
- Approve-with-edits diff check (warns if nothing changed)
- Auto-start-then-action for pending tasks (single background thread)
- Reopen flow for terminal tasks (POST `/reopen`, upsert ReviewResult)
- Prefill from `latest_result` on re-edit
- Unsaved-edits close-guard (warns before losing work)
- Copy-to-Lyrics button with overwrite confirm
- Character counter on description header
- Hebrew-safe: no string reversal, `tag_configure("rtl", justify="right")`
- Word export: pure `build_document()`, `export_and_open()` side effect

### Current Tkinter constraints

- No native RTL/bidi: Hebrew renders correctly on Windows (GDI/Uniscribe) but cursor navigates LTR
- No CSS-like styling: every colour/font/spacing must be explicit
- Modal dialogs block the queue panel (`grab_set` + `wait_window`)
- No reactive state: all UI updates are imperative Tk calls

---

## 2. UX Audit Findings

### Information Hierarchy

- **Gap**: Queue panel has no visual distinction between `pending` (orange) and `approved_with_edits` (dark green) — they appear in the default colour
- **Gap**: Status count in status bar is a single "N tasks loaded" — no breakdown by status
- **Gap**: Dialog has no fixed mini-header — operator must scroll up to see Task ID / status badge
- **Gap**: No "Previous Decision" row in Task Info — operator can't see prior result at a glance

### Workflow Speed

- **Friction**: No keyboard shortcut to open a selected row (must double-click)
- **Friction**: No F5 to refresh the queue without moving to the Refresh button
- **Friction**: Reject flow shows a generic confirm dialog — no inline notes capture before confirmation
- **Gap**: No "Next Task" flow — after closing dialog, operator must click the next row manually

### Editing Ergonomics

- **Gap**: `Approve w/ Edits` tooltip delay is 0ms — fires on accidental hover
- **Gap**: Dirty indicator (asterisk in title or field highlight) absent — operator doesn't know they've modified something until close-guard fires

### Status Clarity

- **Good**: Badge colour-coded. **Gap**: Mini-header absent → badge scrolls away
- **Gap**: After reopen, old decision still not prominently shown in Task Info

### Keyboard UX

- **Good**: Ctrl+Enter=Approve, Ctrl+Shift+Enter=Approve w/ Edits, Escape=Close
- **Gap**: No Ctrl+R=Reject, Ctrl+0=No Useful Text
- **Gap**: No Ctrl+Shift+C=Copy to Lyrics shortcut

### Feedback UX

- **Good**: Status bar always visible. **Gap**: API errors shown as blocking messagebox — recoverable errors should be inline banner
- **Gap**: Word export path shown truncated/full in status bar but no "Open exports folder" shortcut

### Visual Polish

- **Gap**: Button bar has no grouping separator between Approve/Reject cluster and Close/Word cluster
- **Gap**: Button labels are long (overflow risk at 1280px wide dialogs)
- **Gap**: No tooltip delay — tooltips appear immediately on hover

### Hebrew/RTL

- **Good**: Segoe UI 10, `justify="right"` via tags. **Gap**: Cursor LTR is a known Tkinter limitation — documented, no unsafe workaround
- **Gap**: Copy-to-Lyrics doesn't auto-apply `rtl` tag after paste

### Open in Word

- **Good**: Organic placement in button bar. **Gap**: Export path shown full (can be long) in status bar
- **Gap**: No "Open exports folder" utility button

### Layout Stress

- **Good**: `minsize(740, 580)`, scrollable canvas. **Gap**: Button bar can overflow at 1280×768 if all 6 buttons render with full text
- **Gap**: No column-resize or truncation on artist/song columns in Treeview at narrow widths

---

## 3. Premium Gap Analysis

| Dimension | Current "good workable UI" | Target "premium operator desktop UI" |
|-----------|---------------------------|--------------------------------------|
| Queue visual scan | All rows same colour except approved/rejected/in_review | Pending rows instantly visible (orange), approved_with_edits distinct (dark green) |
| Queue status info | "N tasks loaded" | "15 tasks — 3 pending · 2 in_review · 7 approved" |
| Dialog header | Badge inside scrollable canvas | Sticky mini-header always visible: Task # · Status · Artist – Title |
| Prior decision | Not shown | "Previous: approved_with_edits by alice on 2026-03-14" in Task Info |
| Keyboard opening | Double-click only | Enter/Space on selected row |
| Keyboard refresh | Click Refresh button | F5 |
| Reject speed | Click Reject → confirm dialog (no notes) | Ctrl+R → reject with inline notes pre-focused |
| Dirty indicator | Close-guard fires on close | Asterisk in window title as soon as field edited |
| API errors | Blocking messagebox | Inline yellow error banner (dismissible) |
| Button bar | All on one row, no grouping | Primary (Approve/ApproveEdited) | Danger (Reject/NoText) | Utility (Word/Close) |
| Tooltip delay | 0ms | 400ms |
| Word export status | Full path in status bar | "Exported: review_42.docx  [Open folder]" |

---

## 4. Prioritized Roadmap

### P0 — Must-have / Operator pain

| # | Improvement | Impact | Complexity | Regression Risk |
|---|-------------|--------|------------|-----------------|
| P0-1 | Enter/Space open selected row in queue | High — keyboard-first | Low | Minimal |
| P0-2 | F5 refresh queue | High — muscle memory | Low | None |
| P0-3 | `pending` orange + `approved_with_edits` dark-green row tags | High — instant status scan | Low | None |
| P0-4 | Status breakdown counter ("3 pending · 2 in_review…") | High — queue overview | Low | None |

### P1 — High-value productivity

| # | Improvement | Impact | Complexity | Regression Risk |
|---|-------------|--------|------------|-----------------|
| P1-1 | Sticky mini-header in dialog (Task ID + badge outside canvas) | High — always visible context | Medium | Low |
| P1-2 | Previous decision row in Task Info | High — re-edit context | Low | None |
| P1-3 | Ctrl+R=Reject, Ctrl+0=No Useful Text, Ctrl+Shift+C=Copy-to-Lyrics hotkeys | High — keyboard-first | Low | None |
| P1-4 | Dirty indicator (asterisk in title bar) | Medium — unsaved-edit awareness | Low | None |

### P2 — Premium polish with strong ROI

| # | Improvement | Impact | Complexity | Regression Risk |
|---|-------------|--------|------------|-----------------|
| P2-1 | Button grouping (primary/danger/utility) with separator | Medium — visual clarity | Low | None |
| P2-2 | Inline error banner instead of blocking messagebox | Medium — workflow continuity | Medium | Low |
| P2-3 | Tooltip delay 400ms | Low — reduces accidental popups | Low | None |
| P2-4 | Word export: short filename + "Open folder" link in status | Low — ergonomic | Low | None |

### P3 — Nice-to-have

| # | Improvement | Impact | Complexity | Regression Risk |
|---|-------------|--------|------------|-----------------|
| P3-1 | "Next Task" flow (close + open next pending from queue) | Medium | High | Medium |
| P3-2 | Reject flow with inline notes field before confirm | Medium | Medium | Low |
| P3-3 | Column auto-resize / truncation in Treeview at narrow widths | Low | Medium | Low |

### Top 5 best ROI

1. **P0-3** — Colour tags for pending/approved_with_edits: 15 min work, immediate scan improvement
2. **P0-1/P0-2** — Enter/Space/F5: 20 min work, eliminates daily mouse friction
3. **P1-1** — Sticky mini-header: 45 min work, fixes context loss on scroll
4. **P1-2** — Previous decision row: 30 min work, eliminates re-edit confusion
5. **P0-4** — Status breakdown: 20 min work, instant queue-state awareness

### Top 3 overengineering risks

1. **Next Task flow** (P3-1) — complex state sync, cache invalidation, easy to break re-open flow
2. **Full RTL/bidi Tkinter workaround** — no safe hack exists; cursor LTR is documented as known limitation
3. **Async/reactive state management** — would require full rewrite; not worth it on Tkinter stack

### What NOT to do now

- Do not switch to PyQt/wxPython/web UI — out of scope, breaks existing deployment
- Do not add real-time queue auto-refresh (polling) — unnecessary complexity, F5 is enough
- Do not add user management / role system — out of scope for operator tool
- Do not add animated transitions or CSS-style themes — Tkinter theming is fragile

---

## 5. PATCH Plan

### PATCH-01 — Queue keyboard + colour + status breakdown

**Scope**: `review_queue_panel.py` only
**Changes**:
- Add `tag_configure("pending", foreground="#e65100")` and `tag_configure("approved_with_edits", foreground="#1b5e20")`
- Bind `<Return>` and `<space>` on Treeview to open selected row
- Bind `<F5>` on panel to refresh
- Update `_populate_tree` to compute per-status counts and show in status bar

**Expected UX**: Queue instantly shows orange pending / dark-green approved_with_edits rows. Enter opens card. F5 refreshes. Status bar shows "15 tasks — 3 pending · 2 in_review · 7 approved".
**Risk**: Low
**Tests**: Manual — open queue, verify colours, press Enter, press F5

---

### PATCH-02 — Sticky mini-header + previous decision in dialog

**Scope**: `review_item_dialog.py` only
**Changes**:
- Add `_mini_header` frame packed `side="top"` BEFORE `content_outer` — contains Task ID label + status badge + artist/title label
- Update `_populate_detail` to update mini-header with live data
- Add "Previous Decision" row in `_build_section_task_info` (shown if `latest_result` present)

**Expected UX**: Task ID and status always visible even when scrolled down. Re-edit shows "Previous: approved_with_edits by alice on 2026-03-14".
**Risk**: Low
**Tests**: Manual — scroll dialog, verify header persists; open previously-processed task

---

### PATCH-03 — Keyboard shortcuts: Reject, No Useful Text, Copy-to-Lyrics

**Scope**: `review_item_dialog.py`
**Changes**:
- `Ctrl+R` → `_on_reject()`
- `Ctrl+0` → `_on_no_useful_text()`
- `Ctrl+Shift+C` → `_copy_desc_to_lyrics()`
- Add tooltip text to buttons listing their hotkeys

**Risk**: Low
**Tests**: Manual — press shortcuts, verify correct action triggers

---

### PATCH-04 — Dirty indicator + button grouping + tooltip delay

**Scope**: `review_item_dialog.py`
**Changes**:
- On any StringVar trace or Text `<<Modified>>` event: prepend `*` to window title
- Add separator between (Approve/ApproveEdited) and (Reject/NoText) button groups
- `_Tooltip` delay: add `after(400, _show)` + cancel on `<Leave>`

**Risk**: Low
**Tests**: Manual — edit field, verify `*` in title; verify separator visible

---

### PATCH-05 — Inline error banner (replace blocking messagebox for recoverable errors)

**Scope**: `review_item_dialog.py`
**Changes**:
- Add `_error_banner` frame (yellow, dismissible) packed between mini-header and canvas
- On recoverable API errors (4xx except 404): show banner instead of messagebox
- On 404/network error: keep messagebox (task gone = non-recoverable)

**Risk**: Medium (changes error handling flow)
**Tests**: Mock API returning 409, verify banner shown not messagebox

---

### PATCH-06 — Word export UX: short filename + open-folder button

**Scope**: `review_item_dialog.py`
**Changes**:
- In `_on_open_in_word` success: extract `os.path.basename(path)`, show "Exported: {filename}"
- Add clickable "📂" label or button next to the message that opens the exports folder

**Risk**: Low
**Tests**: Manual — export, verify short filename, click folder button

---

### PATCH-07 — Next Task flow

**Scope**: `review_item_dialog.py` + `review_queue_panel.py`
**Changes**:
- Pass sorted pending/in_review task list from panel to dialog
- After successful action: `after(0, _open_next_task)` — find next task ID in list, open dialog
- Add "Next Task" button to dialog button bar (visible when pending/in_review tasks remain)

**Risk**: Medium — requires panel-to-dialog data flow
**Tests**: Manual — approve task, verify next dialog opens automatically

---

## 6. Files Likely to Change

| File | PATCHes |
|------|---------|
| `app/ui/review_queue_panel.py` | PATCH-01, PATCH-07 |
| `app/ui/review_item_dialog.py` | PATCH-02..07 |
| `app/services/word_export_service.py` | PATCH-06 (potentially) |
| `tests/test_review_queue_service.py` | PATCH-05 (if API error simulation needed) |

---

## 7. Tests and UX Validation

### A. Automated tests

- `tests/test_review_queue_service.py` — already covers create/start/approve/approve_with_edits/reject/no_useful_text/reopen
- Add mock test for upsert path (re-edit existing result → UPDATE not INSERT)

### B. Manual UX checks

- [ ] Queue shows orange `pending` rows
- [ ] Queue shows dark green `approved_with_edits` rows
- [ ] Enter key opens selected row
- [ ] F5 refreshes queue
- [ ] Status bar shows "N tasks — X pending · Y in_review…"
- [ ] Dialog mini-header persists on scroll
- [ ] Task Info shows previous decision for re-edit task
- [ ] Ctrl+R triggers reject flow
- [ ] Ctrl+0 triggers no-useful-text
- [ ] Ctrl+Shift+C copies description to lyrics
- [ ] Dirty indicator (`*`) appears on field edit
- [ ] Word export shows short filename, folder button works

### C. Operator scenario checks

- [ ] Long Hebrew description (500+ chars) — wrap, scroll, select, copy
- [ ] Mixed Hebrew + URLs + credits — render without corruption
- [ ] Pending task → action button (auto-start-then-action)
- [ ] In-review task → all action buttons active
- [ ] Terminal task → Reopen button, action buttons disabled
- [ ] Re-edit: fields prefill from `latest_result`
- [ ] Approve with edits after changing only lyrics
- [ ] Reject with review notes
- [ ] Open in Word → file opens, Hebrew preserved

### D. Regression checks

- [ ] Upsert ReviewResult on re-edit (no 500 UNIQUE constraint error)
- [ ] Reopen flow → status → `in_review`, `completed_at = None`
- [ ] Close-guard fires if artist/title/lyrics changed and no action submitted
- [ ] Close-guard does NOT fire after successful action (prefill cleared)
- [ ] Double-click in queue opens correct task ID
- [ ] Filter combobox filters correctly for all status values

---

## 8. Smoke-Check Commands (PowerShell)

```powershell
# Start backend
cd J:\Project_Vibe\openclaw_mako_youtube
.\start.bat

# Run UI standalone (after backend is up)
$env:API_BASE_URL = "http://localhost:9000"
python -m app.ui.review_queue_panel

# Run tests
python -m pytest tests/test_review_queue_service.py -v

# Check imports
python -c "from app.ui.review_queue_panel import ReviewQueuePanel; print('OK')"
python -c "from app.ui.review_item_dialog import ReviewItemDialog; print('OK')"
```

---

## 9. Definition of Done

A task is "premium-grade" when:

**Queue view:**
- [ ] Operator can scan pending vs completed rows by colour without reading status column
- [ ] F5 refreshes, Enter opens — no mouse required for basic navigation
- [ ] Status bar gives instant count breakdown

**Dialog view:**
- [ ] Task ID + status badge always visible (never scrolls away)
- [ ] Previous decision visible in Task Info on re-edit
- [ ] All primary actions reachable by keyboard (Ctrl+Enter, Ctrl+Shift+Enter, Ctrl+R, Ctrl+0)
- [ ] Dirty indicator shows if fields were changed
- [ ] Errors shown inline for recoverable cases — no blocking dialog interrupts flow
- [ ] Word export: short filename visible, folder accessible in one click

**Anti-patterns that must disappear:**
- Operator can't tell which rows need action without reading every status cell
- Scrolling the dialog hides Task ID and status badge
- Operator submits Approve on a re-edit and can't remember what the previous decision was
- Reject flow requires mouse-click through two dialogs before notes can be entered
- API error blocks all further interaction with a modal messagebox

---

## 10. Commit Strategy

One commit per PATCH, with descriptive message:

```
feat(ui): PATCH-01 queue colour tags + keyboard open + F5 + status breakdown
feat(ui): PATCH-02 sticky mini-header + previous decision in dialog Task Info
feat(ui): PATCH-03 keyboard shortcuts Ctrl+R / Ctrl+0 / Ctrl+Shift+C
feat(ui): PATCH-04 dirty indicator + button grouping + tooltip delay 400ms
feat(ui): PATCH-05 inline error banner replaces blocking messagebox
feat(ui): PATCH-06 Word export short filename + open-folder button
feat(ui): PATCH-07 Next Task flow — auto-open next pending after action
```

Each commit must pass:
1. `python -m pytest tests/ -v` — no regressions
2. `python -c "from app.ui.review_queue_panel import ReviewQueuePanel"` — no import errors
3. Manual smoke session: open queue → open card → perform action → queue refreshes

---

## Optional: Top 10 Premium Wins

1. Colour tags for `pending` + `approved_with_edits` in queue (15 min, immediate scan improvement)
2. Enter/Space to open row (10 min, eliminates daily double-click)
3. F5 refresh (5 min, muscle memory)
4. Status breakdown in status bar (20 min, queue overview)
5. Sticky mini-header in dialog (45 min, context never lost on scroll)
6. Previous decision row in Task Info (30 min, re-edit context)
7. Ctrl+R/Ctrl+0 shortcuts (20 min, keyboard-first reject flow)
8. Dirty indicator `*` in title (20 min, unsaved awareness without close-guard surprise)
9. Inline error banner (60 min, non-blocking error recovery)
10. Word export short filename + folder button (20 min, export ergonomics)

---

## Optional: Future UX Direction (post-Tkinter)

If the project outgrows Tkinter, the natural next step is a **local web UI** (FastAPI serving a React/Vue SPA at `localhost:PORT`). This would enable:
- Native RTL rendering (CSS `direction: rtl`)
- Proper button grouping with CSS flexbox
- Toast notifications instead of status bar
- Keyboard shortcut library (Mousetrap / react-hotkeys)
- Dark mode
- Queue auto-refresh via WebSocket or SSE

The DB-first architecture and REST API are already web-ready — UI migration would not require backend changes.
