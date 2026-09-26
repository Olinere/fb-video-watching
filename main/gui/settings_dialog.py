"""
Settings dialog module for FB Video Watcher.
Includes SettingsDialog with multi-tab Fluent styling: General, Hotkeys,
Subtitles, Telegram, Network & Proxy, System Info, and About.
"""

import sys
import logging
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser, simpledialog
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable, Optional, Dict, Any, Tuple
from PIL import Image, ImageDraw, ImageTk

logger = logging.getLogger("FBVideoWatcher.SettingsDialog")

from main.constants import (
    APP_NAME,
    APP_VERSION,
    ICON_FILE,
)
from main.theme import ThemeManager
from main.settings import SettingsManager
from main.system_info import SystemInfo
from main.auto_tune import AutoTuner
from main.platform_utils import apply_window_icon, set_windows_dark_titlebar
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
        on_dev_mode_unlocked: Optional[Callable[[], None]] = None,
        on_osd_message: Optional[Callable[[str], None]] = None,
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
        self.on_dev_mode_unlocked = on_dev_mode_unlocked
        self.on_osd_message = on_osd_message
        self._dev_click_count = 0
        self._last_click_time = 0.0

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
        self.gpu_preference_var = tk.StringVar(value=str(perf_cfg.get("gpu_preference", "auto")))

        # Initialize Queue persistence & Windows Protocol variables
        self.queue_persist_var = tk.BooleanVar(value=bool(self.settings.get("playback", "queue_persist", default=False)))
        try:
            from main.platform_utils import is_fbvw_protocol_registered
            self.fbvw_proto_var = tk.BooleanVar(value=bool(is_fbvw_protocol_registered()))
        except Exception:
            self.fbvw_proto_var = tk.BooleanVar(value=False)

        # Initialize PiP Aspect Ratio variables from settings
        self.pip_aspect_ratio_var = tk.StringVar(
            value=str(self.settings.get("ui", "pip_aspect_ratio", default="16:9"))
        )
        self.pip_auto_aspect_var = tk.BooleanVar(
            value=bool(self.settings.get("ui", "pip_auto_aspect_ratio", default=False))
        )

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

        # Initialize Network & Proxy variables from settings
        net_cfg = self.settings.get("network", default={})
        if not isinstance(net_cfg, dict):
            net_cfg = {}
        self.proxy_mode_var = tk.StringVar(value=str(net_cfg.get("proxy_mode", "direct")))
        self.proxy_protocol_var = tk.StringVar(value=str(net_cfg.get("proxy_protocol", "http")))
        self.proxy_host_var = tk.StringVar(value=str(net_cfg.get("proxy_host", "")))
        raw_port = net_cfg.get("proxy_port", 0)
        self.proxy_port_var = tk.StringVar(value=str(raw_port) if raw_port else "")
        self.proxy_user_var = tk.StringVar(value=str(net_cfg.get("proxy_user", "")))
        self.proxy_pass_var = tk.StringVar(value=str(net_cfg.get("proxy_pass", "")))
        self.proxy_show_pass_var = tk.BooleanVar(value=False)
        self.proxy_test_status_var = tk.StringVar(value="")

        self.doh_enabled_var = tk.BooleanVar(value=bool(net_cfg.get("doh_enabled", False)))
        self.doh_provider_var = tk.StringVar(value=str(net_cfg.get("doh_provider", "cloudflare")))
        self.doh_custom_url_var = tk.StringVar(value=str(net_cfg.get("doh_custom_url", "")))
        self.doh_test_status_var = tk.StringVar(value="")

        # Size: 960x720 provides wide, comfortable columns so hotkey and settings text is fully visible
        screen_w = parent.winfo_screenwidth()
        screen_h = parent.winfo_screenheight()
        dialog_w = min(960, max(900, screen_w - 40))
        dialog_h = min(720, max(620, screen_h - 60))
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = max(10, px + max(0, (pw - dialog_w) // 2))
        y = max(10, py + max(0, (ph - dialog_h) // 2))
        self.top.geometry(f"{dialog_w}x{dialog_h}+{x}+{y}")
        self.top.minsize(860, 520)
        self.top.resizable(True, True)
        self.top.transient(parent)
        # Non-modal: do NOT call grab_set() so user can still interact with
        # the main window (e.g. pause/play video) while settings is open.
        self._preview_timer: Optional[str] = None
        self._osd_timer: Optional[str] = None
        self.top.bind("<Destroy>", self._cleanup_dialog, add="+")

        # In-dialog OSD badge for feedback (e.g. Easter Egg countdown / unlock)
        self._osd_label = tk.Label(
            self.top,
            text="",
            font=("Segoe UI", 10, "bold"),
            bg="#1c1c1c",
            fg="#e0e0e0",
            padx=16,
            pady=8,
            relief=tk.RIDGE,
            bd=1,
        )

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

        self.tab_network = tk.Frame(self.content_area, bg=colors["bg"])
        self.tab_network.grid(row=0, column=0, sticky="nsew")

        self._build_general_tab(colors)
        self._build_hotkeys_tab(colors)
        self._build_subtitles_tab(colors)
        self._build_telegram_tab(colors)
        self._build_network_tab(colors)
        self._build_system_info_tab(colors)
        self._build_about_tab(colors)

        # Tab navigation buttons (instant .lift() switching without unmapping lag)
        self._tab_buttons: Dict[str, tk.Button] = {}
        tab_defs = [
            ("general", "  Cấu hình chung  ", self.tab_general),
            ("hotkeys", "  Phím tắt  ", self.tab_hotkeys),
            ("subtitles", "  Phụ đề  ", self.tab_subtitles),
            ("telegram", "  Telegram  ", self.tab_telegram),
            ("network", "  Mạng & Proxy  ", self.tab_network),
            ("sys_info", "  Thông tin hệ thống  ", self.tab_sys_info),
            ("about", "  Về ứng dụng  ", self.tab_about),
        ]

        def _switch_tab(tab_id: str, target_frame: tk.Frame):
            target_frame.lift()
            for w in target_frame.winfo_children():
                if isinstance(w, tk.Canvas):
                    c_w = w.winfo_width()
                    if c_w > 100:
                        for item in w.find_all():
                            try:
                                win_widget = w.nametowidget(w.itemcget(item, "window"))
                                win_widget.configure(width=c_w)
                                w.itemconfig(item, width=c_w)
                            except Exception:
                                pass
            if tab_id == "subtitles":
                self._schedule_subtitle_preview(20)
            if tab_id == "telegram":
                try:
                    self.top.after(20, self._refresh_telegram_status)
                except Exception:
                    pass
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
                padx=12,
                pady=6,
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=2)
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

        self.notebook = NotebookAdapter([self.tab_general, self.tab_hotkeys, self.tab_subtitles, self.tab_telegram, self.tab_network, self.tab_sys_info, self.tab_about])

        # 5. Flush all layout computations in memory while window is still hidden!
        self.top.update_idletasks()
        if hasattr(self, "tab_general"):
            for w in self.tab_general.winfo_children():
                if isinstance(w, tk.Canvas):
                    c_w = w.winfo_width()
                    if c_w > 100:
                        for item in w.find_all():
                            try:
                                win_widget = w.nametowidget(w.itemcget(item, "window"))
                                win_widget.configure(width=c_w)
                                w.itemconfig(item, width=c_w)
                            except Exception:
                                pass
        self.top.update_idletasks()

        # 6. Reveal dialog instantly — 1 single finished frame, zero layout shift!
        if not self._parent_withdrawn:
            self.top.deiconify()
            self.top.lift()
            self.top.focus_set()

    def show_osd(self, text: str) -> None:
        """Display an on-screen toast notification inside the Settings dialog and main window."""
        if getattr(self, "_osd_timer", None) is not None:
            try:
                self.top.after_cancel(self._osd_timer)
            except Exception:
                pass
            self._osd_timer = None

        if hasattr(self, "_osd_label") and self._osd_label.winfo_exists():
            self._osd_label.configure(text=text)
            self._osd_label.place(relx=0.5, rely=0.91, anchor=tk.S)
            self._osd_label.lift()
            self._osd_timer = self.top.after(
                2500,
                lambda: self._osd_label.place_forget()
                if hasattr(self, "_osd_label") and self._osd_label.winfo_exists()
                else None,
            )

        if self.on_osd_message:
            try:
                self.on_osd_message(text)
            except Exception:
                pass

    def _on_app_name_clicked(self, event=None) -> None:
        """Handle 7 clicks on app name to unlock developer mode (Android-style Easter Egg)."""
        if self.settings.get("ui", "dev_mode_unlocked", default=False):
            self.show_osd("ℹ️ Chế độ nhà phát triển đã được kích hoạt.")
            return

        import time
        now = time.time()
        if now - self._last_click_time > 3.0:
            self._dev_click_count = 0
        self._last_click_time = now
        self._dev_click_count += 1

        remaining = 7 - self._dev_click_count
        if 0 < remaining <= 3:
            self.show_osd(f"Còn {remaining} bước nữa để mở khóa Devlog.")
        elif remaining <= 0:
            self.settings.set("ui", "dev_mode_unlocked", True)
            self.settings.save()
            if self.on_dev_mode_unlocked:
                self.on_dev_mode_unlocked()
            self.show_osd("🛠 Đã mở khóa chế độ nhà phát triển (Devlog).")

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

        # Smooth scrollable canvas container ensuring all cards and actions are reachable
        canvas = tk.Canvas(tab, bg=colors["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=colors["bg"])

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        win_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_canvas_configure(event):
            canvas.itemconfig(win_id, width=event.width)
            scrollable_frame.configure(width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        cols_frame = tk.Frame(scrollable_frame, bg=colors["bg"], padx=14, pady=8)
        cols_frame.pack(fill=tk.BOTH, expand=True)
        cols_frame.grid_columnconfigure(0, weight=1, uniform="col")
        cols_frame.grid_columnconfigure(1, weight=1, uniform="col")

        left_col = tk.Frame(cols_frame, bg=colors["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right_col = tk.Frame(cols_frame, bg=colors["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        def _bind_all_wheel(w):
            try:
                w.bind("<MouseWheel>", _on_mousewheel, add="+")
            except Exception:
                pass
            for ch in w.winfo_children():
                _bind_all_wheel(ch)

        tab.after(100, lambda: _bind_all_wheel(scrollable_frame) if scrollable_frame.winfo_exists() else None)

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

        tk.Label(
            card_display,
            text="Tỷ lệ khung hình PiP:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=2, column=0, sticky=tk.W, pady=4)
        combo_pip = ttk.Combobox(
            card_display,
            textvariable=self.pip_aspect_ratio_var,
            values=["16:9", "9:16"],
            state="readonly",
            width=10,
        )
        combo_pip.grid(row=2, column=1, sticky=tk.W, padx=6, pady=4)
        tk.Label(
            card_display,
            text="(16:9 Ngang, 9:16 Dọc)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=2, column=2, sticky=tk.W)

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
        chk_top.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

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
        chk_resume.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=2)

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
        chk_clip.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=2)

        chk_queue_persist = tk.Checkbutton(
            card_display,
            text="Ghi nhớ hàng đợi phát khi đóng ứng dụng",
            variable=self.queue_persist_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_queue_persist.grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=2)

        chk_pip_auto = tk.Checkbutton(
            card_display,
            text="Tự động đổi tỷ lệ PiP theo video dọc (Reels/Shorts)",
            variable=self.pip_auto_aspect_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_pip_auto.grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=2)

        chk_fbvw_proto = tk.Checkbutton(
            card_display,
            text="Đăng ký liên kết fbvw:// (Mở video từ trình duyệt/web)",
            variable=self.fbvw_proto_var,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["entry_bg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        chk_fbvw_proto.grid(row=8, column=0, columnspan=3, sticky=tk.W, pady=2)

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

        # --- Left Column: Card 3 (Performance & CPU Scheduling) ---
        card_perf = tk.LabelFrame(
            left_col,
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
        ).grid(row=0, column=0, sticky=tk.W, pady=(4, 1))
        combo_affinity = ttk.Combobox(
            card_perf,
            textvariable=self.cpu_affinity_var,
            values=["auto", "p_cores", "all"],
            state="readonly",
            width=10,
        )
        combo_affinity.grid(row=0, column=1, sticky=tk.W, padx=6, pady=(4, 1))
        tk.Label(
            card_perf,
            text="(auto: Tự động | p_cores: Chỉ P-cores | all: Tất cả)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 4))

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
        chk_eco.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(2, 2))

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
        chk_timer.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=2)

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
        chk_hw.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(2, 2))

        # GPU Preference (Gaming Mode / Smart iGPU Offload)
        tk.Label(
            card_perf,
            text="Phân bổ GPU:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=5, column=0, sticky=tk.W, pady=(4, 1))
        combo_gpu = ttk.Combobox(
            card_perf,
            textvariable=self.gpu_preference_var,
            values=["auto", "integrated", "discrete", "software"],
            state="readonly",
            width=10,
        )
        combo_gpu.grid(row=5, column=1, sticky=tk.W, padx=6, pady=(4, 1))
        tk.Label(
            card_perf,
            text="(auto: Tự động | discrete: Tiết kiệm RAM nhất | integrated: iGPU * Cần khởi động lại)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=(0, 4))

        # Network caching
        tk.Label(
            card_perf,
            text="Bộ đệm mạng (Cache):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=7, column=0, sticky=tk.W, pady=4)
        self.buffer_var = tk.StringVar(value=str(self.settings.get("streaming", "network_caching", default=3000)))
        combo_buffer = ttk.Combobox(
            card_perf,
            textvariable=self.buffer_var,
            values=["1000", "2000", "3000", "5000"],
            state="readonly",
            width=10,
        )
        combo_buffer.grid(row=7, column=1, sticky=tk.W, padx=6, pady=4)
        tk.Label(
            card_perf,
            text="ms (3000: chuẩn)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=7, column=2, sticky=tk.W)

        # Playback Source Profile Mode
        tk.Label(
            card_perf,
            text="Cấu hình phát (Profile):",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=8, column=0, sticky=tk.W, pady=(4, 1))
        profiles_cfg = self.settings.get("source_profiles", default={})
        global_mode = "auto"
        if isinstance(profiles_cfg, dict):
            global_raw = profiles_cfg.get("global", {})
            if isinstance(global_raw, dict):
                global_mode = global_raw.get("mode", "auto")
        self.profile_mode_var = tk.StringVar(value=global_mode)
        combo_profile_mode = ttk.Combobox(
            card_perf,
            textvariable=self.profile_mode_var,
            values=["auto", "custom"],
            state="readonly",
            width=10,
        )
        combo_profile_mode.grid(row=8, column=1, sticky=tk.W, padx=6, pady=(4, 1))
        tk.Label(
            card_perf,
            text="(auto: tự tối ưu | custom: giữ nguyên)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["disabled"],
        ).grid(row=9, column=0, columnspan=3, sticky=tk.W, pady=(0, 4))

        # --- Right Column: Card 1 (Cookies) ---
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

        # --- Right Column: Card 2 (Download & Data) ---
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

        # Row 7: FFmpeg Add-on
        tk.Label(
            card_download,
            text="Tiện ích FFmpeg:",
            bg=colors["bg"],
            fg=colors["fg"],
            font=("Segoe UI", 9),
        ).grid(row=7, column=0, sticky=tk.W, pady=3)

        self.ffmpeg_status_var = tk.StringVar()
        lbl_ff = tk.Label(
            card_download,
            textvariable=self.ffmpeg_status_var,
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["fg"],
            anchor=tk.W,
            justify=tk.LEFT,
        )
        lbl_ff.grid(row=7, column=1, sticky=tk.W, padx=6, pady=3)

        self.btn_ffmpeg_action = tk.Button(
            card_download,
            text="📥 Tải FFmpeg",
            font=("Segoe UI", 8, "bold"),
            bg=colors["accent"],
            fg="#ffffff",
            activebackground=colors["accent_hover"],
            activeforeground="#ffffff",
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._on_install_ffmpeg_clicked,
        )
        self.btn_ffmpeg_action.grid(row=7, column=2, sticky=tk.W)

        def _refresh_ffmpeg_status():
            from main.ffmpeg_utils import is_ffmpeg_available, get_ffmpeg_path
            avail = is_ffmpeg_available()
            path = get_ffmpeg_path()
            if avail and path:
                self.ffmpeg_status_var.set("✅ Đã có (Ghép 1080p+ & MP3)")
                self.btn_ffmpeg_action.config(
                    text="🔄 Kiểm tra",
                    bg=colors["surface_variant"],
                    fg=colors["fg"],
                    command=_refresh_ffmpeg_status,
                )
            else:
                self.ffmpeg_status_var.set("⚠️ Chưa cài (Tải thường MP4)")
                self.btn_ffmpeg_action.config(
                    text="📥 Tải FFmpeg",
                    bg=colors["accent"],
                    fg="#ffffff",
                    command=self._on_install_ffmpeg_clicked,
                )

        self._refresh_ffmpeg_ui = _refresh_ffmpeg_status
        _refresh_ffmpeg_status()

    def _on_install_ffmpeg_clicked(self) -> None:
        """Launch FFmpeg setup and management dialog."""
        from main.ffmpeg_setup_dialog import FFmpegSetupDialog
        is_dark = (getattr(self.theme, "current_theme", "") == "dark")
        def on_done():
            if hasattr(self, "_refresh_ffmpeg_ui"):
                self._refresh_ffmpeg_ui()
        FFmpegSetupDialog(parent=self.top, theme_mgr=self.theme, is_dark=is_dark, on_change=on_done)

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
        self._schedule_subtitle_preview(50)

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

    def _schedule_subtitle_preview(self, delay: int = 50) -> None:
        """Schedule subtitle preview draw safely, canceling any pending draw on destroy."""
        if getattr(self, "_preview_timer", None) is not None:
            try:
                self.top.after_cancel(self._preview_timer)
            except Exception:
                pass
            self._preview_timer = None
        try:
            if hasattr(self, "top") and self.top.winfo_exists():
                self._preview_timer = self.top.after(delay, self._safe_update_subtitle_preview)
        except Exception:
            pass

    def _cleanup_dialog(self, event=None) -> None:
        """Cancel any pending timers when SettingsDialog is destroyed."""
        if getattr(self, "_preview_timer", None) is not None:
            try:
                self.top.after_cancel(self._preview_timer)
            except Exception:
                pass
            self._preview_timer = None
        if getattr(self, "_osd_timer", None) is not None:
            try:
                self.top.after_cancel(self._osd_timer)
            except Exception:
                pass
            self._osd_timer = None

    def _safe_update_subtitle_preview(self) -> None:
        self._preview_timer = None
        if not hasattr(self, "top") or not self.top.winfo_exists():
            return
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

    def _build_network_tab(self, colors: Optional[Dict[str, str]] = None) -> None:
        """In-app isolated Proxy and DoH DNS configuration tab."""
        if colors is None:
            colors = self.theme.PALETTES[self.theme.current_theme]

        tab = self.tab_network

        # Smooth scrollable canvas container ensuring all cards are reachable
        canvas = tk.Canvas(tab, bg=colors["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=colors["bg"])

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        win_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_canvas_configure(event):
            canvas.itemconfig(win_id, width=event.width)
            scrollable_frame.configure(width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        cols_frame = tk.Frame(scrollable_frame, bg=colors["bg"], padx=14, pady=8)
        cols_frame.pack(fill=tk.BOTH, expand=True)
        cols_frame.grid_columnconfigure(0, weight=1, uniform="net_col")
        cols_frame.grid_columnconfigure(1, weight=1, uniform="net_col")

        left_col = tk.Frame(cols_frame, bg=colors["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right_col = tk.Frame(cols_frame, bg=colors["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        def _bind_all_wheel(w):
            try:
                w.bind("<MouseWheel>", _on_mousewheel, add="+")
            except Exception:
                pass
            for ch in w.winfo_children():
                _bind_all_wheel(ch)

        tab.after(100, lambda: _bind_all_wheel(scrollable_frame) if scrollable_frame.winfo_exists() else None)

        muted_color = colors.get("disabled", "#8a8a8a")

        # ------------------------------------------------------------------ #
        #  LEFT COLUMN: App-Isolated Proxy Configuration                     #
        # ------------------------------------------------------------------ #
        card_proxy = tk.LabelFrame(
            left_col,
            text=" Cấu hình Proxy Ứng Dụng (Isolated Proxy) ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=10,
        )
        card_proxy.pack(fill=tk.X, pady=(0, 10))

        lbl_proxy_desc = tk.Label(
            card_proxy,
            text=(
                "Định tuyến lưu lượng xem và tải video qua Proxy riêng của app.\n"
                "• Không can thiệp hoặc thay đổi cấu hình mạng toàn máy Windows.\n"
                "• Mặc định TẮT (kết nối trực tiếp theo mạng của bạn)."
            ),
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=muted_color,
            justify=tk.LEFT,
            anchor="w",
        )
        lbl_proxy_desc.pack(fill=tk.X, pady=(0, 8))

        # Proxy Modes: direct, system, custom
        lbl_mode = tk.Label(
            card_proxy,
            text="Chế độ Proxy:",
            font=("Segoe UI", 9, "bold"),
            bg=colors["bg"],
            fg=colors["fg"],
            anchor="w",
        )
        lbl_mode.pack(fill=tk.X, pady=(4, 2))

        modes = [
            ("direct", "Tắt / Kết nối trực tiếp (Mặc định máy)"),
            ("system", "Sử dụng Proxy của Windows (Hệ thống)"),
            ("custom", "Sử dụng Proxy tùy chỉnh"),
        ]

        proxy_inputs_frame = tk.Frame(card_proxy, bg=colors["bg"])
        self._proxy_custom_widgets = []

        def _on_proxy_mode_change():
            mode = self.proxy_mode_var.get()
            is_custom = (mode == "custom")
            state = tk.NORMAL if is_custom else tk.DISABLED
            for w in getattr(self, "_proxy_custom_widgets", []):
                try:
                    if isinstance(w, ttk.Combobox):
                        w.configure(state="readonly" if is_custom else tk.DISABLED)
                    else:
                        w.configure(state=state)
                except Exception:
                    pass

        for val, text in modes:
            rb = tk.Radiobutton(
                card_proxy,
                text=text,
                value=val,
                variable=self.proxy_mode_var,
                command=_on_proxy_mode_change,
                bg=colors["bg"],
                fg=colors["fg"],
                selectcolor=colors["surface"],
                activebackground=colors["bg"],
                activeforeground=colors["accent"],
                font=("Segoe UI", 9),
                anchor="w",
            )
            rb.pack(fill=tk.X, pady=2)

        # Custom Proxy Inputs Container
        proxy_inputs_frame.pack(fill=tk.X, pady=(8, 0))

        # Protocol + Port in a 2-col row
        row_proto_port = tk.Frame(proxy_inputs_frame, bg=colors["bg"])
        row_proto_port.pack(fill=tk.X, pady=(4, 4))
        row_proto_port.grid_columnconfigure(0, weight=2)
        row_proto_port.grid_columnconfigure(1, weight=1)

        f_proto = tk.Frame(row_proto_port, bg=colors["bg"])
        f_proto.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        lbl_proto = tk.Label(f_proto, text="Giao thức:", font=("Segoe UI", 8), bg=colors["bg"], fg=colors["fg"], anchor="w")
        lbl_proto.pack(fill=tk.X)
        proto_combo = ttk.Combobox(
            f_proto,
            textvariable=self.proxy_protocol_var,
            values=["http", "socks5", "socks5h"],
            state="readonly",
            font=("Segoe UI", 9),
        )
        proto_combo.pack(fill=tk.X, pady=(2, 0))
        self._proxy_custom_widgets.append(proto_combo)

        f_port = tk.Frame(row_proto_port, bg=colors["bg"])
        f_port.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        lbl_port = tk.Label(f_port, text="Cổng (Port):", font=("Segoe UI", 8), bg=colors["bg"], fg=colors["fg"], anchor="w")
        lbl_port.pack(fill=tk.X)
        port_entry = tk.Entry(
            f_port,
            textvariable=self.proxy_port_var,
            font=("Segoe UI", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["entry_fg"],
            relief=tk.SOLID,
            bd=1,
        )
        port_entry.pack(fill=tk.X, pady=(2, 0))
        self._proxy_custom_widgets.append(port_entry)

        # Host
        lbl_host = tk.Label(proxy_inputs_frame, text="Máy chủ (Host / IP):", font=("Segoe UI", 8), bg=colors["bg"], fg=colors["fg"], anchor="w")
        lbl_host.pack(fill=tk.X, pady=(4, 2))
        host_entry = tk.Entry(
            proxy_inputs_frame,
            textvariable=self.proxy_host_var,
            font=("Segoe UI", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["entry_fg"],
            relief=tk.SOLID,
            bd=1,
        )
        host_entry.pack(fill=tk.X, pady=(0, 4))
        self._proxy_custom_widgets.append(host_entry)

        # Username
        lbl_user = tk.Label(proxy_inputs_frame, text="Tên đăng nhập (Tùy chọn):", font=("Segoe UI", 8), bg=colors["bg"], fg=colors["fg"], anchor="w")
        lbl_user.pack(fill=tk.X, pady=(4, 2))
        user_entry = tk.Entry(
            proxy_inputs_frame,
            textvariable=self.proxy_user_var,
            font=("Segoe UI", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["entry_fg"],
            relief=tk.SOLID,
            bd=1,
        )
        user_entry.pack(fill=tk.X, pady=(0, 4))
        self._proxy_custom_widgets.append(user_entry)

        # Password + Show Password Checkbox
        lbl_pass = tk.Label(proxy_inputs_frame, text="Mật khẩu (Tùy chọn):", font=("Segoe UI", 8), bg=colors["bg"], fg=colors["fg"], anchor="w")
        lbl_pass.pack(fill=tk.X, pady=(4, 2))
        pass_entry = tk.Entry(
            proxy_inputs_frame,
            textvariable=self.proxy_pass_var,
            show="*",
            font=("Segoe UI", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["entry_fg"],
            relief=tk.SOLID,
            bd=1,
        )
        pass_entry.pack(fill=tk.X, pady=(0, 2))
        self._proxy_custom_widgets.append(pass_entry)

        def _toggle_show_pass():
            pass_entry.configure(show="" if self.proxy_show_pass_var.get() else "*")

        chk_show_pass = tk.Checkbutton(
            proxy_inputs_frame,
            text="Hiển thị mật khẩu",
            variable=self.proxy_show_pass_var,
            command=_toggle_show_pass,
            bg=colors["bg"],
            fg=muted_color,
            selectcolor=colors["surface"],
            activebackground=colors["bg"],
            font=("Segoe UI", 8),
            anchor="w",
        )
        chk_show_pass.pack(anchor="w", pady=(0, 8))
        self._proxy_custom_widgets.append(chk_show_pass)

        # Test Proxy Button + Status Label
        def _test_proxy_connection():
            mode = self.proxy_mode_var.get()
            port_val = 0
            try:
                port_val = int(str(self.proxy_port_var.get()).strip() or "0")
            except ValueError:
                pass

            from main.network.proxy_config import ProxyConfig
            cfg = ProxyConfig(
                mode=mode,
                protocol=self.proxy_protocol_var.get().strip() or "http",
                host=self.proxy_host_var.get().strip(),
                port=port_val,
                username=self.proxy_user_var.get().strip(),
                password=self.proxy_pass_var.get().strip(),
            )
            if mode == "custom" and not cfg.host:
                self.proxy_test_status_var.set("⚠️ Vui lòng nhập Host và Port trước khi kiểm tra.")
                return

            self.proxy_test_status_var.set("⏳ Đang kết nối kiểm tra proxy...")

            def _bg():
                ok, latency, egress_info = cfg.test_connection(timeout=5.0)
                if ok:
                    text = f"✓ Kết nối tốt! Ping: {latency:.0f}ms | IP thoát: {egress_info}"
                else:
                    text = f"✗ Thất bại: {egress_info}"
                if self.top.winfo_exists():
                    self.top.after(0, lambda: self.proxy_test_status_var.set(text))

            threading.Thread(target=_bg, daemon=True).start()

        btn_test_proxy = tk.Button(
            card_proxy,
            text="  Kiểm tra kết nối Proxy  ",
            command=_test_proxy_connection,
            bg=colors["surface"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
        )
        btn_test_proxy.pack(anchor="w", pady=(4, 4))

        lbl_proxy_status = tk.Label(
            card_proxy,
            textvariable=self.proxy_test_status_var,
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["fg"],
            justify=tk.LEFT,
            wraplength=380,
            anchor="w",
        )
        lbl_proxy_status.pack(fill=tk.X, pady=(2, 4))

        # Initial call to sync custom proxy inputs
        _on_proxy_mode_change()

        # ------------------------------------------------------------------ #
        #  RIGHT COLUMN: App-Isolated DNS-over-HTTPS (DoH)                   #
        # ------------------------------------------------------------------ #
        card_doh = tk.LabelFrame(
            right_col,
            text=" DNS Mã Hóa Ứng Dụng (DNS-over-HTTPS) ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=10,
        )
        card_doh.pack(fill=tk.X, pady=(0, 10))

        lbl_doh_desc = tk.Label(
            card_doh,
            text=(
                "Mã hóa các truy vấn tên miền (DNS) qua HTTPS để vượt chặn mạng\n"
                "và chống đầu độc DNS (DNS Poisoning) từ nhà mạng (ISP).\n"
                "• Chỉ hook bên trong tiến trình ứng dụng, không cần quyền Admin.\n"
                "• Tự động fallback DNS hệ thống nếu DoH gặp sự cố hoặc timeout.\n"
                "• Mặc định TẮT (dùng cấu hình DNS máy của bạn)."
            ),
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=muted_color,
            justify=tk.LEFT,
            anchor="w",
        )
        lbl_doh_desc.pack(fill=tk.X, pady=(0, 8))

        provider_labels = {
            "cloudflare": "Cloudflare (1.1.1.1 - Tốc độ cao & Bảo mật)",
            "google": "Google Public DNS (8.8.8.8 - Ổn định toàn cầu)",
            "quad9": "Quad9 (9.9.9.9 - Chặn mã độc & Phishing)",
            "adguard": "AdGuard DNS (Chặn quảng cáo & Trình theo dõi)",
            "custom": "Tùy chỉnh DoH URL...",
        }
        self._doh_key_from_display = {v: k for k, v in provider_labels.items()}
        self._doh_display_from_key = provider_labels

        current_prov_key = self.doh_provider_var.get() or "cloudflare"
        current_display = provider_labels.get(current_prov_key, provider_labels["cloudflare"])
        self._doh_display_var = tk.StringVar(value=current_display)

        def _on_provider_change(event=None):
            sel_display = self._doh_display_var.get()
            sel_key = self._doh_key_from_display.get(sel_display, "cloudflare")
            self.doh_provider_var.set(sel_key)
            is_doh_on = self.doh_enabled_var.get()
            if is_doh_on and sel_key == "custom":
                custom_entry.configure(state=tk.NORMAL)
            else:
                custom_entry.configure(state=tk.DISABLED)

        def _on_doh_toggle():
            is_enabled = self.doh_enabled_var.get()
            doh_prov_combo.configure(state="readonly" if is_enabled else tk.DISABLED)
            _on_provider_change()

        chk_doh = tk.Checkbutton(
            card_doh,
            text="Kích hoạt DNS-over-HTTPS (DoH)",
            variable=self.doh_enabled_var,
            command=_on_doh_toggle,
            bg=colors["bg"],
            fg=colors["fg"],
            selectcolor=colors["surface"],
            activebackground=colors["bg"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        chk_doh.pack(anchor="w", pady=(0, 8))

        lbl_provider = tk.Label(
            card_doh,
            text="Nhà cung cấp DoH:",
            font=("Segoe UI", 8, "bold"),
            bg=colors["bg"],
            fg=colors["fg"],
            anchor="w",
        )
        lbl_provider.pack(fill=tk.X, pady=(4, 2))

        doh_prov_combo = ttk.Combobox(
            card_doh,
            textvariable=self._doh_display_var,
            values=list(provider_labels.values()),
            state="readonly",
            font=("Segoe UI", 9),
        )
        doh_prov_combo.pack(fill=tk.X, pady=(2, 6))
        doh_prov_combo.bind("<<ComboboxSelected>>", _on_provider_change)

        lbl_custom_url = tk.Label(
            card_doh,
            text="DoH Endpoint URL (khi chọn Tùy chỉnh):",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["fg"],
            anchor="w",
        )
        lbl_custom_url.pack(fill=tk.X, pady=(4, 2))

        custom_entry = tk.Entry(
            card_doh,
            textvariable=self.doh_custom_url_var,
            font=("Segoe UI", 9),
            bg=colors["entry_bg"],
            fg=colors["entry_fg"],
            insertbackground=colors["entry_fg"],
            relief=tk.SOLID,
            bd=1,
        )
        custom_entry.pack(fill=tk.X, pady=(0, 8))

        # Test DoH Button + Status Label
        def _test_doh_resolution():
            sel_display = self._doh_display_var.get()
            sel_key = self._doh_key_from_display.get(sel_display, "cloudflare")
            self.doh_provider_var.set(sel_key)
            custom_url = self.doh_custom_url_var.get().strip()

            from main.network.doh_resolver import DoHResolver
            resolver = DoHResolver(provider=sel_key, custom_url=custom_url)
            self.doh_test_status_var.set(f"⏳ Đang gửi truy vấn DoH tới {sel_key}...")

            def _bg():
                ok, latency, res_info = resolver.test_provider(test_domain="facebook.com")
                if ok:
                    text = f"✓ Phân giải thành công! ({latency:.0f}ms)\nfacebook.com -> {res_info}"
                else:
                    text = f"✗ Thất bại: {res_info}"
                if self.top.winfo_exists():
                    self.top.after(0, lambda: self.doh_test_status_var.set(text))

            threading.Thread(target=_bg, daemon=True).start()

        btn_test_doh = tk.Button(
            card_doh,
            text="  Kiểm tra phân giải DoH  ",
            command=_test_doh_resolution,
            bg=colors["surface"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
        )
        btn_test_doh.pack(anchor="w", pady=(4, 4))

        lbl_doh_status = tk.Label(
            card_doh,
            textvariable=self.doh_test_status_var,
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["fg"],
            justify=tk.LEFT,
            wraplength=380,
            anchor="w",
        )
        lbl_doh_status.pack(fill=tk.X, pady=(2, 4))

        # Initial call to sync DoH widgets
        _on_doh_toggle()

        # ------------------------------------------------------------------ #
        #  RIGHT COLUMN: Security & Isolation Summary Card                   #
        # ------------------------------------------------------------------ #
        card_sec = tk.LabelFrame(
            right_col,
            text=" An Toàn & Độc Lập Hệ Thống ",
            bg=colors["bg"],
            fg=colors["accent"],
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=8,
        )
        card_sec.pack(fill=tk.X, pady=(6, 0))

        security_tips = (
            "✓ Không đổi Windows Registry, Card mạng, hay cần quyền Admin.\n"
            "✓ Hoàn toàn cục bộ trong tiến trình app, không ảnh hưởng game/web.\n"
            "✓ Tự động bỏ qua localhost và StreamProxy để phát mượt mà.\n"
            "✓ Bộ đệm LRU siêu nhẹ: giới hạn 256 bản ghi, chiếm < 50KB RAM."
        )
        lbl_sec = tk.Label(
            card_sec,
            text=security_tips,
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=muted_color,
            justify=tk.LEFT,
            anchor="w",
        )
        lbl_sec.pack(fill=tk.X)

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

        self.lbl_app_name = tk.Label(
            hero_text_frame,
            text=f"{APP_NAME}",
            font=("Segoe UI", 16, "bold"),
            bg=colors["bg"],
            fg=colors["accent"],
            cursor="hand2",
        )
        self.lbl_app_name.pack(anchor=tk.W)
        self.lbl_app_name.bind("<Button-1>", self._on_app_name_clicked)
        lbl_app_name = self.lbl_app_name

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
            self.settings.set("performance", "gpu_preference", self.gpu_preference_var.get())
            self.settings.set("playback", "queue_persist", self.queue_persist_var.get())
            new_pip_ratio = self.pip_aspect_ratio_var.get()
            self.settings.set("ui", "pip_aspect_ratio", new_pip_ratio)
            self.settings.set("ui", "pip_auto_aspect_ratio", self.pip_auto_aspect_var.get())
            try:
                master = self.top.master
                if hasattr(master, "set_pip_aspect_ratio"):
                    master.set_pip_aspect_ratio(new_pip_ratio)
            except Exception:
                pass

            # Save source profile mode
            profiles = self.settings.get("source_profiles", default={})
            if not isinstance(profiles, dict):
                profiles = {}
            if "global" not in profiles or not isinstance(profiles["global"], dict):
                profiles["global"] = {}
            profiles["global"]["mode"] = self.profile_mode_var.get()
            self.settings.set("source_profiles", profiles)

            # Windows protocol registration toggle (fbvw://)
            try:
                from main.platform_utils import (
                    register_fbvw_protocol,
                    unregister_fbvw_protocol,
                    is_fbvw_protocol_registered,
                )
                wanted_proto = self.fbvw_proto_var.get()
                current_proto = is_fbvw_protocol_registered()
                if wanted_proto and not current_proto:
                    register_fbvw_protocol()
                elif not wanted_proto and current_proto:
                    unregister_fbvw_protocol()
            except Exception as proto_err:
                logger.warning(f"Không thể cập nhật protocol fbvw://: {proto_err}")

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

            # Save Network & Proxy configuration
            try:
                port_val = int(str(self.proxy_port_var.get()).strip() or "0")
            except ValueError:
                port_val = 0

            doh_key = self.doh_provider_var.get().strip() or "cloudflare"

            net_dict = {
                "proxy_mode": self.proxy_mode_var.get().strip() or "direct",
                "proxy_protocol": self.proxy_protocol_var.get().strip() or "http",
                "proxy_host": self.proxy_host_var.get().strip(),
                "proxy_port": port_val,
                "proxy_user": self.proxy_user_var.get().strip(),
                "proxy_pass": self.proxy_pass_var.get().strip(),
                "doh_enabled": bool(self.doh_enabled_var.get()),
                "doh_provider": doh_key or "cloudflare",
                "doh_custom_url": self.doh_custom_url_var.get().strip(),
            }
            self.settings.set("network", net_dict)

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
