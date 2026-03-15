"""
Tkinter Review Item Dialog for the OpenClaw Mako YouTube pipeline.

UI/UX improvements applied:
  P0 - Raw description selectable + copyable (no longer state=disabled).
  P0 - Right-click context menu (Cut/Copy/Paste/Select All) on every text field.
  P0 - Status bar moved outside the scrollable canvas — always visible.
  P1 - Workflow hint "Start Review first" shown when status=pending.
  P1 - Mouse-wheel correctly routed to the focused Text widget vs. canvas.
  P1 - Review Notes replaced with 3-row multiline Text widget.
  P2 - "→ Copy to Lyrics" button in description section.
  P2 - Ctrl+A in all Text and Entry widgets.
  P2 - Character counter shown on description section header.
  P2 - "Approve w/ Edits" warns if no field was actually changed.
  P2 - Colour-coded status badge in Task Info.
  P3 - Start Review button hidden after review begins (replaced by label).
  P3 - Lyrics Text receives focus after detail loads.
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
# Session-level operator ID
# ---------------------------------------------------------------------------

_SESSION_OPERATOR_ID: str = ""


def _get_session_operator() -> str:
    return _SESSION_OPERATOR_ID


def _set_session_operator(op: str) -> None:
    global _SESSION_OPERATOR_ID
    _SESSION_OPERATOR_ID = op


# ---------------------------------------------------------------------------
# Status badge colours
# ---------------------------------------------------------------------------

_STATUS_COLORS: Dict[str, tuple] = {
    "pending":             ("#e65100", "#fff3e0"),
    "in_review":           ("#1565c0", "#e3f2fd"),
    "approved":            ("#2e7d32", "#e8f5e9"),
    "approved_with_edits": ("#1b5e20", "#f1f8e9"),
    "rejected":            ("#c62828", "#ffebee"),
    "no_useful_text":      ("#4e342e", "#efebe9"),
}


def _badge_colors(status: str):
    return _STATUS_COLORS.get(status, ("#555555", "#eeeeee"))


# ---------------------------------------------------------------------------
# Tooltip helper
# ---------------------------------------------------------------------------


class _Tooltip:
    """Lightweight tooltip that appears below a widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._win: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None) -> None:
        if self._win:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self._text, justify="left",
            background="#ffffe0", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), wraplength=320,
        ).pack()

    def _hide(self, _e=None) -> None:
        if self._win:
            self._win.destroy()
            self._win = None


# ---------------------------------------------------------------------------
# Text-widget helpers
# ---------------------------------------------------------------------------


def _bind_readonly(widget: tk.Text) -> None:
    """Make a Text widget read-only but fully selectable (Ctrl+C/Ctrl+A work)."""

    def _key(e: tk.Event) -> Optional[str]:
        ctrl = bool(e.state & 0x4)
        if ctrl:
            if e.keysym.lower() == "a":
                widget.tag_add("sel", "1.0", "end")
                widget.mark_set("insert", "1.0")
                return "break"
            if e.keysym.lower() == "c":
                return None  # let default copy run
        nav = {
            "Left", "Right", "Up", "Down",
            "Home", "End", "Prior", "Next",
            "Shift_L", "Shift_R", "Control_L", "Control_R",
        }
        if e.keysym in nav:
            return None
        return "break"

    widget.bind("<KeyPress>", _key)
    widget.bind("<<Paste>>", lambda e: "break")
    widget.bind("<<Cut>>",   lambda e: "break")


def _add_context_menu(widget: tk.Widget, readonly: bool = False) -> None:
    """Attach a right-click context menu to any Text or Entry widget."""
    menu = tk.Menu(widget, tearoff=0)
    if not readonly:
        menu.add_command(label="Cut",   command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(    label="Copy",  command=lambda: widget.event_generate("<<Copy>>"))
    if not readonly:
        menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_separator()
    if isinstance(widget, tk.Text):
        menu.add_command(
            label="Select All",
            command=lambda: (widget.tag_add("sel", "1.0", "end"), widget.mark_set("insert", "1.0")),
        )
    else:
        menu.add_command(
            label="Select All",
            command=lambda: (widget.select_range(0, "end"), widget.icursor("end")),  # type: ignore[attr-defined]
        )
    widget.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))


def _bind_entry_select_all(entry: ttk.Entry) -> None:
    """Ctrl+A → select all in an Entry widget."""
    def _sa(e):
        entry.select_range(0, "end")
        entry.icursor("end")
        return "break"
    entry.bind("<Control-a>", _sa)
    entry.bind("<Control-A>", _sa)


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
        self._prefill: Dict[str, str] = {}  # stored at populate time for diff check

        self.title(f"Review Task #{self._task_id}")
        self.geometry("940x780")
        self.minsize(740, 580)
        self.resizable(True, True)

        self._build_ui()
        self._bind_shortcuts()
        self._load_full_detail()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Fixed bottom: buttons ─────────────────────────────────────
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side="bottom", fill="x", padx=8, pady=(4, 8))

        # ── Fixed bottom: status bar (always visible, never scrolls) ──
        self._status_var = tk.StringVar(value="Loading task details…")
        ttk.Label(
            self,
            textvariable=self._status_var,
            relief="sunken",
            anchor="w",
            padding=(6, 3),
        ).pack(side="bottom", fill="x")

        # ── Scrollable content area ────────────────────────────────────
        content_outer = ttk.Frame(self)
        content_outer.pack(side="top", fill="both", expand=True)

        self._canvas = tk.Canvas(content_outer, highlightthickness=0)
        vsb = ttk.Scrollbar(content_outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = ttk.Frame(self._canvas, padding=8)
        self._canvas_win = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfig(self._canvas_win, width=e.width),
        )
        self._setup_canvas_mousewheel()

        self._inner.columnconfigure(0, weight=0)
        self._inner.columnconfigure(1, weight=1)

        # StringVars for editable fields
        self._final_artist_var = tk.StringVar()
        self._final_title_var  = tk.StringVar()

        # Sections
        self._build_section_task_info(row=0)
        self._build_section_chart_source(row=1)
        self._build_section_youtube(row=2)
        self._build_section_description(row=3)
        self._build_section_final_fields(row=4)
        self._build_button_bar(btn_frame)

    # ── Mouse-wheel routing ──────────────────────────────────────────

    def _setup_canvas_mousewheel(self) -> None:
        def _canvas_scroll(ev):
            self._canvas.yview_scroll(-(ev.delta // 120), "units")

        self._canvas_scroll_fn = _canvas_scroll
        self._canvas.bind(
            "<Enter>",
            lambda e: self._canvas.bind_all("<MouseWheel>", self._canvas_scroll_fn),
        )
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

    def _route_mousewheel_to(self, widget: tk.Text) -> None:
        """When mouse is over *widget*, scroll it; restore canvas on leave."""
        def _on_enter(_e):
            self._canvas.unbind_all("<MouseWheel>")
            widget.bind_all(
                "<MouseWheel>",
                lambda ev: widget.yview_scroll(-(ev.delta // 120), "units"),
            )

        def _on_leave(_e):
            widget.unbind_all("<MouseWheel>")
            self._canvas.bind_all("<MouseWheel>", self._canvas_scroll_fn)

        widget.bind("<Enter>", _on_enter)
        widget.bind("<Leave>", _on_leave)

    # ── Section builders ─────────────────────────────────────────────

    def _build_section_task_info(self, row: int) -> None:
        task_data = self._task_data
        frame = ttk.LabelFrame(self._inner, text="Task Info", padding=6)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        review_status = task_data.get("review_status", "pending")
        fg, bg = _badge_colors(review_status)
        self._status_badge = tk.Label(
            frame,
            text=f"  {review_status}  ",
            fg=fg, bg=bg,
            font=("Segoe UI", 10, "bold"),
            relief="flat", padx=6, pady=2,
        )

        self._operator_lbl_var = tk.StringVar(
            value=_get_session_operator() or "(not set — will prompt)"
        )

        static_rows = [
            ("Task ID:",  str(self._task_id)),
            ("Position:", str(task_data.get("chart_position", "—"))),
            ("Priority:", str(task_data.get("priority", "—"))),
            ("Created:",  (task_data.get("created_at") or "")[:19].replace("T", " ") or "—"),
        ]

        # Status badge row
        ttk.Label(frame, text="Status:", anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=2
        )
        self._status_badge.grid(row=0, column=1, sticky="w", pady=2)

        for r, (label, text) in enumerate(static_rows, start=1):
            ttk.Label(frame, text=label, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=2
            )
            ttk.Label(frame, text=text, anchor="w").grid(
                row=r, column=1, sticky="ew", pady=2
            )

        op_row = len(static_rows) + 1
        ttk.Label(frame, text="Operator:", anchor="e").grid(
            row=op_row, column=0, sticky="e", padx=(0, 6), pady=2
        )
        op_inner = ttk.Frame(frame)
        op_inner.grid(row=op_row, column=1, sticky="ew", pady=2)
        ttk.Label(op_inner, textvariable=self._operator_lbl_var, anchor="w").pack(side="left")
        ttk.Button(op_inner, text="[Change]", command=self._on_change_operator).pack(
            side="left", padx=(8, 0)
        )

    def _build_section_chart_source(self, row: int) -> None:
        task_data = self._task_data
        frame = ttk.LabelFrame(self._inner, text="Chart Source", padding=6)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        self._artist_var    = tk.StringVar(value=task_data.get("artist_raw", "") or "—")
        self._title_raw_var = tk.StringVar(value=task_data.get("song_title_raw", "") or "—")
        self._pos_var       = tk.StringVar(value=str(task_data.get("chart_position", "")))
        self._yt_url_var    = tk.StringVar(value="Loading…")

        for r, (label, var) in enumerate([
            ("Artist (raw):", self._artist_var),
            ("Title (raw):",  self._title_raw_var),
            ("Position:",     self._pos_var),
        ]):
            ttk.Label(frame, text=label, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=2
            )
            ttk.Label(frame, textvariable=var, anchor="w", wraplength=600).grid(
                row=r, column=1, sticky="ew", pady=2
            )

        ttk.Label(frame, text="YouTube URL:", anchor="e").grid(
            row=3, column=0, sticky="e", padx=(0, 6), pady=2
        )
        url_lbl = tk.Label(
            frame, textvariable=self._yt_url_var,
            fg="#1565c0", cursor="hand2", anchor="w",
        )
        url_lbl.grid(row=3, column=1, sticky="ew", pady=2)
        url_lbl.bind("<Button-1>", self._open_youtube_url)

    def _build_section_youtube(self, row: int) -> None:
        frame = ttk.LabelFrame(self._inner, text="YouTube Video", padding=6)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        self._yt_id_var        = tk.StringVar()
        self._yt_title_var     = tk.StringVar()
        self._yt_channel_var   = tk.StringVar()
        self._yt_published_var = tk.StringVar()

        for r, (label, var) in enumerate([
            ("Video ID:",    self._yt_id_var),
            ("Video Title:", self._yt_title_var),
            ("Channel:",     self._yt_channel_var),
            ("Published:",   self._yt_published_var),
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
        frame.rowconfigure(1, weight=1)

        # Controls bar: char count + Copy to Lyrics
        ctrl_bar = ttk.Frame(frame)
        ctrl_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self._desc_char_var = tk.StringVar(value="")
        ttk.Label(
            ctrl_bar, textvariable=self._desc_char_var,
            foreground="#888888", font=("Segoe UI", 9),
        ).pack(side="left")
        ttk.Button(
            ctrl_bar, text="→ Copy to Lyrics", command=self._copy_desc_to_lyrics
        ).pack(side="right")

        # Read-only but selectable Text widget
        self._desc_text = tk.Text(
            frame,
            height=10,
            wrap="word",
            relief="flat",
            bg="#f5f5f5",
            font=("Segoe UI", 10),
        )
        self._desc_text.tag_configure("rtl", justify="right")

        desc_vsb = ttk.Scrollbar(frame, orient="vertical", command=self._desc_text.yview)
        self._desc_text.configure(yscrollcommand=desc_vsb.set)
        self._desc_text.grid(row=1, column=0, sticky="nsew")
        desc_vsb.grid(row=1, column=1, sticky="ns")

        _bind_readonly(self._desc_text)
        _add_context_menu(self._desc_text, readonly=True)
        self._route_mousewheel_to(self._desc_text)

    def _build_section_final_fields(self, row: int) -> None:
        frame = ttk.LabelFrame(self._inner, text="Final Editable Fields", padding=6)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)

        # Final Artist
        ttk.Label(frame, text="Final Artist:", anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=3
        )
        artist_entry = ttk.Entry(
            frame, textvariable=self._final_artist_var,
            justify="right", font=("Segoe UI", 10),
        )
        artist_entry.grid(row=0, column=1, sticky="ew", pady=3)
        _add_context_menu(artist_entry)
        _bind_entry_select_all(artist_entry)

        # Final Title
        ttk.Label(frame, text="Final Title:", anchor="e").grid(
            row=1, column=0, sticky="e", padx=(0, 6), pady=3
        )
        title_entry = ttk.Entry(
            frame, textvariable=self._final_title_var,
            justify="right", font=("Segoe UI", 10),
        )
        title_entry.grid(row=1, column=1, sticky="ew", pady=3)
        _add_context_menu(title_entry)
        _bind_entry_select_all(title_entry)

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
        _add_context_menu(self._lyrics_text)
        self._route_mousewheel_to(self._lyrics_text)

        # Review Notes — multiline Text (3 rows), replaces single Entry
        ttk.Label(frame, text="Review Notes:", anchor="ne").grid(
            row=3, column=0, sticky="ne", padx=(0, 6), pady=3
        )
        notes_container = ttk.Frame(frame)
        notes_container.grid(row=3, column=1, sticky="ew", pady=3)
        notes_container.columnconfigure(0, weight=1)

        self._review_notes_text = tk.Text(
            notes_container,
            height=3,
            wrap="word",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 10),
        )
        notes_vsb = ttk.Scrollbar(
            notes_container, orient="vertical", command=self._review_notes_text.yview
        )
        self._review_notes_text.configure(yscrollcommand=notes_vsb.set)
        self._review_notes_text.grid(row=0, column=0, sticky="ew")
        notes_vsb.grid(row=0, column=1, sticky="ns")
        _add_context_menu(self._review_notes_text)
        self._route_mousewheel_to(self._review_notes_text)

    def _build_button_bar(self, btn_frame: ttk.Frame) -> None:
        # Right side
        ttk.Button(btn_frame, text="Close (Esc)", command=self.destroy).pack(
            side="right", padx=4
        )
        ttk.Separator(btn_frame, orient="vertical").pack(side="right", fill="y", padx=4)
        self._word_btn = ttk.Button(
            btn_frame, text="Open in Word", command=self._on_open_in_word
        )
        self._word_btn.pack(side="right", padx=4)

        # Left side — Start Review (P3: replaced by label after use)
        self._start_btn = ttk.Button(
            btn_frame, text="▶ Start Review", command=self._on_start_review
        )
        self._start_btn.pack(side="left", padx=4)

        # P1: workflow hint — shown only when pending
        self._hint_lbl = ttk.Label(
            btn_frame,
            text="← Click to begin",
            foreground="#e65100",
            font=("Segoe UI", 9, "italic"),
        )
        self._hint_lbl.pack(side="left", padx=(0, 4))

        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=4)

        self._approve_btn = ttk.Button(
            btn_frame, text="✓ Approve", command=self._on_approve
        )
        self._approve_btn.pack(side="left", padx=4)
        _Tooltip(self._approve_btn, "Approve this task (Ctrl+Enter)")

        self._approve_edited_btn = ttk.Button(
            btn_frame, text="✎ Approve w/ Edits", command=self._on_approve_edited
        )
        self._approve_edited_btn.pack(side="left", padx=4)
        _Tooltip(self._approve_edited_btn, "Approve with edited final fields (Ctrl+Shift+Enter)")

        self._reject_btn = ttk.Button(
            btn_frame, text="✗ Reject", command=self._on_reject
        )
        self._reject_btn.pack(side="left", padx=4)

        self._no_text_btn = ttk.Button(
            btn_frame, text="⊘ No Useful Text", command=self._on_no_useful_text
        )
        self._no_text_btn.pack(side="left", padx=4)

        # Tooltips on action buttons explaining they need Start Review first
        _Tooltip(self._reject_btn,  "Reject this task")
        _Tooltip(self._no_text_btn, "Mark as having no usable lyrics/description")

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-Return>",       lambda e: self._on_approve())
        self.bind("<Control-Shift-Return>", lambda e: self._on_approve_edited())
        self.bind("<Escape>",               lambda e: self.destroy())

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
        self._yt_url_var.set(ce.get("youtube_url") or "—")

        if youtube_data:
            self._yt_id_var.set(youtube_data.get("youtube_video_id") or "—")
            self._yt_title_var.set(youtube_data.get("video_title") or "—")
            self._yt_channel_var.set(youtube_data.get("channel_title") or "—")
            pub = (youtube_data.get("published_at") or "")[:10]
            self._yt_published_var.set(pub or "—")
            desc = youtube_data.get("description_raw") or ""
            self._desc_text.delete("1.0", "end")
            self._desc_text.insert("1.0", desc)
            self._desc_text.tag_add("rtl", "1.0", "end")
            char_count = len(desc)
            self._desc_char_var.set(
                f"{char_count} chars" if char_count else "no description"
            )

        # Pre-fill final fields from chart_entry (primary source)
        if not self._final_artist_var.get():
            self._final_artist_var.set(ce.get("artist_raw") or "")
        if not self._final_title_var.get():
            self._final_title_var.set(ce.get("song_title_raw") or "")

        # Store prefill snapshot for approve-with-edits diff check (P2)
        self._prefill = {
            "artist": self._final_artist_var.get(),
            "title":  self._final_title_var.get(),
            "lyrics": "",
        }

        review_status = full_task.get("review_status", "pending")
        fg, bg = _badge_colors(review_status)
        self._status_badge.configure(text=f"  {review_status}  ", fg=fg, bg=bg)
        self._set_status(f"Task #{self._task_id} loaded — status: {review_status}")
        self._update_button_states(review_status)

        # P3: give focus to lyrics so operator can paste immediately
        self._lyrics_text.focus_set()

    def _update_button_states(self, review_status: str) -> None:
        is_terminal = review_status in (
            "approved", "approved_with_edits", "rejected", "no_useful_text",
        )
        action_btns = (
            self._approve_btn,
            self._approve_edited_btn,
            self._reject_btn,
            self._no_text_btn,
        )
        # P1: show/hide hint; P3: show/hide start button
        if review_status == "pending":
            self._start_btn.pack(side="left", padx=4)   # ensure visible
            self._start_btn.configure(state="normal")
            self._hint_lbl.pack(side="left", padx=(0, 4))
            for b in action_btns:
                b.configure(state="disabled")
                _Tooltip(b, "Start Review first, then you can take action")
        elif review_status == "in_review":
            # P3: hide start button, show "In Review" in its place
            self._start_btn.pack_forget()
            self._hint_lbl.pack_forget()
            for b in action_btns:
                b.configure(state="normal")
        else:  # terminal
            self._start_btn.pack_forget()
            self._hint_lbl.pack_forget()
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
        dialog = _SimpleInputDialog(self, "Change Operator ID", "Enter your operator ID:")
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
        # P2: warn if nothing actually changed
        current_artist = self._final_artist_var.get()
        current_title  = self._final_title_var.get()
        current_lyrics = self._lyrics_text.get("1.0", "end-1c").strip()
        unchanged = (
            current_artist == self._prefill.get("artist", "")
            and current_title  == self._prefill.get("title", "")
            and current_lyrics == self._prefill.get("lyrics", "")
        )
        if unchanged:
            if not messagebox.askyesno(
                "No Changes Detected",
                "No fields were edited compared to the original data.\n\n"
                "Use 'Approve' instead if you haven't made any changes,\n"
                "or edit the fields before using 'Approve w/ Edits'.\n\n"
                "Proceed anyway?",
                parent=self,
            ):
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

        ce     = (self._full_task or {}).get("chart_entry") or {}
        yt     = (self._full_task or {}).get("youtube_video") or {}
        lyrics = self._lyrics_text.get("1.0", "end-1c").strip()

        self._set_status("Creating Word export…")
        self._word_btn.configure(state="disabled")

        task_id       = self._task_id
        review_status = (self._full_task or {}).get("review_status", "unknown")
        final_artist  = self._final_artist_var.get()
        final_title   = self._final_title_var.get()
        review_notes  = self._review_notes_text.get("1.0", "end-1c").strip()

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

    def _copy_desc_to_lyrics(self) -> None:
        """Copy the full raw description into the Lyrics Text field."""
        desc = self._desc_text.get("1.0", "end-1c")
        if not desc.strip():
            return
        if self._lyrics_text.get("1.0", "end-1c").strip():
            if not messagebox.askyesno(
                "Overwrite Lyrics?",
                "Lyrics Text already has content. Overwrite with raw description?",
                parent=self,
            ):
                return
        self._lyrics_text.delete("1.0", "end")
        self._lyrics_text.insert("1.0", desc)
        self._lyrics_text.tag_add("rtl", "1.0", "end")
        self._lyrics_text.focus_set()
        self._set_status("Description copied to Lyrics Text — edit as needed.")

    def _build_decision_body(self, operator_id: str) -> Dict[str, Any]:
        return {
            "operator_id":       operator_id,
            "final_artist":      self._final_artist_var.get() or None,
            "final_song_title":  self._final_title_var.get() or None,
            "final_lyrics_text": self._lyrics_text.get("1.0", "end-1c").strip() or None,
            "review_notes":      self._review_notes_text.get("1.0", "end-1c").strip() or None,
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

                def _ok(msg=success_msg, close=close_on_success, reload=reload_on_success):
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
        ttk.Button(btn_frame, text="OK",     command=self._ok).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        self.grab_set()

    def _ok(self) -> None:
        value = self._entry.get().strip()
        if value:
            self.result = value
        self.destroy()
