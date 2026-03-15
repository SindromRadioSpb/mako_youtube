"""
Tkinter Review Queue Panel for the OpenClaw Mako YouTube pipeline.

Displays a filterable Treeview of ReviewTask rows fetched from the REST API.
Double-clicking a row opens a ReviewItemDialog for detailed review.
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
        self.rowconfigure(1, weight=1)

        # --- Toolbar ---
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

        # --- Treeview ---
        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=2)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=COLUMNS,
            show="headings",
            selectmode="browse",
        )
        for col in COLUMNS:
            self._tree.heading(col, text=COLUMN_LABELS[col])
        self._tree.column("task_id", width=60, anchor="e")
        self._tree.column("chart_position", width=65, anchor="center")
        self._tree.column("artist_raw", width=160)
        self._tree.column("song_title_raw", width=200)
        self._tree.column("youtube_present", width=40, anchor="center")
        self._tree.column("review_status", width=130)
        self._tree.column("created_at", width=165)
        self._tree.column("priority", width=60, anchor="e")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.bind("<Double-1>", self._on_row_double_click)
        self._tree.tag_configure("approved", foreground="#2e7d32")
        self._tree.tag_configure("rejected", foreground="#c62828")
        self._tree.tag_configure("in_review", foreground="#1565c0")
        self._tree.tag_configure("no_useful_text", foreground="#6d4c41")

        # --- Status bar ---
        self._status_bar_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self,
            textvariable=self._status_bar_var,
            relief="sunken",
            anchor="w",
            padding=(4, 2),
        )
        status_bar.grid(row=2, column=0, sticky="ew")

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
            yt_present = "Y" if task.get("has_youtube") else "N"
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

        self._set_status(f"{len(self._tasks)} task(s) loaded")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_filter_changed(self, _event: Any = None) -> None:
        self._load_tasks(self._status_var.get())

    def _on_refresh(self) -> None:
        self._load_tasks(self._status_var.get())

    def _on_row_double_click(self, event: Any) -> None:
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

        # Import here to avoid circular / heavy import at module level
        from app.ui.review_item_dialog import ReviewItemDialog

        dialog = ReviewItemDialog(self, task_data)
        dialog.grab_set()
        self.wait_window(dialog)
        # Refresh after dialog closes in case status changed
        self._load_tasks(self._status_var.get())

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
