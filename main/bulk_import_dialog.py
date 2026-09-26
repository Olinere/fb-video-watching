"""Bulk Import Dialog for extracting video URLs and context from raw text.

Allows users to paste Facebook posts, forum threads, or multi-episode lists,
automatically preview the extracted links in sequential order, and batch-import
them into the playback queue.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, List, Optional

from main.platform_utils import set_windows_dark_titlebar
from main.text_parser import ParsedVideoItem, SmartTextParser
from main.theme import ThemeManager


class BulkImportDialog:
    """Modal dialog for parsing arbitrary text into sequential queue items."""

    def __init__(
        self,
        parent: tk.Tk,
        theme_mgr: ThemeManager,
        on_import_to_queue: Callable[[List[ParsedVideoItem]], None],
        on_replace_and_play: Optional[Callable[[List[ParsedVideoItem]], None]] = None,
        initial_text: str = "",
    ):
        self.parent = parent
        self.theme = theme_mgr
        self.on_import_to_queue = on_import_to_queue
        self.on_replace_and_play = on_replace_and_play
        self.parsed_items: List[ParsedVideoItem] = []

        self.top = tk.Toplevel(parent)
        try:
            self._parent_withdrawn = parent.winfo_toplevel().state() == "withdrawn"
        except Exception:
            self._parent_withdrawn = False
        if self._parent_withdrawn:
            self.top.withdraw()

        self.top.title("📋 Nhập danh sách video từ văn bản")
        self.top.minsize(680, 520)
        self.top.transient(parent)

        # Center over parent
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = 760, 560
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        self.top.geometry(f"{w}x{h}+{x}+{y}")

        try:
            if parent.attributes("-topmost"):
                self.top.attributes("-topmost", True)
        except Exception:
            pass

        is_dark = getattr(self.theme, "current_theme", "dark") == "dark"
        try:
            set_windows_dark_titlebar(self.top, is_dark)
        except Exception:
            pass

        self._build_ui()

        if initial_text:
            self.text_input.insert("1.0", initial_text)
            self._analyze_text()

        self.top.grab_set()
        self.text_input.focus_set()

    def _build_ui(self) -> None:
        palette = getattr(self.theme, "PALETTES", {}).get(
            getattr(self.theme, "current_theme", "dark"),
            {"bg": "#202020", "fg": "#f0f0f0", "surface": "#2c2c2c", "entry_bg": "#2d2d2d", "entry_fg": "#ffffff", "accent": "#4cc2ff"}
        )
        bg = palette.get("bg", "#202020")
        fg = palette.get("fg", "#f0f0f0")
        entry_bg = palette.get("entry_bg", "#2d2d2d")
        entry_fg = palette.get("entry_fg", "#ffffff")
        accent = palette.get("accent", "#4cc2ff")
        self.top.configure(bg=bg)

        main_frame = ttk.Frame(self.top, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Header instruction
        header_lbl = ttk.Label(
            main_frame,
            text="Dán nội dung bài đăng Facebook hoặc văn bản chứa danh sách tập/video vào đây:",
            font=("Segoe UI", 10, "bold"),
        )
        header_lbl.pack(anchor="w", pady=(0, 6))

        # 2. Input Text Frame with Scrollbar
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 8))

        text_scroll = ttk.Scrollbar(input_frame, orient=tk.VERTICAL)
        self.text_input = tk.Text(
            input_frame,
            height=6,
            wrap=tk.WORD,
            bg=entry_bg,
            fg=entry_fg,
            insertbackground=entry_fg,
            relief="flat",
            highlightthickness=1,
            highlightcolor=accent,
            font=("Segoe UI", 9),
            yscrollcommand=text_scroll.set,
        )
        text_scroll.config(command=self.text_input.yview)
        self.text_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 3. Control toolbar above results
        tool_frame = ttk.Frame(main_frame)
        tool_frame.pack(fill=tk.X, pady=(0, 8))

        self.btn_analyze = ttk.Button(
            tool_frame,
            text="🔍 Phân tích liên kết",
            command=self._analyze_text,
        )
        self.btn_analyze.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_paste = ttk.Button(
            tool_frame,
            text="📋 Dán từ Clipboard",
            command=self._paste_clipboard,
        )
        self.btn_paste.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_clear = ttk.Button(
            tool_frame,
            text="🧹 Xóa văn bản",
            command=self._clear_text,
        )
        self.btn_clear.pack(side=tk.LEFT, padx=(0, 6))

        self.lbl_status = ttk.Label(
            tool_frame,
            text="Chưa phân tích",
            font=("Segoe UI", 9, "italic"),
        )
        self.lbl_status.pack(side=tk.RIGHT)

        # 4. Preview Treeview
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        columns = ("stt", "desc", "source", "url")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("stt", text="#", anchor="center")
        self.tree.heading("desc", text="Mô tả / Ngữ cảnh", anchor="w")
        self.tree.heading("source", text="Nguồn", anchor="center")
        self.tree.heading("url", text="URL Video", anchor="w")

        self.tree.column("stt", width=45, minwidth=35, anchor="center")
        self.tree.column("desc", width=180, minwidth=100, anchor="w")
        self.tree.column("source", width=90, minwidth=70, anchor="center")
        self.tree.column("url", width=380, minwidth=200, anchor="w")

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        # 5. Bottom action bar
        btn_bar = ttk.Frame(main_frame)
        btn_bar.pack(fill=tk.X, pady=(6, 0))

        self.btn_add_queue = ttk.Button(
            btn_bar,
            text="[+] Thêm vào hàng đợi",
            command=self._import_to_queue,
            state="disabled",
        )
        self.btn_add_queue.pack(side=tk.LEFT, padx=(0, 6))

        if self.on_replace_and_play:
            self.btn_play_now = ttk.Button(
                btn_bar,
                text="[▶] Thay thế & Phát ngay",
                command=self._replace_and_play,
                state="disabled",
            )
            self.btn_play_now.pack(side=tk.LEFT, padx=(0, 6))

        btn_close = ttk.Button(
            btn_bar,
            text="Đóng",
            command=self.top.destroy,
        )
        btn_close.pack(side=tk.RIGHT)

    def _paste_clipboard(self) -> None:
        try:
            clip = self.top.clipboard_get()
            if clip:
                self.text_input.delete("1.0", tk.END)
                self.text_input.insert("1.0", clip)
                self._analyze_text()
        except Exception:
            messagebox.showwarning("Clipboard", "Không thể đọc dữ liệu từ clipboard.", parent=self.top)

    def _clear_text(self) -> None:
        self.text_input.delete("1.0", tk.END)
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.parsed_items.clear()
        self.lbl_status.config(text="Đã xóa văn bản")
        self.btn_add_queue.config(state="disabled", text="[+] Thêm vào hàng đợi")
        if hasattr(self, "btn_play_now"):
            self.btn_play_now.config(state="disabled")

    def _analyze_text(self) -> None:
        raw_text = self.text_input.get("1.0", tk.END)
        self.parsed_items = SmartTextParser.parse_text(raw_text)

        for item in self.tree.get_children():
            self.tree.delete(item)

        if not self.parsed_items:
            self.lbl_status.config(text="Không tìm thấy liên kết video hợp lệ nào.")
            self.btn_add_queue.config(state="disabled", text="[+] Thêm vào hàng đợi")
            if hasattr(self, "btn_play_now"):
                self.btn_play_now.config(state="disabled")
            return

        # Populate treeview in exact sequential order
        yt_count = sum(1 for it in self.parsed_items if it.source_name == "YouTube")
        fb_count = sum(1 for it in self.parsed_items if it.source_name == "Facebook")
        other_count = len(self.parsed_items) - yt_count - fb_count

        for idx, it in enumerate(self.parsed_items, start=1):
            desc_display = it.description if it.description else f"#{idx}"
            self.tree.insert("", tk.END, values=(idx, desc_display, it.source_name, it.url))

        summary_parts = []
        if yt_count:
            summary_parts.append(f"{yt_count} YouTube")
        if fb_count:
            summary_parts.append(f"{fb_count} Facebook")
        if other_count:
            summary_parts.append(f"{other_count} Khác")

        summary_str = f"Đã tìm thấy {len(self.parsed_items)} liên kết ({', '.join(summary_parts)})"
        self.lbl_status.config(text=summary_str)

        self.btn_add_queue.config(
            state="normal",
            text=f"[+] Thêm {len(self.parsed_items)} video vào hàng đợi",
        )
        if hasattr(self, "btn_play_now"):
            self.btn_play_now.config(state="normal")

    def _import_to_queue(self) -> None:
        if not self.parsed_items:
            return
        self.on_import_to_queue(self.parsed_items)
        self.top.destroy()

    def _replace_and_play(self) -> None:
        if not self.parsed_items or not self.on_replace_and_play:
            return
        self.on_replace_and_play(self.parsed_items)
        self.top.destroy()
