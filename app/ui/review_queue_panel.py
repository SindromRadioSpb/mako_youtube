"""
Tkinter Review Queue Panel for the OpenClaw Mako YouTube pipeline.

Displays a filterable Treeview of ReviewTask rows fetched from the REST API.
Double-clicking (or Enter/Space) on a row opens a ReviewItemDialog.
Supports multi-select and bulk actions via the bulk toolbar.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

import os

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

STATUS_OPTIONS: List[str] = [
    "all",
    "pending",
    "in_review",
    "approved",
    "approved_with_edits",
    "rejected",
    "no_useful_text",
]

COLUMNS = (
    "task_id",
    "chart_position",
    "artist_raw",
    "song_title_raw",
    "youtube_present",
    "review_status",
    "created_at",
    "priority",
)

COLUMN_LABELS = {
    "task_id": "Task ID",
    "chart_position": "Position",
    "artist_raw": "Artist",
    "song_title_raw": "Song Title",
    "youtube_present": "YT?",
    "review_status": "Status",
    "created_at": "Created",
    "priority": "Priority",
}


# ---------------------------------------------------------------------------
# Tooltip helper (panel-local, no delay needed for toolbar buttons)
# ---------------------------------------------------------------------------


def _attach_tooltip(widget: tk.Widget, text: str) -> None:
    """Attach a simple hover tooltip to a toolbar widget."""
    _win: list = [None]

    def _show(_e=None) -> None:
        if _win[0]:
            return
        x = widget.winfo_rootx() + 20
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        _win[0] = tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=text,
            background="#ffffe0", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=6, pady=3, justify="left",
        ).pack()

    def _hide(_e=None) -> None:
        if _win[0]:
            _win[0].destroy()
            _win[0] = None

    widget.bind("<Enter>", _show, add="+")
    widget.bind("<Leave>", _hide, add="+")


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class ReviewQueuePanel(tk.Frame):
    """
    Main review queue panel widget.

    Intended to be embedded in a parent Tk window or Toplevel.
    """

    def __init__(self, parent: tk.Widget, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self._tasks: List[Dict[str, Any]] = []
        self._build_ui()
        self._load_tasks("all")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)   # row 2 = treeview (bulk bar is row 1)

        # ── Row 0: Main toolbar ────────────────────────────────────────
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))

        ttk.Label(toolbar, text="Filter:").pack(side="left", padx=(0, 4))

        self._status_var = tk.StringVar(value="all")
        self._status_combo = ttk.Combobox(
            toolbar,
            textvariable=self._status_var,
            values=STATUS_OPTIONS,
            state="readonly",
            width=20,
        )
        self._status_combo.pack(side="left")
        self._status_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)

        self._refresh_btn = ttk.Button(
            toolbar, text="Refresh", command=self._on_refresh
        )
        self._refresh_btn.pack(side="left", padx=(8, 0))
        _attach_tooltip(
            self._refresh_btn,
            "Reload task list from the server (F5)\n"
            "Applies the current status filter.",
        )

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=(12, 0))

        self._fetch_btn = ttk.Button(
            toolbar, text="↓ Fetch Chart", command=self._on_fetch_chart
        )
        self._fetch_btn.pack(side="left", padx=(8, 0))
        _attach_tooltip(
            self._fetch_btn,
            "Fetch a new chart snapshot from hitlist.mako.co.il\n"
            "and create review tasks for all new entries.\n\n"
            "This may take 1–2 minutes (fetches YouTube metadata\n"
            "for each entry via yt-dlp).",
        )

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=(12, 0))
        self._auto_next_var = tk.BooleanVar(value=True)
        auto_next_cb = ttk.Checkbutton(
            toolbar,
            text="Auto-next",
            variable=self._auto_next_var,
        )
        auto_next_cb.pack(side="left", padx=(8, 0))
        _attach_tooltip(
            auto_next_cb,
            "Auto-next: when enabled, after approving / rejecting a task\n"
            "the next pending or in-review task opens automatically.\n"
            "Also shows the \"Next →\" button inside each task dialog.\n\n"
            "Uncheck to process tasks one at a time.",
        )

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=(12, 0))

        self._export_btn = tk.Menubutton(
            toolbar,
            text="⬇ Export DOCX",
            relief="groove",
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        self._export_btn.pack(side="left", padx=(8, 0))
        _attach_tooltip(
            self._export_btn,
            "Export songs to a single Word (.docx) document.\n"
            "Only approved / approved_with_edits by default.\n\n"
            "• Export selected — uses currently selected rows\n"
            "• Export all filtered — uses current filter view",
        )
        export_menu = tk.Menu(self._export_btn, tearoff=0)
        export_menu.add_command(
            label="Export selected to DOCX",
            command=lambda: self._on_export_docx(selected_only=True),
        )
        export_menu.add_command(
            label="Export all filtered to DOCX",
            command=lambda: self._on_export_docx(selected_only=False),
        )
        self._export_btn.configure(menu=export_menu)

        # ── Row 1: Bulk toolbar (contextual) ──────────────────────────
        bulk_bar = tk.Frame(self, bg="#eceff1", height=36)
        bulk_bar.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        bulk_bar.pack_propagate(False)  # fixed height
        self._build_bulk_bar(bulk_bar)

        # ── Row 2: Treeview ────────────────────────────────────────────
        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=6, pady=2)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=COLUMNS,
            show="headings",
            selectmode="extended",   # PATCH-BULK-01: multi-select
        )
        self._sort_state: Dict[str, bool] = {col: False for col in COLUMNS}  # False=asc
        for col in COLUMNS:
            self._tree.heading(
                col,
                text=COLUMN_LABELS[col],
                command=lambda c=col: self._sort_column(c),
            )
        self._tree.column("task_id",        width=60,  anchor="e")
        self._tree.column("chart_position", width=65,  anchor="center")
        self._tree.column("artist_raw",     width=160)
        self._tree.column("song_title_raw", width=200)
        self._tree.column("youtube_present",width=40,  anchor="center")
        self._tree.column("review_status",  width=130)
        self._tree.column("created_at",     width=165)
        self._tree.column("priority",       width=60,  anchor="e")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # Bindings
        self._tree.bind("<Double-1>",           self._on_row_double_click)
        self._tree.bind("<Return>",             self._on_row_open)
        self._tree.bind("<space>",              self._on_row_open)
        self._tree.bind("<<TreeviewSelect>>",   self._on_selection_changed)
        self._tree.bind("<Control-a>",          self._on_select_all)
        self._tree.bind("<Control-A>",          self._on_select_all)
        self.bind_all("<F5>", lambda _e: self._on_refresh())

        # Row colour tags
        self._tree.tag_configure("pending",             foreground="#e65100")
        self._tree.tag_configure("approved",            foreground="#2e7d32")
        self._tree.tag_configure("approved_with_edits", foreground="#1b5e20")
        self._tree.tag_configure("rejected",            foreground="#c62828")
        self._tree.tag_configure("in_review",           foreground="#1565c0")
        self._tree.tag_configure("no_useful_text",      foreground="#6d4c41")

        # ── Row 3: Status bar ──────────────────────────────────────────
        self._status_bar_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self,
            textvariable=self._status_bar_var,
            relief="sunken",
            anchor="w",
            padding=(4, 2),
        )
        status_bar.grid(row=3, column=0, sticky="ew")

    # ------------------------------------------------------------------
    # Bulk toolbar construction
    # ------------------------------------------------------------------

    def _build_bulk_bar(self, bar: tk.Frame) -> None:
        """
        Build the contextual bulk action toolbar.

        Inactive hint shown when <2 items selected.
        Action buttons enabled when 2+ items selected.
        All-filtered button always enabled.
        """
        inner = tk.Frame(bar, bg="#eceff1")
        inner.pack(side="left", fill="y", padx=8)

        # Selection count label
        self._sel_lbl_var = tk.StringVar(value="Select tasks for bulk actions  (Ctrl+A = all)")
        self._sel_lbl = tk.Label(
            inner,
            textvariable=self._sel_lbl_var,
            bg="#eceff1", fg="#78909c",
            font=("Segoe UI", 9),
        )
        self._sel_lbl.pack(side="left", padx=(0, 10))

        # Separator
        tk.Frame(bar, bg="#b0bec5", width=1).pack(side="left", fill="y", padx=4, pady=4)

        # Bulk action buttons (operate on SELECTED tasks)
        self._bulk_btns: List[ttk.Button] = []

        def _make_bulk_btn(text: str, action: str, tooltip: str) -> ttk.Button:
            btn = ttk.Button(
                bar,
                text=text,
                state="disabled",
                command=lambda a=action: self._on_bulk_action_selected(a),
            )
            btn.pack(side="left", padx=3, pady=4)
            _attach_tooltip(btn, tooltip)
            self._bulk_btns.append(btn)
            return btn

        _make_bulk_btn(
            "↺ Reopen",
            "reopen",
            "Reopen every selected terminal task → returns to in_review.\n"
            "Pending/in_review tasks are skipped.",
        )
        _make_bulk_btn(
            "✓ Approve",
            "approve",
            "Approve all selected tasks using raw chart data.\n"
            "Pending tasks are started automatically.",
        )
        _make_bulk_btn(
            "✎ Approve w/ Edits",
            "approve_with_edits",
            "Approve-with-edits all selected tasks using raw chart data.\n"
            "Pending tasks are started automatically.",
        )
        _make_bulk_btn(
            "★ Fill+Approve",
            "fill_approve",
            "Macro: for each selected task —\n"
            "  1. Reopen if terminal (optional)\n"
            "  2. Fetch raw YouTube description\n"
            "  3. Use description as Lyrics Text\n"
            "  4. Submit Approve with edits\n\n"
            "Safety options shown before run.",
        )

        # Right side: separator + All-filtered button
        tk.Frame(bar, bg="#b0bec5", width=1).pack(side="right", fill="y", padx=4, pady=4)

        self._all_filtered_var = tk.StringVar(value="All filtered (0) →")
        self._all_filtered_btn = tk.Menubutton(
            bar,
            textvariable=self._all_filtered_var,
            bg="#eceff1", fg="#37474f",
            font=("Segoe UI", 9),
            relief="groove",
            cursor="hand2",
        )
        self._all_filtered_btn.pack(side="right", padx=6, pady=4)
        _attach_tooltip(
            self._all_filtered_btn,
            "Apply a bulk action to ALL currently filtered tasks\n"
            "(regardless of what is selected in the list).",
        )
        # Build dropdown menu for all-filtered
        self._filtered_menu = tk.Menu(self._all_filtered_btn, tearoff=0)
        self._filtered_menu.add_command(
            label="↺ Reopen",
            command=lambda: self._on_bulk_action_filtered("reopen"),
        )
        self._filtered_menu.add_command(
            label="✓ Approve",
            command=lambda: self._on_bulk_action_filtered("approve"),
        )
        self._filtered_menu.add_command(
            label="✎ Approve w/ Edits",
            command=lambda: self._on_bulk_action_filtered("approve_with_edits"),
        )
        self._filtered_menu.add_separator()
        self._filtered_menu.add_command(
            label="★ Fill+Approve  (macro)",
            command=lambda: self._on_bulk_action_filtered("fill_approve"),
        )
        self._all_filtered_btn.configure(menu=self._filtered_menu)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_tasks(self, status_filter: str) -> None:
        """Fetch tasks from the API in a background thread to keep UI responsive."""
        self._set_status("Loading…")
        self._refresh_btn.configure(state="disabled")

        def _worker() -> None:
            try:
                params: Dict[str, str] = {}
                if status_filter != "all":
                    params["status"] = status_filter

                with httpx.Client(base_url=API_BASE_URL, timeout=10.0) as client:
                    resp = client.get("/api/review/tasks", params=params)
                    resp.raise_for_status()
                    data = resp.json()

                self._tasks = data.get("items", [])
                self.after(0, self._populate_tree)
            except Exception as exc:
                msg = str(exc)
                self.after(
                    0,
                    lambda m=msg: self._set_status(f"Error: {m}") if self.winfo_exists() else None,
                )
            finally:
                self.after(0, lambda: self._refresh_btn.configure(state="normal") if self.winfo_exists() else None)

        threading.Thread(target=_worker, daemon=True).start()

    def _populate_tree(self) -> None:
        """Repopulate the Treeview from self._tasks."""
        for item in self._tree.get_children():
            self._tree.delete(item)

        for task in self._tasks:
            yt_present = "Y" if task.get("has_youtube") else "—"
            created = (task.get("created_at") or "")[:19].replace("T", " ")
            row_tag = task.get("review_status", "")
            self._tree.insert(
                "",
                "end",
                iid=str(task["id"]),
                values=(
                    task["id"],
                    task.get("chart_position", ""),
                    task.get("artist_raw", ""),
                    task.get("song_title_raw", ""),
                    yt_present,
                    task.get("review_status", ""),
                    created,
                    task.get("priority", ""),
                ),
                tags=(row_tag,),
            )

        counts: Dict[str, int] = {}
        for t in self._tasks:
            s = t.get("review_status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        parts = []
        for key in ("pending", "in_review", "approved", "approved_with_edits",
                    "rejected", "no_useful_text"):
            if counts.get(key, 0):
                parts.append(f"{counts[key]} {key.replace('_', ' ')}")
        breakdown = " · ".join(parts) if parts else "none"
        self._set_status(f"{len(self._tasks)} task(s) — {breakdown}")

        # Update "All filtered" button label
        self._all_filtered_var.set(f"All filtered ({len(self._tasks)}) →")

        # Reset selection state
        self._on_selection_changed()

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _on_selection_changed(self, _event: Any = None) -> None:
        """Update bulk bar state when Treeview selection changes."""
        selected_iids = self._tree.selection()
        n = len(selected_iids)

        if n >= 2:
            self._sel_lbl_var.set(f"{n} selected")
            self._sel_lbl.configure(fg="#263238", font=("Segoe UI", 9, "bold"))
            for btn in self._bulk_btns:
                btn.configure(state="normal")
        elif n == 1:
            self._sel_lbl_var.set("1 selected  (select 2+ for bulk actions)")
            self._sel_lbl.configure(fg="#78909c", font=("Segoe UI", 9))
            for btn in self._bulk_btns:
                btn.configure(state="disabled")
        else:
            self._sel_lbl_var.set("Select tasks for bulk actions  (Ctrl+A = all)")
            self._sel_lbl.configure(fg="#78909c", font=("Segoe UI", 9))
            for btn in self._bulk_btns:
                btn.configure(state="disabled")

    def _on_select_all(self, _event: Any = None) -> None:
        """Ctrl+A — select all visible rows."""
        self._tree.selection_set(self._tree.get_children())
        return "break"

    def _get_selected_tasks(self) -> List[Dict[str, Any]]:
        selected_ids = {int(iid) for iid in self._tree.selection()}
        return [t for t in self._tasks if t["id"] in selected_ids]

    def _get_operator_id(self) -> Optional[str]:
        """Return the current session operator ID, prompting if not set."""
        from app.ui.review_item_dialog import (
            _get_session_operator,
            _set_session_operator,
        )
        from app.ui.review_item_dialog import _SimpleInputDialog

        op = _get_session_operator()
        if op:
            return op
        dialog = _SimpleInputDialog(self, "Operator ID", "Enter your operator ID for bulk action:")
        self.wait_window(dialog)
        if dialog.result:
            _set_session_operator(dialog.result)
            return dialog.result
        return None

    # ------------------------------------------------------------------
    # Bulk action triggers
    # ------------------------------------------------------------------

    def _on_bulk_action_selected(self, action: str) -> None:
        """Run bulk action on selected tasks."""
        tasks = self._get_selected_tasks()
        if not tasks:
            messagebox.showinfo("No selection", "Select at least 2 tasks first.", parent=self)
            return
        self._run_bulk(action, tasks)

    def _on_bulk_action_filtered(self, action: str) -> None:
        """Run bulk action on all currently filtered tasks."""
        tasks = list(self._tasks)
        if not tasks:
            messagebox.showinfo("No tasks", "No tasks in the current filtered view.", parent=self)
            return
        self._run_bulk(action, tasks)

    def _run_bulk(self, action: str, tasks: List[Dict[str, Any]]) -> None:
        """Show options dialog, then run the bulk worker with a progress dialog."""
        operator_id = self._get_operator_id()
        if not operator_id:
            return

        from app.ui.bulk_dialogs import (
            BulkOptionsDialog,
            BulkProgressDialog,
            BulkSummaryDialog,
        )
        from app.ui.bulk_worker import BulkWorker

        # 1 — Options dialog
        opts_dlg = BulkOptionsDialog(self, action=action, tasks=tasks)
        self.wait_window(opts_dlg)
        if opts_dlg.result is None:
            return  # cancelled
        options = opts_dlg.result

        # 2 — Progress dialog + worker
        worker = BulkWorker(tasks, options, operator_id)
        progress_dlg = BulkProgressDialog(self, total=len(tasks), cancel_callback=worker.cancel)
        progress_dlg.grab_set()

        def _on_progress(current: int, total: int, result) -> None:
            if progress_dlg.winfo_exists():
                progress_dlg.after(
                    0,
                    lambda c=current, t=total, r=result: progress_dlg.update_progress(c, t, r),
                )

        worker.set_progress_callback(_on_progress)

        def _worker_thread() -> None:
            summary = worker.run()
            if progress_dlg.winfo_exists():
                progress_dlg.after(0, lambda s=summary: _on_complete(s))

        def _on_complete(summary) -> None:
            if progress_dlg.winfo_exists():
                progress_dlg.destroy()
            # Refresh queue
            self._load_tasks(self._status_var.get())
            # Summary dialog
            sum_dlg = BulkSummaryDialog(self, summary)
            sum_dlg.grab_set()

        threading.Thread(target=_worker_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Event handlers (single-item)
    # ------------------------------------------------------------------

    def _sort_column(self, col: str) -> None:
        """Sort treeview rows by the given column, toggling asc/desc."""
        reverse = self._sort_state[col]
        self._sort_state[col] = not reverse

        # Map col name → task dict key
        key_map = {
            "task_id":        "id",
            "chart_position": "chart_position",
            "artist_raw":     "artist_raw",
            "song_title_raw": "song_title_raw",
            "youtube_present":"has_youtube",
            "review_status":  "review_status",
            "created_at":     "created_at",
            "priority":       "priority",
        }
        task_key = key_map.get(col, col)

        def _sort_key(task: Dict[str, Any]) -> Any:
            v = task.get(task_key)
            if v is None:
                return ("" if reverse else "\xff")  # nulls last when asc, first when desc
            return str(v).lower() if isinstance(v, str) else v

        self._tasks.sort(key=_sort_key, reverse=reverse)
        self._populate_tree()

        # Update heading arrows
        for c in COLUMNS:
            label = COLUMN_LABELS[c]
            if c == col:
                arrow = " ▼" if reverse else " ▲"
                self._tree.heading(c, text=label + arrow)
            else:
                self._tree.heading(c, text=label)

    def _on_filter_changed(self, _event: Any = None) -> None:
        self._load_tasks(self._status_var.get())

    def _on_refresh(self) -> None:
        self._load_tasks(self._status_var.get())

    def _on_fetch_chart(self) -> None:
        """Fetch a new chart snapshot from Mako and process it (background thread)."""
        self._fetch_btn.configure(state="disabled")
        self._refresh_btn.configure(state="disabled")
        self._set_status("Step 1/2 — Fetching chart from hitlist.mako.co.il…")

        def _worker() -> None:
            try:
                with httpx.Client(base_url=API_BASE_URL, timeout=60.0) as client:
                    # Step 1: fetch snapshot
                    r1 = client.post("/api/chart/fetch")
                    r1.raise_for_status()
                    snap = r1.json()
                    snapshot_id = snap["snapshot_id"]
                    discovered = snap["entries_discovered"]

                def _step2(sid=snapshot_id, disc=discovered):
                    if not self.winfo_exists():
                        return
                    self._set_status(
                        f"Step 2/2 — Processing {disc} entries "
                        f"(fetching YouTube metadata, may take 1–2 min)…"
                    )
                    threading.Thread(target=_process, args=(sid,), daemon=True).start()

                self.after(0, _step2)

            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._fetch_error(f"Fetch failed: {m}"))

        def _process(snapshot_id: int) -> None:
            try:
                with httpx.Client(base_url=API_BASE_URL, timeout=300.0) as client:
                    r2 = client.post(f"/api/chart/{snapshot_id}/process")
                    r2.raise_for_status()
                    result = r2.json()

                tasks_created = result.get("tasks_created", "?")
                yt_found = result.get("youtube_found", "?")
                yt_missing = result.get("youtube_missing", "?")
                meta_failed = result.get("metadata_failed", "?")

                def _done():
                    if not self.winfo_exists():
                        return
                    self._fetch_btn.configure(state="normal")
                    self._refresh_btn.configure(state="normal")
                    self._set_status(
                        f"Chart updated — {tasks_created} new tasks created  "
                        f"(YouTube: {yt_found} found, {yt_missing} missing, "
                        f"{meta_failed} metadata failed)"
                    )
                    self._load_tasks(self._status_var.get())

                self.after(0, _done)

            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._fetch_error(f"Process failed: {m}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _fetch_error(self, msg: str) -> None:
        if not self.winfo_exists():
            return
        self._fetch_btn.configure(state="normal")
        self._refresh_btn.configure(state="normal")
        self._set_status(f"Error: {msg}")
        messagebox.showerror("Fetch Chart Failed", msg, parent=self)

    def _on_export_docx(self, selected_only: bool) -> None:
        """Collect tasks, show export options dialog, run export."""
        from app.services.unified_word_export_service import (
            ExportItem, export_collection,
        )
        from app.ui.export_dialogs import ExportOptionsDialog, ExportSummaryDialog

        # Determine source tasks
        if selected_only:
            source = self._get_selected_tasks()
            if not source:
                messagebox.showinfo(
                    "No selection",
                    "Select at least one task first, or use 'Export all filtered'.",
                    parent=self,
                )
                return
        else:
            source = list(self._tasks)
            if not source:
                messagebox.showinfo(
                    "No tasks",
                    "No tasks in the current filtered view.",
                    parent=self,
                )
                return

        # Fetch final fields from API for each task
        self._set_status("Fetching export data…")
        self._export_btn.configure(state="disabled")

        def _worker() -> None:
            try:
                with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
                    resp = client.get("/api/review/export-items")
                    resp.raise_for_status()
                    data = resp.json()

                all_items_map = {i["task_id"]: i for i in data.get("items", [])}

                items = []
                for task in source:
                    tid = task["id"]
                    raw = all_items_map.get(tid) or {}
                    items.append(ExportItem(
                        task_id=tid,
                        chart_position=raw.get("chart_position") or task.get("chart_position"),
                        final_artist=raw.get("final_artist") or task.get("artist_raw") or "",
                        final_song_title=raw.get("final_song_title") or task.get("song_title_raw") or "",
                        final_lyrics_text=raw.get("final_lyrics_text") or "",
                        review_status=raw.get("review_status") or task.get("review_status") or "",
                    ))

                self.after(0, lambda i=items: _show_dialog(i))

            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: _on_error(m))

        def _show_dialog(items) -> None:
            if not self.winfo_exists():
                return
            self._export_btn.configure(state="normal")
            self._set_status("Ready")

            opts_dlg = ExportOptionsDialog(self, items)
            self.wait_window(opts_dlg)
            if opts_dlg.result is None:
                return

            try:
                label = "selected" if selected_only else "all_filtered"
                summary = export_collection(items, opts_dlg.result, label=label)
            except ValueError as exc:
                messagebox.showinfo("Nothing to export", str(exc), parent=self)
                return
            except RuntimeError as exc:
                messagebox.showerror("Export failed", str(exc), parent=self)
                return

            sum_dlg = ExportSummaryDialog(self, summary)
            self.wait_window(sum_dlg)

        def _on_error(msg: str) -> None:
            if not self.winfo_exists():
                return
            self._export_btn.configure(state="normal")
            self._set_status("Ready")
            messagebox.showerror("Export data fetch failed", msg, parent=self)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_row_open(self, event: Any = None) -> None:
        """Open the focused row — bound to Enter, Space."""
        iid = self._tree.focus()
        if not iid:
            return
        try:
            task_id = int(iid)
        except ValueError:
            return
        task_data = next((t for t in self._tasks if t["id"] == task_id), None)
        if task_data is None:
            return
        self._open_task_data(task_data)
        return "break"

    def _open_task_data(self, task_data: Dict[str, Any]) -> None:
        """Open a ReviewItemDialog for task_data, then advance if requested."""
        from app.ui.review_item_dialog import ReviewItemDialog
        auto_next = self._auto_next_var.get()
        dialog = ReviewItemDialog(
            self, task_data,
            task_list=self._tasks if auto_next else None,
            auto_next=auto_next,
        )
        dialog.grab_set()
        self.wait_window(dialog)
        next_task = dialog.next_task_data
        self._load_tasks(self._status_var.get())
        if next_task:
            self.after(0, lambda t=next_task: self._open_task_data(t))

    def _on_row_double_click(self, event: Any) -> None:
        self._on_row_open()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        self._status_bar_var.set(message)


# ---------------------------------------------------------------------------
# Standalone launcher for development / testing
# ---------------------------------------------------------------------------


def _launch_standalone() -> None:
    root = tk.Tk()
    root.title("OpenClaw — Review Queue")
    root.geometry("900x600")
    panel = ReviewQueuePanel(root)
    panel.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    _launch_standalone()
