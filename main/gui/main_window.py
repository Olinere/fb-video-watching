"""
Main application window module for FB Video Watcher.
Implements the core MainWindow container, player surface, playback controls,
playlist/queue interface, and application event orchestration.
"""

import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser, simpledialog
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable, Optional, Dict, Any, Tuple
from PIL import Image, ImageDraw, ImageTk

from main.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    DEFAULT_PIP_WIDTH,
    DEFAULT_PIP_HEIGHT,
    MIN_PIP_WIDTH,
    MIN_PIP_HEIGHT,
    DEFAULT_PIP_VERTICAL_WIDTH,
    DEFAULT_PIP_VERTICAL_HEIGHT,
    MIN_PIP_VERTICAL_WIDTH,
    MIN_PIP_VERTICAL_HEIGHT,
    PIP_SNAP_MARGIN,
    SPEED_OPTIONS,
    ICON_FILE,
)
from main.timestamp import format_timestamp, parse_timestamp
from main.theme import ThemeManager
from main.settings import SettingsManager
from main.system_info import SystemInfo
from main.auto_tune import AutoTuner
from main.devlog import DevLogPanel
from main.platform_utils import (
    apply_window_icon,
    set_windows_dark_titlebar,
    hook_drop_files,
    get_monitor_bounds_for_window,
    get_monitor_work_area_for_window,
    get_monitor_work_area_for_rect,
    is_rect_visible_on_any_monitor,
)
from main.history_dialog import HistoryDialog
from main.hotkeys import (
    DEFAULT_HOTKEYS,
    HOTKEY_DEFINITIONS,
    hotkey_to_tk_sequences,
)
from main.subtitle import (
    validate_subtitle_file,
    SUPPORTED_SUBTITLE_EXTENSIONS,
    SUBTITLE_FORMAT_NAMES,
)

from main.gui.components import (
    SeekBarController,
    OSDOverlay,
    PiPProgressOverlay,
    ListboxTooltip,
)
from main.gui.menu_bar import ThemedMenuBar
from main.gui.settings_dialog import SettingsDialog

class MainWindow:
    """Main application window container and UI orchestrator."""

    def __init__(
        self,
        root: tk.Tk,
        settings_mgr: SettingsManager,
        theme_mgr: ThemeManager,
        on_play_request: Callable[[str], None],
        on_pause_toggle: Callable[[], None],
        on_seek_request: Callable[[int], None],
        on_seek_relative: Callable[[int], None],
        on_volume_change: Callable[[int], None],
        on_mute_toggle: Callable[[], None],
        on_rate_change: Callable[[float], None],
        on_settings_saved: Optional[Callable[[], None]] = None,
        on_history_request: Optional[Callable[[], None]] = None,
        on_download_request: Optional[Callable[[], None]] = None,
        on_pip_ratio_change: Optional[Callable[[str], None]] = None,
        on_loop_toggle: Optional[Callable[[], None]] = None,
        on_ab_repeat_toggle: Optional[Callable[[], None]] = None,
        on_subtitle_load: Optional[Callable[[str], None]] = None,
        on_update_request: Optional[Callable[[Any], None]] = None,
        on_add_to_queue: Optional[Callable[[str], None]] = None,
        on_play_queue_item: Optional[Callable[[str], None]] = None,
        on_remove_queue_item: Optional[Callable[[str], None]] = None,
        on_move_queue_item: Optional[Callable[[str, int], None]] = None,
        on_clear_queue: Optional[Callable[[], None]] = None,
        on_clear_played_queue: Optional[Callable[[], None]] = None,
        on_retry_queue_item: Optional[Callable[[str], None]] = None,
        on_next_track: Optional[Callable[[], None]] = None,
        on_previous_track: Optional[Callable[[], None]] = None,
        on_chapter_seek: Optional[Callable[[int], None]] = None,
        on_privacy_toggle: Optional[Callable[[], None]] = None,
        on_bulk_import_queue: Optional[Callable[[list], None]] = None,
        on_bulk_replace_and_play: Optional[Callable[[list], None]] = None,
        on_queue_persist_toggle: Optional[Callable[[bool], None]] = None,
    ):
        self.root = root
        self.settings = settings_mgr
        self.theme = theme_mgr

        # Event callbacks to App Orchestrator
        self.on_play_request = on_play_request
        self.on_pause_toggle = on_pause_toggle
        self.on_seek_request = on_seek_request
        self.on_seek_relative = on_seek_relative
        self.on_volume_change = on_volume_change
        self.on_mute_toggle = on_mute_toggle
        self.on_rate_change = on_rate_change
        self.on_settings_saved = on_settings_saved
        self.on_history_request = on_history_request
        self.on_download_request = on_download_request
        self.on_pip_ratio_change = on_pip_ratio_change
        self.on_loop_toggle = on_loop_toggle
        self.on_ab_repeat_toggle = on_ab_repeat_toggle
        self.on_subtitle_load = on_subtitle_load
        self.on_update_request = on_update_request
        self.on_add_to_queue = on_add_to_queue
        self.on_play_queue_item = on_play_queue_item
        self.on_remove_queue_item = on_remove_queue_item
        self.on_move_queue_item = on_move_queue_item
        self.on_clear_queue = on_clear_queue
        self.on_clear_played_queue = on_clear_played_queue
        self.on_retry_queue_item = on_retry_queue_item
        self.on_next_track = on_next_track
        self.on_previous_track = on_previous_track
        self.on_chapter_seek = on_chapter_seek
        self.on_privacy_toggle = on_privacy_toggle
        self.on_bulk_import_queue = on_bulk_import_queue
        self.on_bulk_replace_and_play = on_bulk_replace_and_play
        self.on_queue_persist_toggle = on_queue_persist_toggle
        self._chapters: list[dict] = []
        self._chapters_visible = False
        self._chapters_expanded_width = 0
        self._queue_visible = False
        self._queue_expanded_width = 0
        self._devlog_expanded_width = 0
        self._queue_rows: list[dict] = []
        self._queue_window: Optional[tk.Toplevel] = None
        self._queue_is_detached: bool = False
        self._dev_mode_unlocked: bool = bool(self.settings.get("ui", "dev_mode_unlocked", default=False))
        self._bound_hotkey_sequences: set[str] = set()

        # Window configuration
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self._window_width: int = DEFAULT_WINDOW_WIDTH
        self._window_height: int = DEFAULT_WINDOW_HEIGHT
        self.root.geometry(f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}")
        self.root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        apply_window_icon(self.root, ICON_FILE)

        # Apply Always on top setting
        if self.settings.get("ui", "always_on_top", default=False):
            self.root.attributes("-topmost", True)

        self._is_fullscreen = False
        self._is_pip = False
        self._pip_aspect_ratio: str = self.settings.get("ui", "pip_aspect_ratio", default="16:9")
        self._saved_geometry: Optional[str] = None
        self._current_duration_ms = 0
        self._last_time_str = ""
        self._video_click_timer: Optional[str] = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._win_start_x = 0
        self._win_start_y = 0
        self._win_start_w = 0
        self._win_start_h = 0
        self._drag_mode: str = "none"
        self._has_dragged = False
        self._last_resized_pip_w: Optional[int] = None
        self._last_resized_pip_h: Optional[int] = None

        # Clipboard auto-detect toast state
        self._detected_clipboard_url = ""
        self._clipboard_toast_timer: Optional[str] = None

        # Network health suggestion toast state
        self._network_toast_timer: Optional[str] = None
        self._on_network_toast_apply: Optional[Callable[[], None]] = None

        # On-Screen Display (OSD) overlay state
        self._osd_timer: Optional[str] = None
        self._osd_fade_step = 0
        self._seek_accum_seconds = 0
        self._last_seek_direction = 0
        self._last_seek_time = 0.0
        self._current_position_ms = 0
        self._current_duration_ms = 0

        # Fullscreen animated controls slide state
        self._fs_controls_visible = True
        self._fs_is_animating = False
        self._fs_anim_direction = "idle"
        self._fs_anim_timer: Optional[str] = None
        self._fs_autohide_timer: Optional[str] = None
        self._fs_cached_top_h = 42
        self._fs_cached_bot_h = 76

        # Build UI layout
        self._build_ui()
        self._bind_shortcuts()

        # Initialize floating hardware-composited OSD overlay (renders above Direct3D VLC)
        self.osd_overlay = OSDOverlay(
            parent_root=self.root,
            target_widget=self.video_container,
        )
        self.pip_progress_overlay = PiPProgressOverlay(
            parent_root=self.root,
            height=3,
        )
        self.root.bind("<Configure>", self._on_window_configure, add="+")

        # Initialize native drag-and-drop for local media files
        self._init_drag_and_drop()

        # Listen to theme changes to dynamically re-style custom themed widgets (MenuBar, Menus)
        if hasattr(self.theme, "add_listener"):
            self.theme.add_listener(self._on_theme_changed)

    def _on_theme_changed(self, theme_name: str, colors: Dict[str, str]) -> None:
        """Callback invoked when ThemeManager changes theme."""
        self.apply_theme()

    def _on_window_configure(self, event) -> None:
        if getattr(event, "widget", None) == self.root:
            if hasattr(self, "osd_overlay"):
                self.osd_overlay.reposition()
            if getattr(self, "_is_pip", False) and hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.reposition(self.root)

    def destroy(self) -> None:
        """Cleanly release all pending timers, OSD overlay, and resources on shutdown."""
        # Cancel every after() timer that might still be pending to prevent
        # TclError "invalid command name" spam after root.destroy() is called.
        for attr in (
            "_fs_anim_timer",
            "_fs_autohide_timer",
            "_osd_timer",
            "_clipboard_toast_timer",
            "_network_toast_timer",
            "_video_click_timer",
        ):
            timer = getattr(self, attr, None)
            if timer is not None:
                try:
                    self.root.after_cancel(timer)
                except Exception:
                    pass
                setattr(self, attr, None)

        if hasattr(self, "osd_overlay"):
            self.osd_overlay.destroy()
        if hasattr(self, "pip_progress_overlay"):
            self.pip_progress_overlay.destroy()

        # Cleanly unbind hotkeys to prevent binding accumulation across instances
        for seq in list(getattr(self, "_bound_hotkey_sequences", set())):
            try:
                self.root.unbind_all(seq)
                self.root.unbind(seq)
            except Exception:
                pass
        if hasattr(self, "_bound_hotkey_sequences"):
            self._bound_hotkey_sequences.clear()

        # Unregister theme listener
        if hasattr(self, "theme") and hasattr(self.theme, "remove_listener"):
            try:
                self.theme.remove_listener(self._on_theme_changed)
            except Exception:
                pass

        if hasattr(self, "_queue_window") and self._queue_window and self._queue_window.winfo_exists():
            try:
                self._queue_window.destroy()
            except Exception:
                pass
            self._queue_window = None

        # Destroy main widget container
        if hasattr(self, "main_container") and self.main_container.winfo_exists():
            try:
                self.main_container.destroy()
            except Exception:
                pass

    def _build_ui(self) -> None:
        """Construct the UI widgets from top to bottom."""
        # 0. Windows Native Menu Bar (VLC / PotPlayer style)
        self._build_menu_bar()

        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True)
        self.main_container.bind("<Button-1>", lambda e: self.root.focus_set())

        # 1. Top URL Bar Wrapper (for smooth fullscreen slide animation)
        self.top_wrapper = ttk.Frame(self.main_container)
        self.top_wrapper.pack(side=tk.TOP, fill=tk.X)
        self._build_url_bar()

        # 2. Bottom Controls Wrapper (for smooth fullscreen slide animation)
        self.bottom_wrapper = ttk.Frame(self.main_container)
        self.bottom_wrapper.pack(side=tk.BOTTOM, fill=tk.X)

        self.bottom_inner = ttk.Frame(self.bottom_wrapper)
        self.bottom_inner.pack(fill=tk.BOTH, expand=True)

        self._build_bottom_bar()
        self._build_transport_bar()

        # 3. Central Video Surface Frame
        self._build_video_surface()

        # 4. Right-Click Context Menu
        self._build_context_menu()

        # Track mouse motion for fullscreen auto-reveal
        for w in (self.main_container, self.top_wrapper, self.bottom_wrapper):
            w.bind("<Motion>", self._on_fs_mouse_motion, add="+")

    def _open_ffmpeg_dialog(self) -> None:
        """Open portable FFmpeg setup and management dialog."""
        import logging
        logger = logging.getLogger("FBVideoWatcher.MainWindow")
        try:
            from main.ffmpeg_setup_dialog import FFmpegSetupDialog
            is_dark = (getattr(self.theme, "current_theme", "") == "dark")
            FFmpegSetupDialog(
                self.root,
                theme_mgr=self.theme,
                is_dark=is_dark,
                on_change=getattr(self, "_refresh_ffmpeg_ui", None),
            )
        except Exception as exc:
            logger.error("Lỗi khi mở hộp thoại FFmpeg: %s", exc, exc_info=True)
            self.show_osd_message(f"❌ Không thể mở hộp thoại FFmpeg: {exc}")

    def _build_menu_bar(self) -> None:
        """Construct themed, cohesive Menu Bar in modern desktop media player style."""
        colors = self.theme.PALETTES.get(self.theme.current_theme, self.theme.PALETTES["dark"])
        self.menu_bar = ThemedMenuBar(self.root, colors)
        self.menu_bar.pack(side=tk.TOP, fill=tk.X)

        # 1. Menu Tập tin (File / Media)
        self.menu_file = tk.Menu(self.root, tearoff=0)
        self.menu_file.add_command(
            label="📁 Mở file video cục bộ...",
            accelerator="Ctrl+O",
            command=self._on_open_file_clicked,
        )
        self.menu_file.add_command(
            label="📋 Dán liên kết & Phát",
            accelerator="Ctrl+V",
            command=self._on_paste_and_play,
        )
        self.menu_file.add_command(
            label="📜 Lịch sử xem video...",
            accelerator="Ctrl+H",
            command=self._on_history_clicked,
        )
        self.menu_file.add_separator()
        self.menu_file.add_command(
            label="🎬 Tải Video đầy đủ (MP4)",
            accelerator="Ctrl+S",
            command=lambda: self._on_download_clicked(audio_only=False),
        )
        self.menu_file.add_command(
            label="🎵 Tách riêng Âm thanh (MP3)",
            command=lambda: self._on_download_clicked(audio_only=True),
        )
        self.menu_file.add_separator()
        self.menu_file.add_command(
            label="❌ Thoát",
            accelerator="Alt+F4",
            command=self.root.destroy,
        )
        self.menu_bar.add_cascade(label="Tập tin", menu=self.menu_file)

        # 2. Menu Danh sách phát (Playlist / Queue)
        self.menu_queue = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_playlist = self.menu_queue
        self.menu_queue.add_command(
            label="📋 Bật/Tắt thanh hàng đợi",
            accelerator="F9",
            command=self.toggle_queue,
        )
        self.menu_queue.add_command(
            label="⧉ Mở cửa sổ Queue riêng (Popup)",
            command=self.toggle_queue_popup,
        )
        self.menu_queue.add_separator()
        self.menu_queue.add_command(
            label="📥 Nhập hàng loạt từ URL/Text...",
            command=lambda: self.open_bulk_import_dialog(),
        )
        self.menu_queue.add_command(
            label="💾 Xuất danh sách phát ra file...",
            command=self._export_queue_to_file,
        )
        self.menu_queue.add_command(
            label="🔗 Sao chép tất cả link hàng đợi",
            command=self._copy_all_queue_links,
        )
        self.menu_queue.add_separator()
        self.menu_queue.add_command(
            label="🧹 Dọn dẹp video đã xem",
            command=lambda: (self.on_clear_played_queue() if self.on_clear_played_queue else None),
        )
        self.menu_queue.add_command(
            label="🗑 Xóa toàn bộ hàng đợi",
            command=lambda: (self.on_clear_queue() if self.on_clear_queue else None),
        )
        self.menu_bar.add_cascade(label="Danh sách phát", menu=self.menu_queue)

        # 3. Menu Phát lại (Playback)
        self.menu_playback = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_playback.add_command(
            label="▶ Phát / Tạm dừng",
            accelerator="Space",
            command=self.on_pause_toggle,
        )
        self.menu_playback.add_command(
            label="⏮ Lùi 5 giây",
            accelerator="Left",
            command=lambda: self.on_seek_relative(-5),
        )
        self.menu_playback.add_command(
            label="⏭ Tiến 5 giây",
            accelerator="Right",
            command=lambda: self.on_seek_relative(5),
        )
        self.menu_playback.add_separator()
        self.menu_playback.add_command(
            label="🔁 Lặp lại video",
            accelerator="L",
            command=self._on_loop_click,
        )
        self.menu_playback.add_command(
            label="🔂 Lặp đoạn A-B",
            accelerator="B",
            command=self._on_ab_repeat_click,
        )
        self.menu_playback.add_separator()
        self.menu_playback.add_command(
            label="☰ Mục lục phân đoạn (Chapters)",
            command=self.toggle_chapters,
        )
        self.menu_bar.add_cascade(label="Phát lại", menu=self.menu_playback)

        # 4. Menu Công cụ (Tools)
        self.menu_tools = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_tools.add_command(
            label="⚙ Cài đặt ứng dụng...",
            accelerator="Ctrl+P",
            command=self.open_settings_dialog,
        )
        self.menu_tools.add_command(
            label="🔒 Phiên riêng tư (Private Session)",
            command=self._on_privacy_toggle,
        )
        self.menu_tools.add_command(
            label="📌 Cửa sổ nổi thu nhỏ (PiP)",
            accelerator="P",
            command=self.toggle_pip,
        )
        self.menu_pip_aspect = tk.Menu(self.menu_tools, tearoff=0)
        self.menu_tools.add_cascade(
            label="📐 Tỷ lệ khung hình PiP",
            menu=self.menu_pip_aspect,
        )
        self._update_menubar_pip_ratio()
        self.menu_tools.add_command(
            label="⛶ Toàn màn hình",
            accelerator="F11",
            command=self.toggle_fullscreen,
        )
        self.menu_tools.add_separator()
        self.menu_tools.add_command(
            label="🎬 Add-on FFmpeg Portable...",
            command=self._open_ffmpeg_dialog,
        )
        if getattr(self, "_dev_mode_unlocked", False):
            self.menu_tools.add_command(
                label="🛠 Nhật ký nhà phát triển (Devlog)",
                accelerator="F12",
                command=self.toggle_devlog,
            )
        self.menu_bar.add_cascade(label="Công cụ", menu=self.menu_tools)

        # 5. Menu Trợ giúp (Help)
        self.menu_help = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_help.add_command(
            label="⌨ Bảng phím tắt ứng dụng",
            accelerator="F1",
            command=lambda: self.open_settings_dialog(initial_tab="hotkeys"),
        )
        self.menu_help.add_command(
            label="🔄 Kiểm tra cập nhật mới...",
            command=lambda: self.open_settings_dialog(initial_tab="about"),
        )
        self.menu_help.add_separator()
        self.menu_help.add_command(
            label="ℹ Về FB Video Watcher...",
            command=lambda: self.open_settings_dialog(initial_tab="about"),
        )
        self.menu_bar.add_cascade(label="Trợ giúp", menu=self.menu_help)

    def _build_url_bar(self) -> None:
        """Construct Top URL entry and action buttons on a single, spacious row."""
        self.url_bar = ttk.Frame(self.top_wrapper, padding=(8, 6))
        self.url_bar.pack(fill=tk.BOTH, expand=True)
        bar = self.url_bar

        lbl = ttk.Label(bar, text="🔗 URL Video:")
        lbl.pack(side=tk.LEFT, padx=(0, 6))

        self.url_entry = ttk.Entry(bar, font=("Segoe UI", 9))
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.url_entry.bind("<Return>", lambda e: self._on_play_click())
        self.url_entry.bind("<Escape>", lambda e: self.root.focus_set())

        self.btn_play = ttk.Button(
            bar,
            text="▶ Phát",
            style="Accent.TButton",
            command=self._on_play_click,
        )
        self.btn_play.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_paste_play = ttk.Button(
            bar,
            text="📋 Dán & Phát",
            command=self._on_paste_and_play,
        )
        self.btn_paste_play.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_add_queue = ttk.Button(
            bar,
            text="➕ Hàng đợi",
            command=self._on_add_to_queue_click,
        )
        self.btn_add_queue.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_toggle_queue = ttk.Button(
            bar,
            text="📋 Xem queue",
            command=self.toggle_queue,
        )
        self.btn_toggle_queue.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_download = ttk.Button(
            bar,
            text="⬇ Tải về",
            command=self._on_download_clicked,
        )
        self.btn_download.pack(side=tk.LEFT, padx=(0, 4))

        # Right-click menu for direct Video vs Audio selection
        self._dl_menu = tk.Menu(self.root, tearoff=False)
        self._dl_menu.add_command(
            label="🎬 Tải Video đầy đủ (MP4)",
            command=lambda: self._on_download_clicked(audio_only=False),
        )
        self._dl_menu.add_command(
            label="🎵 Tách riêng Âm thanh (MP3)",
            command=lambda: self._on_download_clicked(audio_only=True),
        )
        self.btn_download.bind("<Button-3>", lambda e: self._dl_menu.post(e.x_root, e.y_root))

        self.btn_privacy = ttk.Button(bar, text="🔒 Riêng tư", command=self._on_privacy_toggle)
        self.btn_privacy.pack(side=tk.RIGHT, padx=(4, 0))

        self.privacy_badge = ttk.Label(bar, text="🔒 PRIVATE SESSION")

        # Keep widget attributes for backward compatibility with existing tests
        self.btn_open_file = ttk.Button(bar, text="📁 Mở file", command=self._on_open_file_clicked)
        self.btn_history = ttk.Button(bar, text="📜 Lịch sử", command=self._on_history_clicked)
        self.btn_chapters = ttk.Button(bar, text="☰ Mục lục", state=tk.DISABLED, command=self.toggle_chapters)
        self.btn_settings = ttk.Button(bar, text="⚙ Cài đặt", command=self.open_settings_dialog)

    def _build_video_surface(self) -> None:
        """Construct Central Content Area: Video Render Surface on Left + Devlog Sidebar on Right."""
        self.content_area = ttk.Frame(self.main_container)
        self.content_area.pack(fill=tk.BOTH, expand=True)

        self.video_container = tk.Frame(self.content_area, bg="#000000")
        self.video_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Queue is constructed once inside content_area, hidden by default.
        # Window size remains constant so main UI buttons never shift.
        self.queue_panel = ttk.Frame(self.content_area, width=300)
        self.queue_panel.pack_propagate(False)
        self._build_queue_content(self.queue_panel, is_detached=False)

        self.chapter_panel = ttk.Frame(self.content_area, width=280)
        self.chapter_panel.pack_propagate(False)
        chapter_header = ttk.Frame(self.chapter_panel)
        chapter_header.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(chapter_header, text="Mục lục").pack(side=tk.LEFT)
        ttk.Button(chapter_header, text="×", width=3, command=self.toggle_chapters).pack(side=tk.RIGHT)
        self.chapter_list = tk.Listbox(self.chapter_panel, height=10, activestyle="none", exportselection=False)
        self.chapter_list.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))
        self.chapter_list.bind("<Double-Button-1>", self._on_chapter_double_click)

        # Initialize Devlog Sidebar panel (hidden by default)
        self.devlog_panel = DevLogPanel(
            root=self.root,
            sidebar_parent=self.content_area,
            on_visibility_change=self._on_devlog_visibility_changed,
            is_dark_theme_fn=lambda: (self.theme.current_theme == "dark"),
            on_dock_change=self._on_devlog_dock_changed,
        )

        # Overlay label for Loading / Buffer / Placeholder messages
        self.overlay_label = tk.Label(
            self.video_container,
            text="Kéo thả file video vào đây hoặc dán liên kết (Facebook, YouTube, Bilibili...)",
            bg="#000000",
            fg="#888888",
            font=("Segoe UI", 12),
        )
        self.overlay_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Video surface mouse interaction: dragging & resizing for PiP, single click for play/pause in normal mode, double click for fullscreen/exit PiP
        for w in (self.video_container, self.overlay_label):
            w.bind("<ButtonPress-1>", self._on_video_press)
            w.bind("<B1-Motion>", self._on_video_motion)
            w.bind("<ButtonRelease-1>", self._on_video_release)
            w.bind("<Double-Button-1>", self._on_video_double_click)
            w.bind("<Motion>", self._on_video_hover)
            w.bind("<Leave>", self._on_video_leave)
            w.bind("<MouseWheel>", self._on_video_wheel)
            w.bind("<Button-2>", lambda e: self.on_pause_toggle())

        # Corner resize grip for PiP mode (positioned at bottom-right)
        self.resize_grip = tk.Label(
            self.video_container,
            text="⇲",
            font=("Segoe UI", 9, "bold"),
            bg="#181818",
            fg="#999999",
            activebackground="#2a2a2a",
            activeforeground="#ffffff",
            cursor="size_nw_se",
            padx=2,
            pady=0,
            relief=tk.FLAT,
        )
        self.resize_grip.bind("<ButtonPress-1>", self._on_grip_press)
        self.resize_grip.bind("<B1-Motion>", self._on_video_motion)
        self.resize_grip.bind("<ButtonRelease-1>", self._on_video_release)
        self.resize_grip.bind("<MouseWheel>", self._on_video_wheel)
        self.resize_grip.bind("<Button-3>", self._show_context_menu)
        self.resize_grip.bind("<Button-2>", lambda e: self.on_pause_toggle())

        # On-Screen Display (OSD) Overlay Label for Pause/Resume and Seek notifications
        self.osd_label = tk.Label(
            self.video_container,
            text="",
            font=("Segoe UI", 11, "bold"),
            bg="#1c1c1c",
            fg="#e0e0e0",
            relief=tk.FLAT,
            padx=14,
            pady=6,
            bd=0,
        )
        self.osd_label.bind("<ButtonPress-1>", self._on_video_press)
        self.osd_label.bind("<B1-Motion>", self._on_video_motion)
        self.osd_label.bind("<ButtonRelease-1>", self._on_video_release)
        self.osd_label.bind("<Double-Button-1>", self._on_video_double_click)
        self.osd_label.bind("<Motion>", self._on_video_hover)
        self.osd_label.bind("<Leave>", self._on_video_leave)
        self.osd_label.bind("<MouseWheel>", self._on_video_wheel)
        self.osd_label.bind("<Button-3>", self._show_context_menu)
        self.osd_label.bind("<Button-2>", lambda e: self.on_pause_toggle())

        # Mini Progress Bar for PiP Mode (3px sleek red line #ff0033)
        self.pip_progress = tk.Frame(
            self.video_container,
            height=3,
            bg="#1a1a1a",
        )
        self.pip_progress_fill = tk.Frame(
            self.pip_progress,
            bg="#ff0033",
            height=3,
        )

        # Clipboard Auto-detect Toast Prompt Banner
        self.clipboard_toast = tk.Frame(
            self.video_container,
            bg="#202124",
            highlightbackground="#0078d4",
            highlightthickness=1,
            padx=12,
            pady=6,
        )
        self.lbl_clip_toast = tk.Label(
            self.clipboard_toast,
            text="📋 Phát hiện link video",
            bg="#202124",
            fg="#ffffff",
            font=("Segoe UI", 9),
        )
        self.lbl_clip_toast.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_clip_play = ttk.Button(
            self.clipboard_toast,
            text="▶ Phát ngay",
            style="Accent.TButton",
            command=self._on_clipboard_toast_play,
        )
        self.btn_clip_play.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_clip_download = ttk.Button(
            self.clipboard_toast,
            text="⬇ Tải ngay",
            command=self._on_clipboard_toast_download,
        )
        self.btn_clip_download.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_clip_close = tk.Button(
            self.clipboard_toast,
            text="✕",
            bg="#202124",
            fg="#aaaaaa",
            activebackground="#333333",
            activeforeground="#ffffff",
            bd=0,
            padx=6,
            pady=2,
            cursor="hand2",
            command=self.hide_clipboard_prompt,
        )
        self.btn_clip_close.pack(side=tk.RIGHT)

        # Network Suggestion Toast Prompt Banner (Degraded/Critical streaming health)
        self.network_toast = tk.Frame(
            self.video_container,
            bg="#202124",
            highlightbackground="#e3711a",
            highlightthickness=1,
            padx=12,
            pady=6,
        )
        self.lbl_network_toast = tk.Label(
            self.network_toast,
            text="",
            bg="#202124",
            fg="#ffffff",
            font=("Segoe UI", 9),
            justify=tk.LEFT,
        )
        self.lbl_network_toast.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_network_auto = ttk.Button(
            self.network_toast,
            text="⚡ Đổi sang Auto",
            style="Accent.TButton",
            command=self._on_network_toast_apply_click,
        )
        self.btn_network_auto.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_network_close = tk.Button(
            self.network_toast,
            text="✕",
            bg="#202124",
            fg="#aaaaaa",
            activebackground="#333333",
            activeforeground="#ffffff",
            bd=0,
            padx=6,
            pady=2,
            cursor="hand2",
            command=self.hide_network_suggestion_prompt,
        )
        self.btn_network_close.pack(side=tk.RIGHT)

    def _build_transport_bar(self) -> None:
        """Construct Seek bar, Play/Pause, Volume, Speed, and Fullscreen widgets."""
        self.transport_bar = ttk.Frame(self.bottom_inner, padding=(8, 4))
        self.transport_bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar = self.transport_bar

        # Seek Bar line
        seek_row = ttk.Frame(bar)
        seek_row.pack(fill=tk.X, expand=True, pady=(0, 4))

        self.seek_scale = ttk.Scale(
            seek_row,
            from_=0,
            to=1000,
            orient=tk.HORIZONTAL,
            style="Horizontal.TScale",
        )
        self.seek_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.seek_controller = SeekBarController(
            self.seek_scale,
            on_seek=self.on_seek_request,
            on_preview=self._on_seek_preview,
        )

        self.lbl_time = ttk.Label(seek_row, text="00:00 / 00:00", font=("Consolas", 9))
        self.lbl_time.pack(side=tk.RIGHT)

        # Controls line
        ctrl_row = ttk.Frame(bar)
        ctrl_row.pack(fill=tk.X, expand=True)

        self.btn_toggle = ttk.Button(ctrl_row, text="▶", width=4, command=self.on_pause_toggle)
        self.btn_toggle.pack(side=tk.LEFT, padx=(0, 4))

        short_seek = self.settings.get("ui", "seek_short", default=5)
        self.btn_rewind = ttk.Button(
            ctrl_row,
            text=f"⏮ {short_seek}s",
            width=6,
            command=lambda: self.on_seek_relative(-short_seek),
        )
        self.btn_rewind.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_forward = ttk.Button(
            ctrl_row,
            text=f"⏭ {short_seek}s",
            width=6,
            command=lambda: self.on_seek_relative(short_seek),
        )
        self.btn_forward.pack(side=tk.LEFT, padx=(0, 10))

        # Volume Controls
        self.btn_mute = ttk.Button(ctrl_row, text="🔊", width=3, command=self._on_mute_clicked)
        self.btn_mute.pack(side=tk.LEFT, padx=(0, 4))

        vol_container = ttk.Frame(ctrl_row)
        vol_container.pack(side=tk.LEFT, padx=(0, 10))

        default_vol = self.settings.get("audio", "default_volume", default=80)
        self.volume_scale = ttk.Scale(
            vol_container,
            from_=0,
            to=150,
            length=110,
            orient=tk.HORIZONTAL,
            value=default_vol,
            command=self._on_volume_slide,
        )
        self.volume_scale.pack(side=tk.TOP)

        self.lbl_volume = ttk.Label(
            vol_container,
            text=f"{default_vol}%",
            font=("Segoe UI", 8),
            anchor=tk.CENTER,
        )
        self.lbl_volume.pack(side=tk.TOP, fill=tk.X)

        # Speed Dropdown
        ttk.Label(ctrl_row, text="Tốc độ:").pack(side=tk.LEFT, padx=(0, 4))
        self.speed_var = tk.StringVar(value="1.0x")
        self.speed_combo = ttk.Combobox(
            ctrl_row,
            textvariable=self.speed_var,
            values=[f"{s}x" for s in SPEED_OPTIONS],
            width=6,
            state="readonly",
        )
        self.speed_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.speed_combo.bind("<<ComboboxSelected>>", self._on_speed_selected)

        # Fullscreen Button
        self.btn_fs = ttk.Button(ctrl_row, text="⛶ Toàn màn hình", command=self.toggle_fullscreen)
        self.btn_fs.pack(side=tk.RIGHT)

        # PiP Button
        self.btn_pip = ttk.Button(ctrl_row, text="📌 PiP", width=6, command=self.toggle_pip)
        self.btn_pip.pack(side=tk.RIGHT, padx=(0, 6))

        # A-B Repeat Button
        self.btn_ab_repeat = ttk.Button(ctrl_row, text="A-B", width=6, command=self._on_ab_repeat_click)
        self.btn_ab_repeat.pack(side=tk.RIGHT, padx=(0, 6))

        # Loop Button
        self.btn_loop = ttk.Button(ctrl_row, text="🔁 Lặp", width=6, command=self._on_loop_click)
        self.btn_loop.pack(side=tk.RIGHT, padx=(0, 6))

        self.transport_bar.bind("<Button-1>", lambda e: self.root.focus_set())

    def _build_bottom_bar(self) -> None:
        """Construct Timestamp Jump input and Info/Status bar."""
        self.bottom_bar = ttk.Frame(self.bottom_inner, padding=(8, 4))
        self.bottom_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.bottom_bar.bind("<Button-1>", lambda e: self.root.focus_set())
        bar = self.bottom_bar

        # Timestamp jump widgets
        jump_frame = ttk.Frame(bar)
        jump_frame.pack(side=tk.LEFT)

        ttk.Label(jump_frame, text="Nhảy tới:").pack(side=tk.LEFT, padx=(0, 4))
        self.jump_entry = ttk.Entry(jump_frame, width=10)
        self.jump_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.jump_entry.bind("<Return>", lambda e: self._on_jump_click())
        self.jump_entry.bind("<Escape>", lambda e: self.root.focus_set())

        btn_jump = ttk.Button(jump_frame, text="→ Nhảy", width=8, command=self._on_jump_click)
        btn_jump.pack(side=tk.LEFT, padx=(0, 12))

        # Devlog Checkbox on the right (hidden by default unless dev mode unlocked)
        self.devlog_var = tk.BooleanVar(value=False)
        self.chk_devlog = ttk.Checkbutton(
            bar,
            text="Devlog",
            variable=self.devlog_var,
            command=self._on_toggle_devlog,
        )
        if getattr(self, "_dev_mode_unlocked", False):
            self.chk_devlog.pack(side=tk.RIGHT, padx=(8, 2))

        # Status / Title label
        self.lbl_status = ttk.Label(
            bar,
            text="",
            font=("Segoe UI", 9, "italic"),
        )
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def enable_dev_mode(self) -> None:
        """Unlock developer mode and reveal Devlog checkbox at the bottom right."""
        self._dev_mode_unlocked = True
        if hasattr(self, "chk_devlog"):
            if hasattr(self, "lbl_status") and self.lbl_status.winfo_manager() == "pack":
                self.lbl_status.pack_forget()
                self.chk_devlog.pack(side=tk.RIGHT, padx=(8, 2))
                self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
            elif self.chk_devlog.winfo_manager() != "pack":
                self.chk_devlog.pack(side=tk.RIGHT, padx=(8, 2))
        if hasattr(self, "menu_tools"):
            try:
                self.menu_tools.add_command(
                    label="🛠 Nhật ký nhà phát triển (Devlog)",
                    accelerator="F12",
                    command=self.toggle_devlog,
                )
            except Exception:
                pass
        self.show_osd_message("🛠 Đã mở khóa chế độ nhà phát triển (Devlog).")

    def _expand_window_width(self, delta_w: int) -> int:
        """Deprecated: Kept for backward compatibility. Returns 0 to keep window geometry fixed so buttons never shift."""
        return 0

    def _shrink_window_width(self, delta_w: int) -> None:
        """Deprecated: Kept for backward compatibility. No-op to keep window geometry fixed so buttons never shift."""
        pass

    def _repack_right_panels(self) -> None:
        """
        Enforce right-side hierarchy:
        Devlog is furthest right (sát phải),
        then Queue/Playlist,
        then Chapters,
        with Video Player filling all remaining area to the left.
        """
        if hasattr(self, "devlog_panel") and hasattr(self.devlog_panel, "panel_frame"):
            self.devlog_panel.panel_frame.pack_forget()
        if hasattr(self, "queue_panel"):
            self.queue_panel.pack_forget()
        if hasattr(self, "chapter_panel"):
            self.chapter_panel.pack_forget()

        # In Fullscreen or PiP mode, right panels remain hidden to keep video pure
        if getattr(self, "_is_fullscreen", False) or getattr(self, "_is_pip", False):
            return

        # 1. Devlog panel is packed FIRST with side=tk.RIGHT -> sits at the far right edge (sát phải)
        if (
            hasattr(self, "devlog_panel")
            and getattr(self.devlog_panel, "_is_visible", False)
            and not getattr(self.devlog_panel, "_is_detached", False)
        ):
            self.devlog_panel.panel_frame.pack(side=tk.RIGHT, fill=tk.BOTH)

        # 2. Queue / Playlist panel is packed SECOND with side=tk.RIGHT -> sits directly to the left of Devlog
        if getattr(self, "_queue_visible", False) and not getattr(self, "_queue_is_detached", False):
            self.queue_panel.pack(side=tk.RIGHT, fill=tk.Y)

        # 3. Chapter panel is packed THIRD with side=tk.RIGHT -> sits directly to the left of Queue
        if getattr(self, "_chapters_visible", False):
            self.chapter_panel.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_toggle_devlog(self) -> None:
        """Handle Devlog checkbox toggle without shifting window geometry or buttons."""
        if self.devlog_var.get():
            self.devlog_panel.show()
            self._repack_right_panels()
        else:
            self.devlog_panel.hide()
            self._repack_right_panels()

    def _on_devlog_visibility_changed(self, is_visible: bool) -> None:
        """Sync Devlog checkbox when the detached window is closed."""
        self.devlog_var.set(is_visible)
        self._repack_right_panels()

    def _on_devlog_dock_changed(self, is_detached: bool) -> None:
        """Handle Devlog detachment/docking to keep main window geometry aligned."""
        self._repack_right_panels()

    def toggle_devlog(self) -> None:
        """Toggle Devlog via keyboard shortcut (F12)."""
        if not getattr(self, "_dev_mode_unlocked", False):
            self.show_osd_message("🔒 Chế độ nhà phát triển chưa được kích hoạt.")
            return
        self.devlog_var.set(not self.devlog_var.get())
        self._on_toggle_devlog()

    # --- Keyboard Shortcuts & Focus Filtering (§7.4 case #31) ---

    def _bind_shortcuts(self) -> None:
        """Register dynamic global hotkeys from settings, ignoring them when focused on Entry inputs."""
        # 1. Unbind previous dynamically bound hotkey sequences
        if not hasattr(self, "_bound_hotkey_sequences"):
            self._bound_hotkey_sequences = set()

        for seq in self._bound_hotkey_sequences:
            try:
                self.root.unbind(seq)
                self.root.unbind_all(seq)
            except Exception:
                pass
        self._bound_hotkey_sequences.clear()

        # 2. Dynamic seek intervals from settings
        seek_short = lambda: self.settings.get("ui", "seek_short", default=5)
        seek_long = lambda: self.settings.get("ui", "seek_long", default=30)

        # 3. Action map linking action IDs to application functions
        action_handlers = {
            "play_pause": lambda e: self.on_pause_toggle(),
            "seek_backward": lambda e: self.on_seek_relative(-seek_short()),
            "seek_forward": lambda e: self.on_seek_relative(seek_short()),
            "seek_backward_long": lambda e: self.on_seek_relative(-seek_long()),
            "seek_forward_long": lambda e: self.on_seek_relative(seek_long()),
            "speed_down": lambda e: self._step_speed(-1),
            "speed_up": lambda e: self._step_speed(1),
            "volume_up": lambda e: self._step_volume(5),
            "volume_down": lambda e: self._step_volume(-5),
            "mute": lambda e: self._on_mute_clicked(),
            "fullscreen": lambda e: self.toggle_fullscreen(),
            "pip": lambda e: self.toggle_pip(),
            "pip_ratio": lambda e: self.toggle_pip_aspect_ratio(),
            "toggle_loop": lambda e: self._on_loop_click(),
            "toggle_ab_repeat": lambda e: self._on_ab_repeat_click(),
            "history": lambda e: self._on_history_clicked(),
            "open_file": lambda e: self._on_open_file_clicked(),
            "download": lambda e: self._on_download_clicked(),
            "paste_and_play": lambda e: self._on_paste_and_play(),
            "settings": lambda e: self.open_settings_dialog(),
            "devlog": lambda e: self.toggle_devlog(),
            "queue": lambda e: self.toggle_queue(),
            "next_track": lambda e: (self.on_next_track() if self.on_next_track else None),
            "previous_track": lambda e: (self.on_previous_track() if self.on_previous_track else None),
        }

        # 4. Standard extra relative seek aliases (<, >, ,, .)
        for seq in ("<less>", "<comma>"):
            h = self._wrap_shortcut(lambda e: self.on_seek_relative(-seek_short()))
            self.root.bind(seq, h)
            self.root.bind_all(seq, h)
            self._bound_hotkey_sequences.add(seq)
        for seq in ("<greater>", "<period>"):
            h = self._wrap_shortcut(lambda e: self.on_seek_relative(seek_short()))
            self.root.bind(seq, h)
            self.root.bind_all(seq, h)
            self._bound_hotkey_sequences.add(seq)

        # 5. Retrieve configured hotkeys from settings with fallback to factory defaults
        saved_hotkeys = self.settings.get("hotkeys", default={})
        has_space_bound = False

        for action_id, fn in action_handlers.items():
            hotkey_str = saved_hotkeys.get(action_id, DEFAULT_HOTKEYS.get(action_id, ""))
            if not hotkey_str:
                continue
            sequences = hotkey_to_tk_sequences(hotkey_str)
            allow_in_entry = action_id in ("history", "open_file", "settings", "devlog", "download", "paste_and_play")
            for seq in sequences:
                if seq == "<space>":
                    has_space_bound = True
                    self.root.bind("<space>", self._on_space_pressed)
                    self.root.bind_all("<space>", self._on_space_pressed)
                    self._bound_hotkey_sequences.add("<space>")
                else:
                    handler = self._wrap_shortcut(fn, allow_in_entry=allow_in_entry)
                    self.root.bind(seq, handler)
                    self.root.bind_all(seq, handler)
                    self._bound_hotkey_sequences.add(seq)

        # Spacebar TTK button class interception if Space is bound
        if has_space_bound:
            self.root.bind_class("TButton", "<space>", self._on_button_space)
        else:
            try:
                self.root.unbind_class("TButton", "<space>")
            except Exception:
                pass

        # 6. Static window-level bindings
        self.root.bind("<Escape>", lambda e: self._on_escape_pressed())
        self.root.bind_all("<Escape>", lambda e: self._on_escape_pressed())
        self.root.bind("<Control-v>", lambda e: None)  # Normal paste handled by entry

    def rebind_shortcuts(self) -> None:
        """Reload hotkey settings and re-register keyboard shortcuts dynamically."""
        self._bind_shortcuts()
        self._build_context_menu()

    def _on_space_pressed(self, event) -> Optional[str]:
        """Handle global spacebar press to pause/resume playback."""
        try:
            widget = getattr(event, "widget", None)
            top = widget.winfo_toplevel() if widget else None
            if top and top != self.root:
                return None
        except Exception:
            return None

        focused = self.root.focus_get()
        if isinstance(focused, (ttk.Entry, tk.Entry, tk.Text)) or isinstance(widget, (ttk.Entry, tk.Entry, tk.Text)):
            return None

        self.on_pause_toggle()
        return "break"

    def _on_button_space(self, event) -> Optional[str]:
        """Intercept spacebar on ttk buttons in MainWindow so Space toggles pause instead of re-activating button."""
        try:
            top = event.widget.winfo_toplevel()
            if top != self.root:
                event.widget.invoke()
                return "break"
        except Exception:
            return None

        self.on_pause_toggle()
        return "break"

    def _on_escape_pressed(self) -> None:
        """Handle Escape key: cancel seek drag if dragging, exit PiP if in PiP mode, exit fullscreen if fullscreen, else unfocus."""
        if hasattr(self, "seek_controller") and self.seek_controller._is_user_dragging:
            self.seek_controller.cancel_drag(self._current_position_ms)
            cur_str = format_timestamp(self._current_position_ms)
            dur_str = format_timestamp(self._current_duration_ms) if self._current_duration_ms > 0 else "--:--"
            self.lbl_time.configure(text=f"{cur_str} / {dur_str}")
            if hasattr(self, "osd_overlay"):
                self.osd_overlay.hide()
            return

        if self._is_pip:
            self.toggle_pip()
        elif self._is_fullscreen:
            self.exit_fullscreen()
        else:
            self.root.focus_set()

    def _detect_pip_region(
        self,
        rel_x: int,
        rel_y: int,
        win_w: Optional[int] = None,
        win_h: Optional[int] = None,
    ) -> Tuple[str, str]:
        """
        Detect whether cursor is over an edge/corner (for resizing) or interior (for moving).
        Returns (mode_str, cursor_name).
        """
        w = win_w if win_w is not None else self.root.winfo_width()
        h = win_h if win_h is not None else self.root.winfo_height()
        CORNER = 16
        EDGE = 8

        # 1. Corners (takes precedence over straight edges)
        if rel_x >= w - CORNER and rel_y >= h - CORNER:
            return "resize_br", "size_nw_se"
        if rel_x <= CORNER and rel_y <= CORNER:
            return "resize_tl", "size_nw_se"
        if rel_x >= w - CORNER and rel_y <= CORNER:
            return "resize_tr", "size_ne_sw"
        if rel_x <= CORNER and rel_y >= h - CORNER:
            return "resize_bl", "size_ne_sw"

        # 2. Straight edges
        if rel_x >= w - EDGE:
            return "resize_r", "size_we"
        if rel_x <= EDGE:
            return "resize_l", "size_we"
        if rel_y >= h - EDGE:
            return "resize_b", "size_ns"
        if rel_y <= EDGE:
            return "resize_t", "size_ns"

        # 3. Interior window body
        return "move", "fleur"

    def _on_video_hover(self, event) -> None:
        """Dynamically update cursor when hovering over PiP edges/corners for resizing, or reveal controls in fullscreen."""
        if self._is_fullscreen:
            self._on_fs_mouse_motion(event)
            return

        if not self._is_pip:
            return
        rel_x = event.x_root - self.root.winfo_rootx()
        rel_y = event.y_root - self.root.winfo_rooty()
        _, cursor_name = self._detect_pip_region(rel_x, rel_y)
        try:
            self.video_container.configure(cursor=cursor_name)
            self.overlay_label.configure(cursor=cursor_name)
        except Exception:
            pass

    def _on_video_leave(self, event) -> None:
        """Reset cursor to default when mouse leaves video surface."""
        if not self._is_pip:
            return
        try:
            self.video_container.configure(cursor="")
            self.overlay_label.configure(cursor="")
        except Exception:
            pass

    def _on_video_wheel(self, event) -> None:
        """Scale PiP window size smoothly with mouse wheel while maintaining active aspect ratio."""
        if not self._is_pip:
            return
        delta = getattr(event, "delta", 0)
        step = 32 if delta > 0 else -32
        cur_w = self.root.winfo_width()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        is_vert = (self._pip_aspect_ratio == "9:16")
        min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
        new_w = max(min_w, min(screen_w - 40, cur_w + step))
        new_h = int(new_w * 16 / 9) if is_vert else int(new_w * 9 / 16)
        if new_h > screen_h - 40:
            new_h = screen_h - 40
            new_w = int(new_h * (9 / 16 if is_vert else 16 / 9))
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()
        new_x = max(10, min(screen_w - new_w - 30, cur_x))
        new_y = max(10, min(screen_h - new_h - 60, cur_y))
        self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")
        self._last_resized_pip_w = new_w
        self._last_resized_pip_h = new_h
        self._save_current_pip_size(new_w, new_h)
        if hasattr(self, "osd_overlay"):
            self.osd_overlay.reposition()
        if hasattr(self, "pip_progress_overlay"):
            self.pip_progress_overlay.reposition(self.root)

    def _on_grip_press(self, event) -> None:
        """Handle mouse press on corner resize grip indicator."""
        self.root.focus_force()
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._win_start_x = self.root.winfo_x()
        self._win_start_y = self.root.winfo_y()
        self._win_start_w = self.root.winfo_width()
        self._win_start_h = self.root.winfo_height()
        self._drag_mode = "resize_br"
        self._has_dragged = False

    def _on_video_press(self, event) -> None:
        """Record coordinates and detect drag/resize mode on mouse press."""
        self.root.focus_force()
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._win_start_x = self.root.winfo_x()
        self._win_start_y = self.root.winfo_y()
        self._win_start_w = self.root.winfo_width()
        self._win_start_h = self.root.winfo_height()
        self._has_dragged = False

        if self._is_pip:
            rel_x = event.x_root - self.root.winfo_rootx()
            rel_y = event.y_root - self.root.winfo_rooty()
            self._drag_mode, _ = self._detect_pip_region(rel_x, rel_y)
        else:
            self._drag_mode = "none"

    def _on_video_motion(self, event) -> None:
        """Drag to move (with edge snapping) or resize floating borderless PiP window."""
        if not self._is_pip:
            return

        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y
        if abs(dx) > 3 or abs(dy) > 3:
            self._has_dragged = True

        if self._drag_mode == "move":
            new_x = self._win_start_x + dx
            new_y = self._win_start_y + dy

            # Edge and Corner Snapping relative to current monitor (PIP_SNAP_MARGIN = 24px)
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            mon_left, mon_top, mon_w, mon_h = get_monitor_work_area_for_rect(new_x, new_y, cur_w, cur_h)
            snap = PIP_SNAP_MARGIN

            if abs(new_x - mon_left) < snap:
                new_x = mon_left
            elif abs((new_x + cur_w) - (mon_left + mon_w)) < snap:
                new_x = mon_left + mon_w - cur_w

            if abs(new_y - mon_top) < snap:
                new_y = mon_top
            elif abs((new_y + cur_h) - (mon_top + mon_h)) < snap:
                new_y = mon_top + mon_h - cur_h

            self.root.geometry(f"+{new_x}+{new_y}")
            if hasattr(self, "osd_overlay"):
                self.osd_overlay.reposition()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.reposition(self.root)

        elif self._drag_mode.startswith("resize"):
            mon_left, mon_top, mon_w, mon_h = get_monitor_work_area_for_rect(
                self._win_start_x, self._win_start_y, self._win_start_w, self._win_start_h
            )
            max_w = mon_w - 40
            max_h = mon_h - 40

            is_vert = (self._pip_aspect_ratio == "9:16")
            r_h_w = 16 / 9 if is_vert else 9 / 16
            r_w_h = 9 / 16 if is_vert else 16 / 9
            min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
            min_h = MIN_PIP_VERTICAL_HEIGHT if is_vert else MIN_PIP_HEIGHT

            if self._drag_mode in ("resize_br", "resize_r"):
                new_w = max(min_w, min(max_w, self._win_start_w + dx))
                new_h = int(new_w * r_h_w)
                self.root.geometry(f"{new_w}x{new_h}+{self._win_start_x}+{self._win_start_y}")

            elif self._drag_mode == "resize_b":
                new_h = max(min_h, min(max_h, self._win_start_h + dy))
                new_w = int(new_h * r_w_h)
                self.root.geometry(f"{new_w}x{new_h}+{self._win_start_x}+{self._win_start_y}")

            elif self._drag_mode in ("resize_tl", "resize_l"):
                new_w = max(min_w, min(max_w, self._win_start_w - dx))
                new_h = int(new_w * r_h_w)
                new_x = self._win_start_x + (self._win_start_w - new_w)
                new_y = self._win_start_y + (self._win_start_h - new_h) if self._drag_mode == "resize_tl" else self._win_start_y
                self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")

            elif self._drag_mode == "resize_tr":
                new_w = max(min_w, min(max_w, self._win_start_w + dx))
                new_h = int(new_w * r_h_w)
                new_y = self._win_start_y + (self._win_start_h - new_h)
                self.root.geometry(f"{new_w}x{new_h}+{self._win_start_x}+{new_y}")

            elif self._drag_mode == "resize_bl":
                new_w = max(min_w, min(max_w, self._win_start_w - dx))
                new_h = int(new_w * r_h_w)
                new_x = self._win_start_x + (self._win_start_w - new_w)
                self.root.geometry(f"{new_w}x{new_h}+{new_x}+{self._win_start_y}")

            elif self._drag_mode == "resize_t":
                new_h = max(min_h, min(max_h, self._win_start_h - dy))
                new_w = int(new_h * r_w_h)
                new_y = self._win_start_y + (self._win_start_h - new_h)
                self.root.geometry(f"{new_w}x{new_h}+{self._win_start_x}+{new_y}")

            self._last_resized_pip_w = new_w
            self._last_resized_pip_h = new_h

            if hasattr(self, "osd_overlay"):
                self.osd_overlay.reposition()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.reposition(self.root)

    def _on_video_release(self, event) -> None:
        """
        On mouse release:
        - In PiP mode: persist updated geometry (w, h, x, y) on drag/resize release.
          Left-clicking NEVER toggles pause in PiP mode so user can drag without accidental pauses.
        - In normal window mode: debounce single click to toggle play/pause.
        """
        if self._is_pip:
            was_resizing = self._drag_mode.startswith("resize")
            was_moving = (self._drag_mode == "move")
            had_dragged = self._has_dragged
            self._drag_mode = "none"
            self._has_dragged = False
            self.pip_progress.place(relx=0, rely=1.0, relwidth=1.0, height=3, anchor=tk.SW)
            self.pip_progress.lift()
            self.resize_grip.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-2, y=-2)
            self.resize_grip.lift()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.reposition(self.root)
            if was_resizing or was_moving or had_dragged:
                w = getattr(self, "_last_resized_pip_w", None) or self.root.winfo_width()
                h = getattr(self, "_last_resized_pip_h", None) or self.root.winfo_height()
                pos_x = self.root.winfo_x()
                pos_y = self.root.winfo_y()
                self._save_current_pip_geometry(w, h, pos_x, pos_y)
            return

        if self._has_dragged:
            self._has_dragged = False
            return

        if self._video_click_timer is not None:
            self.root.after_cancel(self._video_click_timer)
            self._video_click_timer = None
            return
        self._video_click_timer = self.root.after(250, self._execute_video_single_click)

    def _execute_video_single_click(self) -> None:
        self._video_click_timer = None
        self.on_pause_toggle()

    def _on_video_double_click(self, event) -> None:
        """Handle double-click: exit PiP if in PiP mode, otherwise toggle fullscreen."""
        if self._video_click_timer is not None:
            self.root.after_cancel(self._video_click_timer)
            self._video_click_timer = None

        if self._is_pip:
            self.toggle_pip()
        else:
            self.toggle_fullscreen()

    def _wrap_shortcut(self, action: Callable[[Any], None], allow_in_entry: bool = False):
        """Filter out shortcuts when the focused widget is a text Entry (§7.4 case #31)."""
        def handler(event):
            try:
                widget = getattr(event, "widget", None)
                top = widget.winfo_toplevel() if widget else None
                if top and top != self.root:
                    return None
            except Exception:
                pass

            # If action is allowed in entry OR it's a Control/Alt combination, allow it through
            state = getattr(event, "state", 0)
            is_modifier_combo = isinstance(state, int) and bool(state & (4 | 8 | 131072))
            if not (allow_in_entry or is_modifier_combo):
                focused = self.root.focus_get()
                if isinstance(focused, (ttk.Entry, tk.Entry, tk.Text)) or isinstance(widget, (ttk.Entry, tk.Entry, tk.Text)):
                    return None

            action(event)
            return "break"
        return handler

    # --- Action Handlers ---

    def _on_play_click(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self.set_status("Vui lòng dán liên kết video trước khi phát.")
            return

        # Smart bulk text detection
        if "\n" in url or len(url) > 150:
            from main.text_parser import SmartTextParser
            parsed = SmartTextParser.parse_text(url)
            if len(parsed) >= 2:
                confirm = messagebox.askyesno(
                    "Nhập danh sách video",
                    f"Phát hiện danh sách gồm {len(parsed)} video trong văn bản vừa nhập.\n"
                    "Bạn có muốn mở hộp thoại xem trước và thêm vào danh sách phát không?",
                    parent=self.root,
                )
                if confirm:
                    self.open_bulk_import_dialog(initial_text=url)
                    return
                else:
                    url = parsed[0].url

        self.root.focus_set()
        self.on_play_request(url)

    def _on_paste_and_play(self) -> None:
        try:
            clipboard = self.root.clipboard_get().strip()
            if not clipboard:
                self.set_status("Bộ nhớ tạm (clipboard) không chứa văn bản hợp lệ.")
                return

            # Check if clipboard has multiple video links
            if "\n" in clipboard or len(clipboard) > 150:
                from main.text_parser import SmartTextParser
                parsed = SmartTextParser.parse_text(clipboard)
                if len(parsed) >= 2:
                    self.url_entry.delete(0, tk.END)
                    self.url_entry.insert(0, f"📋 Danh sách {len(parsed)} video: {parsed[0].url}")
                    self.open_bulk_import_dialog(initial_text=clipboard)
                    return

            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, clipboard)
            self._on_play_click()
        except Exception:
            self.set_status("Bộ nhớ tạm (clipboard) không chứa văn bản hợp lệ.")

    def _on_open_file_clicked(self) -> None:
        """Prompt user to choose a local video or audio file and begin playback."""
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="Chọn file video hoặc âm thanh từ máy tính",
            filetypes=[
                (
                    "Tất cả file media (*.mp4, *.mkv, *.avi, *.mp3...)",
                    "*.mp4 *.mkv *.avi *.webm *.mov *.flv *.ts *.m4v *.wmv *.3gp *.mp3 *.wav *.m4a *.flac *.aac *.ogg",
                ),
                (
                    "File Video (*.mp4, *.mkv, *.avi, ...)",
                    "*.mp4 *.mkv *.avi *.webm *.mov *.flv *.ts *.m4v *.wmv *.3gp",
                ),
                (
                    "File Âm thanh (*.mp3, *.wav, *.m4a, ...)",
                    "*.mp3 *.wav *.m4a *.flac *.aac *.ogg",
                ),
                ("Tất cả tập tin (*.*)", "*.*"),
            ],
        )
        if file_path:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, file_path)
            self._on_play_click()

    def _init_drag_and_drop(self) -> None:
        """Initialize native drag-and-drop support for dropping media files onto the window."""
        if sys.platform != "win32":
            return
        try:
            self.root.update_idletasks()
            for widget in (self.root, self.video_container):
                hook_drop_files(widget, on_drop_callback=self._on_files_dropped)
        except Exception as ex:
            import logging
            logging.getLogger(__name__).warning("Lỗi khởi tạo tính năng kéo-thả file: %s", ex)

    def _on_files_dropped(self, files: list) -> None:
        """Handle media files dropped directly onto application window or video screen."""
        if not files:
            return
        first_file = files[0]
        if isinstance(first_file, bytes):
            try:
                path_str = first_file.decode("utf-8")
            except UnicodeDecodeError:
                path_str = first_file.decode("mbcs", errors="ignore")
        else:
            path_str = str(first_file)

        path_str = path_str.strip().strip('"').strip("'")
        if not path_str:
            return

        # Bring window to front
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, path_str)
        self._on_play_click()

    def _on_history_clicked(self) -> None:
        """Open watch history dialog."""
        if self.on_history_request:
            self.on_history_request()

    def _on_download_clicked(self, audio_only: Optional[bool] = None) -> None:
        """Request download of active video."""
        if self.on_download_request:
            try:
                self.on_download_request(audio_only=audio_only)
            except TypeError:
                self.on_download_request()

    def _on_load_subtitle_clicked(self) -> None:
        """Prompt user to choose a subtitle file, validate format, and attach to active player."""
        filetypes = [
            (
                "Tất cả phụ đề hỗ trợ",
                "*.srt;*.vtt;*.ass;*.ssa;*.sub;*.smi;*.sami;*.idx;*.txt;*.lrc;*.ttml;*.dfxp",
            ),
            ("SubRip Subtitle (*.srt)", "*.srt"),
            ("WebVTT Subtitle (*.vtt)", "*.vtt"),
            ("Advanced SubStation Alpha (*.ass, *.ssa)", "*.ass;*.ssa"),
            ("MicroDVD / SubViewer (*.sub)", "*.sub"),
            ("SAMI Caption (*.smi, *.sami)", "*.smi;*.sami"),
            ("VobSub Index (*.idx)", "*.idx"),
            ("LRC Lyrics (*.lrc)", "*.lrc"),
            ("Timed Text (*.ttml, *.dfxp, *.txt)", "*.ttml;*.dfxp;*.txt"),
            ("Tất cả tệp (*.*)", "*.*"),
        ]
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="Chọn tệp phụ đề",
            filetypes=filetypes,
        )
        if not file_path:
            return

        is_valid, fmt_name, msg = validate_subtitle_file(file_path)
        if not is_valid:
            messagebox.showerror(
                "Lỗi định dạng phụ đề",
                f"Tệp không hợp lệ: '{Path(file_path).name}'\n\nChi tiết: {msg}\n\nVui lòng chọn một tệp phụ đề hợp lệ (.srt, .vtt, .ass, ...).",
                parent=self.root,
            )
            return

        self.settings.set("subtitle", "file", file_path)
        self.show_osd_message(f"💬 Đã nạp phụ đề: {Path(file_path).name}")
        if self.on_subtitle_load:
            self.on_subtitle_load(file_path)

    def show_clipboard_prompt(self, url: str) -> None:
        """Display non-intrusive toast banner offering to play detected clipboard video URL."""
        if self._clipboard_toast_timer is not None:
            try:
                self.root.after_cancel(self._clipboard_toast_timer)
            except Exception:
                pass
            self._clipboard_toast_timer = None

        self._detected_clipboard_url = url
        short_url = url if len(url) <= 38 else f"{url[:35]}..."
        self.lbl_clip_toast.configure(text=f"📋 Phát hiện link video: {short_url}")
        self.clipboard_toast.place(relx=0.5, rely=0.04, anchor=tk.N)
        self.clipboard_toast.lift()
        self._clipboard_toast_timer = self.root.after(10000, self.hide_clipboard_prompt)

    def hide_clipboard_prompt(self) -> None:
        """Dismiss clipboard prompt banner."""
        if self._clipboard_toast_timer is not None:
            try:
                self.root.after_cancel(self._clipboard_toast_timer)
            except Exception:
                pass
            self._clipboard_toast_timer = None
        try:
            if hasattr(self, "clipboard_toast") and self.clipboard_toast.winfo_exists():
                self.clipboard_toast.place_forget()
        except Exception:
            pass


    def _on_clipboard_toast_play(self) -> None:
        """Play detected clipboard URL and dismiss banner."""
        url = self._detected_clipboard_url
        self.hide_clipboard_prompt()
        if url:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, url)
            self._on_play_click()

    def _on_clipboard_toast_download(self) -> None:
        """Download detected clipboard URL and dismiss banner."""
        url = self._detected_clipboard_url
        self.hide_clipboard_prompt()
        if url:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, url)
            self._on_download_clicked()

    def show_network_suggestion_prompt(self, message: str, on_apply: Callable[[], None]) -> None:
        """Display non-intrusive toast banner offering to switch to Auto profile."""
        if getattr(self, "_network_toast_timer", None) is not None:
            try:
                self.root.after_cancel(self._network_toast_timer)
            except Exception:
                pass
            self._network_toast_timer = None

        self._on_network_toast_apply = on_apply
        if hasattr(self, "lbl_network_toast"):
            self.lbl_network_toast.configure(text=message)
        if hasattr(self, "network_toast"):
            self.network_toast.place(relx=0.5, rely=0.04, anchor=tk.N)
            self.network_toast.lift()
        self._network_toast_timer = self.root.after(12000, self.hide_network_suggestion_prompt)

    def hide_network_suggestion_prompt(self) -> None:
        """Dismiss network suggestion prompt banner."""
        if getattr(self, "_network_toast_timer", None) is not None:
            try:
                self.root.after_cancel(self._network_toast_timer)
            except Exception:
                pass
            self._network_toast_timer = None
        if hasattr(self, "network_toast"):
            self.network_toast.place_forget()

    def _on_network_toast_apply_click(self) -> None:
        """Handle user clicking 'Đổi sang Auto' button on network toast."""
        callback = getattr(self, "_on_network_toast_apply", None)
        self.hide_network_suggestion_prompt()
        if callback:
            try:
                callback()
            except Exception as exc:
                logger.error(f"Lỗi khi áp dụng Auto profile: {exc}")

    def _on_jump_click(self) -> None:
        val = self.jump_entry.get().strip()
        if not val:
            return
        try:
            target_ms = parse_timestamp(val)
            self.on_seek_request(target_ms)
            self.jump_entry.delete(0, tk.END)
            self.root.focus_set()
        except ValueError as err:
            messagebox.showwarning("Thời gian không hợp lệ", f"Định dạng thời gian không đúng: {err}")

    def _on_add_to_queue_click(self) -> None:
        if self.on_add_to_queue:
            self.on_add_to_queue(self.url_entry.get().strip())

    def set_privacy_state(self, enabled: bool) -> None:
        """Show a clear runtime-only privacy indicator."""
        if enabled:
            self.privacy_badge.pack(side=tk.RIGHT, padx=(6, 4))
        else:
            self.privacy_badge.pack_forget()

    def _on_privacy_toggle(self) -> None:
        if self.on_privacy_toggle:
            self.on_privacy_toggle()

    def _build_queue_content(self, parent: tk.Widget, is_detached: bool = False) -> None:
        """Construct queue widgets into target parent (either sidebar panel or floating popup)."""
        for child in parent.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        # 1. Header: Title & Window docking/closing controls
        queue_header = ttk.Frame(parent)
        queue_header.pack(fill=tk.X, padx=6, pady=(6, 2))

        lbl_title = ttk.Label(queue_header, text="📋 Danh sách phát", font=("Segoe UI", 9, "bold"))
        lbl_title.pack(side=tk.LEFT)

        close_cmd = self._on_queue_window_close if is_detached else self.toggle_queue
        ttk.Button(queue_header, text="✕", width=3, command=close_cmd).pack(side=tk.RIGHT)

        detach_btn_text = "⬇ Thu về" if is_detached else "⧉ Tách"
        ttk.Button(queue_header, text=detach_btn_text, width=8, command=self.toggle_queue_popup).pack(side=tk.RIGHT, padx=(0, 4))

        # 2. Action Toolbar: Quick queue operations
        queue_toolbar = ttk.Frame(parent)
        queue_toolbar.pack(fill=tk.X, padx=6, pady=(2, 4))

        ttk.Button(queue_toolbar, text="📋 Nhập...", command=lambda: self.open_bulk_import_dialog()).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(queue_toolbar, text="💾 Xuất", command=self._export_queue_to_file).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(
            queue_toolbar,
            text="🧹 Dọn đã xem",
            command=lambda: (self.on_clear_played_queue() if self.on_clear_played_queue else None),
        ).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(
            queue_toolbar,
            text="🗑 Xóa hết",
            command=lambda: (self.on_clear_queue() if self.on_clear_queue else None),
        ).pack(side=tk.LEFT, padx=(0, 2))

        # 3. Main Listbox Body
        queue_body = ttk.Frame(parent)
        queue_body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 4))
        queue_scroll = ttk.Scrollbar(queue_body, orient=tk.VERTICAL)
        self.queue_list = tk.Listbox(
            queue_body,
            height=10,
            activestyle="none",
            exportselection=False,
            yscrollcommand=queue_scroll.set,
            font=("Segoe UI", 9),
        )
        queue_scroll.config(command=self.queue_list.yview)
        queue_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.queue_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.queue_tooltip = ListboxTooltip(
            self.queue_list,
            get_text_fn=self._get_queue_item_tooltip,
            theme_mgr=self.theme,
        )

        self.queue_list.bind("<Double-Button-1>", self._on_queue_double_click)
        self.queue_list.bind("<Return>", self._on_queue_double_click)
        self.queue_list.bind("<Button-3>", self._show_queue_context_menu)
        self.queue_list.bind("<Button-2>", self._show_queue_context_menu)

        # 4. Footer Bar: Persist Toggle + Quick Reorder / Remove
        queue_footer = ttk.Frame(parent)
        queue_footer.pack(fill=tk.X, padx=6, pady=(4, 6))

        self.queue_persist_inline_var = tk.BooleanVar(
            value=bool(self.settings.get("playback", "queue_persist", default=True))
        )

        def _on_toggle_queue_persist():
            val = self.queue_persist_inline_var.get()
            self.settings.set("playback", "queue_persist", val)
            self.settings.save()
            if self.on_queue_persist_toggle:
                self.on_queue_persist_toggle(val)
            self.show_osd_message("💾 Đã bật ghi nhớ hàng đợi" if val else "ℹ️ Đã tắt ghi nhớ hàng đợi")

        chk_persist = ttk.Checkbutton(
            queue_footer,
            text="Ghi nhớ khi tắt",
            variable=self.queue_persist_inline_var,
            command=_on_toggle_queue_persist,
        )
        chk_persist.pack(side=tk.LEFT)

        def _get_selected_queue_id():
            sel = self.queue_list.curselection()
            if sel and 0 <= sel[0] < len(self._queue_rows):
                return self._queue_rows[sel[0]].get("queue_id")
            return None

        def _move_selected(delta: int):
            qid = _get_selected_queue_id()
            if qid and self.on_move_queue_item:
                self.on_move_queue_item(qid, delta)

        def _remove_selected():
            qid = _get_selected_queue_id()
            if qid and self.on_remove_queue_item:
                self.on_remove_queue_item(qid)

        btn_del = ttk.Button(queue_footer, text="✖ Xóa", width=5, command=_remove_selected)
        btn_del.pack(side=tk.RIGHT, padx=(2, 0))
        btn_down = ttk.Button(queue_footer, text="▼", width=3, command=lambda: _move_selected(1))
        btn_down.pack(side=tk.RIGHT, padx=(2, 0))
        btn_up = ttk.Button(queue_footer, text="▲", width=3, command=lambda: _move_selected(-1))
        btn_up.pack(side=tk.RIGHT, padx=(2, 0))

        if getattr(self, "_queue_rows", None):
            self.refresh_queue(self._queue_rows)

    def toggle_queue_popup(self) -> None:
        """Switch between embedded sidebar mode and floating independent popup window."""
        if getattr(self, "_queue_is_detached", False):
            self.dock_queue_back()
        else:
            self.detach_queue_to_window()

    def detach_queue_to_window(self) -> None:
        """Detach queue panel into an independent floating popup window."""
        if getattr(self, "_queue_is_detached", False):
            return
        self._queue_is_detached = True
        self.queue_panel.pack_forget()
        self._repack_right_panels()

        self._queue_window = tk.Toplevel(self.root)
        self._queue_window.title("📋 FB Video Watcher - Danh sách phát (Queue)")
        self._queue_window.geometry("440x560")
        self._queue_window.minsize(360, 320)
        apply_window_icon(self._queue_window, ICON_FILE)
        set_windows_dark_titlebar(self._queue_window, dark=(self.theme.current_theme == "dark"))
        self._queue_window.protocol("WM_DELETE_WINDOW", self._on_queue_window_close)

        self._build_queue_content(self._queue_window, is_detached=True)
        self._queue_visible = True
        self._queue_window.focus_set()

    def dock_queue_back(self) -> None:
        """Dock queue back into the main application sidebar."""
        if not getattr(self, "_queue_is_detached", False):
            return
        self._queue_is_detached = False

        if self._queue_window and self._queue_window.winfo_exists():
            try:
                self._queue_window.destroy()
            except Exception:
                pass
            self._queue_window = None

        self._build_queue_content(self.queue_panel, is_detached=False)
        if self._queue_visible:
            self._repack_right_panels()

    def _on_queue_window_close(self) -> None:
        """Called when user closes floating queue window with 'X' button."""
        self.dock_queue_back()
        self._queue_visible = False
        self._repack_right_panels()

    def toggle_queue(self) -> None:
        """Show/hide the bounded queue panel without shifting window geometry or buttons."""
        if getattr(self, "_queue_is_detached", False) and self._queue_window and self._queue_window.winfo_exists():
            if self._queue_window.winfo_viewable():
                self._queue_window.withdraw()
                self._queue_visible = False
            else:
                self._queue_window.deiconify()
                self._queue_window.lift()
                self._queue_visible = True
            return

        if self._queue_visible:
            self._queue_visible = False
            self.queue_panel.pack_forget()
            self._queue_expanded_width = 0
            self._repack_right_panels()
        else:
            self._queue_visible = True
            self._queue_expanded_width = 0
            self._repack_right_panels()

    def refresh_queue(self, rows: list[dict]) -> None:
        """Render compact queue snapshots with status icons and durations."""
        self._queue_rows = list(rows)
        if not hasattr(self, "queue_list"):
            return
        self.queue_list.delete(0, tk.END)
        status_icons = {
            "playing": "▶",
            "resolving": "⏳",
            "played": "✓",
            "error": "✖",
            "skipped": "↷",
            "ready": "•",
            "pending": "•",
        }
        for index, row in enumerate(self._queue_rows, 1):
            title = str(row.get("title") or row.get("source_url") or "Video")
            status = str(row.get("status") or "pending")
            icon = status_icons.get(status, "•")
            dur_ms = row.get("duration_ms")
            dur_str = f" [{format_timestamp(dur_ms)}]" if (dur_ms and dur_ms > 0) else ""
            self.queue_list.insert(tk.END, f"{icon} {index}. {title[:80]}{dur_str}")
            if status == "playing":
                self.queue_list.selection_clear(0, tk.END)
                self.queue_list.selection_set(index - 1)

    def _trigger_play_queue_item(self, queue_id: str, source_url: str) -> None:
        if self.on_play_queue_item and queue_id:
            self.on_play_queue_item(queue_id)
        elif self.on_play_request and source_url:
            self.on_play_request(source_url)

    def _on_queue_double_click(self, _event=None) -> None:
        selection = self.queue_list.curselection()
        if not selection:
            return
        index = selection[0]
        if 0 <= index < len(self._queue_rows):
            row = self._queue_rows[index]
            queue_id = row.get("queue_id", "")
            source_url = row.get("source_url", "")
            self._trigger_play_queue_item(queue_id, str(source_url))

    def _show_queue_context_menu(self, event: tk.Event) -> None:
        """Context menu for playlist/queue items."""
        clicked_idx = self.queue_list.nearest(event.y)
        row = None
        if 0 <= clicked_idx < len(self._queue_rows):
            self.queue_list.selection_clear(0, tk.END)
            self.queue_list.selection_set(clicked_idx)
            self.queue_list.activate(clicked_idx)
            row = self._queue_rows[clicked_idx]

        menu = tk.Menu(self.root, tearoff=False)
        if row:
            queue_id = row.get("queue_id", "")
            source_url = row.get("source_url", "")
            status = row.get("status", "")

            menu.add_command(
                label="▶ Phát video này",
                command=lambda: self._trigger_play_queue_item(queue_id, source_url),
            )
            menu.add_separator()
            menu.add_command(
                label="▲ Di chuyển lên",
                command=lambda: (self.on_move_queue_item(queue_id, -1) if self.on_move_queue_item else None),
            )
            menu.add_command(
                label="▼ Di chuyển xuống",
                command=lambda: (self.on_move_queue_item(queue_id, 1) if self.on_move_queue_item else None),
            )
            menu.add_separator()
            if status == "error":
                menu.add_command(
                    label="🔄 Thử lại video lỗi",
                    command=lambda: (self.on_retry_queue_item(queue_id) if self.on_retry_queue_item else None),
                )
            menu.add_command(
                label="📋 Sao chép URL video",
                command=lambda: self._copy_queue_url(source_url),
            )
            menu.add_command(
                label="✖ Xóa khỏi danh sách",
                command=lambda: (self.on_remove_queue_item(queue_id) if self.on_remove_queue_item else None),
            )
            menu.add_separator()

        menu.add_command(
            label="🧹 Dọn các video đã xem",
            command=lambda: (self.on_clear_played_queue() if self.on_clear_played_queue else None),
        )
        menu.add_command(
            label="🗑️ Xóa toàn bộ danh sách",
            command=lambda: (self.on_clear_queue() if self.on_clear_queue else None),
        )
        menu.add_separator()
        menu.add_command(
            label="📋 Nhập danh sách từ văn bản...",
            command=lambda: self.open_bulk_import_dialog(),
        )
        menu.add_command(
            label="💾 Xuất danh sách phát ra file...",
            command=self._export_queue_to_file,
        )
        menu.add_command(
            label="📋 Sao chép tất cả liên kết (Copy All)",
            command=self._copy_all_queue_links,
        )

        if hasattr(self, "menu_bar") and hasattr(self.menu_bar, "style_menu"):
            self.menu_bar.style_menu(menu)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _export_queue_to_file(self) -> None:
        """Export current queue items to a readable text, json or m3u playlist file."""
        if not self._queue_rows:
            self.show_error("Danh sách phát hiện đang trống.")
            return
        from tkinter import filedialog
        file_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Lưu danh sách phát ra file",
            defaultextension=".txt",
            filetypes=[
                ("Text File (*.txt)", "*.txt"),
                ("JSON Playlist (*.json)", "*.json"),
                ("M3U Playlist (*.m3u)", "*.m3u"),
                ("Tất cả tập tin", "*.*"),
            ],
            initialfile="playlist.txt",
        )
        if not file_path:
            return
        try:
            p = Path(file_path)
            if p.suffix.lower() == ".json":
                import json
                p.write_text(json.dumps(self._queue_rows, ensure_ascii=False, indent=2), encoding="utf-8")
            elif p.suffix.lower() == ".m3u":
                lines = ["#EXTM3U\n"]
                for row in self._queue_rows:
                    title = row.get("title") or row.get("source_url") or ""
                    url = row.get("source_url") or ""
                    lines.append(f"#EXTINF:-1,{title}\n{url}\n")
                p.write_text("".join(lines), encoding="utf-8")
            else:
                lines = []
                for row in self._queue_rows:
                    desc = row.get("description")
                    title = row.get("title")
                    url = row.get("source_url") or ""
                    if desc:
                        lines.append(f"{desc}: {url}")
                    elif title and title != url:
                        lines.append(f"{title}: {url}")
                    else:
                        lines.append(url)
                p.write_text("\n".join(lines), encoding="utf-8")
            self.set_status(f"Đã lưu danh sách phát ({len(self._queue_rows)} video) vào {p.name}")
            self.show_osd_message(f"💾 Đã xuất {len(self._queue_rows)} video ra {p.name}")
        except Exception as exc:
            self.show_error(f"Không thể lưu file: {exc}")

    def _copy_all_queue_links(self) -> None:
        """Copy all queue links to clipboard as formatted text."""
        if not self._queue_rows:
            return
        lines = []
        for row in self._queue_rows:
            desc = row.get("description")
            title = row.get("title")
            url = row.get("source_url") or ""
            if desc:
                lines.append(f"{desc}: {url}")
            elif title and title != url:
                lines.append(f"{title}: {url}")
            else:
                lines.append(url)
        text = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.show_osd_message(f"📋 Đã sao chép {len(lines)} liên kết vào clipboard")

    def _get_queue_item_tooltip(self, index: int) -> Optional[str]:
        """Generate tooltip text when hovering over a queue item."""
        if not (0 <= index < len(self._queue_rows)):
            return None
        row = self._queue_rows[index]
        desc = row.get("description")
        url = row.get("source_url") or ""
        title = row.get("title") or ""

        lines = []
        if desc:
            lines.append(f"📌 Ngữ cảnh: {desc}")
        if title and title != url and title != "Video":
            lines.append(f"🎬 Tiêu đề: {title[:70]}")
        if url:
            url_display = url if len(url) <= 80 else url[:77] + "..."
            lines.append(f"🔗 URL: {url_display}")

        return "\n".join(lines) if lines else None

    def open_bulk_import_dialog(self, initial_text: str = "") -> None:
        """Open Bulk Import Dialog for parsing multi-video lists from text."""
        from main.bulk_import_dialog import BulkImportDialog
        BulkImportDialog(
            parent=self.root,
            theme_mgr=self.theme,
            on_import_to_queue=self.on_bulk_import_queue or (lambda items: None),
            on_replace_and_play=self.on_bulk_replace_and_play or (lambda items: None),
            initial_text=initial_text,
        )

    def _copy_queue_url(self, url: str) -> None:
        if not url:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.show_osd_message("📋 Đã sao chép liên kết video")

    def toggle_chapters(self) -> None:
        """Show/hide chapters panel without shifting window geometry or buttons."""
        if not self._chapters:
            return
        if self._chapters_visible:
            self._chapters_visible = False
            self.chapter_panel.pack_forget()
            self._chapters_expanded_width = 0
            self._repack_right_panels()
        else:
            self._chapters_visible = True
            self._chapters_expanded_width = 0
            self._repack_right_panels()

    def set_chapters(self, chapters) -> None:
        """Atomically replace the small chapter view for the active video."""
        self._chapters = list(chapters or ())
        self.chapter_list.delete(0, tk.END)
        for chapter in self._chapters:
            self.chapter_list.insert(tk.END, f"{format_timestamp(chapter.start_ms)}  {chapter.title[:100]}")
        self.btn_chapters.configure(state=tk.NORMAL if self._chapters else tk.DISABLED)
        if not self._chapters and self._chapters_visible:
            self.chapter_panel.pack_forget()
            self._chapters_visible = False
            self._chapters_expanded_width = 0
            self._repack_right_panels()

    def update_chapter_position(self, position_ms: int) -> None:
        if not self._chapters:
            return
        active = 0
        for index, chapter in enumerate(self._chapters):
            if position_ms >= chapter.start_ms:
                active = index
            else:
                break
        self.chapter_list.selection_clear(0, tk.END)
        self.chapter_list.selection_set(active)
        self.chapter_list.see(active)

    def _on_chapter_double_click(self, _event=None) -> None:
        selection = self.chapter_list.curselection()
        if selection and self.on_chapter_seek and selection[0] < len(self._chapters):
            self.on_chapter_seek(int(self._chapters[selection[0]].start_ms))

    def _on_mute_clicked(self) -> None:
        self.on_mute_toggle()

    def _on_loop_click(self) -> None:
        """Handle Loop button click."""
        if self.on_loop_toggle:
            self.on_loop_toggle()

    def _on_ab_repeat_click(self) -> None:
        """Handle A-B repeat button click."""
        if self.on_ab_repeat_toggle:
            self.on_ab_repeat_toggle()

    def set_loop_state(self, enabled: bool) -> None:
        """Update visual state of the Loop button."""
        if hasattr(self, "btn_loop"):
            if enabled:
                self.btn_loop.configure(text="🔁 Bật", style="Accent.TButton")
            else:
                self.btn_loop.configure(text="🔁 Lặp", style="TButton")

    def set_ab_repeat_state(self, state_str: str, time_a_ms: int = 0, time_b_ms: int = 0) -> None:
        """Update visual state of the A-B Repeat button ('A', 'AB', or 'OFF')."""
        if hasattr(self, "btn_ab_repeat"):
            if state_str == "A":
                time_str = format_timestamp(time_a_ms)
                self.btn_ab_repeat.configure(text=f"[A: {time_str}]", style="Accent.TButton")
            elif state_str == "AB":
                self.btn_ab_repeat.configure(text="[A-B: ON]", style="Accent.TButton")
            else:
                self.btn_ab_repeat.configure(text="A-B", style="TButton")

    def _on_speed_selected(self, event=None) -> None:
        val_str = self.speed_var.get().replace("x", "")
        try:
            rate = float(val_str)
            self.on_rate_change(rate)
        except ValueError:
            pass

    def _step_speed(self, direction: int) -> None:
        current_str = self.speed_var.get().replace("x", "")
        try:
            current_rate = float(current_str)
            idx = SPEED_OPTIONS.index(current_rate) if current_rate in SPEED_OPTIONS else 3
            new_idx = max(0, min(len(SPEED_OPTIONS) - 1, idx + direction))
            new_rate = SPEED_OPTIONS[new_idx]
            self.speed_var.set(f"{new_rate}x")
            self.on_rate_change(new_rate)
        except Exception:
            pass

    def _on_volume_slide(self, val_str: str) -> None:
        try:
            vol = int(float(val_str))
            self.lbl_volume.configure(text=f"{vol}%")
            self.on_volume_change(vol)
        except ValueError:
            pass

    def _step_volume(self, delta: int) -> None:
        curr = int(self.volume_scale.get())
        new_vol = max(0, min(150, curr + delta))
        self.volume_scale.set(new_vol)
        self.lbl_volume.configure(text=f"{new_vol}%")
        self.on_volume_change(new_vol)

    # --- Display & State Updates ---

    def set_loading(self, text: str = "Đang tải video Facebook...") -> None:
        """Show loading spinner/overlay on the video surface."""
        self.overlay_label.configure(text=text)
        self.overlay_label.lift()
        self.btn_play.configure(state=tk.DISABLED)

    def hide_overlay(self) -> None:
        """Hide overlay to reveal playing video."""
        self.overlay_label.lower()
        self.btn_play.configure(state=tk.NORMAL)

    def show_error(self, message: str) -> None:
        """Display error state on overlay and status bar."""
        self.overlay_label.configure(text=f"⚠️ {message}")
        self.overlay_label.lift()
        self.btn_play.configure(state=tk.NORMAL)
        self.set_status(message)

    def set_play_pause_button_state(self, is_playing: bool) -> None:
        """Update toggle button glyph."""
        self.btn_toggle.configure(text="⏸" if is_playing else "▶")

    def set_mute_button_state(self, is_muted: bool) -> None:
        """Update volume button glyph and percentage label."""
        self.btn_mute.configure(text="🔇" if is_muted else "🔊")
        if is_muted:
            self.lbl_volume.configure(text="0% (Mute)")
        else:
            vol = int(self.volume_scale.get())
            self.lbl_volume.configure(text=f"{vol}%")

    def set_status(self, text: str) -> None:
        """Update status line."""
        self.lbl_status.configure(text=text)

    def _on_seek_preview(self, target_ms: int) -> None:
        """Update time label and display preview OSD when user moves/drags the seek bar."""
        cur_str = format_timestamp(target_ms)
        dur_str = format_timestamp(self._current_duration_ms) if self._current_duration_ms > 0 else "--:--"
        time_str = f"{cur_str} / {dur_str}"
        self.lbl_time.configure(text=time_str)
        self._last_time_str = time_str

        # Also show floating OSD preview with progress bar on the video
        if hasattr(self, "osd_overlay") and self._current_duration_ms > 0:
            prog = max(0.0, min(1.0, target_ms / self._current_duration_ms))
            self.osd_overlay.show(
                f"⏱️ {cur_str} / {dur_str}",
                relx=0.5,
                rely=0.88,
                anchor=tk.S,
                progress=prog,
            )

    def update_playback_time(self, current_ms: int, duration_ms: int) -> None:
        """Called every 250ms by application orchestrator."""
        self._current_position_ms = current_ms
        self._current_duration_ms = duration_ms
        self.seek_controller.update_position(current_ms, duration_ms)

        # Do not overwrite the time label if the user is currently dragging or seeking
        if getattr(self.seek_controller, "is_user_interacting", False):
            return

        cur_str = format_timestamp(current_ms)
        dur_str = format_timestamp(duration_ms) if duration_ms > 0 else "--:--"
        time_str = f"{cur_str} / {dur_str}"
        if time_str != self._last_time_str:
            self._last_time_str = time_str
            self.lbl_time.configure(text=time_str)

        # Update mini progress bar in PiP mode
        if self._is_pip:
            if duration_ms > 0:
                frac = max(0.0, min(1.0, current_ms / duration_ms))
                self.pip_progress_fill.place(relx=0, rely=0, relwidth=frac, relheight=1.0)
                if hasattr(self, "pip_progress_overlay"):
                    self.pip_progress_overlay.update(frac, self.root)
            else:
                self.pip_progress_fill.place_forget()
                if hasattr(self, "pip_progress_overlay"):
                    self.pip_progress_overlay.hide()
        else:
            if hasattr(self, "pip_progress_overlay") and self.pip_progress_overlay._is_visible:
                self.pip_progress_overlay.hide()

    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode with smooth animated slide for top and bottom controls."""
        if self._is_pip:
            self.toggle_pip()

        if self._is_fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self) -> None:
        """Enter fullscreen mode and initiate smooth slide-out of top & bottom bars."""
        if self._is_pip:
            self.toggle_pip()
        if self._is_fullscreen:
            return
        self._is_fullscreen = True
        self._fs_controls_visible = True
        self._fs_is_animating = False

        if hasattr(self, "menu_bar") and self.menu_bar:
            self.menu_bar.pack_forget()

        # Hide docked right panels if open so video surface occupies full width
        if hasattr(self, "devlog_panel") and self.devlog_panel._is_visible and not self.devlog_panel._is_detached:
            self.devlog_panel.panel_frame.pack_forget()
        if hasattr(self, "queue_panel"):
            self.queue_panel.pack_forget()
        if hasattr(self, "chapter_panel"):
            self.chapter_panel.pack_forget()

        # Save previous window geometry and state to restore exactly on the same monitor
        self._fs_prev_geometry = self.root.geometry()
        self._fs_prev_state = self.root.state()

        # Detect the monitor where the window is currently located
        from main.platform_utils import get_monitor_bounds_for_window, apply_fullscreen_on_monitor
        mon_bounds = get_monitor_bounds_for_window(self.root)

        # Enter borderless OS fullscreen
        self.root.attributes("-fullscreen", True)

        # Ensure window stays on the current monitor via native Win32 SetWindowPos
        # (root.geometry() is ignored by Tkinter on Windows when -fullscreen is active)
        if mon_bounds:
            apply_fullscreen_on_monitor(self.root, mon_bounds)

        self.root.update_idletasks()
        self.btn_fs.configure(text="⛶ Thoát toàn màn hình")

        # Cache actual visible heights before switching layout
        self._fs_cached_top_h = max(42, self.top_wrapper.winfo_height())
        self._fs_cached_bot_h = max(76, self.bottom_wrapper.winfo_height())

        # --- Switch to overlay layout (Video fills 100% of window, bars float on top) ---
        # 1. Remove bars from pack flow so content_area (video) occupies full screen
        self.top_wrapper.pack_forget()
        self.bottom_wrapper.pack_forget()

        # 2. Inner widgets fill wrappers completely
        self.url_bar.pack_forget()
        self.bottom_inner.pack_forget()
        self.url_bar.place(x=0, y=0, relwidth=1.0, height=self._fs_cached_top_h)
        self.bottom_inner.place(x=0, y=0, relwidth=1.0, height=self._fs_cached_bot_h)

        # 3. Place bars as overlays on top of video — initially visible
        win_h = self.root.winfo_height()
        if win_h <= 10:
            win_h = self.root.winfo_screenheight()
        self.top_wrapper.place(x=0, y=0, relwidth=1.0, height=self._fs_cached_top_h)
        self.bottom_wrapper.place(x=0, y=win_h - self._fs_cached_bot_h,
                                  relwidth=1.0, height=self._fs_cached_bot_h)
        self.top_wrapper.lift()
        self.bottom_wrapper.lift()

        # Automatically slide out after 1.2s of entering fullscreen
        self._fs_schedule_autohide(delay_ms=1200)

    def exit_fullscreen(self) -> None:
        """Exit fullscreen mode and cleanly restore standard layout on the same monitor."""
        if not self._is_fullscreen:
            return
        self._is_fullscreen = False

        # Cancel any active fullscreen timers
        if self._fs_anim_timer:
            try:
                self.root.after_cancel(self._fs_anim_timer)
            except Exception:
                pass
            self._fs_anim_timer = None

        if self._fs_autohide_timer:
            try:
                self.root.after_cancel(self._fs_autohide_timer)
            except Exception:
                pass
            self._fs_autohide_timer = None

        self._fs_is_animating = False
        self._fs_controls_visible = True

        # Restore mouse cursor
        try:
            self.root.configure(cursor="")
            self.video_container.configure(cursor="")
            self.overlay_label.configure(cursor="")
        except Exception:
            pass

        # Exit OS fullscreen
        self.root.attributes("-fullscreen", False)
        self.root.update_idletasks()

        # Restore previous window state and geometry on the exact monitor where it was
        if hasattr(self, "_fs_prev_state") and self._fs_prev_state == "zoomed":
            try:
                self.root.state("zoomed")
            except Exception:
                pass
        elif hasattr(self, "_fs_prev_geometry") and self._fs_prev_geometry:
            try:
                self.root.geometry(self._fs_prev_geometry)
            except Exception:
                pass
        self.root.update_idletasks()

        self.btn_fs.configure(text="⛶ Toàn màn hình")

        # Re-apply native dark titlebar if in dark theme
        is_dark = (self.theme.current_theme == "dark")
        set_windows_dark_titlebar(self.root, dark=is_dark)

        if hasattr(self, "menu_bar") and self.menu_bar:
            self.menu_bar.pack(side=tk.TOP, fill=tk.X, before=self.main_container)

        # Restore normal toolbars layout without place offsets
        self.top_wrapper.place_forget()
        self.bottom_wrapper.place_forget()
        self.url_bar.place_forget()
        self.bottom_inner.place_forget()
        self.top_wrapper.pack_propagate(True)
        self.bottom_wrapper.pack_propagate(True)
        self.url_bar.pack(fill=tk.BOTH, expand=True)
        self.bottom_inner.pack(fill=tk.BOTH, expand=True)
        self.content_area.pack_forget()
        self.top_wrapper.pack(side=tk.TOP, fill=tk.X)
        self.bottom_wrapper.pack(side=tk.BOTTOM, fill=tk.X)
        self.content_area.pack(fill=tk.BOTH, expand=True)

        # Restore docked right-side panels in proper order
        self._repack_right_panels()

        self._build_context_menu()
        self.root.focus_set()

    def _fs_schedule_autohide(self, delay_ms: int = 2500) -> None:
        """Schedule automatic slide-out of top & bottom controls in fullscreen mode."""
        if not self._is_fullscreen:
            return
        if self._fs_autohide_timer:
            try:
                self.root.after_cancel(self._fs_autohide_timer)
            except Exception:
                pass
            self._fs_autohide_timer = None

        self._fs_autohide_timer = self.root.after(delay_ms, self._fs_autohide_check)

    def _fs_autohide_check(self) -> None:
        """Check if conditions are safe to slide out controls."""
        self._fs_autohide_timer = None
        if not self._is_fullscreen:
            return

        # Do not hide if user is actively typing in entry
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text)):
            self._fs_schedule_autohide(1500)
            return

        # Do not hide if mouse pointer is hovering over controls
        if self._is_cursor_in_controls():
            self._fs_schedule_autohide(1500)
            return

        # Slide out controls (pull up top bar, pull down bottom bar)
        self._fs_animate_controls(show=False)

    def _is_cursor_in_controls(self) -> bool:
        """Return True if mouse pointer is currently hovering inside top or bottom control bar."""
        if not getattr(self, "_fs_controls_visible", True):
            return False
        try:
            px = self.root.winfo_pointerx()
            py = self.root.winfo_pointery()
            for w in (self.top_wrapper, self.bottom_wrapper):
                if w.winfo_ismapped():
                    wx = w.winfo_rootx()
                    wy = w.winfo_rooty()
                    ww = w.winfo_width()
                    wh = w.winfo_height()
                    if wx <= px <= wx + ww and wy <= py <= wy + wh:
                        return True
        except Exception:
            pass
        return False

    def _on_fs_mouse_motion(self, event=None) -> None:
        """Respond to mouse motion during fullscreen mode by revealing controls smoothly."""
        if not self._is_fullscreen:
            return

        # Restore mouse cursor if it was hidden
        if getattr(self, "_fs_cursor_hidden", False):
            self._fs_cursor_hidden = False
            try:
                self.root.configure(cursor="")
                self.video_container.configure(cursor="")
                self.overlay_label.configure(cursor="")
            except Exception:
                pass

        # If controls are already fully visible and not animating, just extend autohide timer (throttled)
        now = time.monotonic()
        if self._fs_controls_visible and not self._fs_is_animating:
            if now - getattr(self, "_fs_last_autohide_time", 0) > 0.2:
                self._fs_last_autohide_time = now
                self._fs_schedule_autohide(2500)
            return

        # If already animating IN, do NOT restart animation on every mouse move!
        if self._fs_is_animating and getattr(self, "_fs_anim_direction", "") == "showing":
            if now - getattr(self, "_fs_last_autohide_time", 0) > 0.2:
                self._fs_last_autohide_time = now
                self._fs_schedule_autohide(2500)
            return

        # Otherwise (hidden or currently sliding out), smoothly animate controls in
        self._fs_animate_controls(show=True)

    def _fs_animate_controls(self, show: bool) -> None:
        """
        Smoothly slide top/bottom overlay bars by animating only their y coordinate.
        No height changes, no layout reflow — video area is never touched during animation.

        show=True:  top y: -top_h → 0              (slides down into view)
                    bot y:  win_h → win_h-bot_h     (slides up into view)
        show=False: top y: 0 → -top_h              (slides up out of view)
                    bot y:  win_h-bot_h → win_h     (slides down out of view)
        """
        if not self._is_fullscreen:
            return

        # Avoid redundant animation calls
        if show and self._fs_controls_visible and not self._fs_is_animating:
            self._fs_schedule_autohide(2500)
            return
        if show and self._fs_is_animating and getattr(self, "_fs_anim_direction", "") == "showing":
            self._fs_schedule_autohide(2500)
            return
        if not show and not self._fs_controls_visible and not self._fs_is_animating:
            return
        if not show and self._fs_is_animating and getattr(self, "_fs_anim_direction", "") == "hiding":
            return

        # Cancel any active animation timer before starting/reversing
        if self._fs_anim_timer:
            try:
                self.root.after_cancel(self._fs_anim_timer)
            except Exception:
                pass
            self._fs_anim_timer = None

        top_h = max(42, getattr(self, "_fs_cached_top_h", 42))
        bot_h = max(76, getattr(self, "_fs_cached_bot_h", 76))

        win_h = self.root.winfo_height()
        if win_h <= 10:
            win_h = self.root.winfo_screenheight()

        # 24 steps × 16ms = 384ms (~0.4s) — perfectly aligned to 60Hz display refresh
        total_steps = 24
        step_ms = 16

        def _smooth(t: float) -> float:
            """Hermite smoothstep curve: 3t^2 - 2t^3."""
            t_clamped = max(0.0, min(1.0, t))
            return t_clamped * t_clamped * (3.0 - 2.0 * t_clamped)

        # Check if reversing mid-animation to resume from current position smoothly
        prev_step = getattr(self, "_fs_current_anim_step", None)
        was_animating = self._fs_is_animating

        self._fs_is_animating = True
        self._fs_anim_direction = "showing" if show else "hiding"

        # Ensure wrappers are placed in overlay mode
        if not self.top_wrapper.winfo_manager():
            self.top_wrapper.place(x=0, y=-top_h, relwidth=1.0, height=top_h)
            self.url_bar.place(x=0, y=0, relwidth=1.0, height=top_h)
        if not self.bottom_wrapper.winfo_manager():
            self.bottom_wrapper.place(x=0, y=win_h, relwidth=1.0, height=bot_h)
            self.bottom_inner.place(x=0, y=0, relwidth=1.0, height=bot_h)
        self.top_wrapper.lift()
        self.bottom_wrapper.lift()

        if show:
            # Restore mouse cursor immediately
            if getattr(self, "_fs_cursor_hidden", False):
                self._fs_cursor_hidden = False
                try:
                    self.root.configure(cursor="")
                    self.video_container.configure(cursor="")
                    self.overlay_label.configure(cursor="")
                except Exception:
                    pass

            start_step = prev_step if (was_animating and prev_step is not None) else 1

            def _step_in(step: int):
                if not self._is_fullscreen:
                    return
                self._fs_current_anim_step = step
                t = _smooth(step / float(total_steps))

                # Only the y coordinate changes — zero layout reflow
                top_y = int(-top_h * (1.0 - t))           # -top_h → 0
                bot_y = int(win_h - bot_h * t)            # win_h → win_h - bot_h

                self.top_wrapper.place(y=top_y)
                self.bottom_wrapper.place(y=bot_y)

                if step >= total_steps:
                    self.top_wrapper.place(y=0)
                    self.bottom_wrapper.place(y=win_h - bot_h)
                    self._fs_controls_visible = True
                    self._fs_is_animating = False
                    self._fs_anim_timer = None
                    self._fs_current_anim_step = total_steps
                    self._fs_schedule_autohide(2500)
                else:
                    self._fs_anim_timer = self.root.after(step_ms, lambda: _step_in(step + 1))

            _step_in(start_step)

        else:
            start_step = prev_step if (was_animating and prev_step is not None) else (total_steps - 1)

            def _step_out(step: int):
                if not self._is_fullscreen:
                    return
                self._fs_current_anim_step = step
                if step <= 0:
                    # Fully hidden: park at off-screen coordinates
                    self.top_wrapper.place(y=-top_h)
                    self.bottom_wrapper.place(y=win_h)
                    self._fs_controls_visible = False
                    self._fs_is_animating = False
                    self._fs_anim_timer = None
                    self._fs_current_anim_step = 0
                    # Hide mouse cursor in fullscreen
                    self._fs_cursor_hidden = True
                    try:
                        self.root.configure(cursor="none")
                        self.video_container.configure(cursor="none")
                        self.overlay_label.configure(cursor="none")
                    except Exception:
                        pass
                    return

                t = _smooth(step / float(total_steps))

                # Only y changes — zero layout reflow
                top_y = int(-top_h * (1.0 - t))           # 0 → -top_h
                bot_y = int(win_h - bot_h * t)            # win_h - bot_h → win_h

                self.top_wrapper.place(y=top_y)
                self.bottom_wrapper.place(y=bot_y)

                self._fs_anim_timer = self.root.after(step_ms, lambda: _step_out(step - 1))

            _step_out(start_step)

    # --- On-Screen Display (OSD) Overlay Notification ---

    def show_osd_seek(self, delta_seconds: int) -> None:
        """
        Show on-screen display badge when seeking relative with arrow keys.
        Forward (delta > 0) displays at bottom-right corner.
        Backward (delta < 0) displays at bottom-left corner.
        Displays for 1s with smooth fade-out (similar to YouTube).
        """
        now = time.monotonic()
        direction = 1 if delta_seconds > 0 else -1

        # Accumulate if continuing in the same direction within 1 second
        if direction == self._last_seek_direction and (now - self._last_seek_time) < 1.0:
            self._seek_accum_seconds += delta_seconds
        else:
            self._seek_accum_seconds = delta_seconds
            self._last_seek_direction = direction

        self._last_seek_time = now
        total = self._seek_accum_seconds

        time_info = ""
        progress = None
        dur = getattr(self, "_current_duration_ms", 0) or 0
        if dur > 0:
            cur = getattr(self, "_current_position_ms", 0) or 0
            target_ms = max(0, min(dur, cur + total * 1000))
            cur_str = format_timestamp(target_ms)
            dur_str = format_timestamp(dur)
            time_info = f"  [{cur_str} / {dur_str}]"
            progress = max(0.0, min(1.0, target_ms / dur))

        if total > 0:
            text = f"+{total}s ⏩{time_info}"
            relx = 0.95 if not time_info else 0.5
            rely = 0.88
            anchor = tk.SE if not time_info else tk.S
        else:
            text = f"⏪ {total}s{time_info}"
            relx = 0.05 if not time_info else 0.5
            rely = 0.88
            anchor = tk.SW if not time_info else tk.S

        self._display_osd(text, relx=relx, rely=rely, anchor=anchor, progress=progress)

    def show_osd_action(self, action: str) -> None:
        """
        Show on-screen display badge when Pausing / Resuming playback.
        Displays at bottom center of the video player for 1s with smooth fade-out.
        """
        self._seek_accum_seconds = 0
        self._last_seek_direction = 0

        if action == "pause":
            text = "⏸ Tạm dừng"
        elif action == "play":
            text = "▶ Tiếp tục"
        else:
            text = action

        # Sát góc dưới và ở chính giữa của trình phát
        self._display_osd(text, relx=0.5, rely=0.88, anchor=tk.S)

    def show_osd_volume(self, volume: int, is_muted: bool) -> None:
        """
        Show on-screen display badge when adjusting volume or muting.
        Displays at bottom center of the video player for 1s with smooth fade-out.
        """
        if is_muted:
            text = "🔇 Tắt tiếng"
        else:
            text = f"🔊 {volume}%"
        self._display_osd(text, relx=0.5, rely=0.88, anchor=tk.S)

    def show_osd_speed(self, speed: float) -> None:
        """
        Show on-screen display badge when changing playback speed.
        Displays at bottom center of the video player for 1s with smooth fade-out.
        """
        text = f"⚡ {speed}x"
        self._display_osd(text, relx=0.5, rely=0.88, anchor=tk.S)

    def show_osd_message(self, message: str, relx: float = 0.5, rely: float = 0.88, anchor: str = tk.S) -> None:
        """
        Show on-screen display badge with custom text message (e.g. resume playback, loop status).
        Displays at bottom center of the video player for 1s with smooth fade-out.
        """
        self._display_osd(message, relx=relx, rely=rely, anchor=anchor)

    def _display_osd(
        self,
        text: str,
        relx: float,
        rely: float,
        anchor: str,
        progress: Optional[float] = None,
    ) -> None:
        """Display OSD label at specified position and start 1-second fade out sequence."""
        if self._osd_timer is not None:
            self.root.after_cancel(self._osd_timer)
            self._osd_timer = None

        self.osd_label.configure(
            text=text,
            fg="#e0e0e0",
            bg="#1c1c1c",
        )
        self.osd_label.place(relx=relx, rely=rely, anchor=anchor)
        self.osd_label.lift()

        # In PiP mode, ensure resize grip stays on top
        if self._is_pip:
            self.resize_grip.lift()

        self._osd_fade_step = 0
        self._osd_timer = self.root.after(600, self._fade_osd_step)

        # Show hardware-composited floating OSD overlay over Direct3D VLC surface
        if hasattr(self, "osd_overlay"):
            self.osd_overlay.show(text, relx=relx, rely=rely, anchor=anchor, progress=progress)

    def _fade_osd_step(self) -> None:
        """Execute smooth 4-step fade out of OSD badge over final 400ms."""
        if not hasattr(self, "osd_label"):
            return
        try:
            if not self.osd_label.winfo_exists():
                return
        except Exception:
            return

        FADE_PALETTE = [
            ("#b0b0b0", "#161616"),
            ("#757575", "#101010"),
            ("#404040", "#0a0a0a"),
            ("#202020", "#040404"),
        ]
        if self._osd_fade_step < len(FADE_PALETTE):
            fg, bg = FADE_PALETTE[self._osd_fade_step]
            try:
                self.osd_label.configure(fg=fg, bg=bg)
            except Exception:
                return
            self._osd_fade_step += 1
            try:
                self._osd_timer = self.root.after(100, self._fade_osd_step)
            except Exception:
                self._osd_timer = None
        else:
            try:
                self.osd_label.place_forget()
            except Exception:
                pass
            self._osd_timer = None
            self._seek_accum_seconds = 0
            self._last_seek_direction = 0
            if hasattr(self, "osd_overlay"):
                try:
                    self.osd_overlay.hide()
                except Exception:
                    pass


    # --- Picture-in-Picture (PiP) & Context Menu ---

    def _get_saved_pip_geometry(self, ratio: Optional[str] = None) -> Tuple[int, int, int, int]:
        """
        Retrieve remembered PiP window geometry (w, h, x, y) for the specified or active aspect ratio.
        Validates whether (x, y, w, h) is visible on any currently connected monitor.
        If not saved or off-screen, defaults to bottom-right corner of the monitor where the window currently resides.
        """
        target_ratio = ratio or self._pip_aspect_ratio
        is_vert = (target_ratio == "9:16")
        min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
        min_h = MIN_PIP_VERTICAL_HEIGHT if is_vert else MIN_PIP_HEIGHT

        if is_vert:
            w = self.settings.get("ui", "pip_width_vertical", default=DEFAULT_PIP_VERTICAL_WIDTH)
            h = self.settings.get("ui", "pip_height_vertical", default=DEFAULT_PIP_VERTICAL_HEIGHT)
            x = self.settings.get("ui", "pip_x_vertical", default=None)
            y = self.settings.get("ui", "pip_y_vertical", default=None)
        else:
            w = self.settings.get("ui", "pip_width_horizontal", default=DEFAULT_PIP_WIDTH)
            h = self.settings.get("ui", "pip_height_horizontal", default=DEFAULT_PIP_HEIGHT)
            x = self.settings.get("ui", "pip_x_horizontal", default=None)
            y = self.settings.get("ui", "pip_y_horizontal", default=None)

        try:
            w = int(w)
            h = int(h)
        except (ValueError, TypeError):
            w = DEFAULT_PIP_VERTICAL_WIDTH if is_vert else DEFAULT_PIP_WIDTH
            h = DEFAULT_PIP_VERTICAL_HEIGHT if is_vert else DEFAULT_PIP_HEIGHT

        # Check if saved position is valid and visible on any physical monitor
        valid_pos = False
        if x is not None and y is not None:
            try:
                x = int(x)
                y = int(y)
                if is_rect_visible_on_any_monitor(x, y, w, h):
                    valid_pos = True
            except (ValueError, TypeError):
                valid_pos = False

        if not valid_pos:
            # Fallback to bottom-right of current active monitor where MainWindow resides
            mon_left, mon_top, mon_w, mon_h = get_monitor_work_area_for_window(self.root)
            w = max(min_w, min(mon_w - 40, w))
            h = max(min_h, min(mon_h - 70, h))
            x = max(mon_left, mon_left + mon_w - w - 24)
            y = max(mon_top, mon_top + mon_h - h - 40)
        else:
            # Keep within the work area of the target monitor
            mon_left, mon_top, mon_w, mon_h = get_monitor_work_area_for_rect(x, y, w, h)
            w = max(min_w, min(mon_w - 40, w))
            h = max(min_h, min(mon_h - 70, h))
            x = max(mon_left, min(mon_left + mon_w - w, x))
            y = max(mon_top, min(mon_top + mon_h - h, y))

        return w, h, x, y

    def _get_saved_pip_size(self, ratio: Optional[str] = None) -> Tuple[int, int]:
        """Retrieve remembered PiP window dimensions for the specified or active aspect ratio."""
        w, h, _, _ = self._get_saved_pip_geometry(ratio)
        return w, h

    def _save_current_pip_geometry(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        ratio: Optional[str] = None,
    ) -> None:
        """
        Persist current PiP dimensions (w, h) and position (x, y) into settings.
        Handles multi-monitor coordinates seamlessly across 16:9 and 9:16 orientations.
        """
        if not self._is_pip and (width is None or height is None):
            return

        if width is None or height is None:
            w = self.root.winfo_width()
            h = self.root.winfo_height()
        else:
            w = width
            h = height

        if x is None or y is None:
            pos_x = self.root.winfo_x()
            pos_y = self.root.winfo_y()
        else:
            pos_x = x
            pos_y = y

        try:
            w = int(w)
            h = int(h)
            pos_x = int(pos_x)
            pos_y = int(pos_y)
        except (ValueError, TypeError):
            return

        target_ratio = ratio or self._pip_aspect_ratio
        # If user explicitly resized the window, detect if the orientation changed
        if ratio is None and w > 0 and h > 0:
            if w > h * 1.15 and self._pip_aspect_ratio != "16:9":
                target_ratio = "16:9"
                self._pip_aspect_ratio = "16:9"
                self.settings.set("ui", "pip_aspect_ratio", "16:9")
                self._build_context_menu()
                self._update_menubar_pip_ratio()
            elif h > w * 1.15 and self._pip_aspect_ratio != "9:16":
                target_ratio = "9:16"
                self._pip_aspect_ratio = "9:16"
                self.settings.set("ui", "pip_aspect_ratio", "9:16")
                self._build_context_menu()
                self._update_menubar_pip_ratio()

        is_vert = (target_ratio == "9:16")
        min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
        min_h = MIN_PIP_VERTICAL_HEIGHT if is_vert else MIN_PIP_HEIGHT

        # Validate against the monitor work area where the rect is located
        mon_left, mon_top, mon_w, mon_h = get_monitor_work_area_for_rect(pos_x, pos_y, w, h)
        w = max(min_w, min(mon_w - 40, w))
        h = max(min_h, min(mon_h - 70, h))

        if is_vert:
            self.settings.set("ui", "pip_width_vertical", w)
            self.settings.set("ui", "pip_height_vertical", h)
            self.settings.set("ui", "pip_x_vertical", pos_x)
            self.settings.set("ui", "pip_y_vertical", pos_y)
        else:
            self.settings.set("ui", "pip_width_horizontal", w)
            self.settings.set("ui", "pip_height_horizontal", h)
            self.settings.set("ui", "pip_x_horizontal", pos_x)
            self.settings.set("ui", "pip_y_horizontal", pos_y)
        self.settings.save()

    def _save_current_pip_size(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        ratio: Optional[str] = None,
    ) -> None:
        """Backwards-compatible wrapper persisting PiP dimensions and current position."""
        self._save_current_pip_geometry(width=width, height=height, ratio=ratio)

    def set_pip_aspect_ratio(self, ratio: str, persist: bool = True) -> None:
        """Set PiP aspect ratio ('16:9' or '9:16') and adapt current window if in PiP."""
        if ratio not in ("16:9", "9:16"):
            return

        old_ratio = self._pip_aspect_ratio
        if self._is_pip and old_ratio != ratio:
            old_w = getattr(self, "_last_resized_pip_w", None) or self.root.winfo_width()
            old_h = getattr(self, "_last_resized_pip_h", None) or self.root.winfo_height()
            self._save_current_pip_size(old_w, old_h, ratio=old_ratio)

        self._pip_aspect_ratio = ratio
        if persist:
            self.settings.set("ui", "pip_aspect_ratio", ratio)
            self.settings.save()
        if self.on_pip_ratio_change:
            self.on_pip_ratio_change(ratio)

        if self._is_pip:
            is_vert = (ratio == "9:16")
            min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
            min_h = MIN_PIP_VERTICAL_HEIGHT if is_vert else MIN_PIP_HEIGHT
            self.root.minsize(min_w, min_h)

            new_w, new_h = self._get_saved_pip_size(ratio)
            self._last_resized_pip_w = new_w
            self._last_resized_pip_h = new_h

            cur_x = self.root.winfo_x()
            cur_y = self.root.winfo_y()
            mon_left, mon_top, mon_w, mon_h = get_monitor_work_area_for_rect(cur_x, cur_y, new_w, new_h)
            new_x = max(mon_left, min(mon_left + mon_w - new_w, cur_x))
            new_y = max(mon_top, min(mon_top + mon_h - new_h, cur_y))

            self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")
            self._save_current_pip_geometry(new_w, new_h, new_x, new_y, ratio=ratio)

            # Re-assert mini 3px timeline progress bar and corner grip at bottom edge of PiP
            self.pip_progress.place(relx=0, rely=1.0, relwidth=1.0, height=3, anchor=tk.SW)
            self.pip_progress.lift()
            self.resize_grip.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-2, y=-2)
            self.resize_grip.lift()

        label = "9:16 (Dọc)" if ratio == "9:16" else "16:9 (Ngang)"
        self._display_osd(f"📐 Tỷ lệ PiP: {label}", relx=0.5, rely=0.88, anchor=tk.S)
        self._build_context_menu()
        self._update_menubar_pip_ratio()
        if hasattr(self, "osd_overlay"):
            self.osd_overlay.reposition()
        if hasattr(self, "pip_progress_overlay"):
            pip_bounds = (new_x, new_y, new_w, new_h) if (self._is_pip and 'new_x' in locals()) else None
            self.pip_progress_overlay.reposition(self.root, bounds=pip_bounds)

    def _update_menubar_pip_ratio(self) -> None:
        """Update PiP aspect ratio checkmarks in the Menu Bar."""
        if not hasattr(self, "menu_pip_aspect"):
            return
        try:
            self.menu_pip_aspect.delete(0, tk.END)
            self.menu_pip_aspect.add_command(
                label="16:9 (Ngang - Chuẩn)" + (" ✓" if self._pip_aspect_ratio == "16:9" else ""),
                command=lambda: self.set_pip_aspect_ratio("16:9"),
            )
            self.menu_pip_aspect.add_command(
                label="9:16 (Dọc - Reels / TikTok / Shorts)" + (" ✓" if self._pip_aspect_ratio == "9:16" else ""),
                command=lambda: self.set_pip_aspect_ratio("9:16"),
            )
        except Exception:
            pass

    def toggle_pip_aspect_ratio(self) -> None:
        """Toggle between 16:9 and 9:16 PiP aspect ratio."""
        new_ratio = "9:16" if self._pip_aspect_ratio == "16:9" else "16:9"
        self.set_pip_aspect_ratio(new_ratio)

    def _build_context_menu(self) -> None:
        """Construct context menu for right-click on video."""
        self.context_menu = tk.Menu(self.root, tearoff=0)
        pip_label = "📌 Thoát PiP" if self._is_pip else "📌 Thu nhỏ PiP (Picture-in-Picture)"
        self.context_menu.add_command(
            label=pip_label,
            command=self.toggle_pip,
            accelerator="P",
        )

        # Submenu: PiP Aspect Ratio
        self.pip_aspect_menu = tk.Menu(self.context_menu, tearoff=0)
        self.pip_aspect_menu.add_command(
            label="16:9 (Ngang - Chuẩn)" + (" ✓" if self._pip_aspect_ratio == "16:9" else ""),
            command=lambda: self.set_pip_aspect_ratio("16:9"),
        )
        self.pip_aspect_menu.add_command(
            label="9:16 (Dọc - Reels / TikTok / Shorts)" + (" ✓" if self._pip_aspect_ratio == "9:16" else ""),
            command=lambda: self.set_pip_aspect_ratio("9:16"),
        )
        self.context_menu.add_cascade(
            label="📐 Tỷ lệ khung hình PiP",
            menu=self.pip_aspect_menu,
        )

        # Submenu for PiP Size Presets
        self.pip_size_menu = tk.Menu(self.context_menu, tearoff=0)
        if self._pip_aspect_ratio == "9:16":
            self.pip_size_menu.add_command(
                label="Nhỏ (202 × 360)",
                command=lambda: self.set_pip_size(202, 360),
            )
            self.pip_size_menu.add_command(
                label="Tiêu chuẩn (270 × 480)",
                command=lambda: self.set_pip_size(270, 480),
            )
            self.pip_size_menu.add_command(
                label="Lớn (360 × 640)",
                command=lambda: self.set_pip_size(360, 640),
            )
        else:
            self.pip_size_menu.add_command(
                label="Nhỏ (360 × 202)",
                command=lambda: self.set_pip_size(360, 202),
            )
            self.pip_size_menu.add_command(
                label="Tiêu chuẩn (480 × 270)",
                command=lambda: self.set_pip_size(480, 270),
            )
            self.pip_size_menu.add_command(
                label="Lớn (640 × 360)",
                command=lambda: self.set_pip_size(640, 360),
            )
            self.pip_size_menu.add_command(
                label="Rất lớn (800 × 450)",
                command=lambda: self.set_pip_size(800, 450),
            )
        self.context_menu.add_cascade(
            label="📏 Kích thước PiP",
            menu=self.pip_size_menu,
        )

        def _get_acc(action_id: str, default: str) -> str:
            raw = self.settings.get("hotkeys", action_id, default=default)
            return raw.split(";")[0].split("|")[0].strip() if raw else ""

        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="📁 Mở file video trong máy...",
            command=self._on_open_file_clicked,
            accelerator=_get_acc("open_file", "Ctrl+O"),
        )
        self.context_menu.add_command(
            label="📜 Lịch sử xem video",
            command=self._on_history_clicked,
            accelerator=_get_acc("history", "Ctrl+H"),
        )
        self.context_menu.add_command(
            label="⬇ Tải video về máy",
            command=self._on_download_clicked,
            accelerator=_get_acc("download", "Ctrl+S"),
        )
        self.context_menu.add_command(
            label="💬 Nạp phụ đề...",
            command=self._on_load_subtitle_clicked,
        )

        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="⏯ Phát / Tạm dừng",
            command=self.on_pause_toggle,
            accelerator=_get_acc("play_pause", "Space"),
        )
        short_seek = self.settings.get("ui", "seek_short", default=5)
        self.context_menu.add_command(
            label=f"⏮ Tua lùi {short_seek}s",
            command=lambda: self.on_seek_relative(-short_seek),
            accelerator=_get_acc("seek_backward", "Left"),
        )
        self.context_menu.add_command(
            label=f"⏭ Tua tới {short_seek}s",
            command=lambda: self.on_seek_relative(short_seek),
            accelerator=_get_acc("seek_forward", "Right"),
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="🔇 Bật / Tắt tiếng",
            command=self.on_mute_toggle,
            accelerator=_get_acc("mute", "m"),
        )
        self.context_menu.add_command(
            label="⛶ Toàn màn hình",
            command=self.toggle_fullscreen,
            accelerator=_get_acc("fullscreen", "f"),
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="⚙ Cài đặt",
            command=self.open_settings_dialog,
            accelerator=_get_acc("settings", "Ctrl+,"),
        )

        # Bind right-click on video surface, container, placeholder label, and resize grip
        self.video_container.bind("<Button-3>", self._show_context_menu)
        self.overlay_label.bind("<Button-3>", self._show_context_menu)
        self.main_container.bind("<Button-3>", self._show_context_menu)

    def _show_context_menu(self, event) -> None:
        """Display right-click context menu at cursor coordinates."""
        try:
            self._build_context_menu()
            if hasattr(self, "menu_bar") and hasattr(self.menu_bar, "style_menu"):
                self.menu_bar.style_menu(self.context_menu)
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def toggle_pip(self) -> None:
        """Toggle Picture-in-Picture mode (borderless, compact, floating, draggable, resizable, always-on-top)."""
        if not self._is_pip and self._is_fullscreen:
            self.exit_fullscreen()
        self._is_pip = not self._is_pip
        if self._is_pip:
            # 1. Save current window position and geometry
            self._saved_geometry = self.root.geometry()

            # 2. Allow window to shrink to compact PiP dimensions based on aspect ratio
            is_vert = (self._pip_aspect_ratio == "9:16")
            if is_vert:
                self.root.minsize(MIN_PIP_VERTICAL_WIDTH, MIN_PIP_VERTICAL_HEIGHT)
            else:
                self.root.minsize(MIN_PIP_WIDTH, MIN_PIP_HEIGHT)

            pip_w, pip_h, x, y = self._get_saved_pip_geometry(self._pip_aspect_ratio)
            self._last_resized_pip_w = pip_w
            self._last_resized_pip_h = pip_h

            if hasattr(self, "menu_bar") and self.menu_bar:
                self.menu_bar.pack_forget()

            # 3. Hide toolbars and docked devlog sidebar so only video surface remains visible
            self.top_wrapper.pack_forget()
            self.bottom_wrapper.pack_forget()
            if hasattr(self, "devlog_panel") and self.devlog_panel._is_visible and not self.devlog_panel._is_detached:
                self.devlog_panel.panel_frame.pack_forget()
            if hasattr(self, "queue_panel"):
                self.queue_panel.pack_forget()
            if hasattr(self, "chapter_panel"):
                self.chapter_panel.pack_forget()

            # 4. Remove window title bar & OS frame decorations for true borderless PiP
            self.root.overrideredirect(True)

            # 5. Force Always-on-Top for floating video window
            self.root.attributes("-topmost", True)

            # 6. Apply remembered geometry (w, h, x, y) on appropriate monitor
            self.root.geometry(f"{pip_w}x{pip_h}+{x}+{y}")
            self.btn_pip.configure(text="📌 Thoát PiP")
            self.resize_grip.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-2, y=-2)
            self.resize_grip.lift()

            # 7. Show mini 3px progress bar at bottom of PiP
            self.pip_progress.place(relx=0, rely=1.0, relwidth=1.0, height=3, anchor=tk.SW)
            self.pip_progress.lift()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.show(self.root, bounds=(x, y, pip_w, pip_h))

            self._build_context_menu()
            self.root.focus_force()
        else:
            # 0. Save current PiP dimensions and position before restoring normal window
            w = getattr(self, "_last_resized_pip_w", None) or self.root.winfo_width()
            h = getattr(self, "_last_resized_pip_h", None) or self.root.winfo_height()
            pos_x = self.root.winfo_x()
            pos_y = self.root.winfo_y()
            self._save_current_pip_geometry(w, h, pos_x, pos_y)

            # 1. Hide corner resize grip and cleanly destroy floating overlay for next PiP cycle
            self.resize_grip.place_forget()
            self.pip_progress.place_forget()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.destroy()
            try:
                self.video_container.configure(cursor="")
                self.overlay_label.configure(cursor="")
            except Exception:
                pass

            # 2. Restore standard window title bar and decorations
            self.root.overrideredirect(False)

            # 3. Restore normal minimum size constraints and previous geometry
            self.root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
            if self._saved_geometry:
                self.root.geometry(self._saved_geometry)

            # 4. Restore user's original topmost preference
            is_topmost = self.settings.get("ui", "always_on_top", default=False)
            self.root.attributes("-topmost", is_topmost)

            # 5. Re-apply native dark titlebar if in dark theme
            is_dark = (self.theme.current_theme == "dark")
            set_windows_dark_titlebar(self.root, dark=is_dark)

            if hasattr(self, "menu_bar") and self.menu_bar:
                self.menu_bar.pack(side=tk.TOP, fill=tk.X, before=self.main_container)

            # 6. Restore toolbars in proper layout order
            self.content_area.pack_forget()
            self.top_wrapper.pack(side=tk.TOP, fill=tk.X)
            self.bottom_wrapper.pack(side=tk.BOTTOM, fill=tk.X)
            self.content_area.pack(fill=tk.BOTH, expand=True)
            self._repack_right_panels()
            self.btn_pip.configure(text="📌 PiP")
            self._build_context_menu()
            self.set_status("")
            self.root.focus_set()

    def set_pip_size(self, width: int, height: int) -> None:
        """Set specific PiP window dimensions, entering PiP mode if not already active."""
        if not self._is_pip:
            self.toggle_pip()
        is_vert = (self._pip_aspect_ratio == "9:16")
        min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
        min_h = MIN_PIP_VERTICAL_HEIGHT if is_vert else MIN_PIP_HEIGHT
        self.root.minsize(min_w, min_h)
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()
        mon_left, mon_top, mon_w, mon_h = get_monitor_work_area_for_rect(cur_x, cur_y, width, height)
        new_x = max(mon_left, min(mon_left + mon_w - width, cur_x))
        new_y = max(mon_top, min(mon_top + mon_h - height, cur_y))
        self.root.geometry(f"{width}x{height}+{new_x}+{new_y}")
        self._last_resized_pip_w = width
        self._last_resized_pip_h = height
        self._save_current_pip_geometry(width, height, new_x, new_y)
        self.pip_progress.place(relx=0, rely=1.0, relwidth=1.0, height=3, anchor=tk.SW)
        self.pip_progress.lift()
        self.resize_grip.lift()
        if hasattr(self, "osd_overlay"):
            self.osd_overlay.reposition()
        if hasattr(self, "pip_progress_overlay"):
            self.pip_progress_overlay.reposition(self.root)

    def update_seek_buttons(self) -> None:
        """Refresh rewind/forward button labels when settings change."""
        short_seek = self.settings.get("ui", "seek_short", default=5)
        self.btn_rewind.configure(
            text=f"⏮ {short_seek}s",
            command=lambda: self.on_seek_relative(-short_seek),
        )
        self.btn_forward.configure(
            text=f"⏭ {short_seek}s",
            command=lambda: self.on_seek_relative(short_seek),
        )
        self._build_context_menu()

    # --- Settings Dialog ---

    def open_settings_dialog(self, initial_tab: str = "general") -> None:
        """Open Settings Toplevel dialog (non-modal). If already open, brings to front and switches tab."""
        if hasattr(self, "_settings_dialog") and self._settings_dialog is not None:
            try:
                if self._settings_dialog.top.winfo_exists():
                    self._settings_dialog.top.lift()
                    self._settings_dialog.top.focus_set()
                    if hasattr(self._settings_dialog, "switch_tab"):
                        self._settings_dialog.switch_tab(initial_tab)
                    return
            except Exception:
                self._settings_dialog = None

        def _on_save():
            saved_pip_ratio = self.settings.get("ui", "pip_aspect_ratio", default="16:9")
            if saved_pip_ratio != self._pip_aspect_ratio:
                self.set_pip_aspect_ratio(saved_pip_ratio)
            self.rebind_shortcuts()
            self.apply_theme()
            if self.on_settings_saved:
                self.on_settings_saved()

        def _on_dialog_destroy(event):
            # Chỉ xử lý khi widget bị destroy chính là cửa sổ dialog (không phải widget con)
            try:
                dlg = self._settings_dialog
                if dlg is not None and getattr(event, "widget", None) is dlg.top:
                    self._settings_dialog = None
                    # Kích hoạt thu hồi bộ nhớ ngay sau khi đóng hộp thoại lớn
                    if hasattr(self, "_trim_memory_if_possible"):
                        self.root.after(100, self._trim_memory_if_possible)
            except Exception:
                self._settings_dialog = None

        self._settings_dialog = SettingsDialog(
            self.root,
            self.settings,
            self.theme,
            on_save_callback=_on_save,
            on_update_request=self.on_update_request,
            initial_tab=initial_tab,
            on_dev_mode_unlocked=self.enable_dev_mode,
            on_osd_message=self.show_osd_message,
        )
        self._settings_dialog.top.bind("<Destroy>", _on_dialog_destroy, add="+")

    def destroy(self) -> None:
        """Clean up MainWindow resources, devlog panel, hotkeys, and dialogs."""
        if getattr(self, "_osd_timer", None) is not None:
            try:
                self.root.after_cancel(self._osd_timer)
            except Exception:
                pass
            self._osd_timer = None
        if getattr(self, "_clipboard_toast_timer", None) is not None:
            try:
                self.root.after_cancel(self._clipboard_toast_timer)
            except Exception:
                pass
            self._clipboard_toast_timer = None
        if hasattr(self, "devlog_panel") and self.devlog_panel:
            try:
                self.devlog_panel.destroy()
            except Exception:
                pass
        if hasattr(self, "_settings_dialog") and self._settings_dialog:
            try:
                if hasattr(self._settings_dialog, "top") and self._settings_dialog.top.winfo_exists():
                    self._settings_dialog.top.destroy()
            except Exception:
                pass
            self._settings_dialog = None
        if hasattr(self, "hotkey_mgr") and self.hotkey_mgr:
            try:
                self.hotkey_mgr.unbind_all()
            except Exception:
                pass
        if hasattr(self, "main_container") and self.main_container:
            try:
                if self.main_container.winfo_exists():
                    self.main_container.destroy()
            except Exception:
                pass


    def apply_theme(self) -> None:
        """Dynamically update themed widgets on theme change."""
        palette = self.theme.PALETTES.get(self.theme.current_theme, self.theme.PALETTES["dark"])
        if hasattr(self, "menu_bar") and self.menu_bar and hasattr(self.menu_bar, "apply_theme"):
            self.menu_bar.apply_theme(palette)
            if hasattr(self, "_dl_menu") and self._dl_menu:
                self.menu_bar.style_menu(self._dl_menu)
            if hasattr(self, "context_menu") and self.context_menu:
                self.menu_bar.style_menu(self.context_menu)
