"""
Devlog module for FB Video Watcher.
Provides a live system diagnostic & log viewer that can be embedded as a sidebar
or detached into an independent floating window.
"""

import logging
import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, List, Tuple
from pathlib import Path

from main.constants import ICON_FILE
from main.platform_utils import apply_window_icon, set_windows_dark_titlebar


class DevLogHandler(logging.Handler):
    """Thread-safe logging handler that dispatches log records to Tkinter main thread."""

    def __init__(self, root: tk.Tk, dispatch_fn: Callable[[str, str], None]):
        super().__init__()
        self.root = root
        self.dispatch_fn = dispatch_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname.upper()
            # Post to Tkinter main thread safely
            self.root.after(0, self.dispatch_fn, msg, level)
        except Exception:
            pass


class DevLogPanel:
    """
    Live Devlog & Diagnostic panel with syntax coloring, log level filtering,
    auto-scrolling, clear, copy-to-clipboard, and dock/undock support.
    """

    MAX_LOG_ENTRIES = 2000

    def __init__(
        self,
        root: tk.Tk,
        sidebar_parent: tk.Widget,
        on_visibility_change: Optional[Callable[[bool], None]] = None,
        is_dark_theme_fn: Optional[Callable[[], bool]] = None,
    ):
        self.root = root
        self.sidebar_parent = sidebar_parent
        self.on_visibility_change = on_visibility_change
        self.is_dark_theme_fn = is_dark_theme_fn or (lambda: True)

        self._is_detached = False
        self._is_visible = False
        self._detached_window: Optional[tk.Toplevel] = None
        self._log_records: List[Tuple[str, str]] = []  # (msg, level)
        self._auto_scroll_var = tk.BooleanVar(value=True)
        self._filter_var = tk.StringVar(value="Tất cả (All)")

        # Container for sidebar mode
        self.panel_frame = ttk.Frame(self.sidebar_parent, width=380)
        self._build_panel_content(self.panel_frame)

        # Connect logging handler to root logger so all components are captured
        root_logger = logging.getLogger()
        if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
            root_logger.setLevel(logging.INFO)

        self._handler = DevLogHandler(self.root, self.add_log_entry)
        self._handler.setLevel(logging.INFO)
        self._handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        root_logger.addHandler(self._handler)

    def _build_panel_content(self, container: tk.Widget) -> None:
        """Build the header toolbar, log text widget with scrollbars, and filter bar inside container."""
        # 1. Header Toolbar
        self.header_frame = ttk.Frame(container, padding=(6, 6))
        self.header_frame.pack(fill=tk.X, side=tk.TOP)

        lbl_title = ttk.Label(
            self.header_frame,
            text="📋 Devlog (Live)",
            font=("Segoe UI", 10, "bold"),
        )
        lbl_title.pack(side=tk.LEFT, padx=(0, 6))

        # Detach / Dock button
        detach_text = "⧈ Gắn lại" if self._is_detached else "⧉ Tách rời"
        self.btn_detach = ttk.Button(
            self.header_frame,
            text=detach_text,
            width=9,
            command=self.toggle_detach,
        )
        self.btn_detach.pack(side=tk.RIGHT, padx=(2, 0))

        # Copy button
        self.btn_copy = ttk.Button(
            self.header_frame,
            text="📋 Copy",
            width=7,
            command=self.copy_to_clipboard,
        )
        self.btn_copy.pack(side=tk.RIGHT, padx=(2, 2))

        # Clear button
        self.btn_clear = ttk.Button(
            self.header_frame,
            text="🧹 Xóa",
            width=6,
            command=self.clear_logs,
        )
        self.btn_clear.pack(side=tk.RIGHT, padx=(2, 2))

        # 2. Filter & Options Bar
        filter_bar = ttk.Frame(container, padding=(6, 2))
        filter_bar.pack(fill=tk.X, side=tk.TOP)

        ttk.Label(filter_bar, text="Lọc:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 4))
        self.combo_filter = ttk.Combobox(
            filter_bar,
            textvariable=self._filter_var,
            values=["Tất cả (All)", "INFO+", "WARNING+", "ERROR+"],
            state="readonly",
            width=12,
            font=("Segoe UI", 8),
        )
        self.combo_filter.pack(side=tk.LEFT)
        self.combo_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_log_display())

        chk_autoscroll = ttk.Checkbutton(
            filter_bar,
            text="Tự cuộn",
            variable=self._auto_scroll_var,
        )
        chk_autoscroll.pack(side=tk.RIGHT)

        # 3. Log Text Area with Vertical and Horizontal Scrollbars
        text_container = ttk.Frame(container)
        text_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.scrollbar_y = ttk.Scrollbar(text_container, orient=tk.VERTICAL)
        self.scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.scrollbar_x = ttk.Scrollbar(text_container, orient=tk.HORIZONTAL)
        self.scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.text_widget = tk.Text(
            text_container,
            wrap=tk.NONE,
            font=("Consolas", 9),
            yscrollcommand=self.scrollbar_y.set,
            xscrollcommand=self.scrollbar_x.set,
            relief=tk.FLAT,
            borderwidth=0,
            padx=6,
            pady=6,
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        self.scrollbar_y.config(command=self.text_widget.yview)
        self.scrollbar_x.config(command=self.text_widget.xview)

        # Configure color tags
        self._configure_color_tags()

    def _configure_color_tags(self) -> None:
        """Apply theme-appropriate syntax highlighting tags."""
        is_dark = self.is_dark_theme_fn()
        if is_dark:
            bg_color = "#181818"
            fg_color = "#e0e0e0"
            self.text_widget.configure(bg=bg_color, fg=fg_color, insertbackground="#ffffff")
            self.text_widget.tag_configure("time", foreground="#888888")
            self.text_widget.tag_configure("level_info", foreground="#4caf50", font=("Consolas", 9, "bold"))
            self.text_widget.tag_configure("level_warning", foreground="#ffa726", font=("Consolas", 9, "bold"))
            self.text_widget.tag_configure("level_error", foreground="#ef5350", font=("Consolas", 9, "bold"))
            self.text_widget.tag_configure("level_debug", foreground="#78909c")
            self.text_widget.tag_configure("msg_text", foreground="#e0e0e0")
        else:
            bg_color = "#f9f9f9"
            fg_color = "#212121"
            self.text_widget.configure(bg=bg_color, fg=fg_color, insertbackground="#000000")
            self.text_widget.tag_configure("time", foreground="#757575")
            self.text_widget.tag_configure("level_info", foreground="#2e7d32", font=("Consolas", 9, "bold"))
            self.text_widget.tag_configure("level_warning", foreground="#e65100", font=("Consolas", 9, "bold"))
            self.text_widget.tag_configure("level_error", foreground="#c62828", font=("Consolas", 9, "bold"))
            self.text_widget.tag_configure("level_debug", foreground="#546e7a")
            self.text_widget.tag_configure("msg_text", foreground="#212121")

    def update_theme(self) -> None:
        """Refresh styling colors when application theme toggles."""
        self._configure_color_tags()
        if self._detached_window and self._detached_window.winfo_exists():
            set_windows_dark_titlebar(self._detached_window, dark=self.is_dark_theme_fn())

    def add_log_entry(self, msg: str, level: str) -> None:
        """Append log record to history and text widget."""
        self._log_records.append((msg, level))
        if len(self._log_records) > self.MAX_LOG_ENTRIES:
            self._log_records.pop(0)

        # Guard against the case where the widget has already been destroyed
        # (happens when a background logging handler fires after root.destroy())
        try:
            if not self.text_widget.winfo_exists():
                return
        except Exception:
            return

        if self._matches_filter(level):
            self._insert_formatted_line(msg, level)
            if self._auto_scroll_var.get():
                self.text_widget.see(tk.END)


    def _matches_filter(self, level: str) -> bool:
        """Check whether log level matches currently selected filter."""
        f = self._filter_var.get()
        if f == "Tất cả (All)":
            return True
        elif f == "INFO+":
            return level in ("INFO", "WARNING", "ERROR", "CRITICAL")
        elif f == "WARNING+":
            return level in ("WARNING", "ERROR", "CRITICAL")
        elif f == "ERROR+":
            return level in ("ERROR", "CRITICAL")
        return True

    def _insert_formatted_line(self, msg: str, level: str) -> None:
        """Parse and insert a color-tagged line into the text widget."""
        self.text_widget.configure(state=tk.NORMAL)

        # Parse timestamp [HH:MM:SS] and level [LEVEL]
        if msg.startswith("[") and "]" in msg:
            try:
                parts = msg.split("] ", 2)
                if len(parts) >= 2 and parts[0].startswith("[") and parts[1].startswith("["):
                    time_part = parts[0] + "] "
                    level_part = parts[1] + "] "
                    rest = parts[2] if len(parts) > 2 else ""

                    self.text_widget.insert(tk.END, time_part, "time")
                    lvl_tag = f"level_{level.lower()}"
                    self.text_widget.insert(tk.END, level_part, lvl_tag)
                    self.text_widget.insert(tk.END, rest + "\n", "msg_text")
                else:
                    lvl_tag = f"level_{level.lower()}"
                    self.text_widget.insert(tk.END, msg + "\n", lvl_tag)
            except Exception:
                self.text_widget.insert(tk.END, msg + "\n")
        else:
            lvl_tag = f"level_{level.lower()}"
            self.text_widget.insert(tk.END, msg + "\n", lvl_tag)

        self.text_widget.configure(state=tk.DISABLED)

    def _refresh_log_display(self) -> None:
        """Re-render entire log buffer according to current filter."""
        self.text_widget.configure(state=tk.NORMAL)
        self.text_widget.delete("1.0", tk.END)
        for msg, level in self._log_records:
            if self._matches_filter(level):
                self._insert_formatted_line(msg, level)
        if self._auto_scroll_var.get():
            self.text_widget.see(tk.END)
        self.text_widget.configure(state=tk.DISABLED)

    def show(self) -> None:
        """Show Devlog sidebar or bring detached window to front."""
        self._is_visible = True
        if self._is_detached and self._detached_window and self._detached_window.winfo_exists():
            self._detached_window.deiconify()
            self._detached_window.lift()
            self._detached_window.focus_set()
        else:
            self.panel_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)
            if self._auto_scroll_var.get():
                self.text_widget.see(tk.END)

    def hide(self) -> None:
        """Hide Devlog sidebar or minimize detached window."""
        self._is_visible = False
        if self._is_detached and self._detached_window and self._detached_window.winfo_exists():
            self._detached_window.withdraw()
        else:
            self.panel_frame.pack_forget()

    def toggle_detach(self) -> None:
        """Switch between embedded sidebar mode and floating independent window mode."""
        if self._is_detached:
            self.dock_back()
        else:
            self.detach_to_window()

    def detach_to_window(self) -> None:
        """Detach Devlog into an independent floating window."""
        if self._is_detached:
            return

        self._is_detached = True
        self.panel_frame.pack_forget()
        for child in self.panel_frame.winfo_children():
            child.destroy()

        # Create Toplevel floating window
        self._detached_window = tk.Toplevel(self.root)
        self._detached_window.title("📋 FB Video Watcher - Devlog")
        self._detached_window.geometry("720x480")
        self._detached_window.minsize(450, 300)
        apply_window_icon(self._detached_window, ICON_FILE)
        set_windows_dark_titlebar(self._detached_window, dark=self.is_dark_theme_fn())

        self._detached_window.protocol("WM_DELETE_WINDOW", self._on_detached_window_close)

        # Build content directly in detached window
        self._build_panel_content(self._detached_window)
        self._refresh_log_display()
        self._detached_window.focus_set()

    def dock_back(self) -> None:
        """Dock Devlog back into the main application sidebar."""
        if not self._is_detached:
            return

        self._is_detached = False

        if self._detached_window and self._detached_window.winfo_exists():
            self._detached_window.destroy()
            self._detached_window = None

        # Re-build content in panel_frame
        for child in self.panel_frame.winfo_children():
            child.destroy()
        self._build_panel_content(self.panel_frame)
        self._refresh_log_display()

        if self._is_visible:
            self.panel_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)
            if self._auto_scroll_var.get():
                self.text_widget.see(tk.END)

    def _on_detached_window_close(self) -> None:
        """Called when user closes the floating Devlog window with 'X' button."""
        self._is_visible = False
        if self._detached_window and self._detached_window.winfo_exists():
            self._detached_window.withdraw()
        if self.on_visibility_change:
            self.on_visibility_change(False)

    def clear_logs(self) -> None:
        """Clear all stored and displayed log messages."""
        self._log_records.clear()
        self.text_widget.configure(state=tk.NORMAL)
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.configure(state=tk.DISABLED)

    def copy_to_clipboard(self) -> None:
        """Copy all log messages to system clipboard."""
        lines = [record[0] for record in self._log_records]
        full_text = "\n".join(lines)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(full_text)
        except Exception:
            pass
