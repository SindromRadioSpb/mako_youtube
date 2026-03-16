"""
Export dialogs for unified Word export.

ExportOptionsDialog  — options/preview before export
ExportSummaryDialog  — result after export
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import messagebox, ttk

from app.services.unified_word_export_service import (
    ExportItem,
    ExportPolicy,
    ExportSummary,
    filter_and_sort,
)


class ExportOptionsDialog(tk.Toplevel):
    """
    Modal dialog shown before export.
    Lets operator choose statuses, skip rules, sort, page breaks.
    Shows preview: how many songs will be exported / skipped.
    """

    def __init__(self, parent: tk.Widget, items: List[ExportItem]) -> None:
        super().__init__(parent)
        self.title("Export to Word — Options")
        self.resizable(False, False)
        self.grab_set()
        self.result: Optional[ExportPolicy] = None
        self._items = items
        self._build(items)
        self._update_preview()
        self.transient(parent)
        self.wait_visibility()
        # Centre over parent
        self.geometry(f"+{parent.winfo_rootx()+60}+{parent.winfo_rooty()+60}")

    # ------------------------------------------------------------------

    def _build(self, items: List[ExportItem]) -> None:
        pad = dict(padx=12, pady=4)

        # ── Statuses ────────────────────────────────────────────────────
        status_lf = ttk.LabelFrame(self, text="Include statuses")
        status_lf.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        self._status_vars: Dict[str, tk.BooleanVar] = {}
        defaults = {"approved": True, "approved_with_edits": True,
                    "pending": False, "in_review": False,
                    "rejected": False, "no_useful_text": False}
        for i, (status, default) in enumerate(defaults.items()):
            var = tk.BooleanVar(value=default)
            self._status_vars[status] = var
            cb = ttk.Checkbutton(status_lf, text=status.replace("_", " "), variable=var,
                                  command=self._update_preview)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=8, pady=2)

        # ── Options ─────────────────────────────────────────────────────
        opt_lf = ttk.LabelFrame(self, text="Options")
        opt_lf.grid(row=1, column=0, sticky="ew", padx=12, pady=4)

        self._skip_empty_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_lf, text="Skip entries with empty lyrics",
                        variable=self._skip_empty_var,
                        command=self._update_preview).grid(row=0, column=0, sticky="w", padx=8, pady=2)

        self._sort_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_lf, text="Sort by chart position (ascending)",
                        variable=self._sort_var,
                        command=self._update_preview).grid(row=1, column=0, sticky="w", padx=8, pady=2)

        self._page_break_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_lf, text="Page break between songs",
                        variable=self._page_break_var,
                        command=self._update_preview).grid(row=2, column=0, sticky="w", padx=8, pady=2)

        # ── Preview ─────────────────────────────────────────────────────
        prev_lf = ttk.LabelFrame(self, text="Preview")
        prev_lf.grid(row=2, column=0, sticky="ew", padx=12, pady=4)

        self._preview_var = tk.StringVar()
        ttk.Label(prev_lf, textvariable=self._preview_var,
                  justify="left", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w", padx=8, pady=6)

        # ── Format example ──────────────────────────────────────────────
        ex_lf = ttk.LabelFrame(self, text="Section format")
        ex_lf.grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        ex_text = "Position 17. Artist Name - Song Title\n<lyrics text...>"
        ttk.Label(ex_lf, text=ex_text, font=("Consolas", 9),
                  foreground="#455a64").grid(row=0, column=0, sticky="w", padx=8, pady=6)

        # ── Buttons ─────────────────────────────────────────────────────
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, pady=(8, 12))
        ttk.Button(btn_frame, text="Export", command=self._on_export).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    def _get_policy(self) -> ExportPolicy:
        statuses = {s for s, v in self._status_vars.items() if v.get()}
        return ExportPolicy(
            included_statuses=statuses,
            skip_empty_lyrics=self._skip_empty_var.get(),
            sort_by_position=self._sort_var.get(),
            page_breaks=self._page_break_var.get(),
        )

    def _update_preview(self) -> None:
        policy = self._get_policy()
        included, summary = filter_and_sort(self._items, policy)
        lines = [
            f"Input:    {summary.total_input} tasks",
            f"Export:   {summary.exported} songs",
            f"Skipped:  {summary.skipped}"
            + (f"  ({summary.skipped_status} wrong status, {summary.skipped_empty} empty lyrics)"
               if summary.skipped else ""),
        ]
        self._preview_var.set("\n".join(lines))

    def _on_export(self) -> None:
        policy = self._get_policy()
        _, summary = filter_and_sort(self._items, policy)
        if summary.exported == 0:
            messagebox.showwarning(
                "Nothing to export",
                "No eligible items match the current options.\n"
                "Adjust the included statuses or uncheck 'Skip empty lyrics'.",
                parent=self,
            )
            return
        self.result = policy
        self.destroy()


class ExportSummaryDialog(tk.Toplevel):
    """
    Shown after a successful export.
    Displays path, counts, and Open file / Open folder buttons.
    """

    def __init__(self, parent: tk.Widget, summary: ExportSummary) -> None:
        super().__init__(parent)
        self.title("Export Complete")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)
        self._build(summary)
        self.wait_visibility()
        self.geometry(f"+{parent.winfo_rootx()+80}+{parent.winfo_rooty()+80}")

    def _build(self, s: ExportSummary) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Export complete!", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        file_name = Path(s.path).name
        ttk.Label(frame, text=f"File:").grid(row=1, column=0, sticky="w")
        ttk.Label(frame, text=file_name, font=("Consolas", 9)).grid(
            row=1, column=1, sticky="w", padx=(8, 0))

        ttk.Label(frame, text="Exported:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, text=str(s.exported)).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

        if s.skipped:
            ttk.Label(frame, text="Skipped:").grid(row=3, column=0, sticky="w")
            skip_detail = []
            if s.skipped_status:
                skip_detail.append(f"{s.skipped_status} wrong status")
            if s.skipped_empty:
                skip_detail.append(f"{s.skipped_empty} empty lyrics")
            ttk.Label(frame, text=f"{s.skipped}  ({', '.join(skip_detail)})",
                      foreground="#e65100").grid(row=3, column=1, sticky="w", padx=(8, 0))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(14, 0))

        ttk.Button(btn_frame, text="Open File",
                   command=lambda: self._open(s.path, file=True)).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Open Folder",
                   command=lambda: self._open(s.path, file=False)).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Close",
                   command=self.destroy).pack(side="left", padx=4)

    def _open(self, path: str, file: bool) -> None:
        from app.services.unified_word_export_service import open_file, open_folder
        try:
            if file:
                open_file(path)
            else:
                open_folder(path)
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc), parent=self)
