"""
History Dialog module for FB Video Watcher.
Provides a modern Fluent-styled modal for searching, browsing, and managing watch history.
Consistent with dark/light themes and allows 1-click resumption of past video sessions.
"""

from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional, List, Dict, Any

from main.history import HistoryManager
from main.theme import ThemeManager
from main.timestamp import format_timestamp
from main.platform_utils import set_windows_dark_titlebar


class HistoryDialog:
    """Toplevel modal window for browsing, searching, and managing video watch history."""

    def __init__(
        self,
        parent: tk.Tk,
        history_mgr: HistoryManager,
        theme_mgr: ThemeManager,
        on_play_video: Callable[[str, int], None],
    ):
        self.parent = parent
        self.history = history_mgr
        self.theme = theme_mgr
        self.on_play_video = on_play_video

        self.top = tk.Toplevel(parent)
        try:
            self._parent_withdrawn = parent.winfo_toplevel().state() == "withdrawn"
        except Exception:
            self._parent_withdrawn = False
        if self._parent_withdrawn:
            self.top.withdraw()
        self.top.title("📜 Lịch sử xem video")
        self.top.minsize(640, 420)
        self.top.transient(parent)

        # Center dialog over parent
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = 720, 480
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        self.top.geometry(f"{w}x{h}+{x}+{y}")

        # Keep on top if parent window is topmost
        try:
            if parent.attributes("-topmost"):
                self.top.attributes("-topmost", True)
        except Exception:
            pass

        # Apply dark titlebar if applicable
        is_dark = (self.theme.current_theme == "dark")
        set_windows_dark_titlebar(self.top, dark=is_dark)

        self._all_entries: List[Dict[str, Any]] = []
        self._filtered_entries: List[Dict[str, Any]] = []

        self._build_ui()
        self._load_history()

        if not self._parent_withdrawn:
            self.top.lift()
            self.top.focus_force()

        # Keyboard shortcuts
        self.top.bind("<Escape>", lambda e: self.top.destroy())
        self.top.bind("<Control-h>", lambda e: self.top.destroy())
        self.top.bind("<Control-H>", lambda e: self.top.destroy())
        self.top.bind("<Delete>", lambda e: self._on_delete_selected())
        self.top.bind("<Return>", lambda e: self._on_play_selected())
        self.top.bind("<b>", lambda e: self._on_toggle_bookmark())
        self.top.bind("<B>", lambda e: self._on_toggle_bookmark())

    def _build_ui(self) -> None:
        """Construct the search bar, Treeview, and action buttons."""
        main_frame = ttk.Frame(self.top, padding=(12, 10))
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top Bar: Search input & entry count
        top_bar = ttk.Frame(main_frame)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        lbl_search = ttk.Label(top_bar, text="🔍 Tìm kiếm:")
        lbl_search.pack(side=tk.LEFT, padx=(0, 6))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_history())
        self.search_entry = ttk.Entry(top_bar, textvariable=self.search_var, font=("Segoe UI", 9))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.search_entry.focus_set()

        self.bookmark_only_var = tk.BooleanVar(value=False)
        self.chk_bookmark = ttk.Checkbutton(
            top_bar,
            text="⭐ Chỉ yêu thích",
            variable=self.bookmark_only_var,
            command=self._filter_history,
        )
        self.chk_bookmark.pack(side=tk.RIGHT, padx=(8, 0))

        self.lbl_count = ttk.Label(top_bar, text="0 video", font=("Segoe UI", 9))
        self.lbl_count.pack(side=tk.RIGHT)

        # Center Area: Treeview with vertical scrollbar
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        columns = ("title", "progress", "duration", "last_watched")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tree.heading("title", text="Tiêu đề video / URL")
        self.tree.heading("progress", text="Tiến độ xem")
        self.tree.heading("duration", text="Thời lượng")
        self.tree.heading("last_watched", text="Xem gần nhất")

        self.tree.column("title", width=340, anchor=tk.W)
        self.tree.column("progress", width=110, anchor=tk.CENTER)
        self.tree.column("duration", width=80, anchor=tk.CENTER)
        self.tree.column("last_watched", width=130, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-Button-1>", lambda e: self._on_play_selected())

        # Right-click context menu on Treeview
        self._ctx_menu = tk.Menu(self.top, tearoff=False)
        self._ctx_menu.add_command(label="▶ Phát video này", command=self._on_play_selected)
        self._ctx_menu.add_command(label="⭐ Đánh dấu / Bỏ dấu yêu thích (B)", command=self._on_toggle_bookmark)
        self._ctx_menu.add_command(label="📋 Sao chép liên kết (URL)", command=self._on_copy_url)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="🗑 Xóa khỏi lịch sử (Delete)", command=self._on_delete_selected)

        def _on_tree_right_click(event):
            row_id = self.tree.identify_row(event.y)
            if row_id:
                self.tree.selection_set(row_id)
                self._ctx_menu.post(event.x_root, event.y_root)

        self.tree.bind("<Button-3>", _on_tree_right_click)

        # Bottom Bar: Action buttons
        btn_bar = ttk.Frame(main_frame)
        btn_bar.pack(fill=tk.X)

        self.btn_play = ttk.Button(
            btn_bar,
            text="▶ Phát tiếp",
            style="Accent.TButton",
            command=self._on_play_selected,
        )
        self.btn_play.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_bookmark = ttk.Button(
            btn_bar,
            text="⭐ Đánh dấu",
            command=self._on_toggle_bookmark,
        )
        self.btn_bookmark.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_copy = ttk.Button(
            btn_bar,
            text="📋 Sao chép URL",
            command=self._on_copy_url,
        )
        self.btn_copy.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_delete = ttk.Button(
            btn_bar,
            text="🗑 Xóa mục",
            command=self._on_delete_selected,
        )
        self.btn_delete.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_clear_all = ttk.Button(
            btn_bar,
            text="🧹 Xóa toàn bộ",
            command=self._on_clear_all,
        )
        self.btn_clear_all.pack(side=tk.LEFT)

        self.btn_close = ttk.Button(
            btn_bar,
            text="Đóng",
            command=self.top.destroy,
        )
        self.btn_close.pack(side=tk.RIGHT)

    def _load_history(self) -> None:
        """Fetch records from database and render into Treeview."""
        self._all_entries = self.history.get_history(limit=150)
        self._filter_history()

    def _filter_history(self) -> None:
        """Filter cached records against search query and bookmark filter."""
        query = self.search_var.get().strip().lower()
        only_bm = getattr(self, "bookmark_only_var", None) and self.bookmark_only_var.get()

        filtered = []
        for e in self._all_entries:
            if only_bm and not e.get("is_bookmarked"):
                continue
            if query:
                title = (e.get("title") or "").lower()
                url = (e.get("url") or "").lower()
                if query not in title and query not in url:
                    continue
            filtered.append(e)

        self._filtered_entries = filtered
        self._populate_tree()

    def _populate_tree(self) -> None:
        """Populate Treeview items with formatted progress, bookmark star, and time."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        for e in self._filtered_entries:
            pos_ms = e.get("last_position") or 0
            dur_ms = e.get("duration_ms") or 0

            # Compute progress display
            if dur_ms > 0:
                pct = int((pos_ms / dur_ms) * 100)
                progress_str = f"{pct}% ({format_timestamp(pos_ms)})"
            elif pos_ms > 0:
                progress_str = format_timestamp(pos_ms)
            else:
                progress_str = "Chưa xem"

            dur_str = format_timestamp(dur_ms) if dur_ms > 0 else "--:--"

            raw_time = e.get("last_watched", "")
            time_display = raw_time[:16] if raw_time else ""

            raw_title = e.get("title") or e.get("url") or "Video không tên"
            is_bm = bool(e.get("is_bookmarked"))
            title_display = f"⭐ {raw_title}" if is_bm else raw_title

            self.tree.insert(
                "",
                tk.END,
                iid=str(e.get("id")),
                values=(title_display, progress_str, dur_str, time_display),
            )

        count = len(self._filtered_entries)
        self.lbl_count.configure(text=f"{count} video" if count != 1 else "1 video")

    def _on_toggle_bookmark(self) -> None:
        """Toggle bookmark (favorite) status on currently selected video."""
        entry = self._get_selected_entry()
        if not entry:
            return
        entry_id = entry.get("id")
        if entry_id is not None:
            new_state = self.history.toggle_bookmark(entry_id)
            entry["is_bookmarked"] = 1 if new_state else 0
            # Sort bookmarked items towards the top
            self._all_entries.sort(key=lambda x: (not bool(x.get("is_bookmarked")), x.get("last_watched", "")), reverse=False)
            self._filter_history()

    def _get_selected_entry(self) -> Optional[Dict[str, Any]]:
        """Return data dict of currently selected Treeview item."""
        sel = self.tree.selection()
        if not sel:
            return None
        selected_id = int(sel[0])
        for e in self._all_entries:
            if e.get("id") == selected_id:
                return e
        return None

    def _on_play_selected(self) -> None:
        """Resume playback of chosen historical video."""
        entry = self._get_selected_entry()
        if not entry:
            messagebox.showinfo("Chọn video", "Vui lòng chọn một video từ danh sách để phát.", parent=self.top)
            return

        url = entry.get("url")
        last_pos = entry.get("last_position") or 0

        self.top.destroy()
        if self.on_play_video and url:
            self.on_play_video(url, last_pos)

    def _on_copy_url(self) -> None:
        """Copy selected video URL to system clipboard."""
        entry = self._get_selected_entry()
        if not entry:
            return
        url = entry.get("url", "")
        if url:
            self.top.clipboard_clear()
            self.top.clipboard_append(url)
            messagebox.showinfo("Đã sao chép", "Đã sao chép liên kết video vào bộ nhớ tạm!", parent=self.top)

    def _on_delete_selected(self) -> None:
        """Remove selected entry from database."""
        entry = self._get_selected_entry()
        if not entry:
            return

        entry_id = entry.get("id")
        if entry_id is not None:
            self.history.delete_entry_by_id(entry_id)
            self._all_entries = [e for e in self._all_entries if e.get("id") != entry_id]
            self._filter_history()

    def _on_clear_all(self) -> None:
        """Clear entire watch history after user confirmation."""
        if not self._all_entries:
            return
        confirmed = messagebox.askyesno(
            "Xóa toàn bộ lịch sử",
            "Bạn có chắc chắn muốn xóa toàn bộ danh sách lịch sử xem video không?",
            parent=self.top,
        )
        if confirmed:
            self.history.clear_history()
            self._all_entries.clear()
            self._filter_history()
