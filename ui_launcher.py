"""
OpenClaw Mako YouTube — Review UI launcher.

Run with:
    python ui_launcher.py
or via start.bat (uses pythonw for windowless launch).
"""
import os
import sys

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to path so `app.*` imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk

from app.ui.review_queue_panel import ReviewQueuePanel


def main() -> None:
    root = tk.Tk()
    root.title("OpenClaw — Review Queue")
    root.geometry("980x640")
    root.minsize(700, 400)

    # Allow the window to resize properly
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    panel = ReviewQueuePanel(root)
    panel.grid(row=0, column=0, sticky="nsew")

    root.mainloop()


if __name__ == "__main__":
    main()
