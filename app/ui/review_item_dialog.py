"""
Tkinter Review Item Dialog for the OpenClaw Mako YouTube pipeline.

Opens a detailed view of a ReviewTask, including source metadata,
YouTube information, raw description text, and manual finalization fields.
Supports approve, approve-with-edits, reject, and no-useful-text workflows.

Fixes applied (PATCH-02 / PATCH-03 / PATCH-04):
  - Module-level _SESSION_OPERATOR_ID: operator is prompted once per session.
  - Exception capture bug fixed: lambda m=msg pattern throughout.
  - winfo_exists() guard on every .after(0, ...) callback.
  - Close button added (Esc also works).
  - Open in Word button via word_export_service.
  - Font changed to Segoe UI 10 for Hebrew readability.
  - justify="right" on text/entry widgets for Hebrew RTL.
  - Scrollable canvas layout so all sections are accessible at any window size.
"""
from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional

import os

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Session-level operator ID — persists for the lifetime of the Python process
# ---------------------------------------------------------------------------

_SESSION_OPERATOR_ID: str = ""


def _get_session_operator() -> str:
    return _SESSION_OPERATOR_ID


def _set_session_operator(op: str) -> None:
    global _SESSION_OPERATOR_ID
    _SESSION_OPERATOR_ID = op


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


class ReviewItemDialog(tk.Toplevel):
    """
    Dialog for reviewing a single ReviewTask.

    Args:
        parent:    Parent widget (typically ReviewQueuePanel).
        task_data: Dict matching ReviewTaskSummary shape from the API.
    """

    def __init__(self, parent: tk.Widget, task_data: Dict[str, Any]) -> None:
        super().__init__(parent)
        self._task_id: int = task_data["id"]
        self._task_data = task_data
        self._full_task: Optional[Dict[str, Any]] = None
        self._loading = False

        self.title(f"Review Task #{self._task_id}")
        self.geometry("920x760")
        self.minsize(720, 560)
        self.resizable(True, True)

        self._build_ui()
        self._bind_shortcuts()
        self._load_full_detail()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Two direct children of Toplevel — use pack only at this level.
        # btn_frame at bottom, content_outer fills the rest.
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side="bottom", fill="x", padx=8, pady=(4, 8))

        content_outer = ttk.Frame(self)
        content_outer.pack(side="top", fill="both", expand=True)

        # --- Scrollable canvas inside content_outer ---
        canvas = tk.Canvas(content_outer, highlightthickness=0)
        vsb = ttk.Scrollbar(content_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._inner = ttk.Frame(canvas, padding=8)
        self._canvas_win = canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._canvas_win, width=e.width),
        )
        # Mouse-wheel scrolling
        canvas.bind(
            "<Enter>",
            lambda e: canvas.bind_all(
                "<MouseWheel>",
                lambda ev: canvas.yview_scroll(-(ev.delta // 120), "units"),
            ),
        )
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # Grid layout inside self._inner
        self._inner.columnconfigure(0, weight=0)
        self._inner.columnconfigure(1, weight=1)

        # StringVars for finalization fields (declared before sections that read them)
        self._final_artist_var = tk.StringVar()
        self._final_title_var = tk.StringVar()
        self._review_notes_var = tk.StringVar()

        # ---- SECTION A: Task Info ----
        self._build_section_task_info(row=0)

        # ---- SECTION B: Chart Source ----
        self._build_section_chart_source(row=1)

        # ---- SECTION C: YouTube Video ----
        self._build_section_youtube(row=2)

        # ---- SECTION D: Raw Description ----
        self._build_section_description(row=3)

        # ---- SECTION E: Final Editable Fields ----
        self._build_section_final_fields(row=4)

        # ---- Status bar ----
        self._status_var = tk.StringVar(value="Loading task details…")
        status_lbl = ttk.Label(
            self._inner,
            textvariable=self._status_var,
            relief="sunken",
            anchor="w",
            padding=(4, 2),
        )
        status_lbl.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # ---- Button bar (inside btn_frame) ----
        self._build_button_bar(btn_frame)

    def _build_section_task_info(self, row: int) -> None:
        task_data = self._task_data
        frame = ttk.LabelFrame(self._inner, text="Task Info", padding=6)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        self._status_lbl_var = tk.StringVar(
            value=task_data.get("review_status", "—")
        )
        self._operator_lbl_var = tk.StringVar(
            value=_get_session_operator() or "(not set — will prompt)"
        )

        rows = [
            ("Task ID:", str(self._task_id), None),
            ("Status:", None, self._status_lbl_var),
            ("Position:", str(task_data.get("chart_position", "—")), None),
            ("Priority:", str(task_data.get("priority", "—")), None),
            (
                "Created:",
                (task_data.get("created_at") or "")[:19].replace("T", " ") or "—",
                None,
            ),
        ]

        for r, (label, literal, var) in enumerate(rows):
            ttk.Label(frame, text=label, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=2
            )
            if var is not None:
                ttk.Label(frame, textvariable=var, anchor="w").grid(
                    row=r, column=1, sticky="ew", pady=2
                )
            else:
                ttk.Label(frame, text=literal, anchor="w").grid(
                    row=r, column=1, sticky="ew", pady=2
                )

        # Operator row with [Change] button
        op_row = len(rows)
        ttk.Label(frame, text="Operator:", anchor="e").grid(
            row=op_row, column=0, sticky="e", padx=(0, 6), pady=2
        )
        op_inner = ttk.Frame(frame)
        op_inner.grid(row=op_row, column=1, sticky="ew", pady=2)
        ttk.Label(op_inner, textvariable=self._operator_lbl_var, anchor="w").pack(
            side="left"
        )
        ttk.Button(op_inner, text="[Change]", command=self._on_change_operator).pack(
            side="left", padx=(8, 0)
        )

    def _build_section_chart_source(self, row: int) -> None:
        task_data = self._task_data
        frame = ttk.LabelFrame(self._inner, text="Chart Source", padding=6)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        self._artist_var = tk.StringVar(value=task_data.get("artist_raw", "") or "—")
        self._title_raw_var = tk.StringVar(
            value=task_data.get("song_title_raw", "") or "—"
        )
        self._pos_var = tk.StringVar(value=str(task_data.get("chart_position", "")))
        self._yt_url_var = tk.StringVar(value="Loading…")

        for r, (label, var) in enumerate([
            ("Artist (raw):", self._artist_var),
            ("Title (raw):", self._title_raw_var),
            ("Position:", self._pos_var),
        ]):
            ttk.Label(frame, text=label, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=2
            )
            ttk.Label(frame, textvariable=var, anchor="w", wraplength=600).grid(
                row=r, column=1, sticky="ew", pady=2
            )

        # YouTube URL as clickable label
        ttk.Label(frame, text="YouTube URL:", anchor="e").grid(
            row=3, column=0, sticky="e", padx=(0, 6), pady=2
        )
        url_lbl = tk.Label(
            frame,
            textvariable=self._yt_url_var,
            fg="#1565c0",
            cursor="hand2",
            anchor="w",
        )
        url_lbl.grid(row=3, column=1, sticky="ew", pady=2)
        url_lbl.bind("<Button-1>", self._open_youtube_url)

    def _build_section_youtube(self, row: int) -> None:
        frame = ttk.LabelFrame(self._inner, text="YouTube Video", padding=6)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        self._yt_id_var = tk.StringVar(value="")
        self._yt_title_var = tk.StringVar(value="")
        self._yt_channel_var = tk.StringVar(value="")
        self._yt_published_var = tk.StringVar(value="")

        for r, (label, var) in enumerate([
            ("Video ID:", self._yt_id_var),
            ("Video Title:", self._yt_title_var),
            ("Channel:", self._yt_channel_var),
            ("Published:", self._yt_published_var),
        ]):
            ttk.Label(frame, text=label, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=2
            )
            ttk.Label(frame, textvariable=var, anchor="w", wraplength=600).grid(
                row=r, column=1, sticky="ew", pady=2
            )

    def _build_section_description(self, row: int) -> None:
        frame = ttk.LabelFrame(
            self._inner, text="Raw Description (read-only)", padding=6
        )
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self._desc_text = tk.Text(
            frame,
            height=10,
            wrap="word",
            state="disabled",
            relief="flat",
            bg="#f5f5f5",
            font=("Segoe UI", 10),
        )
        self._desc_text.tag_configure("rtl", justify="right")
        desc_vsb = ttk.Scrollbar(
            frame, orient="vertical", command=self._desc_text.yview
        )
        self._desc_text.configure(yscrollcommand=desc_vsb.set)
        self._desc_text.grid(row=0, column=0, sticky="nsew")
        desc_vsb.grid(row=0, column=1, sticky="ns")

    def _build_section_final_fields(self, row: int) -> None:
        frame = ttk.LabelFrame(
            self._inner, text="Final Editable Fields", padding=6
        )
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        # Final Artist
        ttk.Label(frame, text="Final Artist:", anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=3
        )
        ttk.Entry(
            frame,
            textvariable=self._final_artist_var,
            justify="right",
            font=("Segoe UI", 10),
        ).grid(row=0, column=1, sticky="ew", pady=3)

        # Final Title
        ttk.Label(frame, text="Final Title:", anchor="e").grid(
            row=1, column=0, sticky="e", padx=(0, 6), pady=3
        )
        ttk.Entry(
            frame,
            textvariable=self._final_title_var,
            justify="right",
            font=("Segoe UI", 10),
        ).grid(row=1, column=1, sticky="ew", pady=3)

        # Lyrics Text
        ttk.Label(frame, text="Lyrics Text:", anchor="ne").grid(
            row=2, column=0, sticky="ne", padx=(0, 6), pady=3
        )
        lyrics_container = ttk.Frame(frame)
        lyrics_container.grid(row=2, column=1, sticky="nsew", pady=3)
        lyrics_container.columnconfigure(0, weight=1)
        lyrics_container.rowconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        self._lyrics_text = tk.Text(
            lyrics_container,
            height=8,
            wrap="word",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 10),
        )
        self._lyrics_text.tag_configure("rtl", justify="right")
        lyrics_vsb = ttk.Scrollbar(
            lyrics_container, orient="vertical", command=self._lyrics_text.yview
        )
        self._lyrics_text.configure(yscrollcommand=lyrics_vsb.set)
        self._lyrics_text.grid(row=0, column=0, sticky="nsew")
        lyrics_vsb.grid(row=0, column=1, sticky="ns")

        # Review Notes
        ttk.Label(frame, text="Review Notes:", anchor="e").grid(
            row=3, column=0, sticky="e", padx=(0, 6), pady=3
        )
        ttk.Entry(frame, textvariable=self._review_notes_var).grid(
            row=3, column=1, sticky="ew", pady=3
        )

    def _build_button_bar(self, btn_frame: ttk.Frame) -> None:
        # Right-side buttons first (pack side="right")
        self._close_btn = ttk.Button(
            btn_frame, text="Close (Esc)", command=self.destroy
        )
        self._close_btn.pack(side="right", padx=4)

        ttk.Separator(btn_frame, orient="vertical").pack(
            side="right", fill="y", padx=4
        )

        self._word_btn = ttk.Button(
            btn_frame, text="Open in Word", command=self._on_open_in_word
        )
        self._word_btn.pack(side="right", padx=4)

        # Left-side action buttons
        self._start_btn = ttk.Button(
            btn_frame, text="▶ Start Review", command=self._on_start_review
        )
        self._start_btn.pack(side="left", padx=4)

        ttk.Separator(btn_frame, orient="vertical").pack(
            side="left", fill="y", padx=4
        )

        self._approve_btn = ttk.Button(
            btn_frame, text="✓ Approve (Ctrl+↵)", command=self._on_approve
        )
        self._approve_btn.pack(side="left", padx=4)

        self._approve_edited_btn = ttk.Button(
            btn_frame,
            text="✎ Approve w/ Edits (Ctrl+⇧+↵)",
            command=self._on_approve_edited,
        )
        self._approve_edited_btn.pack(side="left", padx=4)

        self._reject_btn = ttk.Button(
            btn_frame, text="✗ Reject", command=self._on_reject
        )
        self._reject_btn.pack(side="left", padx=4)

        self._no_text_btn = ttk.Button(
            btn_frame, text="⊘ No Useful Text", command=self._on_no_useful_text
        )
        self._no_text_btn.pack(side="left", padx=4)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-Return>", lambda e: self._on_approve())
        self.bind("<Control-Shift-Return>", lambda e: self._on_approve_edited())
        self.bind("<Escape>", lambda e: self.destroy())

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_full_detail(self) -> None:
        def _worker() -> None:
            try:
                with httpx.Client(base_url=API_BASE_URL, timeout=10.0) as client:
                    resp = client.get(f"/api/review/tasks/{self._task_id}")
                    resp.raise_for_status()
                    full_task = resp.json()
                youtube_data = full_task.get("youtube_video")
                self.after(
                    0,
                    lambda ft=full_task, yt=youtube_data: (
                        self._populate_detail(ft, yt) if self.winfo_exists() else None
                    ),
                )
            except Exception as exc:
                msg = str(exc)
                self.after(
                    0,
                    lambda m=msg: (
                        self._set_status(f"Error loading details: {m}")
                        if self.winfo_exists()
                        else None
                    ),
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _populate_detail(
        self,
        full_task: Dict[str, Any],
        youtube_data: Optional[Dict[str, Any]],
    ) -> None:
        self._full_task = full_task

        ce = full_task.get("chart_entry") or {}
        if ce.get("chart_position"):
            self._pos_var.set(str(ce["chart_position"]))
        if ce.get("artist_raw"):
            self._artist_var.set(ce["artist_raw"])
        if ce.get("song_title_raw"):
            self._title_raw_var.set(ce["song_title_raw"])
        yt_url = ce.get("youtube_url") or ""
        self._yt_url_var.set(yt_url or "—")

        if youtube_data:
            self._yt_id_var.set(youtube_data.get("youtube_video_id") or "—")
            self._yt_title_var.set(youtube_data.get("video_title") or "—")
            self._yt_channel_var.set(youtube_data.get("channel_title") or "—")
            pub = (youtube_data.get("published_at") or "")[:10]
            self._yt_published_var.set(pub or "—")
            desc = youtube_data.get("description_raw") or ""
            self._desc_text.configure(state="normal")
            self._desc_text.delete("1.0", "end")
            self._desc_text.insert("1.0", desc)
            self._desc_text.tag_add("rtl", "1.0", "end")
            self._desc_text.configure(state="disabled")

        # Pre-fill final fields from chart_entry (primary source)
        if not self._final_artist_var.get():
            self._final_artist_var.set(ce.get("artist_raw") or "")
        if not self._final_title_var.get():
            self._final_title_var.set(ce.get("song_title_raw") or "")

        review_status = full_task.get("review_status", "pending")
        self._status_lbl_var.set(review_status)
        self._set_status(
            f"Task #{self._task_id} loaded — status: {review_status}"
        )
        self._update_button_states(review_status)

    def _update_button_states(self, review_status: str) -> None:
        is_terminal = review_status in (
            "approved",
            "approved_with_edits",
            "rejected",
            "no_useful_text",
        )
        action_btns = (
            self._approve_btn,
            self._approve_edited_btn,
            self._reject_btn,
            self._no_text_btn,
        )
        if is_terminal:
            self._start_btn.configure(state="disabled")
            for b in action_btns:
                b.configure(state="disabled")
        elif review_status == "in_review":
            self._start_btn.configure(state="disabled")
            for b in action_btns:
                b.configure(state="normal")
        else:  # pending
            self._start_btn.configure(state="normal")
            for b in action_btns:
                b.configure(state="disabled")

    # ------------------------------------------------------------------
    # Operator ID management
    # ------------------------------------------------------------------

    def _ensure_operator_id(self) -> Optional[str]:
        op = _get_session_operator()
        if op:
            return op
        dialog = _SimpleInputDialog(self, "Operator ID", "Enter your operator ID:")
        self.wait_window(dialog)
        if dialog.result:
            _set_session_operator(dialog.result)
            self._operator_lbl_var.set(dialog.result)
            return dialog.result
        return None

    def _on_change_operator(self) -> None:
        dialog = _SimpleInputDialog(
            self, "Change Operator ID", "Enter your operator ID:"
        )
        self.wait_window(dialog)
        if dialog.result:
            _set_session_operator(dialog.result)
            self._operator_lbl_var.set(dialog.result)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_start_review(self) -> None:
        op = self._ensure_operator_id()
        if not op:
            return
        self._call_api_async(
            "POST",
            f"/api/review/tasks/{self._task_id}/start",
            {"operator_id": op},
            success_msg="Review started",
            close_on_success=False,
            reload_on_success=True,
        )

    def _on_approve(self) -> None:
        op = self._ensure_operator_id()
        if not op:
            return
        self._call_api_async(
            "POST",
            f"/api/review/tasks/{self._task_id}/approve",
            self._build_decision_body(op),
            success_msg="Task approved",
            close_on_success=True,
        )

    def _on_approve_edited(self) -> None:
        op = self._ensure_operator_id()
        if not op:
            return
        self._call_api_async(
            "POST",
            f"/api/review/tasks/{self._task_id}/approve-edited",
            self._build_decision_body(op),
            success_msg="Task approved with edits",
            close_on_success=True,
        )

    def _on_reject(self) -> None:
        if not messagebox.askyesno(
            "Confirm Reject",
            "Are you sure you want to reject this task?",
            parent=self,
        ):
            return
        op = self._ensure_operator_id()
        if not op:
            return
        self._call_api_async(
            "POST",
            f"/api/review/tasks/{self._task_id}/reject",
            self._build_decision_body(op),
            success_msg="Task rejected",
            close_on_success=True,
        )

    def _on_no_useful_text(self) -> None:
        if not messagebox.askyesno(
            "Confirm No Useful Text",
            "Mark this task as having no useful text?",
            parent=self,
        ):
            return
        op = self._ensure_operator_id()
        if not op:
            return
        self._call_api_async(
            "POST",
            f"/api/review/tasks/{self._task_id}/mark-no-useful-text",
            self._build_decision_body(op),
            success_msg="Marked as no useful text",
            close_on_success=True,
        )

    def _on_open_in_word(self) -> None:
        try:
            from app.services.word_export_service import export_and_open
        except ImportError:
            messagebox.showerror(
                "Missing Library",
                "python-docx is required for Word export.\n"
                "Install with: pip install python-docx",
                parent=self,
            )
            return

        ce = (self._full_task or {}).get("chart_entry") or {}
        yt = (self._full_task or {}).get("youtube_video") or {}
        lyrics = self._lyrics_text.get("1.0", "end-1c").strip()

        self._set_status("Creating Word export…")
        self._word_btn.configure(state="disabled")

        task_id = self._task_id
        review_status = (self._full_task or {}).get("review_status", "unknown")
        final_artist = self._final_artist_var.get()
        final_title = self._final_title_var.get()
        review_notes = self._review_notes_var.get()

        def _worker() -> None:
            try:
                path = export_and_open(
                    task_id=task_id,
                    review_status=review_status,
                    chart_entry=ce,
                    youtube_video=yt,
                    final_artist=final_artist,
                    final_title=final_title,
                    final_lyrics_text=lyrics,
                    review_notes=review_notes,
                )
                msg = f"Exported to: {path}"

                def _ok(m=msg):
                    if self.winfo_exists():
                        self._set_status(m)
                        self._word_btn.configure(state="normal")

                self.after(0, _ok)
            except RuntimeError as exc:
                err = str(exc)

                def _err(e=err):
                    if self.winfo_exists():
                        self._set_status(f"Word export failed: {e}")
                        self._word_btn.configure(state="normal")
                        messagebox.showerror("Word Export Failed", e, parent=self)

                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_decision_body(self, operator_id: str) -> Dict[str, Any]:
        return {
            "operator_id": operator_id,
            "final_artist": self._final_artist_var.get() or None,
            "final_song_title": self._final_title_var.get() or None,
            "final_lyrics_text": self._lyrics_text.get("1.0", "end-1c").strip() or None,
            "review_notes": self._review_notes_var.get() or None,
        }

    def _call_api_async(
        self,
        method: str,
        path: str,
        body: Dict[str, Any],
        success_msg: str,
        close_on_success: bool = True,
        reload_on_success: bool = False,
    ) -> None:
        self._set_loading(True)
        self._set_status("Submitting…")

        def _worker() -> None:
            try:
                with httpx.Client(base_url=API_BASE_URL, timeout=15.0) as client:
                    resp = getattr(client, method.lower())(path, json=body)
                    resp.raise_for_status()

                def _ok(
                    msg=success_msg,
                    close=close_on_success,
                    reload=reload_on_success,
                ):
                    if not self.winfo_exists():
                        return
                    self._set_loading(False)
                    self._set_status(msg)
                    if close:
                        self.destroy()
                    elif reload:
                        self._load_full_detail()

                self.after(0, _ok)

            except httpx.HTTPStatusError as exc:
                sc = exc.response.status_code
                try:
                    detail = exc.response.json().get("detail", exc.response.text[:200])
                except Exception:
                    detail = exc.response.text[:200]

                def _err(s=sc, d=detail):
                    if not self.winfo_exists():
                        return
                    self._set_loading(False)
                    self._set_status(f"API error {s}")
                    messagebox.showerror("API Error", f"HTTP {s}: {d}", parent=self)

                self.after(0, _err)

            except Exception as exc:
                msg = str(exc)

                def _gerr(m=msg):
                    if not self.winfo_exists():
                        return
                    self._set_loading(False)
                    self._set_status(f"Error: {m}")
                    messagebox.showerror("Error", m, parent=self)

                self.after(0, _gerr)

        threading.Thread(target=_worker, daemon=True).start()

    def _set_loading(self, loading: bool) -> None:
        self._loading = loading
        state = "disabled" if loading else "normal"
        for btn in (
            self._start_btn,
            self._approve_btn,
            self._approve_edited_btn,
            self._reject_btn,
            self._no_text_btn,
        ):
            btn.configure(state=state)

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _open_youtube_url(self, _event: Any = None) -> None:
        url = self._yt_url_var.get()
        if url and url.startswith("http"):
            webbrowser.open(url)


# ---------------------------------------------------------------------------
# Simple input dialog helper
# ---------------------------------------------------------------------------


class _SimpleInputDialog(tk.Toplevel):
    """Minimal single-field input dialog."""

    def __init__(self, parent: tk.Widget, title: str, prompt: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result: Optional[str] = None

        ttk.Label(self, text=prompt, padding=(10, 10, 10, 4)).pack()
        self._entry = ttk.Entry(self, width=30)
        self._entry.pack(padx=10, pady=(0, 8))
        self._entry.focus_set()

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=(0, 10))
        ttk.Button(btn_frame, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
            side="left", padx=4
        )

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())

        # Centre over parent
        self.transient(parent)
        self.grab_set()

    def _ok(self) -> None:
        value = self._entry.get().strip()
        if value:
            self.result = value
        self.destroy()
