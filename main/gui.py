"""
GUI module for FB Video Watcher.
Implements modern Tkinter/TTK user interface, keyboard shortcuts, video surface,
SeekBarController (preventing drag fighting), and Settings Panel.
Strictly adheres to specs.md §4.3, §7.4, §7.7, and Agent.md §4 & §5.
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
from main.platform_utils import apply_window_icon, set_windows_dark_titlebar, hook_drop_files
from main.devlog import DevLogPanel
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


class SeekBarController:
    """Manages seek bar synchronization and handles user drag conflict (§7.7)."""

    def __init__(
        self,
        scale_widget: ttk.Scale,
        on_seek: Callable[[int], None],
        on_preview: Optional[Callable[[int], None]] = None,
    ):
        self.scale = scale_widget
        self.on_seek = on_seek
        self.on_preview = on_preview
        self._is_user_dragging = False
        self._is_seeking = False
        self._duration_ms = 0
        self._last_scale_max = 0

        self.scale.bind("<ButtonPress-1>", self._on_drag_start)
        self.scale.bind("<B1-Motion>", self._on_drag_motion)
        self.scale.bind("<ButtonRelease-1>", self._on_drag_end)

    @property
    def is_user_interacting(self) -> bool:
        """Return True if user is actively dragging or seek is pending."""
        return self._is_user_dragging or self._is_seeking

    def _get_value_from_x(self, x: int) -> float:
        """Calculate target millisecond value from horizontal mouse coordinate."""
        try:
            width = max(1, self.scale.winfo_width())
            fraction = max(0.0, min(1.0, x / float(width)))
            from_ = float(self.scale.cget("from"))
            to_ = float(self.scale.cget("to"))
            if to_ <= from_:
                return from_
            return from_ + fraction * (to_ - from_)
        except Exception:
            return self.scale.get()

    def _on_drag_start(self, event) -> str:
        self._is_user_dragging = True
        self._is_seeking = False
        val = self._get_value_from_x(event.x)
        self.scale.set(val)
        if self.on_preview:
            self.on_preview(int(val))
        return "break"

    def _on_drag_motion(self, event) -> str:
        if self._is_user_dragging:
            val = self._get_value_from_x(event.x)
            self.scale.set(val)
            if self.on_preview:
                self.on_preview(int(val))
            return "break"
        return ""

    def _on_drag_end(self, event) -> str:
        if self._is_user_dragging:
            val = self._get_value_from_x(event.x)
            self.scale.set(val)
            self._is_user_dragging = False
            target_ms = int(val)
            self._is_seeking = True
            if self.on_preview:
                self.on_preview(target_ms)
            self.on_seek(target_ms)
            # Clear seeking debounce flag after 350ms
            self.scale.after(350, self._confirm_seek)
            return "break"
        return ""

    def cancel_drag(self, current_ms: int = 0) -> None:
        """Cancel active dragging without seeking."""
        self._is_user_dragging = False
        self._is_seeking = False
        self.scale.set(current_ms)

    def _confirm_seek(self) -> None:
        self._is_seeking = False

    def update_position(self, current_ms: int, duration_ms: int) -> None:
        """Update seek bar position unless user is actively dragging."""
        self._duration_ms = duration_ms
        if not self._is_user_dragging and not self._is_seeking:
            if duration_ms > 0:
                if self._last_scale_max != duration_ms:
                    self.scale.configure(to=duration_ms)
                    self._last_scale_max = duration_ms
                self.scale.set(current_ms)


class OSDOverlay:
    """
    Hardware-composited floating on-screen display (OSD) overlay badge.
    Renders as a borderless, translucent Toplevel window on top of the VLC
    video surface across Normal, Fullscreen, and PiP modes.
    Applies Win32 WS_EX_NOACTIVATE strictly to the OS top-level window so focus is never stolen,
    and forwards mouse events directly to the underlying video container.
    """

    def __init__(self, parent_root: tk.Tk, target_widget: tk.Widget):
        self.parent = parent_root
        self.target = target_widget
        self.top: Optional[tk.Toplevel] = None
        self.label: Optional[tk.Label] = None
        self._fade_timer: Optional[str] = None
        self._fade_step: int = 0
        self._last_relx: float = 0.5
        self._last_rely: float = 0.88
        self._last_anchor: str = tk.S
        self._is_visible: bool = False

    def _ensure_window(self) -> None:
        if self.top is not None and self.top.winfo_exists():
            return

        self.top = tk.Toplevel(self.parent)
        self.top.overrideredirect(True)
        try:
            self.top.attributes("-topmost", True)
        except Exception:
            pass
        self.top.configure(bg="#202124")
        self.top.withdraw()

        # Dark pill container with crisp white text
        self.label = tk.Label(
            self.top,
            text="",
            font=("Segoe UI", 12, "bold"),
            bg="#202124",
            fg="#ffffff",
            padx=18,
            pady=8,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.label.pack(fill=tk.BOTH, expand=True)

        # Mini sleek progress bar at bottom edge of OSD badge
        self.progress_frame = tk.Frame(self.top, bg="#333333", height=4)
        self.progress_bar = tk.Frame(self.progress_frame, bg="#0078d4", height=4)
        self._has_progress = False

        # Forward mouse clicks on OSD to target video container so clicks/drags are seamless
        def _forward_mouse(event, event_name):
            try:
                self.parent.focus_force()
                self.target.event_generate(event_name, x=event.x, y=event.y)
            except Exception:
                pass

        for w in (self.top, self.label, self.progress_frame, self.progress_bar):
            w.bind("<ButtonPress-1>", lambda e: _forward_mouse(e, "<ButtonPress-1>"))
            w.bind("<B1-Motion>", lambda e: _forward_mouse(e, "<B1-Motion>"))
            w.bind("<ButtonRelease-1>", lambda e: _forward_mouse(e, "<ButtonRelease-1>"))
            w.bind("<Double-Button-1>", lambda e: _forward_mouse(e, "<Double-Button-1>"))

    def _apply_win32_styles(self) -> None:
        """Apply WS_EX_NOACTIVATE strictly to the OS top-level window so focus is never lost."""
        if sys.platform != "win32" or not self.top or not self.top.winfo_exists():
            return
        try:
            import win32gui
            import win32con
            # Apply WS_EX_NOACTIVATE strictly to the top-level OS window (TkTopLevel)
            top_hwnd = win32gui.GetParent(self.top.winfo_id())
            if not top_hwnd:
                top_hwnd = self.top.winfo_id()
            GWL_EXSTYLE = win32con.GWL_EXSTYLE
            style = win32gui.GetWindowLong(top_hwnd, GWL_EXSTYLE)
            win32gui.SetWindowLong(
                top_hwnd,
                GWL_EXSTYLE,
                style | win32con.WS_EX_NOACTIVATE,
            )
        except Exception:
            pass

    def _calculate_pos(self, relx: float, rely: float, anchor: str) -> Tuple[int, int, int, int]:
        try:
            self.target.update_idletasks()
            self.label.update_idletasks()

            tw_x = self.target.winfo_rootx()
            tw_y = self.target.winfo_rooty()
            tw_w = max(1, self.target.winfo_width())
            tw_h = max(1, self.target.winfo_height())

            is_compact = (tw_w < 320)
            if is_compact:
                self.label.configure(font=("Segoe UI", 9, "bold"), padx=8, pady=5)
            else:
                self.label.configure(font=("Segoe UI", 12, "bold"), padx=18, pady=8)
            self.label.update_idletasks()

            pad = 8 if is_compact else 12
            max_avail_w = max(40, tw_w - (2 * pad))
            ow_w = max(50, min(max_avail_w, self.label.winfo_reqwidth()))
            extra_h = 4 if getattr(self, "_has_progress", False) else 0
            ow_h = max(20, self.label.winfo_reqheight() + extra_h)

            x = tw_x + int(relx * tw_w)
            y = tw_y + int(rely * tw_h)

            anchor_str = str(anchor).lower()
            if anchor_str in ("se", "southeast"):
                x -= ow_w
                y -= ow_h
            elif anchor_str in ("sw", "southwest"):
                y -= ow_h
            elif anchor_str in ("s", "south", "center"):
                x -= (ow_w // 2)
                y -= ow_h
            elif anchor_str in ("e", "east"):
                x -= ow_w
                y -= (ow_h // 2)
            elif anchor_str in ("w", "west"):
                y -= (ow_h // 2)

            # Keep inside visible target bounds
            x = max(tw_x + pad, min(tw_x + tw_w - ow_w - pad, x))
            y = max(tw_y + pad, min(tw_y + tw_h - ow_h - pad, y))
            return max(0, x), max(0, y), ow_w, ow_h
        except Exception:
            return 100, 100, 120, 40

    def show(
        self,
        text: str,
        relx: float = 0.5,
        rely: float = 0.88,
        anchor: str = tk.S,
        progress: Optional[float] = None,
    ) -> None:
        """Display floating OSD overlay badge with text at anchor location for 1.0s."""
        if self._fade_timer is not None:
            try:
                self.parent.after_cancel(self._fade_timer)
            except Exception:
                pass
            self._fade_timer = None

        self._ensure_window()
        if not self.top or not self.label:
            return

        self._last_relx = relx
        self._last_rely = rely
        self._last_anchor = anchor

        if progress is not None and 0.0 <= progress <= 1.0:
            self._has_progress = True
            # Bottom widgets in Tkinter pack must be packed before expand=True widget
            self.label.pack_forget()
            self.progress_frame.pack(fill=tk.X, side=tk.BOTTOM)
            self.progress_bar.place(relx=0, rely=0, relwidth=progress, relheight=1.0)
            self.label.pack(fill=tk.BOTH, expand=True)
        else:
            self._has_progress = False
            self.progress_frame.pack_forget()
            self.label.pack(fill=tk.BOTH, expand=True)

        self.label.configure(text=text, bg="#202124", fg="#ffffff")
        x, y, ow_w, ow_h = self._calculate_pos(relx, rely, anchor)

        try:
            self.top.geometry(f"{ow_w}x{ow_h}+{x}+{y}")
            self.top.attributes("-alpha", 0.95)
            self.top.deiconify()
            self.top.lift(self.parent)
            self._apply_win32_styles()
            self._is_visible = True
        except Exception:
            pass

        self._fade_step = 0
        try:
            self._fade_timer = self.parent.after(600, self._step_fade)
        except Exception:
            pass

    def _step_fade(self) -> None:
        """Smooth 400ms fade-out over 4 steps."""
        ALPHA_STEPS = [0.75, 0.50, 0.25, 0.0]
        if self._fade_step < len(ALPHA_STEPS) and self.top and self.top.winfo_exists():
            alpha = ALPHA_STEPS[self._fade_step]
            self._fade_step += 1
            try:
                self.top.attributes("-alpha", alpha)
            except Exception:
                pass
            try:
                self._fade_timer = self.parent.after(100, self._step_fade)
            except Exception:
                self.hide()
        else:
            self.hide()

    def hide(self) -> None:
        """Hide floating OSD badge."""
        if self._fade_timer is not None:
            try:
                self.parent.after_cancel(self._fade_timer)
            except Exception:
                pass
            self._fade_timer = None
        self._is_visible = False
        if self.top and self.top.winfo_exists():
            try:
                self.top.withdraw()
            except Exception:
                pass

    def reposition(self) -> None:
        """Keep OSD aligned to target widget when moving or resizing parent/PiP window."""
        if self._is_visible and self.top and self.top.winfo_exists():
            x, y, ow_w, ow_h = self._calculate_pos(self._last_relx, self._last_rely, self._last_anchor)
            try:
                self.top.geometry(f"{ow_w}x{ow_h}+{x}+{y}")
            except Exception:
                pass

    def destroy(self) -> None:
        """Cleanly destroy the floating Toplevel."""
        self.hide()
        if self.top and self.top.winfo_exists():
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top = None
        self.label = None


class PiPProgressOverlay:
    """
    Hardware-composited floating progress bar for Picture-in-Picture (PiP) mode.
    Renders as a borderless, always-on-top Toplevel window directly on top of the VLC
    DirectX / Direct3D hardware surface at the bottom edge of the PiP window.
    Applies Win32 WS_EX_NOACTIVATE | WS_EX_TRANSPARENT so mouse clicks fall completely
    through to VLC / PiP window without taking focus or interfering with window drags.
    """

    def __init__(self, parent_root: tk.Tk, height: int = 3):
        self.parent = parent_root
        self.bar_height = height
        self.top: Optional[tk.Toplevel] = None
        self.bg_frame: Optional[tk.Frame] = None
        self.fill_frame: Optional[tk.Frame] = None
        self._fraction: float = 0.0
        self._is_visible: bool = False
        self._styles_applied: bool = False

    def _ensure_window(self) -> None:
        if self.top is not None and self.top.winfo_exists():
            return

        self.top = tk.Toplevel(self.parent)
        self.top.overrideredirect(True)
        try:
            self.top.attributes("-topmost", True)
        except Exception:
            pass
        self.top.configure(bg="#1a1a1a")
        self.top.withdraw()

        # Dark background container
        self.bg_frame = tk.Frame(self.top, bg="#1a1a1a", height=self.bar_height)
        self.bg_frame.pack(fill=tk.BOTH, expand=True)

        # Red fill bar (#ff0033)
        self.fill_frame = tk.Frame(self.bg_frame, bg="#ff0033", height=self.bar_height)
        self.fill_frame.place(relx=0, rely=0, relwidth=self._fraction, relheight=1.0)
        self._styles_applied = False

    def _apply_win32_styles(self) -> None:
        """Apply WS_EX_NOACTIVATE and WS_EX_TRANSPARENT so clicks fall through to VLC."""
        if self._styles_applied:
            return
        if sys.platform != "win32" or not self.top or not self.top.winfo_exists():
            return
        try:
            import win32gui
            import win32con
            top_hwnd = win32gui.GetParent(self.top.winfo_id())
            if not top_hwnd:
                top_hwnd = self.top.winfo_id()
            GWL_EXSTYLE = win32con.GWL_EXSTYLE
            style = win32gui.GetWindowLong(top_hwnd, GWL_EXSTYLE)
            win32gui.SetWindowLong(
                top_hwnd,
                GWL_EXSTYLE,
                style | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT,
            )
            self._styles_applied = True
        except Exception:
            pass

    def update(self, fraction: float, target_window: tk.Tk) -> None:
        """Update progress bar fill width and reposition to bottom of PiP window."""
        self._fraction = max(0.0, min(1.0, fraction))
        self._ensure_window()
        if not self.top or not self.top.winfo_exists():
            return

        if self.fill_frame:
            self.fill_frame.place(relx=0, rely=0, relwidth=self._fraction, relheight=1.0)

        if not self._is_visible:
            self.show(target_window)
        else:
            self.reposition(target_window)

    def show(self, target_window: Optional[tk.Tk] = None) -> None:
        """Show floating progress bar on top of VLC."""
        self._ensure_window()
        if not self.top or not self.top.winfo_exists():
            return
        self._is_visible = True
        target = target_window or self.parent
        self.reposition(target)
        try:
            self.top.deiconify()
            self.top.lift(self.parent)
            self._apply_win32_styles()
        except Exception:
            pass

    def hide(self) -> None:
        """Hide floating progress bar."""
        self._is_visible = False
        if self.top and self.top.winfo_exists():
            try:
                self.top.withdraw()
            except Exception:
                pass

    def reposition(self, target_window: Optional[tk.Tk] = None) -> None:
        """Keep the progress bar attached to the bottom edge of the PiP window."""
        if not self._is_visible or not self.top or not self.top.winfo_exists():
            return
        target = target_window or self.parent
        try:
            wx = target.winfo_rootx()
            wy = target.winfo_rooty()
            ww = max(1, target.winfo_width())
            wh = max(1, target.winfo_height())
            y = wy + wh - self.bar_height
            geo = f"{ww}x{self.bar_height}+{wx}+{y}"
            if getattr(self, "_last_geo", None) != geo:
                self._last_geo = geo
                self.top.geometry(geo)
        except Exception:
            pass

    def destroy(self) -> None:
        """Cleanly destroy floating progress bar on app exit."""
        self.hide()
        if self.top and self.top.winfo_exists():
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top = None
        self.bg_frame = None
        self.fill_frame = None


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
        on_chapter_seek: Optional[Callable[[int], None]] = None,
        on_privacy_toggle: Optional[Callable[[], None]] = None,
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
        self.on_chapter_seek = on_chapter_seek
        self.on_privacy_toggle = on_privacy_toggle
        self._chapters: list[dict] = []
        self._chapters_visible = False
        self._queue_visible = False
        self._queue_rows: list[dict] = []
        self._bound_hotkey_sequences: set[str] = set()

        # Window configuration
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
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

    def _build_ui(self) -> None:
        """Construct the UI widgets from top to bottom."""
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

    def _build_url_bar(self) -> None:
        """Construct Top URL entry and action buttons."""
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

        self.btn_chapters = ttk.Button(
            bar,
            text="☰ Mục lục",
            state=tk.DISABLED,
            command=self.toggle_chapters,
        )
        self.btn_chapters.pack(side=tk.LEFT, padx=(0, 4))

        self.privacy_badge = ttk.Label(bar, text="🔒 PRIVATE SESSION")
        self.btn_privacy = ttk.Button(bar, text="🔒 Riêng tư", command=self._on_privacy_toggle)
        self.btn_privacy.pack(side=tk.RIGHT, padx=(4, 0))

        self.btn_paste_play = ttk.Button(
            bar,
            text="📋 Dán & Phát",
            command=self._on_paste_and_play,
        )
        self.btn_paste_play.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_open_file = ttk.Button(
            bar,
            text="📁 Mở file",
            command=self._on_open_file_clicked,
        )
        self.btn_open_file.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_history = ttk.Button(
            bar,
            text="📜 Lịch sử",
            command=self._on_history_clicked,
        )
        self.btn_history.pack(side=tk.LEFT, padx=(0, 4))

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

        self.btn_settings = ttk.Button(
            bar,
            text="⚙ Cài đặt",
            command=self.open_settings_dialog,
        )
        self.btn_settings.pack(side=tk.RIGHT)

    def _build_video_surface(self) -> None:
        """Construct Central Content Area: Video Render Surface on Left + Devlog Sidebar on Right."""
        self.content_area = ttk.Frame(self.main_container)
        self.content_area.pack(fill=tk.BOTH, expand=True)

        self.video_container = tk.Frame(self.content_area, bg="#000000")
        self.video_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Queue is constructed once but unmapped by default.  This keeps the
        # video surface full-size and avoids creating thumbnails/widgets per
        # playlist entry.
        self.queue_panel = ttk.Frame(self.content_area, width=280)
        self.queue_panel.pack_propagate(False)
        queue_header = ttk.Frame(self.queue_panel)
        queue_header.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(queue_header, text="Hàng đợi phát").pack(side=tk.LEFT)
        ttk.Button(queue_header, text="×", width=3, command=self.toggle_queue).pack(side=tk.RIGHT)
        self.queue_list = tk.Listbox(self.queue_panel, height=10, activestyle="none", exportselection=False)
        self.queue_list.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))
        self.queue_list.bind("<Double-Button-1>", self._on_queue_double_click)

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

        # Devlog Checkbox on the right
        self.devlog_var = tk.BooleanVar(value=False)
        self.chk_devlog = ttk.Checkbutton(
            bar,
            text="Devlog",
            variable=self.devlog_var,
            command=self._on_toggle_devlog,
        )
        self.chk_devlog.pack(side=tk.RIGHT, padx=(8, 2))

        # Status / Title label
        self.lbl_status = ttk.Label(
            bar,
            text="",
            font=("Segoe UI", 9, "italic"),
        )
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _on_toggle_devlog(self) -> None:
        """Handle Devlog checkbox toggle."""
        if self.devlog_var.get():
            self.devlog_panel.show()
        else:
            self.devlog_panel.hide()

    def _on_devlog_visibility_changed(self, is_visible: bool) -> None:
        """Sync Devlog checkbox when the detached window is closed."""
        self.devlog_var.set(is_visible)

    def toggle_devlog(self) -> None:
        """Toggle Devlog via keyboard shortcut."""
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

            # Edge and Corner Snapping (PIP_SNAP_MARGIN = 24px)
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            snap = PIP_SNAP_MARGIN

            if abs(new_x) < snap:
                new_x = 0
            elif abs((new_x + cur_w) - screen_w) < snap:
                new_x = screen_w - cur_w

            if abs(new_y) < snap:
                new_y = 0
            elif abs((new_y + cur_h) - (screen_h - 40)) < snap:
                new_y = screen_h - 40 - cur_h
            elif abs((new_y + cur_h) - screen_h) < snap:
                new_y = screen_h - cur_h

            self.root.geometry(f"+{new_x}+{new_y}")
            if hasattr(self, "osd_overlay"):
                self.osd_overlay.reposition()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.reposition(self.root)

        elif self._drag_mode.startswith("resize"):
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            max_w = screen_w - 40
            max_h = screen_h - 40

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
        - In PiP mode: solely reset drag/resize state. Left-clicking NEVER toggles pause in PiP mode
          so the user can click, focus, and drag without accidental pauses.
        - In normal window mode: debounce single click to toggle play/pause.
        """
        if self._is_pip:
            was_resizing = self._drag_mode.startswith("resize")
            self._drag_mode = "none"
            self._has_dragged = False
            self.pip_progress.place(relx=0, rely=1.0, relwidth=1.0, height=3, anchor=tk.SW)
            self.pip_progress.lift()
            self.resize_grip.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-2, y=-2)
            self.resize_grip.lift()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.reposition(self.root)
            if was_resizing:
                w = getattr(self, "_last_resized_pip_w", None) or self.root.winfo_width()
                h = getattr(self, "_last_resized_pip_h", None) or self.root.winfo_height()
                self._save_current_pip_size(w, h)
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
        self.root.focus_set()
        self.on_play_request(url)

    def _on_paste_and_play(self) -> None:
        try:
            clipboard = self.root.clipboard_get().strip()
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
        self.clipboard_toast.place_forget()

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

    def toggle_queue(self) -> None:
        """Show/hide the bounded queue panel without touching the player."""
        if self._queue_visible:
            self.queue_panel.pack_forget()
            self._queue_visible = False
        else:
            self.queue_panel.pack(side=tk.RIGHT, fill=tk.Y)
            self._queue_visible = True

    def refresh_queue(self, rows: list[dict]) -> None:
        """Render compact queue snapshots; no thumbnail/network work occurs here."""
        self._queue_rows = list(rows)
        if not hasattr(self, "queue_list"):
            return
        self.queue_list.delete(0, tk.END)
        for index, row in enumerate(self._queue_rows, 1):
            title = str(row.get("title") or row.get("source_url") or "Video")
            status = str(row.get("status") or "pending")
            self.queue_list.insert(tk.END, f"{index}. [{status}] {title[:100]}")

    def _on_queue_double_click(self, _event=None) -> None:
        selection = self.queue_list.curselection()
        if not selection or not self.on_play_request:
            return
        index = selection[0]
        if 0 <= index < len(self._queue_rows):
            source_url = self._queue_rows[index].get("source_url")
            if source_url:
                self.on_play_request(str(source_url))

    def toggle_chapters(self) -> None:
        if not self._chapters:
            return
        if self._chapters_visible:
            self.chapter_panel.pack_forget()
            self._chapters_visible = False
        else:
            self.chapter_panel.pack(side=tk.RIGHT, fill=tk.Y)
            self._chapters_visible = True

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

        # Hide docked devlog panel if open so video surface occupies full width
        if hasattr(self, "devlog_panel") and self.devlog_panel._is_visible and not self.devlog_panel._is_detached:
            self.devlog_panel.panel_frame.pack_forget()

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

        # Restore docked devlog panel if it was open
        if hasattr(self, "devlog_panel") and self.devlog_var.get() and not self.devlog_panel._is_detached:
            self.devlog_panel.show()

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
        FADE_PALETTE = [
            ("#b0b0b0", "#161616"),
            ("#757575", "#101010"),
            ("#404040", "#0a0a0a"),
            ("#202020", "#040404"),
        ]
        if self._osd_fade_step < len(FADE_PALETTE):
            fg, bg = FADE_PALETTE[self._osd_fade_step]
            self.osd_label.configure(fg=fg, bg=bg)
            self._osd_fade_step += 1
            self._osd_timer = self.root.after(100, self._fade_osd_step)
        else:
            self.osd_label.place_forget()
            self._osd_timer = None
            self._seek_accum_seconds = 0
            self._last_seek_direction = 0
            if hasattr(self, "osd_overlay"):
                self.osd_overlay.hide()

    # --- Picture-in-Picture (PiP) & Context Menu ---

    def _get_saved_pip_size(self, ratio: Optional[str] = None) -> Tuple[int, int]:
        """Retrieve remembered PiP window dimensions for the specified or active aspect ratio."""
        target_ratio = ratio or self._pip_aspect_ratio
        is_vert = (target_ratio == "9:16")
        min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
        min_h = MIN_PIP_VERTICAL_HEIGHT if is_vert else MIN_PIP_HEIGHT

        if is_vert:
            w = self.settings.get("ui", "pip_width_vertical", default=DEFAULT_PIP_VERTICAL_WIDTH)
            h = self.settings.get("ui", "pip_height_vertical", default=DEFAULT_PIP_VERTICAL_HEIGHT)
        else:
            w = self.settings.get("ui", "pip_width_horizontal", default=DEFAULT_PIP_WIDTH)
            h = self.settings.get("ui", "pip_height_horizontal", default=DEFAULT_PIP_HEIGHT)

        try:
            w = int(w)
            h = int(h)
        except (ValueError, TypeError):
            w = DEFAULT_PIP_VERTICAL_WIDTH if is_vert else DEFAULT_PIP_WIDTH
            h = DEFAULT_PIP_VERTICAL_HEIGHT if is_vert else DEFAULT_PIP_HEIGHT

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w = max(min_w, min(screen_w - 40, w))
        h = max(min_h, min(screen_h - 70, h))
        return w, h

    def _save_current_pip_size(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        ratio: Optional[str] = None,
    ) -> None:
        """Persist current PiP dimensions for the specified or active aspect ratio into settings."""
        target_ratio = ratio or self._pip_aspect_ratio
        is_vert = (target_ratio == "9:16")

        if width is None or height is None:
            if not self._is_pip:
                return
            w = self.root.winfo_width()
            h = self.root.winfo_height()
        else:
            w = width
            h = height

        try:
            w = int(w)
            h = int(h)
        except (ValueError, TypeError):
            return

        min_w = MIN_PIP_VERTICAL_WIDTH if is_vert else MIN_PIP_WIDTH
        min_h = MIN_PIP_VERTICAL_HEIGHT if is_vert else MIN_PIP_HEIGHT

        # Orientation guard: prevent saving horizontal window dimensions to vertical PiP or vice versa
        if is_vert and w > h * 1.2:
            return
        if not is_vert and h > w * 1.2:
            return

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w = max(min_w, min(screen_w - 40, w))
        h = max(min_h, min(screen_h - 70, h))

        if is_vert:
            self.settings.set("ui", "pip_width_vertical", w)
            self.settings.set("ui", "pip_height_vertical", h)
        else:
            self.settings.set("ui", "pip_width_horizontal", w)
            self.settings.set("ui", "pip_height_horizontal", h)
        self.settings.save()

    def set_pip_aspect_ratio(self, ratio: str) -> None:
        """Set PiP aspect ratio ('16:9' or '9:16') and adapt current window if in PiP."""
        if ratio not in ("16:9", "9:16"):
            return

        old_ratio = self._pip_aspect_ratio
        if self._is_pip and old_ratio != ratio:
            old_w = getattr(self, "_last_resized_pip_w", None) or self.root.winfo_width()
            old_h = getattr(self, "_last_resized_pip_h", None) or self.root.winfo_height()
            self._save_current_pip_size(old_w, old_h, ratio=old_ratio)

        self._pip_aspect_ratio = ratio
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

            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            cur_x = self.root.winfo_x()
            cur_y = self.root.winfo_y()

            new_x = max(10, min(screen_w - new_w - 30, cur_x))
            new_y = max(10, min(screen_h - new_h - 60, cur_y))

            self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")

            # Re-assert mini 3px timeline progress bar and corner grip at bottom edge of PiP
            self.pip_progress.place(relx=0, rely=1.0, relwidth=1.0, height=3, anchor=tk.SW)
            self.pip_progress.lift()
            self.resize_grip.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-2, y=-2)
            self.resize_grip.lift()

        label = "9:16 (Dọc)" if ratio == "9:16" else "16:9 (Ngang)"
        self._display_osd(f"📐 Tỷ lệ PiP: {label}", relx=0.5, rely=0.88, anchor=tk.S)
        self._build_context_menu()
        if hasattr(self, "osd_overlay"):
            self.osd_overlay.reposition()
        if hasattr(self, "pip_progress_overlay"):
            self.pip_progress_overlay.reposition(self.root)

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

            pip_w, pip_h = self._get_saved_pip_size(self._pip_aspect_ratio)
            self._last_resized_pip_w = pip_w
            self._last_resized_pip_h = pip_h

            # 3. Hide toolbars and docked devlog sidebar so only video surface remains visible
            self.top_wrapper.pack_forget()
            self.bottom_wrapper.pack_forget()
            if hasattr(self, "devlog_panel") and self.devlog_panel._is_visible and not self.devlog_panel._is_detached:
                self.devlog_panel.panel_frame.pack_forget()

            # 4. Remove window title bar & OS frame decorations for true borderless PiP
            self.root.overrideredirect(True)

            # 5. Force Always-on-Top for floating video window
            self.root.attributes("-topmost", True)

            # 6. Dock at bottom-right corner of screen
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            x = max(0, screen_w - pip_w - 40)
            y = max(0, screen_h - pip_h - 70)
            self.root.geometry(f"{pip_w}x{pip_h}+{x}+{y}")
            self.btn_pip.configure(text="📌 Thoát PiP")
            self.resize_grip.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-2, y=-2)
            self.resize_grip.lift()

            # 7. Show mini 3px progress bar at bottom of PiP
            self.pip_progress.place(relx=0, rely=1.0, relwidth=1.0, height=3, anchor=tk.SW)
            self.pip_progress.lift()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.show(self.root)

            self._build_context_menu()
            self.root.focus_force()
        else:
            # 0. Save current PiP dimensions before restoring normal window
            w = getattr(self, "_last_resized_pip_w", None) or self.root.winfo_width()
            h = getattr(self, "_last_resized_pip_h", None) or self.root.winfo_height()
            self._save_current_pip_size(w, h)

            # 1. Hide corner resize grip and mini progress bar
            self.resize_grip.place_forget()
            self.pip_progress.place_forget()
            if hasattr(self, "pip_progress_overlay"):
                self.pip_progress_overlay.hide()
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

            # 6. Restore toolbars in proper layout order
            self.content_area.pack_forget()
            self.top_wrapper.pack(side=tk.TOP, fill=tk.X)
            self.bottom_wrapper.pack(side=tk.BOTTOM, fill=tk.X)
            self.content_area.pack(fill=tk.BOTH, expand=True)
            if hasattr(self, "devlog_panel") and self.devlog_var.get() and not self.devlog_panel._is_detached:
                self.devlog_panel.show()
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
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()
        new_x = max(10, min(screen_w - width - 30, cur_x))
        new_y = max(10, min(screen_h - height - 60, cur_y))
        self.root.geometry(f"{width}x{height}+{new_x}+{new_y}")
        self._last_resized_pip_w = width
        self._last_resized_pip_h = height
        self._save_current_pip_size(width, height)
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
            self.rebind_shortcuts()
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
        )
        self._settings_dialog.top.bind("<Destroy>", _on_dialog_destroy, add="+")


class SettingsDialog:
    """Toplevel modal for editing settings and viewing detected hardware info with Fluent aesthetic."""

    def __init__(
        self,
        parent: tk.Tk,
        settings_mgr: SettingsManager,
        theme_mgr: ThemeManager,
        on_save_callback: Optional[Callable[[], None]] = None,
        on_update_request: Optional[Callable[[Any], None]] = None,
        initial_tab: str = "general",
    ):
        self.top = tk.Toplevel(parent)
        self.top.withdraw()  # Crucial: hide until fully built so user never sees drawing steps
        # Unit tests use a withdrawn root. Keep this dialog hidden in that mode
        # so running the test suite never opens real windows on the user's desk.
        try:
            self._parent_withdrawn = parent.winfo_toplevel().state() == "withdrawn"
        except Exception:
            self._parent_withdrawn = False
        self.top.title("Cài đặt ứng dụng")
        self.settings = settings_mgr
        self.theme = theme_mgr
        self.on_save_callback = on_save_callback
        self.on_update_request = on_update_request
        self.initial_tab = initial_tab

        # Initialize hotkey StringVars from settings
        self.hotkey_vars: Dict[str, tk.StringVar] = {}
        saved_hotkeys = self.settings.get("hotkeys", default={})
        for aid, _, _, default_val in HOTKEY_DEFINITIONS:
            current_val = saved_hotkeys.get(aid, default_val)
            self.hotkey_vars[aid] = tk.StringVar(value=str(current_val))

        # Initialize Subtitle variables from settings
        sub_cfg = self.settings.get("subtitle", default={})
        if not isinstance(sub_cfg, dict):
            sub_cfg = {}
        self.sub_file_var = tk.StringVar(value=str(sub_cfg.get("file", "")))
        self.sub_font_var = tk.StringVar(value=str(sub_cfg.get("font_family", "Segoe UI")))
        self.sub_size_var = tk.StringVar(value=str(sub_cfg.get("font_size", 36)))
        self.sub_text_color_var = tk.StringVar(value=str(sub_cfg.get("text_color", "#ffffff")))
        self.sub_bold_var = tk.BooleanVar(value=bool(sub_cfg.get("bold", True)))
        self.sub_italic_var = tk.BooleanVar(value=bool(sub_cfg.get("italic", False)))
        self.sub_underline_var = tk.BooleanVar(value=bool(sub_cfg.get("underline", False)))
        self.sub_outline_color_var = tk.StringVar(value=str(sub_cfg.get("outline_color", "#000000")))
        self.sub_outline_thickness_var = tk.StringVar(value=str(sub_cfg.get("outline_thickness", 2)))
        self.sub_bg_enabled_var = tk.BooleanVar(value=bool(sub_cfg.get("bg_enabled", False)))
        self.sub_bg_color_var = tk.StringVar(value=str(sub_cfg.get("bg_color", "#000000")))
        self.sub_bg_opacity_var = tk.IntVar(value=int(sub_cfg.get("bg_opacity", 128)))

        # Initialize Performance variables from settings
        perf_cfg = self.settings.get("performance", default={})
        if not isinstance(perf_cfg, dict):
            perf_cfg = {}
        self.cpu_affinity_var = tk.StringVar(value=str(perf_cfg.get("cpu_affinity_mode", "auto")))
        self.disable_eco_qos_var = tk.BooleanVar(value=bool(perf_cfg.get("disable_eco_qos", True)))
        self.high_precision_timer_var = tk.BooleanVar(value=bool(perf_cfg.get("high_precision_timer", True)))

        # Initialize Telegram variables from settings
        tg_cfg = self.settings.get("telegram", default={})
        if not isinstance(tg_cfg, dict):
            tg_cfg = {}
        self.tg_api_id_var = tk.StringVar(value=str(tg_cfg.get("api_id", "")))
        self.tg_api_hash_var = tk.StringVar(value=str(tg_cfg.get("api_hash", "")))
        # Legacy single-account status var (kept for compat)
        self.tg_status_var = tk.StringVar(value="Đang kiểm tra...")
        self._qr_cancel_event = threading.Event()
        self._qr_photo_image = None
        # Multi-account: map account id(obj) -> (active_boolvar, status_strvar)
        self._tg_account_vars: Dict[Any, tuple] = {}
        self._tg_accounts_frame: Optional[tk.Frame] = None

        # Size: 960x680 provides wide, comfortable columns so hotkey text is fully visible
        screen_w = parent.winfo_screenwidth()
        screen_h = parent.winfo_screenheight()
        dialog_w = min(960, max(900, screen_w - 40))
        dialog_h = min(680, max(600, screen_h - 80))
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = max(10, px + max(0, (pw - dialog_w) // 2))
        y = max(10, py + max(0, (ph - dialog_h) // 2))
        self.top.geometry(f"{dialog_w}x{dialog_h}+{x}+{y}")
        self.top.minsize(860, 540)
        self.top.resizable(True, True)
        self.top.transient(parent)
        # Non-modal: do NOT call grab_set() so user can still interact with
        # the main window (e.g. pause/play video) while settings is open.

        # Modern styling: native titlebar, icon, and background
        apply_window_icon(self.top, ICON_FILE)
        is_dark = (self.theme.current_theme == "dark")
        set_windows_dark_titlebar(self.top, dark=is_dark)
        colors = self.theme.PALETTES[self.theme.current_theme]
        self.top.configure(bg=colors["bg"])

        # 1. Top Header Banner (packed side=TOP)
        self._build_header(colors)

        # 2. Bottom action buttons (pack BOTTOM first so central area never shrinks upwards!)
        self._build_action_buttons(colors)

        # 3. Modern Segmented Tab Bar (Windows 11 Fluent aesthetic)
        tab_nav_frame = tk.Frame(self.top, bg=colors["surface_variant"], padx=4, pady=4)
        tab_nav_frame.pack(fill=tk.X, padx=16, pady=(0, 10))

        # 4. Stacked Content Area (all 4 tabs stay permanently mapped in memory — 0ms tab switch!)
        self.content_area = tk.Frame(self.top, bg=colors["bg"])
        self.content_area.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 6))
        self.content_area.grid_rowconfigure(0, weight=1)
        self.content_area.grid_columnconfigure(0, weight=1)

        self.tab_general = tk.Frame(self.content_area, bg=colors["bg"])
        self.tab_general.grid(row=0, column=0, sticky="nsew")

        self.tab_hotkeys = tk.Frame(self.content_area, bg=colors["bg"])
        self.tab_hotkeys.grid(row=0, column=0, sticky="nsew")

        self.tab_subtitles = tk.Frame(self.content_area, bg=colors["bg"])
        self.tab_subtitles.grid(row=0, column=0, sticky="nsew")

        self.tab_sys_info = tk.Frame(self.content_area, bg=colors["bg"])
        self.tab_sys_info.grid(row=0, column=0, sticky="nsew")

        self.tab_about = tk.Frame(self.content_area, bg=colors["bg"])
        self.tab_about.grid(row=0, column=0, sticky="nsew")

        self.tab_telegram = tk.Frame(self.content_area, bg=colors["bg"])
        self.tab_telegram.grid(row=0, column=0, sticky="nsew")

        self._build_general_tab(colors)
        self._build_hotkeys_tab(colors)
        self._build_subtitles_tab(colors)
        self._build_telegram_tab(colors)
        self._build_system_info_tab(colors)
        self._build_about_tab(colors)

        # Tab navigation buttons (instant .lift() switching without unmapping lag)
        self._tab_buttons: Dict[str, tk.Button] = {}
        tab_defs = [
            ("general", "  Cấu hình chung  ", self.tab_general),
            ("hotkeys", "  Phím tắt  ", self.tab_hotkeys),
            ("subtitles", "  Phụ đề  ", self.tab_subtitles),
            ("telegram", "  Telegram  ", self.tab_telegram),
            ("sys_info", "  Thông tin hệ thống  ", self.tab_sys_info),
            ("about", "  Về ứng dụng  ", self.tab_about),
        ]

        def _switch_tab(tab_id: str, target_frame: tk.Frame):
            target_frame.lift()
            if tab_id == "subtitles":
                self.top.after(20, self._update_subtitle_preview)
            if tab_id == "telegram":
                self.top.after(20, self._refresh_telegram_status)
            if tab_id == "sys_info" and not getattr(self, "_sys_info_loaded", False):
                self._sys_info_loaded = True
                self._refresh_sys_info(force=False)
            for tid, btn in self._tab_buttons.items():
                if tid == tab_id:
                    btn.configure(
                        bg=colors["surface"],
                        fg=colors["accent"],
                        font=("Segoe UI", 9, "bold"),
                    )
                else:
                    btn.configure(
                        bg=colors["surface_variant"],
                        fg=colors["fg"],
                        font=("Segoe UI", 9),
                    )

        self.switch_tab = _switch_tab

        for tid, title, frame in tab_defs:
            btn = tk.Button(
                tab_nav_frame,
                text=title,
                command=lambda t=tid, f=frame: _switch_tab(t, f),
                relief=tk.FLAT,
                bd=0,
                padx=16,
                pady=6,
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=3)
            self._tab_buttons[tid] = btn

        # Activate initial tab
        target_tab_frame = getattr(self, f"tab_{self.initial_tab}", self.tab_general)
        _switch_tab(self.initial_tab, target_tab_frame)

        # Adapter for compatibility with unit tests expecting dialog.notebook.tabs()
        class NotebookAdapter:
            def __init__(self, tabs_list):
                self._tabs = tabs_list
            def tabs(self):
                return tuple(self._tabs)

        self.notebook = NotebookAdapter([self.tab_general, self.tab_hotkeys, self.tab_subtitles, self.tab_telegram, self.tab_sys_info, self.tab_about])

        # 5. Flush all layout computations in memory while window is still hidden!
        self.top.update_idletasks()

        # 6. Reveal dialog instantly — 1 single finished frame, zero layout shift!
        if not self._parent_withdrawn:
            self.top.deiconify()
            self.top.lift()
            self.top.focus_set()

    def _build_header(self, colors: Dict[str, str]) -> None:
        """Top title banner with clean typography."""
        header_frame = tk.Frame(self.top, bg=colors["bg"], padx=18, pady=12)
        header_frame.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="Cài đặt & Cấu hình",
            font=("Segoe UI", 13, "bold"),
            bg=colors["bg"],
            fg=colors["fg"],
        )
        title_lbl.pack(anchor=tk.W)

        sub_lbl = tk.Label(
            header_frame,
            text="Tùy chỉnh trải nghiệm xem video, phím tắt tua và tối ưu hóa tài nguyên phần cứng.",
            font=("Segoe UI", 9),
            bg=colors["bg"],
            fg=colors["disabled"],
        )
        sub_lbl.pack(anchor=tk.W, pady=(2, 0))

    def _build_general_tab(self, colors: Optional[Dict[str, str]] = None) -> None:
        """General video and app settings in clean 2-column layout (pure fast rendering)."""
        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        tab = self.tab_general

        cols_frame = tk.Frame(tab, bg=colors["bg"], padx=14, pady=8)
        cols_frame.pack(fill=tk.BOTH, expand=True)
        cols_frame.grid_columnconfigure(0, weight=1, uniform="col")
        cols_frame.grid_columnconfigure(1, weight=1, uniform="col")

        left_col = tk.Frame(cols_frame, bg=colors["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right_col = tk.Frame(cols_frame, bg=colors["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # --- Left Column: Card 1 (Display & UI) ---
        card_display = tk.LabelFrame(
            left_col,
            text=" Hiển thị & Giao diện ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_display.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            card_display,
            text="Chất lượng tối đa:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky=tk.W, pady=4)
        self.max_height_var = tk.StringVar(value=str(self.settings.get("video", "max_height", default=1080)))
        combo_height = ttk.Combobox(
            card_display,
            textvariable=self.max_height_var,
            values=["1080", "720", "480", "360", "0", "-1"],
            state="readonly",
            width=10,
        )
        combo_height.grid(row=0, column=1, sticky=tk.W, padx=6, pady=4)
        tk.Label(
            card_display,
            text="(0: Gốc/Tốt nhất, -1: Tự động)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=0, column=2, sticky=tk.W)

        tk.Label(
            card_display,
            text="Chế độ giao diện:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky=tk.W, pady=4)
        self.theme_var = tk.StringVar(value=self.settings.get("ui", "theme", default="system"))
        combo_theme = ttk.Combobox(
            card_display,
            textvariable=self.theme_var,
            values=["system", "dark", "light"],
            state="readonly",
            width=10,
        )
        combo_theme.grid(row=1, column=1, sticky=tk.W, padx=6, pady=4)

        self.always_top_var = tk.BooleanVar(value=self.settings.get("ui", "always_on_top", default=False))
        chk_top = tk.Checkbutton(
            card_display,
            text="Ghim cửa sổ luôn trên cùng (Always on Top)",
            variable=self.always_top_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_top.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

        self.resume_playback_var = tk.BooleanVar(value=self.settings.get("playback", "resume_playback", default=True))
        chk_resume = tk.Checkbutton(
            card_display,
            text="Ghi nhớ & tự động xem tiếp (Resume Playback)",
            variable=self.resume_playback_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_resume.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=2)

        self.clipboard_auto_detect_var = tk.BooleanVar(value=self.settings.get("ui", "clipboard_auto_detect", default=True))
        chk_clip = tk.Checkbutton(
            card_display,
            text="Tự động nhận diện link từ Clipboard",
            variable=self.clipboard_auto_detect_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_clip.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=2)

        # --- Left Column: Card 2 (Seek Steps) ---
        card_seek = tk.LabelFrame(
            left_col,
            text=" Tùy chỉnh bước tua ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_seek.pack(fill=tk.X)

        tk.Label(
            card_seek,
            text="Tua ngắn (← / →):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky=tk.W, pady=4)
        self.seek_short_var = tk.StringVar(value=str(self.settings.get("ui", "seek_short", default=5)))
        combo_short = ttk.Combobox(
            card_seek,
            textvariable=self.seek_short_var,
            values=["3", "5", "10", "15", "30"],
            state="readonly",
            width=8,
        )
        combo_short.grid(row=0, column=1, sticky=tk.W, padx=6, pady=4)
        tk.Label(
            card_seek,
            text="giây",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=0, column=2, sticky=tk.W)

        tk.Label(
            card_seek,
            text="Tua dài (Shift + ← / →):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky=tk.W, pady=4)
        self.seek_long_var = tk.StringVar(value=str(self.settings.get("ui", "seek_long", default=30)))
        combo_long = ttk.Combobox(
            card_seek,
            textvariable=self.seek_long_var,
            values=["10", "15", "30", "60", "90"],
            state="readonly",
            width=8,
        )
        combo_long.grid(row=1, column=1, sticky=tk.W, padx=6, pady=4)
        tk.Label(
            card_seek,
            text="giây",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=1, column=2, sticky=tk.W)

        # --- Right Column: Card 1 (Performance & CPU Scheduling) ---
        card_perf = tk.LabelFrame(
            right_col,
            text=" ⚡ Tối ưu CPU & Tăng tốc phần cứng (Intel P/E & AMD) ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_perf.pack(fill=tk.X, pady=(0, 8))

        # CPU Core Affinity selection
        tk.Label(
            card_perf,
            text="Phân bổ CPU Cores:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky=tk.W, pady=4)
        combo_affinity = ttk.Combobox(
            card_perf,
            textvariable=self.cpu_affinity_var,
            values=["auto", "p_cores", "all"],
            state="readonly",
            width=10,
        )
        combo_affinity.grid(row=0, column=1, sticky=tk.W, padx=6, pady=4)
        tk.Label(
            card_perf,
            text="(auto: Tự động | p_cores: Chỉ P-cores | all: Tất cả)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=0, column=2, sticky=tk.W)

        # Disable Windows Power Throttling / EcoQoS
        chk_eco = tk.Checkbutton(
            card_perf,
            text="Tắt Windows EcoQoS (chống drop frame khi PiP/chạy nền)",
            variable=self.disable_eco_qos_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_eco.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

        # High-Precision Multimedia Timer (1ms)
        chk_timer = tk.Checkbutton(
            card_perf,
            text="Kích hoạt Windows Timer 1ms (chống giật khung hình)",
            variable=self.high_precision_timer_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_timer.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=2)

        # Hardware Acceleration
        self.hw_decode_var = tk.BooleanVar(value=self.settings.get("streaming", "hardware_decode", default=True))
        chk_hw = tk.Checkbutton(
            card_perf,
            text="Giải mã phần cứng GPU (D3D11VA / DXVA2)",
            variable=self.hw_decode_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_hw.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

        # Network caching
        tk.Label(
            card_perf,
            text="Bộ đệm mạng (Cache):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=4, column=0, sticky=tk.W, pady=4)
        self.buffer_var = tk.StringVar(value=str(self.settings.get("streaming", "network_caching", default=3000)))
        combo_buffer = ttk.Combobox(
            card_perf,
            textvariable=self.buffer_var,
            values=["1000", "2000", "3000", "5000"],
            state="readonly",
            width=10,
        )
        combo_buffer.grid(row=4, column=1, sticky=tk.W, padx=6, pady=4)
        tk.Label(
            card_perf,
            text="ms (3000: chuẩn)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=4, column=2, sticky=tk.W)

        # --- Right Column: Card 2 (Cookies) ---
        card_cookie = tk.LabelFrame(
            right_col,
            text=" Video riêng tư & Cookies ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_cookie.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            card_cookie,
            text="File cookies:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)
        self.cookie_var = tk.StringVar(value=self.settings.get("advanced", "cookie_file", default=""))
        entry_cookie = tk.Entry(
            card_cookie,
            textvariable=self.cookie_var,
            font=("Segoe UI", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["fg"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
        )
        entry_cookie.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        btn_browse = tk.Button(
            card_cookie,
            text="Chọn file...",
            font=("Segoe UI", 8),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._browse_cookie_file,
        )
        btn_browse.pack(side=tk.LEFT)

        btn_cookie_help = tk.Button(
            card_cookie,
            text="?",
            font=("Segoe UI", 9, "bold"),
            bg=colors["surface_variant"],
            fg=colors["accent"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=7,
            pady=2,
            cursor="hand2",
            command=self._open_cookie_guide,
        )
        btn_cookie_help.pack(side=tk.LEFT, padx=(4, 0))

        # --- Right Column: Card 3 (Download & Data) ---
        card_download = tk.LabelFrame(
            right_col,
            text=" Tải xuống & Thư mục lưu trữ ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_download.pack(fill=tk.X)
        card_download.columnconfigure(1, weight=1)

        tk.Label(
            card_download,
            text="Thư mục tải về:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky=tk.W, pady=3)
        self.download_dir_var = tk.StringVar(value=self.settings.get("download", "download_dir", default=""))
        entry_download = tk.Entry(
            card_download,
            textvariable=self.download_dir_var,
            font=("Segoe UI", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["fg"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
        )
        entry_download.grid(row=0, column=1, sticky=tk.EW, padx=6, pady=3)
        btn_browse_down = tk.Button(
            card_download,
            text="Chọn...",
            font=("Segoe UI", 8),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._browse_download_dir,
        )
        btn_browse_down.grid(row=0, column=2, sticky=tk.W)

        tk.Label(
            card_download,
            text="(Để trống sẽ tự động lưu vào thư mục Downloads chuẩn)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 2))

        self.always_ask_download_var = tk.BooleanVar(value=self.settings.get("download", "always_ask", default=False))
        chk_ask = tk.Checkbutton(
            card_download,
            text="Hỏi vị trí lưu trước khi tải video",
            variable=self.always_ask_download_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_ask.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=2)

        tk.Label(
            card_download,
            text="Định dạng tải mặc định:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, sticky=tk.W, pady=3)
        current_fmt = self.settings.get("download", "format", default="ask")
        self.download_format_var = tk.StringVar(value=current_fmt)
        combo_fmt = ttk.Combobox(
            card_download,
            textvariable=self.download_format_var,
            values=["ask", "video", "audio"],
            state="readonly",
            width=12,
        )
        combo_fmt.grid(row=3, column=1, sticky=tk.W, padx=6, pady=3)
        tk.Label(
            card_download,
            text="(ask / video / audio)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=3, column=2, sticky=tk.W)

        self.download_toast_var = tk.BooleanVar(value=self.settings.get("download", "show_toast", default=True))
        chk_toast = tk.Checkbutton(
            card_download,
            text="Hiển thị thông báo Windows (Toast) khi tải xong",
            variable=self.download_toast_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_toast.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=2)

        sep_card = tk.Frame(card_download, height=1, bg=colors["border"])
        sep_card.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=6)

        tk.Label(
            card_download,
            text="Dữ liệu & Cấu hình:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=6, column=0, sticky=tk.W, pady=2)
        lbl_data_path = tk.Label(
            card_download,
            text=str(self.settings.config_dir),
            font=("Consolas", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        )
        lbl_data_path.grid(row=6, column=1, sticky=tk.W, padx=6, pady=2)
        btn_open_data = tk.Button(
            card_download,
            text="Mở data",
            font=("Segoe UI", 8),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._open_data_dir,
        )
        btn_open_data.grid(row=6, column=2, sticky=tk.W)

    def _build_hotkeys_tab(self, colors: Dict[str, str]) -> None:
        """Hotkeys customization tab in clean 2-column layout (pure fast rendering)."""
        tab = self.tab_hotkeys

        top_row = tk.Frame(tab, bg=colors["bg"], padx=14, pady=6)
        top_row.pack(fill=tk.X, pady=(0, 6))

        desc_lbl = tk.Label(
            top_row,
            text="Tùy chỉnh phím tắt theo thói quen. Hỗ trợ phím đơn (Space, m, f), tổ hợp (Ctrl+H), hoặc nhiều phím (Space; k).",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        )
        desc_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        btn_reset_all = tk.Button(
            top_row,
            text="Khôi phục mặc định",
            font=("Segoe UI", 8),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._reset_all_hotkeys_to_default,
        )
        btn_reset_all.pack(side=tk.RIGHT)

        cols_container = tk.Frame(tab, bg=colors["bg"], padx=14, pady=0)
        cols_container.pack(fill=tk.BOTH, expand=True)
        cols_container.grid_columnconfigure(0, weight=1, uniform="col")
        cols_container.grid_columnconfigure(1, weight=1, uniform="col")

        left_col = tk.Frame(cols_container, bg=colors["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right_col = tk.Frame(cols_container, bg=colors["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        categories: Dict[str, list] = {}
        for item in HOTKEY_DEFINITIONS:
            cat = item[2]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)

        for cat_name, items in categories.items():
            parent_col = left_col if "Phát" in cat_name else right_col
            clean_cat = cat_name.lstrip("🎬🔊⚡ ").strip()
            card = tk.LabelFrame(
                parent_col,
                text=f" {clean_cat} ",
                bg=colors["bg"],
                fg=colors["accent"],
                font=("Segoe UI", 9, "bold"),
                bd=1,
                relief=tk.SOLID,
                padx=12,
                pady=6,
            )
            card.pack(fill=tk.X, pady=(0, 6))
            card.columnconfigure(0, weight=0)
            card.columnconfigure(1, weight=1)
            card.columnconfigure(2, weight=0)

            for idx, (aid, display_name, _, default_val) in enumerate(items):
                lbl_name = tk.Label(
                    card,
                    text=f"{display_name}:",
                    font=("Segoe UI", 9),
                    bg=colors["bg"],
                    fg=colors["fg"],
                    anchor="w",
                )
                lbl_name.grid(row=idx, column=0, sticky=tk.W, pady=3, padx=(0, 8))

                entry = tk.Entry(
                    card,
                    textvariable=self.hotkey_vars[aid],
                    font=("Consolas", 10),
                    bg=colors["entry_bg"],
                    fg=colors["entry_fg"],
                    insertbackground=colors["fg"],
                    relief=tk.FLAT,
                    highlightthickness=1,
                    highlightbackground=colors["border"],
                    highlightcolor=colors["accent"],
                )
                entry.grid(row=idx, column=1, sticky=tk.EW, pady=3, padx=(0, 6))

                btn_def = tk.Button(
                    card,
                    text="↺",
                    font=("Segoe UI", 8),
                    bg=colors["surface_variant"],
                    fg=colors["fg"],
                    activebackground=colors["surface"],
                    activeforeground=colors["accent"],
                    relief=tk.FLAT,
                    bd=0,
                    padx=5,
                    pady=1,
                    cursor="hand2",
                    command=lambda k=aid, d=default_val: self.hotkey_vars[k].set(d),
                )
                btn_def.grid(row=idx, column=2, sticky=tk.E, pady=3)

    def _reset_all_hotkeys_to_default(self) -> None:
        """Reset all hotkey fields back to application factory defaults."""
        for aid, _, _, default_val in HOTKEY_DEFINITIONS:
            if aid in self.hotkey_vars:
                self.hotkey_vars[aid].set(default_val)

    def _build_subtitles_tab(self, colors: Optional[Dict[str, str]] = None) -> None:
        """Subtitle settings tab with multi-format validation, styling controls, and live preview."""
        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        tab = self.tab_subtitles

        cols_frame = tk.Frame(tab, bg=colors["bg"], padx=14, pady=6)
        cols_frame.pack(fill=tk.BOTH, expand=True)
        cols_frame.grid_columnconfigure(0, weight=1, uniform="col")
        cols_frame.grid_columnconfigure(1, weight=1, uniform="col")

        left_col = tk.Frame(cols_frame, bg=colors["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right_col = tk.Frame(cols_frame, bg=colors["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # --- Left Col Card 1: Nạp tệp phụ đề ---
        card_file = tk.LabelFrame(
            left_col,
            text=" Nạp tệp phụ đề (Subtitle Loader) ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_file.pack(fill=tk.X, pady=(0, 6))
        card_file.columnconfigure(1, weight=1)

        tk.Label(
            card_file,
            text="Đường dẫn:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky=tk.W, pady=3)

        entry_file = tk.Entry(
            card_file,
            textvariable=self.sub_file_var,
            font=("Segoe UI", 8),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["fg"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
        )
        entry_file.grid(row=0, column=1, sticky=tk.EW, padx=6, pady=3)

        btn_box = tk.Frame(card_file, bg=colors["bg"])
        btn_box.grid(row=0, column=2, sticky=tk.E)

        btn_browse = tk.Button(
            btn_box,
            text="Chọn file...",
            font=("Segoe UI", 8),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._browse_subtitle_file,
        )
        btn_browse.pack(side=tk.LEFT, padx=(0, 4))

        btn_clear_sub = tk.Button(
            btn_box,
            text="✖ Xóa",
            font=("Segoe UI", 8),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground="#ef4444",
            relief=tk.FLAT,
            bd=0,
            padx=6,
            pady=2,
            cursor="hand2",
            command=self._clear_subtitle_file,
        )
        btn_clear_sub.pack(side=tk.LEFT)

        # Status badge label
        self.lbl_sub_badge = tk.Label(
            card_file,
            text="(Chưa nạp tệp phụ đề nào)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
            anchor="w",
            wraplength=380,
            justify=tk.LEFT,
        )
        self.lbl_sub_badge.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(2, 2))

        # Initial badge check
        cur_file = self.sub_file_var.get().strip()
        if cur_file:
            is_valid, fmt_name, _ = validate_subtitle_file(cur_file)
            if is_valid:
                self.lbl_sub_badge.configure(text=f"✓ {fmt_name}: {Path(cur_file).name}", fg="#22c55e")
            else:
                self.lbl_sub_badge.configure(text=f"⚠ Tệp không hợp lệ: {Path(cur_file).name}", fg="#ef4444")

        # Supported format hint
        tk.Label(
            card_file,
            text="Hỗ trợ: .srt, .vtt, .ass, .ssa, .sub, .smi, .idx, .txt, .lrc, .ttml, .dfxp",
            font=("Segoe UI", 7),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W)

        # --- Left Col Card 2: Phông chữ & Định dạng chữ ---
        card_font = tk.LabelFrame(
            left_col,
            text=" Định dạng văn bản & Phông chữ ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_font.pack(fill=tk.X, pady=(0, 6))

        # Font family
        tk.Label(
            card_font,
            text="Phông chữ (Font):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky=tk.W, pady=3)
        font_choices = [
            "Segoe UI", "Arial", "Roboto", "Tahoma", "Verdana",
            "Trebuchet MS", "Georgia", "Times New Roman", "Consolas"
        ]
        combo_font = ttk.Combobox(
            card_font,
            textvariable=self.sub_font_var,
            values=font_choices,
            state="readonly",
            width=16,
        )
        combo_font.grid(row=0, column=1, sticky=tk.W, padx=6, pady=3)

        # Font size
        tk.Label(
            card_font,
            text="Cỡ chữ (Size):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky=tk.W, pady=3)
        size_choices = [
            "18", "20", "24", "28", "32", "36", "40", "44", "48",
            "54", "60", "68", "76", "84", "96", "112", "128"
        ]
        combo_size = ttk.Combobox(
            card_font,
            textvariable=self.sub_size_var,
            values=size_choices,
            width=10,
        )
        combo_size.grid(row=1, column=1, sticky=tk.W, padx=6, pady=3)

        # Typography checkbuttons: Bold, Italic ("Italy"), Underline ("Under")
        typo_frame = tk.Frame(card_font, bg=colors["bg"])
        typo_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 4))

        chk_bold = tk.Checkbutton(
            typo_frame,
            text="In đậm (Bold)",
            variable=self.sub_bold_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9, "bold"),
        )
        chk_bold.pack(side=tk.LEFT, padx=(0, 10))

        chk_italic = tk.Checkbutton(
            typo_frame,
            text="In nghiêng (Italic)",
            variable=self.sub_italic_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9, "italic"),
        )
        chk_italic.pack(side=tk.LEFT, padx=(0, 10))

        chk_under = tk.Checkbutton(
            typo_frame,
            text="Gạch chân (Underline)",
            variable=self.sub_underline_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9, "underline"),
        )
        chk_under.pack(side=tk.LEFT)

        # Text color
        tk.Label(
            card_font,
            text="Màu chữ (Text color):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, sticky=tk.W, pady=3)

        text_col_box = tk.Frame(card_font, bg=colors["bg"])
        text_col_box.grid(row=3, column=1, sticky=tk.W, padx=6, pady=3)

        self.btn_text_color = tk.Button(
            text_col_box,
            bg=self.sub_text_color_var.get(),
            width=3,
            height=1,
            relief=tk.SOLID,
            bd=1,
            cursor="hand2",
            command=self._pick_text_color,
        )
        self.btn_text_color.pack(side=tk.LEFT, padx=(0, 6))

        self.lbl_text_color = tk.Label(
            text_col_box,
            text=self.sub_text_color_var.get().upper(),
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Consolas", 9),
        )
        self.lbl_text_color.pack(side=tk.LEFT)

        # --- Right Col Card 3: Viền & Nền phụ đề ---
        card_border = tk.LabelFrame(
            right_col,
            text=" Viền & Nền phụ đề (Outline & Background) ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_border.pack(fill=tk.X, pady=(0, 6))

        # Outline color
        tk.Label(
            card_border,
            text="Màu viền (Border):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky=tk.W, pady=3)

        out_col_box = tk.Frame(card_border, bg=colors["bg"])
        out_col_box.grid(row=0, column=1, sticky=tk.W, padx=6, pady=3)

        self.btn_outline_color = tk.Button(
            out_col_box,
            bg=self.sub_outline_color_var.get(),
            width=3,
            height=1,
            relief=tk.SOLID,
            bd=1,
            cursor="hand2",
            command=self._pick_outline_color,
        )
        self.btn_outline_color.pack(side=tk.LEFT, padx=(0, 6))

        self.lbl_outline_color = tk.Label(
            out_col_box,
            text=self.sub_outline_color_var.get().upper(),
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Consolas", 9),
        )
        self.lbl_outline_color.pack(side=tk.LEFT)

        # Outline thickness
        tk.Label(
            card_border,
            text="Độ dày viền:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky=tk.W, pady=3)

        thick_choices = ["0 (Không viền)", "1 (Mỏng)", "2 (Vừa)", "3 (Dày)", "4 (Rất dày)"]
        cur_thick = str(self.sub_outline_thickness_var.get())
        thick_match = [c for c in thick_choices if c.startswith(cur_thick)]
        self.combo_thick_val = tk.StringVar(value=thick_match[0] if thick_match else thick_choices[2])
        combo_thick = ttk.Combobox(
            card_border,
            textvariable=self.combo_thick_val,
            values=thick_choices,
            state="readonly",
            width=14,
        )
        combo_thick.grid(row=1, column=1, sticky=tk.W, padx=6, pady=3)
        combo_thick.bind("<<ComboboxSelected>>", self._on_thickness_selected)

        # Background Box Enable
        chk_bg = tk.Checkbutton(
            card_border,
            text="Bật khung nền phụ đề (Background Box)",
            variable=self.sub_bg_enabled_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
            command=self._on_bg_enabled_toggled,
        )
        chk_bg.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 2))

        # Background color
        tk.Label(
            card_border,
            text="Màu nền (Background):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, sticky=tk.W, pady=3)

        bg_col_box = tk.Frame(card_border, bg=colors["bg"])
        bg_col_box.grid(row=3, column=1, sticky=tk.W, padx=6, pady=3)

        self.btn_bg_color = tk.Button(
            bg_col_box,
            bg=self.sub_bg_color_var.get(),
            width=3,
            height=1,
            relief=tk.SOLID,
            bd=1,
            cursor="hand2",
            command=self._pick_bg_color,
        )
        self.btn_bg_color.pack(side=tk.LEFT, padx=(0, 6))

        self.lbl_bg_color = tk.Label(
            bg_col_box,
            text=self.sub_bg_color_var.get().upper(),
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Consolas", 9),
        )
        self.lbl_bg_color.pack(side=tk.LEFT)

        # Background opacity
        tk.Label(
            card_border,
            text="Độ đậm nền (0-255):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=4, column=0, sticky=tk.W, pady=3)

        scale_box = tk.Frame(card_border, bg=colors["bg"])
        scale_box.grid(row=4, column=1, sticky=tk.EW, padx=6, pady=3)

        self.scale_opacity = tk.Scale(
            scale_box,
            variable=self.sub_bg_opacity_var,
            from_=0,
            to=255,
            orient=tk.HORIZONTAL,
            showvalue=True,
            bg=colors["bg"],
            fg=colors["fg"],
            troughcolor=colors["entry_bg"],
            activebackground=colors["accent"],
            highlightthickness=0,
            bd=0,
            length=130,
            command=self._on_opacity_slider_changed,
        )
        self.scale_opacity.pack(side=tk.LEFT)

        init_pct = int(self.sub_bg_opacity_var.get() * 100 / 255)
        self.lbl_opacity_val = tk.Label(
            scale_box,
            text=f"({init_pct}%)",
            bg=colors["bg"],
            fg=colors["disabled"],
            font=("Segoe UI", 8),
        )
        self.lbl_opacity_val.pack(side=tk.LEFT, padx=(4, 0))

        # --- Right Col Card 4: Xem trước trực tiếp (Live Preview) ---
        card_preview = tk.LabelFrame(
            right_col,
            text=" Xem trước trực tiếp (Live Preview) ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=6,
        )
        card_preview.pack(fill=tk.BOTH, expand=True)

        prev_header = tk.Frame(card_preview, bg=colors["bg"])
        prev_header.pack(fill=tk.X, pady=(0, 2))

        tk.Label(
            prev_header,
            text="Mô phỏng hiển thị trên video:",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).pack(side=tk.LEFT)

        btn_reset_style = tk.Button(
            prev_header,
            text="↺ Khôi phục mặc định",
            font=("Segoe UI", 8),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=1,
            cursor="hand2",
            command=self._reset_subtitle_style_to_default,
        )
        btn_reset_style.pack(side=tk.RIGHT)

        # Preview Canvas (simulating video frame with subtitles)
        self.sub_preview_canvas = tk.Canvas(
            card_preview,
            bg="#18181b",
            height=100,
            highlightthickness=1,
            highlightbackground=colors["border"],
        )
        self.sub_preview_canvas.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.sub_preview_canvas.bind("<Configure>", lambda e: self._update_subtitle_preview())

        # Wire variable traces to live preview update
        for v in (
            self.sub_font_var,
            self.sub_size_var,
            self.sub_text_color_var,
            self.sub_bold_var,
            self.sub_italic_var,
            self.sub_underline_var,
            self.sub_outline_color_var,
            self.sub_outline_thickness_var,
            self.sub_bg_enabled_var,
            self.sub_bg_color_var,
            self.sub_bg_opacity_var,
        ):
            v.trace_add("write", lambda *args: self._update_subtitle_preview())

        # Set initial enable state for background controls
        self._on_bg_enabled_toggled()

        # Initial preview draw
        self.top.after(50, self._update_subtitle_preview)

    def _browse_subtitle_file(self) -> None:
        filetypes = [
            (
                "Tất cả định dạng phụ đề",
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
        chosen = filedialog.askopenfilename(
            parent=self.top,
            title="Chọn tệp phụ đề video",
            filetypes=filetypes,
        )
        if not chosen:
            return

        is_valid, format_name, msg = validate_subtitle_file(chosen)
        if not is_valid:
            messagebox.showerror(
                "Lỗi định dạng phụ đề",
                f"Tệp không hợp lệ: '{Path(chosen).name}'\n\nChi tiết: {msg}\n\nVui lòng chọn một tệp phụ đề hợp lệ (.srt, .vtt, .ass, ...).",
                parent=self.top,
            )
            return

        self.sub_file_var.set(chosen)
        if hasattr(self, "lbl_sub_badge"):
            self.lbl_sub_badge.configure(
                text=f"✓ {format_name}: {Path(chosen).name}",
                fg="#22c55e",
            )

    def _clear_subtitle_file(self) -> None:
        self.sub_file_var.set("")
        if hasattr(self, "lbl_sub_badge"):
            colors = self.theme.PALETTES[self.theme.current_theme]
            self.lbl_sub_badge.configure(
                text="(Đã xóa phụ đề - chưa nạp file)",
                fg=colors["disabled"],
            )

    def _on_thickness_selected(self, event=None) -> None:
        val_str = self.combo_thick_val.get()
        num = val_str.split()[0] if val_str else "2"
        self.sub_outline_thickness_var.set(num)
        self._update_subtitle_preview()

    def _pick_text_color(self) -> None:
        curr = self.sub_text_color_var.get() or "#ffffff"
        color = colorchooser.askcolor(initialcolor=curr, parent=self.top, title="Chọn màu chữ phụ đề")[1]
        if color:
            self.sub_text_color_var.set(color)
            self.btn_text_color.configure(bg=color)
            self.lbl_text_color.configure(text=color.upper())

    def _pick_outline_color(self) -> None:
        curr = self.sub_outline_color_var.get() or "#000000"
        color = colorchooser.askcolor(initialcolor=curr, parent=self.top, title="Chọn màu viền phụ đề")[1]
        if color:
            self.sub_outline_color_var.set(color)
            self.btn_outline_color.configure(bg=color)
            self.lbl_outline_color.configure(text=color.upper())

    def _pick_bg_color(self) -> None:
        curr = self.sub_bg_color_var.get() or "#000000"
        color = colorchooser.askcolor(initialcolor=curr, parent=self.top, title="Chọn màu nền phụ đề")[1]
        if color:
            self.sub_bg_color_var.set(color)
            self.btn_bg_color.configure(bg=color)
            self.lbl_bg_color.configure(text=color.upper())

    def _on_bg_enabled_toggled(self) -> None:
        """Enable or disable background color and opacity controls based on checkbox state."""
        is_on = bool(self.sub_bg_enabled_var.get())
        state = tk.NORMAL if is_on else tk.DISABLED
        if hasattr(self, "btn_bg_color"):
            self.btn_bg_color.configure(state=state)
        if hasattr(self, "scale_opacity"):
            self.scale_opacity.configure(state=state)
        self._update_subtitle_preview()

    def _on_opacity_slider_changed(self, val=None) -> None:
        """Handle opacity slider dragging: update percentage label and re-render preview."""
        try:
            curr_val = int(self.sub_bg_opacity_var.get())
        except Exception:
            curr_val = 128
        pct = int(curr_val * 100 / 255)
        if hasattr(self, "lbl_opacity_val"):
            self.lbl_opacity_val.configure(text=f"({pct}%)")
        self._update_subtitle_preview()

    def _reset_subtitle_style_to_default(self) -> None:
        self.sub_font_var.set("Segoe UI")
        self.sub_size_var.set("36")
        self.sub_text_color_var.set("#ffffff")
        self.sub_bold_var.set(True)
        self.sub_italic_var.set(False)
        self.sub_underline_var.set(False)
        self.sub_outline_color_var.set("#000000")
        self.sub_outline_thickness_var.set("2")
        self.combo_thick_val.set("2 (Vừa)")
        self.sub_bg_enabled_var.set(False)
        self.sub_bg_color_var.set("#000000")
        self.sub_bg_opacity_var.set(128)

        self.btn_text_color.configure(bg="#ffffff")
        self.lbl_text_color.configure(text="#FFFFFF")
        self.btn_outline_color.configure(bg="#000000")
        self.lbl_outline_color.configure(text="#000000")
        self.btn_bg_color.configure(bg="#000000")
        self.lbl_bg_color.configure(text="#000000")
        if hasattr(self, "lbl_opacity_val"):
            self.lbl_opacity_val.configure(text="(50%)")
        self._on_bg_enabled_toggled()
        self._update_subtitle_preview()

    def _update_subtitle_preview(self) -> None:
        if not hasattr(self, "sub_preview_canvas") or not self.sub_preview_canvas.winfo_exists():
            return

        self.sub_preview_canvas.delete("all")
        w = max(100, self.sub_preview_canvas.winfo_width())
        h = max(60, self.sub_preview_canvas.winfo_height())

        # Font configuration
        family = self.sub_font_var.get().strip() or "Segoe UI"
        try:
            raw_size = int(self.sub_size_var.get().strip())
        except Exception:
            raw_size = 36
        # Scale nicely for preview canvas: clamp between 11 and 36 so size differences are clearly visible
        prev_size = max(11, min(36, int(raw_size * 0.5)))

        is_bold = self.sub_bold_var.get()
        is_italic = self.sub_italic_var.get()
        is_under = self.sub_underline_var.get()

        weight = "bold" if is_bold else "normal"
        slant = "italic" if is_italic else "roman"
        underline = 1 if is_under else 0

        try:
            font_obj = tkfont.Font(family=family, size=prev_size, weight=weight, slant=slant, underline=underline)
        except Exception:
            font_obj = tkfont.Font(size=prev_size, weight=weight, slant=slant, underline=underline)

        sample_lines = [
            "00:01:25 --> 00:01:29",
            "Đây là phụ đề xem trước mẫu - FB Video Watcher",
        ]
        sample_text = "\n".join(sample_lines)

        cx = w // 2
        cy = h // 2

        # Measure bounding box of subtitle text
        max_line_w = max(font_obj.measure(line) for line in sample_lines)
        line_h = font_obj.metrics("linespace")
        total_h = line_h * len(sample_lines)
        pad_x = 16
        pad_y = 6
        bx1 = cx - (max_line_w // 2) - pad_x
        by1 = cy - (total_h // 2) - pad_y
        bx2 = cx + (max_line_w // 2) + pad_x
        by2 = cy + (total_h // 2) + pad_y

        # Outline thickness
        try:
            thick = int(str(self.sub_outline_thickness_var.get()).split()[0])
        except Exception:
            thick = 2

        # 1. Render realistic video frame background with true alpha-composited subtitle box
        rendered_with_pil = False
        try:
            base = Image.new("RGBA", (w, h), (24, 24, 27, 255))
            draw = ImageDraw.Draw(base)

            # Draw cinematic gradient backdrop
            for y in range(h):
                blend = y / h
                r = int(18 + 25 * blend)
                g = int(28 + 35 * (1 - blend))
                b = int(58 + 35 * blend)
                draw.line([(0, y), (w, y)], fill=(r, g, b, 255))

            # Draw soft video scene elements (warm glowing sun & cool mountain silhouette)
            draw.ellipse([25, 12, 130, 88], fill=(245, 158, 11, 130))
            draw.polygon([(240, h), (310, 18), (380, h)], fill=(59, 130, 246, 110))
            draw.polygon([(340, h), (410, 35), (480, h)], fill=(16, 185, 129, 90))
            draw.text((10, 6), "▶ Video Scene Simulator (1080p)", fill=(148, 163, 184, 180))

            # Alpha-blended subtitle background box
            if self.sub_bg_enabled_var.get():
                bg_hex = self.sub_bg_color_var.get().strip() or "#000000"
                try:
                    opacity = max(0, min(255, int(self.sub_bg_opacity_var.get())))
                except Exception:
                    opacity = 128

                if opacity > 0:
                    cleaned_hex = bg_hex.lstrip("#")
                    if len(cleaned_hex) == 6:
                        br = int(cleaned_hex[0:2], 16)
                        bg = int(cleaned_hex[2:4], 16)
                        bb = int(cleaned_hex[4:6], 16)
                    else:
                        br, bg, bb = 0, 0, 0

                    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    odraw = ImageDraw.Draw(overlay)
                    odraw.rounded_rectangle([bx1, by1, bx2, by2], radius=6, fill=(br, bg, bb, opacity))
                    base = Image.alpha_composite(base, overlay)

            self._preview_photo = ImageTk.PhotoImage(base)
            self.sub_preview_canvas.create_image(0, 0, image=self._preview_photo, anchor="nw")
            rendered_with_pil = True
        except Exception:
            pass

        if not rendered_with_pil:
            # Fallback pure Tkinter rendering with mathematical RGB blending
            self.sub_preview_canvas.create_rectangle(0, 0, w, h, fill="#18181b", outline="")
            if self.sub_bg_enabled_var.get():
                bg_hex = self.sub_bg_color_var.get().strip() or "#000000"
                try:
                    opacity = max(0, min(255, int(self.sub_bg_opacity_var.get())))
                except Exception:
                    opacity = 128
                alpha = opacity / 255.0
                if alpha > 0:
                    cleaned_hex = bg_hex.lstrip("#")
                    if len(cleaned_hex) == 6:
                        br = int(cleaned_hex[0:2], 16)
                        bg = int(cleaned_hex[2:4], 16)
                        bb = int(cleaned_hex[4:6], 16)
                    else:
                        br, bg, bb = 0, 0, 0
                    blend_r = int(br * alpha + 24 * (1 - alpha))
                    blend_g = int(bg * alpha + 24 * (1 - alpha))
                    blend_b = int(bb * alpha + 27 * (1 - alpha))
                    blend_hex = f"#{blend_r:02x}{blend_g:02x}{blend_b:02x}"
                    self.sub_preview_canvas.create_rectangle(bx1, by1, bx2, by2, fill=blend_hex, outline="")

        # Draw outline / border shadow around text
        out_col = self.sub_outline_color_var.get() or "#000000"
        if thick > 0:
            for dx in range(-thick, thick + 1):
                for dy in range(-thick, thick + 1):
                    if dx == 0 and dy == 0:
                        continue
                    self.sub_preview_canvas.create_text(
                        cx + dx,
                        cy + dy,
                        text=sample_text,
                        font=font_obj,
                        fill=out_col,
                        justify=tk.CENTER,
                    )

        # Draw main subtitle text
        text_col = self.sub_text_color_var.get() or "#ffffff"
        self.sub_preview_canvas.create_text(
            cx,
            cy,
            text=sample_text,
            font=font_obj,
            fill=text_col,
            justify=tk.CENTER,
        )

    def _build_system_info_tab(self, colors: Dict[str, str]) -> None:
        """System Information and Auto-Tune Tab styled cleanly with scrollbar and colors."""
        tab = self.tab_sys_info
        self._sys_info_loaded = False

        desc_lbl = tk.Label(
            tab,
            text="Báo cáo phần cứng tự động phát hiện và các thông số đề xuất bởi Auto-Tuner:",
            font=("Segoe UI", 9),
            bg=colors["bg"],
            fg=colors["fg"],
        )
        desc_lbl.pack(anchor=tk.W, pady=(0, 8))

        # Text area container with integrated scrollbar
        text_container = tk.Frame(tab, bg=colors["bg"])
        text_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        scrollbar = ttk.Scrollbar(text_container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.sys_text = tk.Text(
            text_container,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["fg"],
            selectbackground=colors["accent"],
            selectforeground="#ffffff",
            relief=tk.FLAT,
            padx=10,
            pady=10,
            yscrollcommand=scrollbar.set,
        )
        self.sys_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.sys_text.yview)

        btn_row = tk.Frame(tab, bg=colors["bg"])
        btn_row.pack(fill=tk.X)

        btn_copy = tk.Button(
            btn_row,
            text="Sao chép báo cáo",
            font=("Segoe UI", 9),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._copy_sys_info,
        )
        btn_copy.pack(side=tk.LEFT, padx=(0, 8))

        btn_refresh = tk.Button(
            btn_row,
            text="Quét lại phần cứng",
            font=("Segoe UI", 9),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=lambda: self._refresh_sys_info(force=True),
        )
        btn_refresh.pack(side=tk.LEFT)

        # Lazy: do not call self._refresh_sys_info here; loaded on tab click

    def _refresh_sys_info(self, force: bool = False) -> None:
        """Query SystemInfo and AutoTuner and populate text box asynchronously."""
        self.sys_text.delete("1.0", tk.END)
        self.sys_text.insert("1.0", "[Đang quét thông tin phần cứng hệ thống... Vui lòng đợi]")

        def _worker():
            info = SystemInfo.detect(force_refresh=force)
            tuner = AutoTuner(info, self.settings.settings)
            lines = [
                "FB Video Watcher - Báo cáo thông tin hệ thống",
                "=" * 45,
            ]
            for k, v in info.to_display_dict().items():
                lines.append(f"{k:14}: {v}")

            lines.append("\n-- Cấu hình Auto-tune đề xuất --")
            for k, v in tuner.get_recommendations_display().items():
                lines.append(f"{k:14}: {v}")

            content = "\n".join(lines)

            def _apply():
                if hasattr(self, "top") and self.top.winfo_exists():
                    self.current_sys_info = info
                    self.sys_text.delete("1.0", tk.END)
                    self.sys_text.insert("1.0", content)

            self.top.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _copy_sys_info(self) -> None:
        """Copy formatted system info text to OS clipboard."""
        text = self.sys_text.get("1.0", tk.END).strip()
        self.top.clipboard_clear()
        self.top.clipboard_append(text)
        messagebox.showinfo("Thành công", "Đã sao chép thông tin hệ thống vào bộ nhớ tạm (clipboard)!")

    def _browse_cookie_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.top,
            title="Chọn file cookies Netscape",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.cookie_var.set(path)

    def _open_cookie_guide(self) -> None:
        """Open the local cookies guide HTML in default web browser."""
        from pathlib import Path
        import webbrowser

        candidates = [
            Path(__file__).resolve().parent.parent / "docs" / "cookies_guide.html",
            Path(__file__).resolve().parent / "docs" / "cookies_guide.html",
        ]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "docs" / "cookies_guide.html")
            candidates.append(Path(meipass) / "main" / "docs" / "cookies_guide.html")

        guide_path = next((p for p in candidates if p.is_file()), None)
        if guide_path:
            try:
                webbrowser.open(guide_path.as_uri())
            except Exception:
                webbrowser.open(str(guide_path))
        else:
            messagebox.showwarning(
                "Không tìm thấy hướng dẫn",
                "Không tìm thấy file hướng dẫn cookies_guide.html trong thư mục ứng dụng.",
                parent=self.top,
            )

    def _browse_download_dir(self) -> None:
        path = filedialog.askdirectory(
            parent=self.top,
            title="Chọn thư mục mặc định để lưu video tải về",
            initialdir=self.download_dir_var.get().strip() or None,
        )
        if path:
            self.download_dir_var.set(path)

    def _open_data_dir(self) -> None:
        import os
        import subprocess
        try:
            target = self.settings.config_dir
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(str(target))
            else:
                subprocess.Popen(["explorer", str(target)])
        except Exception as e:
            messagebox.showwarning("Thông báo", f"Không thể mở thư mục: {e}")

    def _build_telegram_tab(self, colors: Optional[Dict[str, str]] = None) -> None:
        """Telegram configuration tab: API credentials + multi-account management."""
        import webbrowser
        from main.telegram_manager import TelegramManager

        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        tab = self.tab_telegram

        cols_frame = tk.Frame(tab, bg=colors["bg"], padx=14, pady=8)
        cols_frame.pack(fill=tk.BOTH, expand=True)
        cols_frame.grid_columnconfigure(0, weight=1, uniform="tg_col")
        cols_frame.grid_columnconfigure(1, weight=2, uniform="tg_col")

        left_col = tk.Frame(cols_frame, bg=colors["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right_col = tk.Frame(cols_frame, bg=colors["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # ------------------------------------------------------------------ #
        #  LEFT: API Configuration (shared across all accounts)              #
        # ------------------------------------------------------------------ #
        card_api = tk.LabelFrame(
            left_col,
            text=" Cấu hình Telegram API (my.telegram.org) ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=10,
        )
        card_api.pack(fill=tk.X, pady=(0, 10))

        guide_text = (
            "Để xem video từ các kênh và nhóm kín Telegram (t.me/c/...),\n"
            "bạn cần tạo thông tin API miễn phí từ chính Telegram:\n\n"
            "1. Truy cập my.telegram.org và đăng nhập số điện thoại.\n"
            "2. Chọn 'API development tools'.\n"
            "3. Điền tên app bất kỳ để nhận App api_id và App api_hash.\n"
            "4. Copy và dán vào 2 ô bên dưới, sau đó bấm 'Lưu cấu hình API'."
        )
        lbl_guide = tk.Label(
            card_api,
            text=guide_text,
            font=("Segoe UI", 9),
            bg=colors["bg"],
            fg=colors["fg"],
            justify=tk.LEFT,
            anchor="w",
        )
        lbl_guide.pack(fill=tk.X, pady=(0, 8))

        btn_open_web = tk.Button(
            card_api,
            text="  Mở my.telegram.org  ",
            command=lambda: webbrowser.open("https://my.telegram.org"),
            bg=colors["surface"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
        )
        btn_open_web.pack(anchor="w", pady=(0, 12))

        # API ID field
        row_id = tk.Frame(card_api, bg=colors["bg"])
        row_id.pack(fill=tk.X, pady=(0, 6))
        tk.Label(
            row_id, text="API ID:", font=("Segoe UI", 9, "bold"),
            bg=colors["bg"], fg=colors["fg"], width=12, anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row_id, textvariable=self.tg_api_id_var, font=("Segoe UI", 9),
            bg=colors["surface"], fg=colors["fg"], relief=tk.SOLID, bd=1,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # API Hash field
        row_hash = tk.Frame(card_api, bg=colors["bg"])
        row_hash.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            row_hash, text="API Hash:", font=("Segoe UI", 9, "bold"),
            bg=colors["bg"], fg=colors["fg"], width=12, anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row_hash, textvariable=self.tg_api_hash_var, font=("Segoe UI", 9),
            bg=colors["surface"], fg=colors["fg"], relief=tk.SOLID, bd=1,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _save_api_creds():
            raw_id = self.tg_api_id_var.get().strip()
            raw_hash = self.tg_api_hash_var.get().strip()
            if not raw_id or not raw_id.isdigit():
                messagebox.showerror("Lỗi", "API ID phải là số nguyên (ví dụ: 12345678).", parent=self.top)
                return
            if not raw_hash or len(raw_hash) < 10:
                messagebox.showerror("Lỗi", "API Hash không hợp lệ.", parent=self.top)
                return
            self.settings.set("telegram", "api_id", raw_id)
            self.settings.set("telegram", "api_hash", raw_hash)
            TelegramManager.get_instance().set_credentials(int(raw_id), raw_hash)
            messagebox.showinfo("Thành công", "Đã lưu thông tin Telegram API!", parent=self.top)

        tk.Button(
            card_api,
            text="  Lưu cấu hình API  ",
            command=_save_api_creds,
            bg=colors["accent"],
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=14,
            pady=5,
            cursor="hand2",
        ).pack(anchor="w")

        # ------------------------------------------------------------------ #
        #  RIGHT: Multi-account management                                    #
        # ------------------------------------------------------------------ #
        card_acc = tk.LabelFrame(
            right_col,
            text=" Quản lý tài khoản Telegram ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=10,
            pady=8,
        )
        card_acc.pack(fill=tk.BOTH, expand=True)

        hint_lbl = tk.Label(
            card_acc,
            text="✓ = tài khoản sẽ được dùng để xem video. Tick để bật/tắt.",
            font=("Segoe UI", 8, "italic"),
            bg=colors["bg"],
            fg=colors["disabled"],
            anchor="w",
        )
        hint_lbl.pack(fill=tk.X, pady=(0, 6))

        # Scrollable accounts area
        list_outer = tk.Frame(card_acc, bg=colors["border"], bd=1, relief=tk.SOLID)
        list_outer.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        canvas = tk.Canvas(list_outer, bg=colors["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        self._tg_accounts_frame = tk.Frame(canvas, bg=colors["bg"])

        self._tg_accounts_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas_window = canvas.create_window((0, 0), window=self._tg_accounts_frame, anchor="nw")

        def _on_canvas_resize(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Add Account button
        btn_add = tk.Button(
            card_acc,
            text="  + Thêm tài khoản mới  ",
            command=self._add_telegram_account,
            bg=colors["surface"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=10,
            pady=5,
            cursor="hand2",
        )
        btn_add.pack(anchor="w")

        # Populate existing accounts
        self._rebuild_accounts_list(colors)

    def _safe_after(self, fn: Callable[[], None]) -> None:
        """Safely schedule a callback on the Tkinter main thread if window still exists."""
        try:
            if hasattr(self, "top") and self.top is not None and self.top.winfo_exists():
                self.top.after(0, fn)
        except Exception:
            pass

    def _rebuild_accounts_list(self, colors: Optional[Dict[str, str]] = None) -> None:
        """Rebuild the accounts list UI from TelegramManager accounts."""
        from main.telegram_manager import TelegramManager
        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        if self._tg_accounts_frame is None:
            return

        # Clear existing widgets
        for widget in self._tg_accounts_frame.winfo_children():
            widget.destroy()
        self._tg_account_vars.clear()

        tg_mgr = TelegramManager.get_instance()
        accounts = tg_mgr.get_accounts()

        if not accounts:
            empty_lbl = tk.Label(
                self._tg_accounts_frame,
                text="Chưa có tài khoản nào. Nhấn '+ Thêm tài khoản mới' để bắt đầu.",
                font=("Segoe UI", 9, "italic"),
                bg=colors["bg"],
                fg=colors["disabled"],
                pady=16,
                padx=10,
            )
            empty_lbl.pack(fill=tk.X)
            return

        for idx, acc in enumerate(accounts):
            self._build_account_row(acc, idx, colors)

    def _build_account_row(
        self,
        acc,
        idx: int,
        colors: Optional[Dict[str, str]] = None,
    ) -> None:
        """Build one row for an account in the accounts list."""
        from main.telegram_manager import TelegramManager
        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        row_bg = colors["surface"] if idx % 2 == 0 else colors["bg"]

        row = tk.Frame(self._tg_accounts_frame, bg=row_bg, pady=6, padx=8)
        row.pack(fill=tk.X, pady=(0, 1))
        row.grid_columnconfigure(1, weight=1)

        # Checkbox: active/inactive
        active_var = tk.BooleanVar(value=acc.active)
        last_user_info = [None]  # Cache user info: None=checking, dict=logged in, False=not logged in

        def _format_status_text() -> str:
            state_tag = "● Đang dùng" if active_var.get() else "○ Đã tắt"
            info = last_user_info[0]
            if isinstance(info, dict):
                name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
                phone = info.get('phone', '')
                user_str = f"+{phone} ({name})" if phone else name
                return f"[{acc.label}] {state_tag} | {user_str}"
            elif info is False:
                return f"[{acc.label}] {state_tag} | Chưa đăng nhập"
            else:
                return f"[{acc.label}] {state_tag} | Đang kiểm tra..."

        def _on_toggle(a=acc, v=active_var):
            a.active = v.get()
            status_var.set(_format_status_text())
            # Immediately persist to settings so choice is never lost
            tg_mgr = TelegramManager.get_instance()
            self.settings.set("telegram", "accounts", tg_mgr.get_accounts_as_dicts())

        cb = tk.Checkbutton(
            row,
            text="Dùng",
            variable=active_var,
            onvalue=True,
            offvalue=False,
            command=_on_toggle,
            bg=row_bg,
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=row_bg,
            activeforeground=colors["fg"],
            highlightthickness=0,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )
        cb.grid(row=0, column=0, sticky="w", padx=(0, 6))

        # Name / phone status label
        status_var = tk.StringVar(value=_format_status_text())
        self._tg_account_vars[id(acc)] = (active_var, status_var)

        name_lbl = tk.Label(
            row,
            textvariable=status_var,
            font=("Segoe UI", 9),
            bg=row_bg,
            fg=colors["fg"],
            anchor="w",
            cursor="hand2",
        )
        name_lbl.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        # Clicking the label also toggles the checkbox for better UX
        def _on_lbl_click(e, v=active_var):
            v.set(not v.get())
            _on_toggle()

        name_lbl.bind("<Button-1>", _on_lbl_click)

        # Buttons frame
        btn_frame = tk.Frame(row, bg=row_bg)
        btn_frame.grid(row=0, column=2, sticky="e")

        login_btn = tk.Button(
            btn_frame,
            text="Đăng nhập",
            font=("Segoe UI", 8),
            bg=colors["accent"],
            fg="#ffffff",
            relief=tk.FLAT,
            padx=8,
            pady=2,
            cursor="hand2",
            command=lambda a=acc, sv=status_var: self._start_qr_for_account(a, sv, colors),
        )
        login_btn.pack(side=tk.LEFT, padx=(0, 4))

        logout_btn = tk.Button(
            btn_frame,
            text="Đăng xuất",
            font=("Segoe UI", 8),
            bg=colors["surface"],
            fg=colors["fg"],
            relief=tk.FLAT,
            padx=8,
            pady=2,
            cursor="hand2",
            command=lambda a=acc, sv=status_var, lb=login_btn: self._logout_account(a, sv, lb),
        )
        logout_btn.pack(side=tk.LEFT, padx=(0, 4))

        remove_btn = tk.Button(
            btn_frame,
            text="✕",
            font=("Segoe UI", 8, "bold"),
            bg=colors["surface"],
            fg="#e05c5c",
            relief=tk.FLAT,
            padx=6,
            pady=2,
            cursor="hand2",
            command=lambda a=acc: self._remove_account(a, colors),
        )
        remove_btn.pack(side=tk.LEFT)

        # Async status check
        tg_mgr = TelegramManager.get_instance()

        def _check_status(a=acc, sv=status_var, lbtn=login_btn, obtbtn=logout_btn):
            try:
                info = tg_mgr.get_account_user_info(a)
                def _update(i=info, s=sv, l=lbtn, o=obtbtn):
                    last_user_info[0] = i if i else False
                    s.set(_format_status_text())
                    if i:
                        try:
                            l.configure(state=tk.DISABLED)
                            o.configure(state=tk.NORMAL)
                        except Exception:
                            pass
                    else:
                        try:
                            l.configure(state=tk.NORMAL)
                            o.configure(state=tk.DISABLED)
                        except Exception:
                            pass
                self._safe_after(_update)
            except Exception as e:
                self._safe_after(lambda sv=sv, a=a: sv.set(f"[{a.label}] Lỗi: {e}"))

        threading.Thread(target=_check_status, daemon=True).start()

    def _add_telegram_account(self) -> None:
        """Add a new Telegram account slot and refresh the list."""
        from main.telegram_manager import TelegramManager
        raw_id = self.tg_api_id_var.get().strip()
        raw_hash = self.tg_api_hash_var.get().strip()
        if not raw_id or not raw_id.isdigit() or not raw_hash:
            messagebox.showwarning(
                "Thiếu thông tin API",
                "Vui lòng nhập và lưu API ID và API Hash trước khi thêm tài khoản.",
                parent=self.top,
            )
            return
        tg_mgr = TelegramManager.get_instance()
        tg_mgr.set_credentials(int(raw_id), raw_hash)
        tg_mgr.add_account()
        colors = self.theme.PALETTES[self.theme.current_theme]
        self._rebuild_accounts_list(colors)

    def _start_qr_for_account(self, acc, status_var: tk.StringVar, colors: Dict[str, str]) -> None:
        """Start QR login for a specific account."""
        from main.telegram_manager import TelegramManager
        raw_id = self.tg_api_id_var.get().strip()
        raw_hash = self.tg_api_hash_var.get().strip()
        if not raw_id or not raw_id.isdigit() or not raw_hash:
            messagebox.showwarning("Thiếu thông tin API", "Vui lòng nhập API ID và API Hash trước.", parent=self.top)
            return

        tg_mgr = TelegramManager.get_instance()
        tg_mgr.set_credentials(int(raw_id), raw_hash)

        # Create QR popup dialog
        qr_win = tk.Toplevel(self.top)
        qr_win.title(f"Đăng nhập QR — {acc.label}")
        qr_win.resizable(False, False)
        qr_win.grab_set()
        qr_win.configure(bg=colors["bg"])

        cancel_event = threading.Event()

        tk.Label(
            qr_win,
            text=f"Đăng nhập tài khoản: {acc.label}",
            font=("Segoe UI", 10, "bold"),
            bg=colors["bg"],
            fg=colors["fg"],
        ).pack(pady=(12, 4), padx=20)

        tk.Label(
            qr_win,
            text="1. Mở app Telegram trên điện thoại\n2. Cài đặt > Thiết bị > Quét mã QR\n3. Hướng camera quét mã bên dưới:",
            font=("Segoe UI", 9),
            bg=colors["bg"],
            fg=colors["fg"],
            justify=tk.LEFT,
        ).pack(padx=20, pady=(0, 8))

        qr_img_lbl = tk.Label(qr_win, bg=colors["bg"], text="Đang tạo mã QR...")
        qr_img_lbl.pack(pady=6)

        qr_status_lbl = tk.Label(
            qr_win,
            text="Đang kết nối...",
            font=("Segoe UI", 8, "italic"),
            bg=colors["bg"],
            fg=colors["disabled"],
        )
        qr_status_lbl.pack(pady=(0, 6))

        _photo_ref = [None]

        def _safe_qr_after(fn):
            try:
                if qr_win.winfo_exists():
                    qr_win.after(0, fn)
            except Exception:
                pass

        def on_qr_ready(pil_img):
            resized = pil_img.resize((200, 200))
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(resized)
            def _upd():
                _photo_ref[0] = photo
                qr_img_lbl.configure(image=photo, text="")
                qr_status_lbl.configure(text="Đang chờ quét mã từ app Telegram...")
            _safe_qr_after(_upd)

        def on_success(user_info):
            def _upd():
                name = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
                phone = user_info.get('phone', '')
                display = f"+{phone} ({name})" if phone else name
                status_var.set(f"[{acc.label}] ✓ {display}")
                try:
                    qr_win.destroy()
                except Exception:
                    pass
                messagebox.showinfo("Đăng nhập thành công", f"Đã kết nối: {name}", parent=self.top)
                # Refresh the whole list to update button states
                self._safe_after(lambda: self._rebuild_accounts_list(colors))
            _safe_qr_after(_upd)

        def on_fail(err):
            def _upd():
                qr_status_lbl.configure(text=f"Thất bại: {err}")
                messagebox.showerror("Lỗi đăng nhập", f"Không thể đăng nhập: {err}", parent=self.top)
                try:
                    qr_win.destroy()
                except Exception:
                    pass
            _safe_qr_after(_upd)

        def on_2fa_required():
            def _prompt():
                pwd = simpledialog.askstring(
                    "Xác thực 2 bước (2FA)",
                    f"Tài khoản '{acc.label}' đã bật xác thực 2 bước.\nVui lòng nhập mật khẩu:",
                    show="*",
                    parent=qr_win if qr_win.winfo_exists() else self.top,
                )
                if not pwd:
                    on_fail("Đã hủy nhập mật khẩu 2FA.")
                    return
                try:
                    user = tg_mgr.submit_2fa_password(acc, pwd)
                    on_success(user)
                except Exception as e:
                    on_fail(f"Mật khẩu 2FA không đúng: {e}")
            self._safe_after(_prompt)

        def _close_qr():
            cancel_event.set()
            try:
                qr_win.destroy()
            except Exception:
                pass

        tk.Button(
            qr_win,
            text="Hủy",
            command=_close_qr,
            bg=colors["surface"],
            fg=colors["fg"],
            font=("Segoe UI", 8),
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(pady=(0, 12))

        qr_win.protocol("WM_DELETE_WINDOW", _close_qr)

        # Center relative to parent
        qr_win.update_idletasks()
        pw = self.top.winfo_rootx()
        ph = self.top.winfo_rooty()
        qr_win.geometry(f"+{pw + 100}+{ph + 80}")

        threading.Thread(
            target=lambda: tg_mgr.start_qr_login(
                acc, on_qr_ready, on_success, on_fail, on_2fa_required, cancel_event
            ),
            daemon=True,
        ).start()

    def _logout_account(self, acc, status_var: tk.StringVar, login_btn: tk.Button) -> None:
        """Log out a specific account."""
        if not messagebox.askyesno(
            "Xác nhận đăng xuất",
            f"Bạn có chắc muốn đăng xuất tài khoản '{acc.label}'?",
            parent=self.top,
        ):
            return
        from main.telegram_manager import TelegramManager
        TelegramManager.get_instance().logout(acc)
        status_var.set(f"[{acc.label}] Chưa đăng nhập")
        try:
            login_btn.configure(state=tk.NORMAL)
        except Exception:
            pass
        messagebox.showinfo("Đã đăng xuất", f"Đã đăng xuất tài khoản '{acc.label}'.", parent=self.top)

    def _remove_account(self, acc, colors: Dict[str, str]) -> None:
        """Remove an account from the list."""
        if not messagebox.askyesno(
            "Xác nhận xóa",
            f"Bạn có chắc muốn xóa tài khoản '{acc.label}'?\nPhiên đăng nhập sẽ bị xóa vĩnh viễn.",
            parent=self.top,
        ):
            return
        from main.telegram_manager import TelegramManager
        TelegramManager.get_instance().remove_account(acc)
        self._rebuild_accounts_list(colors)

    def _build_about_tab(self, colors: Optional[Dict[str, str]] = None) -> None:
        """About Tab displaying app metadata, licensing, media container capabilities, and Discord link."""
        import webbrowser
        from PIL import Image, ImageTk
        from main.constants import APP_NAME, APP_VERSION

        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        tab = self.tab_about

        container = tk.Frame(tab, bg=colors["bg"], padx=20, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        # 1. Hero Header (App Icon + Name + Tagline + Version)
        hero_frame = tk.Frame(container, bg=colors["bg"])
        hero_frame.pack(fill=tk.X, pady=(0, 14))

        icon_path = Path(__file__).resolve().parent / "image" / "icon-192.png"
        if not icon_path.is_file():
            icon_path = Path(__file__).resolve().parent / "image" / "app_icon.ico"

        if icon_path.is_file():
            try:
                pil_img = Image.open(icon_path).resize((56, 56), Image.Resampling.LANCZOS)
                self._about_app_icon = ImageTk.PhotoImage(pil_img)
                lbl_icon = tk.Label(hero_frame, image=self._about_app_icon, bg=colors["bg"])
                lbl_icon.pack(side=tk.LEFT, padx=(0, 14))
            except Exception:
                pass

        hero_text_frame = tk.Frame(hero_frame, bg=colors["bg"])
        hero_text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        lbl_app_name = tk.Label(
            hero_text_frame,
            text=f"{APP_NAME}",
            font=("Segoe UI", 16, "bold"),
            bg=colors["bg"],
            fg=colors["accent"],
        )
        lbl_app_name.pack(anchor=tk.W)

        lbl_tagline = tk.Label(
            hero_text_frame,
            text="Phần mềm phát video trực tuyến đa nền tảng, mượt mà và nhẹ máy",
            font=("Segoe UI", 9, "italic"),
            bg=colors["bg"],
            fg=colors["disabled"],
        )
        lbl_tagline.pack(anchor=tk.W, pady=(2, 3))

        lbl_version = tk.Label(
            hero_text_frame,
            text=f"Phiên bản: v{APP_VERSION}",
            font=("Segoe UI", 9, "bold"),
            bg=colors["bg"],
            fg=colors["fg"],
        )
        lbl_version.pack(anchor=tk.W)

        # 2. Content 2-Column Grid
        cols_frame = tk.Frame(container, bg=colors["bg"])
        cols_frame.pack(fill=tk.BOTH, expand=True)
        cols_frame.grid_columnconfigure(0, weight=1, uniform="about_col")
        cols_frame.grid_columnconfigure(1, weight=1, uniform="about_col")

        left_col = tk.Frame(cols_frame, bg=colors["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right_col = tk.Frame(cols_frame, bg=colors["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # --- Left Column: Card 1 (Tác giả & Bản quyền) ---
        card_dev = tk.LabelFrame(
            left_col,
            text=" Tác giả & Bản quyền ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=14,
            pady=10,
        )
        card_dev.pack(fill=tk.X, pady=(0, 10))

        dev_items = [
            ("Tác giả / Phát triển:", "P A U L / JustFun"),
            ("Bản quyền (Copyright):", "© 2026 P A U L / JustFun. All rights reserved."),
            ("Giấy phép (License):", "Freeware (Miễn phí cho mục đích cá nhân)"),
        ]
        for row_idx, (k, v) in enumerate(dev_items):
            tk.Label(
                card_dev,
                text=k,
                font=("Segoe UI", 9, "bold"),
                bg=colors["bg"],
                fg=colors["fg"],
            ).grid(row=row_idx * 2, column=0, sticky=tk.W, pady=(4 if row_idx > 0 else 0, 1))
            tk.Label(
                card_dev,
                text=v,
                font=("Segoe UI", 9),
                bg=colors["bg"],
                fg=colors["disabled"] if "rights reserved" in v else colors["fg"],
            ).grid(row=row_idx * 2 + 1, column=0, sticky=tk.W, pady=(0, 4))

        # --- Left Column: Card 2 (Cộng đồng Discord) ---
        card_community = tk.LabelFrame(
            left_col,
            text=" Cộng đồng & Hỗ trợ ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=14,
            pady=10,
        )
        card_community.pack(fill=tk.X)

        tk.Label(
            card_community,
            text="Tham gia máy chủ Discord để trao đổi và nhận thông báo mới:",
            font=("Segoe UI", 9),
            bg=colors["bg"],
            fg=colors["fg"],
        ).pack(anchor=tk.W, pady=(0, 8))

        # Dynamic Discord logo based on theme:
        # - Theme 'system': Discord-Logo-Blurple.png
        # - Theme 'light': Discord-Logo-Black.png
        # - Theme 'dark': Discord-Logo-White.png
        theme_mode = getattr(self.theme, "mode", "system").lower()
        curr_theme = getattr(self.theme, "current_theme", "dark").lower()
        if theme_mode == "system":
            logo_name = "Discord-Logo-Blurple.png"
        elif curr_theme == "light":
            logo_name = "Discord-Logo-Black.png"
        else:
            logo_name = "Discord-Logo-White.png"

        discord_img_path = Path(__file__).resolve().parent / "image" / logo_name
        if not discord_img_path.is_file():
            discord_img_path = Path(__file__).resolve().parent / "image" / "Discord-Logo-Blurple.png"

        try:
            pil_discord = Image.open(discord_img_path)
            # Aspect ratio is ~ 6.6 : 1 (2647, 400). Scale to height 26px -> width ~ 172px
            target_h = 26
            target_w = int(target_h * pil_discord.width / pil_discord.height)
            pil_discord_resized = pil_discord.resize((target_w, target_h), Image.Resampling.LANCZOS)
            self._about_discord_logo = ImageTk.PhotoImage(pil_discord_resized)

            btn_discord = tk.Button(
                card_community,
                image=self._about_discord_logo,
                bg=colors["surface_variant"],
                activebackground=colors["surface"],
                relief=tk.FLAT,
                bd=0,
                padx=12,
                pady=6,
                cursor="hand2",
                command=lambda: webbrowser.open("https://discord.gg/9gM5FAXDrC"),
            )
            btn_discord.pack(anchor=tk.W, pady=(2, 4))
        except Exception:
            btn_discord = tk.Button(
                card_community,
                text="  Tham gia Discord (https://discord.gg/9gM5FAXDrC)  ",
                font=("Segoe UI", 9, "bold"),
                bg=colors["accent"],
                fg="#ffffff",
                relief=tk.FLAT,
                bd=0,
                padx=14,
                pady=6,
                cursor="hand2",
                command=lambda: webbrowser.open("https://discord.gg/9gM5FAXDrC"),
            )
            btn_discord.pack(anchor=tk.W, pady=(2, 4))

        # --- Right Column: Card 3 (Định dạng & Container) ---
        card_media = tk.LabelFrame(
            right_col,
            text=" Định dạng & Nền tảng hỗ trợ ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=14,
            pady=10,
        )
        card_media.pack(fill=tk.X, pady=(0, 10))

        media_items = [
            ("Container & Video:", "MP4, MKV, WebM, M3U8 (HLS), MPD (DASH), TS"),
            ("Nền tảng hỗ trợ:", "Các nền tảng video trực tuyến phổ biến, luồng phát trực tiếp (Live) & tệp tin cục bộ"),
            ("Công nghệ cốt lõi:", "libVLC 64-bit • yt-dlp • Tkinter Fluent Design (sv_ttk)"),
        ]
        for row_idx, (k, v) in enumerate(media_items):
            tk.Label(
                card_media,
                text=k,
                font=("Segoe UI", 9, "bold"),
                bg=colors["bg"],
                fg=colors["fg"],
            ).grid(row=row_idx * 2, column=0, sticky=tk.W, pady=(4 if row_idx > 0 else 0, 1))
            tk.Label(
                card_media,
                text=v,
                font=("Segoe UI", 9),
                bg=colors["bg"],
                fg=colors["fg"],
                wraplength=360,
                justify=tk.LEFT,
            ).grid(row=row_idx * 2 + 1, column=0, sticky=tk.W, pady=(0, 4))

        # --- Right Column: Card 4 (Kiểm tra cập nhật) ---
        card_update = tk.LabelFrame(
            right_col,
            text=" Cập nhật phần mềm ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=14,
            pady=10,
        )
        card_update.pack(fill=tk.X)

        tk.Label(
            card_update,
            text=f"Phiên bản hiện tại: v{APP_VERSION}",
            font=("Segoe UI", 9),
            bg=colors["bg"],
            fg=colors["fg"],
        ).pack(anchor=tk.W, pady=(0, 6))

        self.btn_check_update = tk.Button(
            card_update,
            text="🔄  Kiểm tra bản cập nhật",
            font=("Segoe UI", 9),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["accent"],
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._check_for_updates,
        )
        self.btn_check_update.pack(anchor=tk.W)

    def _check_for_updates(self) -> None:
        """Check for updates asynchronously on user request from About tab."""
        from main.updater import check_for_updates
        from main.constants import APP_VERSION
        import threading

        btn = getattr(self, "btn_check_update", None)
        if btn:
            btn.config(text="⏳  Đang kiểm tra...", state=tk.DISABLED)

        def _worker():
            info = check_for_updates()

            def _apply():
                try:
                    if not hasattr(self, "top") or not self.top.winfo_exists():
                        return
                    if btn and btn.winfo_exists():
                        btn.config(text="🔄  Kiểm tra bản cập nhật", state=tk.NORMAL)
                    if info:
                        ans = messagebox.askyesno(
                            "Có bản cập nhật mới!",
                            f"Đã có phiên bản mới: v{info.version}!\n\n"
                            f"Tiêu đề: {info.title}\n"
                            f"Tệp cập nhật: {info.asset_name} ({info.asset_size // 1024 // 1024} MB)\n\n"
                            f"Ghi chú:\n{info.release_notes[:250]}\n\n"
                            "Bạn có muốn tải về và cập nhật ngay bây giờ không?\n"
                            "(Video đang xem sẽ không bị gián đoạn trong khi tải)",
                            parent=self.top,
                        )
                        if ans:
                            self.top.destroy()
                            if self.on_update_request:
                                self.on_update_request(info)
                    else:
                        messagebox.showinfo(
                            "Kiểm tra cập nhật",
                            f"Bạn đang sử dụng phiên bản FB Video Watcher mới nhất (v{APP_VERSION}).",
                            parent=self.top,
                        )
                except Exception:
                    pass

            try:
                self.top.after(0, _apply)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()



    def _build_action_buttons(self, colors: Optional[Dict[str, str]] = None) -> None:
        """Bottom action buttons bar with separator line."""
        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        btn_frame = tk.Frame(self.top, bg=colors["bg"], padx=16, pady=10)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        btn_save = tk.Button(
            btn_frame,
            text="Lưu & Áp dụng",
            font=("Segoe UI", 9, "bold"),
            bg=colors["accent"],
            fg="#ffffff",
            activebackground=colors["accent_hover"],
            activeforeground="#ffffff",
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=6,
            cursor="hand2",
            command=self._save_and_close,
        )
        btn_save.pack(side=tk.RIGHT, padx=(8, 0))

        btn_cancel = tk.Button(
            btn_frame,
            text="Hủy",
            font=("Segoe UI", 9),
            bg=colors["surface_variant"],
            fg=colors["fg"],
            activebackground=colors["surface"],
            activeforeground=colors["fg"],
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.top.destroy,
        )
        btn_cancel.pack(side=tk.RIGHT)

        sep = tk.Frame(self.top, height=1, bg=colors["border"])
        sep.pack(fill=tk.X, side=tk.BOTTOM)

    def _save_and_close(self) -> None:
        """Save settings and apply immediate updates."""
        try:
            self.settings.set("video", "max_height", int(self.max_height_var.get()))
            self.settings.set("streaming", "network_caching", int(self.buffer_var.get()))
            self.settings.set("streaming", "hardware_decode", self.hw_decode_var.get())
            self.settings.set("ui", "always_on_top", self.always_top_var.get())
            self.settings.set("ui", "clipboard_auto_detect", self.clipboard_auto_detect_var.get())
            self.settings.set("ui", "seek_short", int(self.seek_short_var.get()))
            self.settings.set("ui", "seek_long", int(self.seek_long_var.get()))
            self.settings.set("playback", "resume_playback", self.resume_playback_var.get())
            self.settings.set("advanced", "cookie_file", self.cookie_var.get().strip())
            self.settings.set("download", "download_dir", self.download_dir_var.get().strip())
            self.settings.set("download", "always_ask", self.always_ask_download_var.get())
            self.settings.set("download", "format", self.download_format_var.get())
            self.settings.set("download", "show_toast", self.download_toast_var.get())
            self.settings.set("performance", "cpu_affinity_mode", self.cpu_affinity_var.get())
            self.settings.set("performance", "disable_eco_qos", self.disable_eco_qos_var.get())
            self.settings.set("performance", "high_precision_timer", self.high_precision_timer_var.get())

            # Save Telegram configuration
            from main.telegram_manager import TelegramManager
            raw_tg_id = self.tg_api_id_var.get().strip()
            raw_tg_hash = self.tg_api_hash_var.get().strip()
            self.settings.set("telegram", "api_id", raw_tg_id)
            self.settings.set("telegram", "api_hash", raw_tg_hash)
            # Save multi-account list
            tg_mgr = TelegramManager.get_instance()
            self.settings.set("telegram", "accounts", tg_mgr.get_accounts_as_dicts())
            if raw_tg_id.isdigit() and raw_tg_hash:
                tg_mgr.set_credentials(int(raw_tg_id), raw_tg_hash)

            # Save customized hotkeys
            for aid, var in self.hotkey_vars.items():
                self.settings.set("hotkeys", aid, var.get().strip())

            # Save subtitle configuration
            try:
                sub_size = max(10, min(512, int(self.sub_size_var.get().strip())))
            except Exception:
                sub_size = 36

            try:
                sub_thick = int(str(self.sub_outline_thickness_var.get()).split()[0])
            except Exception:
                sub_thick = 2

            sub_dict = {
                "file": self.sub_file_var.get().strip(),
                "font_family": self.sub_font_var.get().strip() or "Segoe UI",
                "font_size": sub_size,
                "text_color": self.sub_text_color_var.get().strip() or "#ffffff",
                "bold": bool(self.sub_bold_var.get()),
                "italic": bool(self.sub_italic_var.get()),
                "underline": bool(self.sub_underline_var.get()),
                "outline_color": self.sub_outline_color_var.get().strip() or "#000000",
                "outline_thickness": sub_thick,
                "bg_enabled": bool(self.sub_bg_enabled_var.get()),
                "bg_color": self.sub_bg_color_var.get().strip() or "#000000",
                "bg_opacity": int(self.sub_bg_opacity_var.get()),
            }
            self.settings.set("subtitle", sub_dict)

            new_theme = self.theme_var.get()
            old_theme = self.settings.get("ui", "theme", default="system")
            self.settings.set("ui", "theme", new_theme)

            # Apply immediate theme change if modified
            if new_theme != old_theme:
                self.theme.apply_theme(new_theme)

            # Apply immediate topmost change
            self.top.master.attributes("-topmost", self.always_top_var.get())

            if self.on_save_callback:
                self.on_save_callback()

            self.top.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi lưu cài đặt", str(e))
