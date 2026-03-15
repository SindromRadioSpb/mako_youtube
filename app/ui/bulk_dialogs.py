"""
Bulk action dialogs for the OpenClaw Mako YouTube review UI.

Three dialogs:
  BulkOptionsDialog  — pre-run options + task statistics
  BulkProgressDialog — live progress during the worker run
  BulkSummaryDialog  — post-run result summary
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional

from app.ui.bulk_worker import BulkItemResult, BulkOptions, BulkSummary

# ---------------------------------------------------------------------------
# Action display metadata
# ---------------------------------------------------------------------------

_ACTION_LABELS: Dict[str, str] = {
    "reopen":            "Reopen terminal tasks",
    "approve":           "Approve",
    "approve_with_edits":"Approve with edits",
    "fill_approve":      "Fill Lyrics from Description + Approve",
}

_ACTION_DESCRIPTIONS: Dict[str, str] = {
    "reopen": (
        "Reopen every selected terminal task so it returns to in_review state.\n"
        "Only tasks with status approved / rejected / no_useful_text are affected.\n"
        "Pending and in_review tasks are skipped."
    ),
    "approve": (
        "Approve each selected task using raw artist/title data from the chart.\n"
        "Pending tasks are started automatically. Terminal tasks are skipped."
    ),
    "approve_with_edits": (
        "Mark each task as 'approved with edits' using raw chart data.\n"
        "Pending tasks are started automatically. Terminal tasks are skipped."
    ),
    "fill_approve": (
        "For each task: fetch the raw YouTube description, copy it into the\n"
        "Lyrics Text field, then submit 'Approve with edits'.\n"
        "Pending tasks are started automatically.\n"
        "Terminal tasks can optionally be reopened first (see options below)."
    ),
}


# ---------------------------------------------------------------------------
# BulkOptionsDialog
# ---------------------------------------------------------------------------


class BulkOptionsDialog(tk.Toplevel):
    """
    Pre-run dialog showing task statistics and safety options.

    After wait_window(), check self.result:
        None      — operator cancelled
        BulkOptions — operator confirmed
    """

    def __init__(
        self,
        parent: tk.Widget,
        action: str,
        tasks: List[Dict[str, Any]],
    ) -> None:
        super().__init__(parent)
        self._action = action
        self._tasks = tasks
        self.result: Optional[BulkOptions] = None

        self.title(f"Bulk Action — {_ACTION_LABELS.get(action, action)}")
        self.resizable(False, False)
        self.grab_set()

        self._build_ui()
        self._center()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        pad = dict(padx=12, pady=6)

        # Action description
        desc_frame = ttk.LabelFrame(self, text="Action", padding=8)
        desc_frame.pack(fill="x", **pad)
        ttk.Label(
            desc_frame,
            text=_ACTION_DESCRIPTIONS.get(self._action, ""),
            wraplength=460, justify="left",
            foreground="#444444",
        ).pack(anchor="w")

        # Task statistics
        stats_frame = ttk.LabelFrame(self, text="Target tasks", padding=8)
        stats_frame.pack(fill="x", **pad)
        stats_frame.columnconfigure(1, weight=1)

        counts = self._compute_counts()
        rows = [
            ("Total targeted:", str(counts["total"])),
            ("  — pending:",     str(counts["pending"])),
            ("  — in_review:",   str(counts["in_review"])),
            ("  — terminal:",    str(counts["terminal"])),
        ]
        for r, (label, value) in enumerate(rows):
            ttk.Label(stats_frame, text=label, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 8)
            )
            color = "#e65100" if "pending" in label else (
                "#1565c0" if "in_review" in label else (
                "#c62828" if "terminal" in label else "#000000"
            ))
            ttk.Label(stats_frame, text=value, anchor="w", foreground=color).grid(
                row=r, column=1, sticky="w"
            )

        # Safety options (only for relevant actions)
        if self._action in ("fill_approve", "approve", "approve_with_edits"):
            opts_frame = ttk.LabelFrame(self, text="Options", padding=8)
            opts_frame.pack(fill="x", **pad)

            if self._action in ("approve", "approve_with_edits"):
                # Simpler options for plain approve
                self._reopen_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(
                    opts_frame,
                    text="Also reopen terminal tasks before approving",
                    variable=self._reopen_var,
                ).pack(anchor="w")
            else:
                # Full fill_approve options
                self._reopen_var     = tk.BooleanVar(value=True)
                self._fill_only_var  = tk.BooleanVar(value=True)
                self._overwrite_var  = tk.BooleanVar(value=False)
                self._skip_empty_var = tk.BooleanVar(value=True)

                ttk.Checkbutton(
                    opts_frame,
                    text="Reopen terminal tasks automatically",
                    variable=self._reopen_var,
                ).pack(anchor="w", pady=1)
                ttk.Checkbutton(
                    opts_frame,
                    text="Fill only if Lyrics Text is currently empty  (recommended)",
                    variable=self._fill_only_var,
                ).pack(anchor="w", pady=1)
                overwrite_cb = ttk.Checkbutton(
                    opts_frame,
                    text="Overwrite existing lyrics  ⚠ use with caution",
                    variable=self._overwrite_var,
                    command=self._on_overwrite_toggled,
                )
                overwrite_cb.pack(anchor="w", pady=1)
                ttk.Checkbutton(
                    opts_frame,
                    text="Skip tasks with empty description",
                    variable=self._skip_empty_var,
                ).pack(anchor="w", pady=1)

        elif self._action == "reopen":
            # No extra options for plain reopen
            pass

        # Operator note for terminal count > 0 and reopen actions
        if counts["terminal"] > 0 and self._action == "reopen":
            note = ttk.Label(
                self,
                text=f"ℹ  {counts['terminal']} terminal task(s) will be returned to in_review.",
                foreground="#1565c0", font=("Segoe UI", 9),
            )
            note.pack(padx=12, anchor="w")

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(
            btn_frame, text="Run Bulk Action", command=self._on_confirm
        ).pack(side="right")

    def _compute_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {
            "total": len(self._tasks),
            "pending": 0,
            "in_review": 0,
            "terminal": 0,
        }
        for t in self._tasks:
            s = t.get("review_status", "")
            if s == "pending":
                counts["pending"] += 1
            elif s == "in_review":
                counts["in_review"] += 1
            elif s in ("approved", "approved_with_edits", "rejected", "no_useful_text"):
                counts["terminal"] += 1
        return counts

    def _on_overwrite_toggled(self) -> None:
        if self._overwrite_var.get():
            if not messagebox.askyesno(
                "Overwrite Lyrics?",
                "Enabling 'Overwrite existing lyrics' will replace already-edited\n"
                "lyrics with the raw YouTube description for every selected task.\n\n"
                "This cannot be undone automatically.\n\n"
                "Are you sure?",
                parent=self,
            ):
                self._overwrite_var.set(False)

    def _on_confirm(self) -> None:
        opts = BulkOptions(action=self._action)

        if self._action == "fill_approve":
            opts.reopen_terminal  = self._reopen_var.get()
            opts.fill_only_empty  = self._fill_only_var.get()
            opts.overwrite_lyrics = self._overwrite_var.get()
            opts.skip_empty_desc  = self._skip_empty_var.get()
        elif self._action in ("approve", "approve_with_edits"):
            opts.reopen_terminal = self._reopen_var.get()

        self.result = opts
        self.destroy()

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        pw = self.master.winfo_rootx() + self.master.winfo_width() // 2
        ph = self.master.winfo_rooty() + self.master.winfo_height() // 2
        self.geometry(f"+{pw - w // 2}+{ph - h // 2}")


# ---------------------------------------------------------------------------
# BulkProgressDialog
# ---------------------------------------------------------------------------


class BulkProgressDialog(tk.Toplevel):
    """
    Live progress dialog shown while the bulk worker runs.

    Call update_progress() from the main thread (via widget.after()).
    """

    def __init__(
        self,
        parent: tk.Widget,
        total: int,
        cancel_callback: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._total = total
        self._cancel_cb = cancel_callback
        self._cancelled = False

        self.title("Bulk Run in Progress…")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)  # prevent bare close

        self._build_ui()
        self._center()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        pad = dict(padx=16, pady=6)

        # Heading
        ttk.Label(
            self, text="Running bulk action…",
            font=("Segoe UI", 11, "bold"),
        ).pack(**pad)

        # Progress bar
        self._progress_var = tk.DoubleVar(value=0.0)
        self._pb = ttk.Progressbar(
            self, variable=self._progress_var,
            maximum=self._total, length=420, mode="determinate",
        )
        self._pb.pack(padx=16, pady=(0, 4))

        # Progress label
        self._progress_lbl_var = tk.StringVar(value=f"0 / {self._total}")
        ttk.Label(self, textvariable=self._progress_lbl_var, foreground="#555555").pack()

        # Current task info
        info_frame = ttk.LabelFrame(self, text="Current task", padding=6)
        info_frame.pack(fill="x", padx=16, pady=6)
        self._current_var = tk.StringVar(value="Starting…")
        ttk.Label(
            info_frame, textvariable=self._current_var,
            wraplength=400, justify="left",
        ).pack(anchor="w")

        # Counters
        cnt_frame = ttk.Frame(self)
        cnt_frame.pack(padx=16, pady=4)
        self._ok_var      = tk.StringVar(value="0")
        self._skipped_var = tk.StringVar(value="0")
        self._failed_var  = tk.StringVar(value="0")
        for label, var, color in [
            ("Succeeded:", self._ok_var,      "#2e7d32"),
            ("Skipped:",   self._skipped_var, "#795548"),
            ("Failed:",    self._failed_var,  "#c62828"),
        ]:
            f = ttk.Frame(cnt_frame)
            f.pack(side="left", padx=10)
            ttk.Label(f, text=label, foreground="#555555").pack()
            ttk.Label(f, textvariable=var, font=("Segoe UI", 14, "bold"), foreground=color).pack()

        # Cancel button
        self._cancel_btn = ttk.Button(
            self, text="Cancel remaining", command=self._on_cancel
        )
        self._cancel_btn.pack(pady=(4, 12))

        self._ok_count = self._skipped_count = self._failed_count = 0

    def update_progress(
        self, current: int, total: int, result: BulkItemResult
    ) -> None:
        """Call from the main thread to update dialog with latest result."""
        self._progress_var.set(current)
        self._progress_lbl_var.set(f"{current} / {total}")

        if result.status == "ok":
            self._ok_count += 1
        elif result.status == "skipped":
            self._skipped_count += 1
        elif result.status == "failed":
            self._failed_count += 1

        self._ok_var.set(str(self._ok_count))
        self._skipped_var.set(str(self._skipped_count))
        self._failed_var.set(str(self._failed_count))

        artist = result.artist or "—"
        title  = result.title  or "—"
        status_icon = {"ok": "✓", "skipped": "↷", "failed": "✗", "cancelled": "◌"}.get(
            result.status, "?"
        )
        self._current_var.set(
            f"{status_icon}  #{result.task_id}  {artist} — {title}\n"
            f"   {result.reason or '  '.join(result.actions_taken) or result.status}"
        )

    def _on_cancel(self) -> None:
        if not self._cancelled:
            self._cancelled = True
            self._cancel_btn.configure(state="disabled", text="Cancelling…")
            self._cancel_cb()

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        pw = self.master.winfo_rootx() + self.master.winfo_width() // 2
        ph = self.master.winfo_rooty() + self.master.winfo_height() // 2
        self.geometry(f"+{pw - w // 2}+{ph - h // 2}")


# ---------------------------------------------------------------------------
# BulkSummaryDialog
# ---------------------------------------------------------------------------


class BulkSummaryDialog(tk.Toplevel):
    """Post-run result summary dialog."""

    def __init__(self, parent: tk.Widget, summary: BulkSummary) -> None:
        super().__init__(parent)
        self._summary = summary
        self.title("Bulk Run — Summary")
        self.resizable(True, True)
        self.geometry("560x500")
        self.minsize(480, 380)
        self._build_ui()
        self._center()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        s = self._summary
        pad = dict(padx=12, pady=4)

        # --- Top stats ---
        stats_frame = ttk.LabelFrame(self, text="Results", padding=8)
        stats_frame.pack(fill="x", **pad)
        stats_frame.columnconfigure(1, weight=1)
        stats_frame.columnconfigure(3, weight=1)

        stat_rows = [
            ("Total targeted:", str(s.total),     "Processed:",  str(s.processed)),
            ("Approved:",       str(s.approved),  "Reopened:",   str(s.reopened)),
            ("Filled:",         str(s.filled),    "Skipped:",    str(s.skipped)),
            ("Failed:",         str(s.failed),    "Cancelled:",  str(s.cancelled)),
        ]
        for r, (l1, v1, l2, v2) in enumerate(stat_rows):
            ttk.Label(stats_frame, text=l1, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 4)
            )
            fg1 = "#c62828" if "Failed" in l1 and int(v1) > 0 else "#000000"
            ttk.Label(stats_frame, text=v1, anchor="w", foreground=fg1).grid(
                row=r, column=1, sticky="w", padx=(0, 16)
            )
            ttk.Label(stats_frame, text=l2, anchor="e").grid(
                row=r, column=2, sticky="e", padx=(0, 4)
            )
            ttk.Label(stats_frame, text=v2, anchor="w").grid(
                row=r, column=3, sticky="w"
            )

        # --- Failed / skipped detail ---
        problem_items = [r for r in s.results if r.status in ("failed", "skipped", "cancelled")]
        if problem_items:
            detail_frame = ttk.LabelFrame(self, text="Skipped / Failed / Cancelled items", padding=6)
            detail_frame.pack(fill="both", expand=True, padx=12, pady=4)
            detail_frame.columnconfigure(0, weight=1)
            detail_frame.rowconfigure(0, weight=1)

            cols = ("task_id", "artist", "status", "reason")
            tree = ttk.Treeview(detail_frame, columns=cols, show="headings", height=8)
            tree.heading("task_id", text="Task ID")
            tree.heading("artist",  text="Artist")
            tree.heading("status",  text="Status")
            tree.heading("reason",  text="Reason")
            tree.column("task_id", width=65,  anchor="e")
            tree.column("artist",  width=130)
            tree.column("status",  width=80)
            tree.column("reason",  width=260)

            vsb = ttk.Scrollbar(detail_frame, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=vsb.set)
            tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")

            for item in problem_items:
                tree.insert(
                    "", "end",
                    values=(item.task_id, item.artist or "—", item.status, item.reason),
                )
                tag = {"failed": "failed", "skipped": "skipped", "cancelled": "cancelled"}.get(
                    item.status, ""
                )
                if tag:
                    tree.item(tree.get_children()[-1], tags=(tag,))

            tree.tag_configure("failed",    foreground="#c62828")
            tree.tag_configure("skipped",   foreground="#795548")
            tree.tag_configure("cancelled", foreground="#888888")
        else:
            ttk.Label(
                self,
                text="✓  All tasks processed successfully.",
                foreground="#2e7d32",
                font=("Segoe UI", 10),
            ).pack(padx=12, pady=8, anchor="w")

        # --- Buttons ---
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(
            btn_frame, text="Copy summary", command=self._copy_summary
        ).pack(side="right", padx=(0, 8))

    def _copy_summary(self) -> None:
        s = self._summary
        lines = [
            "Bulk Run Summary",
            "─" * 30,
            f"Total targeted : {s.total}",
            f"Processed      : {s.processed}",
            f"Approved       : {s.approved}",
            f"Reopened       : {s.reopened}",
            f"Filled         : {s.filled}",
            f"Skipped        : {s.skipped}",
            f"Failed         : {s.failed}",
            f"Cancelled      : {s.cancelled}",
        ]
        problems = [r for r in s.results if r.status != "ok"]
        if problems:
            lines.append("")
            lines.append("Issues:")
            for r in problems:
                lines.append(f"  #{r.task_id} [{r.status}] {r.reason}")
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)

    def _center(self) -> None:
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        pw = self.master.winfo_rootx() + self.master.winfo_width() // 2
        ph = self.master.winfo_rooty() + self.master.winfo_height() // 2
        self.geometry(f"+{pw - w // 2}+{ph - h // 2}")
