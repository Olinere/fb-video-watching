"""
Floating and overlay GUI components for FB Video Watcher.
Includes SeekBarController, OSDOverlay, PiPProgressOverlay, and ListboxTooltip.
"""

import sys
import time
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont
from typing import Callable, Optional, Dict, Any, Tuple, Union
from main.theme import ThemeManager


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
        self._is_loading: bool = False
        self._loading_timeout_timer: Optional[str] = None

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

        if self._loading_timeout_timer is not None:
            try:
                self.parent.after_cancel(self._loading_timeout_timer)
            except Exception:
                pass
            self._loading_timeout_timer = None
        self._is_loading = False

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
        if not self.top:
            return
        try:
            if not self.top.winfo_exists() or not self.parent.winfo_exists():
                self.hide()
                return
        except Exception:
            self.hide()
            return
        if self._fade_step < len(ALPHA_STEPS):
            alpha = ALPHA_STEPS[self._fade_step]
            self._fade_step += 1
            try:
                self.top.attributes("-alpha", alpha)
            except Exception:
                pass
            try:
                if self.parent.winfo_exists():
                    self._fade_timer = self.parent.after(100, self._step_fade)
                else:
                    self.hide()
            except Exception:
                self.hide()
        else:
            self.hide()

    def show_loading(self, text: str = "Đang tải siêu dữ liệu video...") -> None:
        """Display persistent floating OSD overlay badge without auto-fading during media open."""
        if self._fade_timer is not None:
            try:
                self.parent.after_cancel(self._fade_timer)
            except Exception:
                pass
            self._fade_timer = None

        if self._loading_timeout_timer is not None:
            try:
                self.parent.after_cancel(self._loading_timeout_timer)
            except Exception:
                pass
            self._loading_timeout_timer = None

        self._ensure_window()
        if not self.top or not self.label:
            return

        self._is_loading = True
        self._last_relx = 0.5
        self._last_rely = 0.88
        self._last_anchor = tk.S

        self._has_progress = True
        self.label.pack_forget()
        self.progress_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.progress_bar.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        self.label.pack(fill=tk.BOTH, expand=True)

        self.label.configure(text=text, bg="#202124", fg="#ffffff")
        x, y, ow_w, ow_h = self._calculate_pos(0.5, 0.88, tk.S)

        try:
            self.top.geometry(f"{ow_w}x{ow_h}+{x}+{y}")
            self.top.attributes("-alpha", 0.95)
            self.top.deiconify()
            self.top.lift(self.parent)
            self._apply_win32_styles()
            self._is_visible = True
        except Exception:
            pass

        # Failsafe fallback: auto-fade loading overlay after 3.5s if not explicitly hidden
        try:
            self._loading_timeout_timer = self.parent.after(3500, self.hide)
        except Exception:
            pass

    def hide(self) -> None:
        """Hide floating OSD badge."""
        self._is_loading = False
        if self._loading_timeout_timer is not None:
            try:
                self.parent.after_cancel(self._loading_timeout_timer)
            except Exception:
                pass
            self._loading_timeout_timer = None
        if self._fade_timer is not None:
            try:
                self.parent.after_cancel(self._fade_timer)
            except Exception:
                pass
            self._fade_timer = None
        if self.top:
            try:
                if self.top.winfo_exists():
                    self.top.withdraw()
            except Exception:
                pass

        self._is_visible = False

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
        if self._loading_timeout_timer is not None:
            try:
                self.parent.after_cancel(self._loading_timeout_timer)
            except Exception:
                pass
            self._loading_timeout_timer = None
        if self._fade_timer is not None:
            try:
                self.parent.after_cancel(self._fade_timer)
            except Exception:
                pass
            self._fade_timer = None
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
        self._last_geo: Optional[str] = None

    def _ensure_window(self) -> None:
        if self.top is not None and self.top.winfo_exists():
            return

        self.top = tk.Toplevel(self.parent)
        self.top.overrideredirect(True)
        try:
            self.top.attributes("-topmost", True)
            self.top.attributes("-alpha", 1.0)
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

    def _get_hwnds(self) -> Tuple[int, int]:
        """Retrieve Win32 HWNDs for overlay and parent window."""
        if not self.top or not self.top.winfo_exists():
            return 0, 0
        try:
            import win32gui
            import win32con
            w_id = self.top.winfo_id()
            top_hwnd = win32gui.GetAncestor(w_id, win32con.GA_ROOT) or w_id
            r_id = self.parent.winfo_id()
            root_hwnd = win32gui.GetAncestor(r_id, win32con.GA_ROOT) or r_id
            return top_hwnd, root_hwnd
        except Exception:
            return 0, 0

    def _apply_win32_styles(self) -> None:
        """
        Apply Win32 Owner-Child relationship and WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED.
        By setting root_hwnd as the Win32 owner of top_hwnd (GWL_HWNDPARENT), Windows DWM
        guarantees that top_hwnd is always ordered strictly ABOVE root_hwnd, even when root
        receives focus or renders hardware-composited Direct3D 11 video frames.
        """
        if sys.platform != "win32" or not self.top or not self.top.winfo_exists():
            return
        try:
            import win32gui
            import win32con
            top_hwnd, root_hwnd = self._get_hwnds()
            if not top_hwnd:
                return

            # 1. Establish Win32 Owner-Child contract: Topmost owned window strictly floats above owner
            if root_hwnd:
                win32gui.SetWindowLong(top_hwnd, win32con.GWL_HWNDPARENT, root_hwnd)

            # 2. Add WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
            GWL_EXSTYLE = win32con.GWL_EXSTYLE
            style = win32gui.GetWindowLong(top_hwnd, GWL_EXSTYLE)
            win32gui.SetWindowLong(
                top_hwnd,
                GWL_EXSTYLE,
                style | win32con.WS_EX_LAYERED | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT,
            )

            # 3. Flush frame changes and enforce HWND_TOPMOST
            win32gui.SetWindowPos(
                top_hwnd,
                win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE,
            )
            self._styles_applied = True
        except Exception:
            pass

    def update(
        self,
        fraction: float,
        target_window: Optional[tk.Tk] = None,
        bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        """Update progress bar fill width and reposition to bottom of PiP window."""
        self._fraction = max(0.0, min(1.0, fraction))
        self._ensure_window()
        if not self.top or not self.top.winfo_exists():
            return

        if self.fill_frame:
            self.fill_frame.place(relx=0, rely=0, relwidth=self._fraction, relheight=1.0)
            try:
                self.top.update_idletasks()
            except Exception:
                pass

        if not self._is_visible:
            self.show(target_window, bounds=bounds)
        else:
            self.reposition(target_window, bounds=bounds)

    def show(
        self,
        target_window: Optional[tk.Tk] = None,
        bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        """Show floating progress bar on top of VLC."""
        self._ensure_window()
        if not self.top or not self.top.winfo_exists():
            return
        self._is_visible = True
        target = target_window or self.parent
        self.reposition(target, bounds=bounds)
        try:
            self.top.deiconify()
            self.top.update_idletasks()
            self._apply_win32_styles()
            self.top.lift(self.parent)
            top_hwnd, _ = self._get_hwnds()
            if top_hwnd:
                import win32gui
                import win32con
                win32gui.SetWindowPos(
                    top_hwnd,
                    win32con.HWND_TOPMOST,
                    0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
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

    def reposition(
        self,
        target_window: Optional[tk.Tk] = None,
        bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        """Keep the progress bar attached to the bottom edge of the PiP window."""
        if not self._is_visible or not self.top or not self.top.winfo_exists():
            return
        target = target_window or self.parent
        try:
            if bounds:
                wx, wy, ww, wh = bounds
            else:
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
        """Cleanly destroy floating progress bar on app exit or PiP exit."""
        self.hide()
        if self.top and self.top.winfo_exists():
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top = None
        self.bg_frame = None
        self.fill_frame = None
        self._last_geo = None
        self._styles_applied = False


class ListboxTooltip:
    """Displays hovering context tooltip over items in a Tkinter Listbox."""

    def __init__(self, listbox: tk.Listbox, get_text_fn: Callable[[int], Optional[str]], theme_mgr: Optional[ThemeManager] = None):
        self.listbox = listbox
        self.get_text_fn = get_text_fn
        self.theme_mgr = theme_mgr
        self.tooltip_window: Optional[tk.Toplevel] = None
        self._last_index: Optional[int] = None
        self._after_id: Optional[str] = None

        self.listbox.bind("<Motion>", self._on_motion, add="+")
        self.listbox.bind("<Leave>", self._on_leave, add="+")
        self.listbox.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_motion(self, event: tk.Event) -> None:
        index = self.listbox.nearest(event.y)
        bbox = self.listbox.bbox(index)
        if not bbox or not (bbox[1] <= event.y <= bbox[1] + bbox[3]):
            self._hide()
            return

        if index == self._last_index and self.tooltip_window:
            return

        self._last_index = index
        self._cancel_after()
        # Responsive 180ms hover delay
        self._after_id = self.listbox.after(180, lambda idx=index, ex=event.x_root, ey=event.y_root: self._show(idx, ex, ey))

    def _show(self, index: int, x_root: int, y_root: int) -> None:
        text = self.get_text_fn(index)
        if not text:
            self._hide()
            return

        self._hide()
        self.tooltip_window = tk.Toplevel(self.listbox)
        self.tooltip_window.wm_overrideredirect(True)
        try:
            self.tooltip_window.attributes("-topmost", True)
        except Exception:
            pass

        if self.theme_mgr:
            if hasattr(self.theme_mgr, "is_dark") and callable(self.theme_mgr.is_dark):
                is_dark = self.theme_mgr.is_dark()
            else:
                is_dark = getattr(self.theme_mgr, "current_theme", "dark") == "dark"
        else:
            is_dark = True

        bg = "#252526" if is_dark else "#ffffe0"
        fg = "#ffffff" if is_dark else "#000000"
        border_color = "#454545" if is_dark else "#999999"

        frame = tk.Frame(self.tooltip_window, bg=border_color, padx=1, pady=1)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(
            frame,
            text=text,
            bg=bg,
            fg=fg,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
            padx=6,
            pady=4,
        )
        lbl.pack()

        self.tooltip_window.geometry(f"+{x_root + 15}+{y_root + 10}")

    def _cancel_after(self) -> None:
        if self._after_id:
            try:
                self.listbox.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _hide(self) -> None:
        self._cancel_after()
        self._last_index = None
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
            self.tooltip_window = None

    def _on_leave(self, _event=None) -> None:
        self._hide()


class WidgetTooltip:
    """Displays hovering context tooltip over any Tkinter/TTK widget."""

    def __init__(
        self,
        widget: tk.Widget,
        text: Union[str, Callable[[], str]],
        theme_mgr: Optional[ThemeManager] = None,
        delay_ms: int = 300,
    ):
        self.widget = widget
        self.text = text
        self.theme_mgr = theme_mgr
        self.delay_ms = delay_ms
        self.tooltip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event=None) -> None:
        self._cancel_after()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self) -> None:
        if self.tooltip_window:
            return
        content = self.text() if callable(self.text) else self.text
        if not content:
            return

        self._hide()
        try:
            x_root = self.widget.winfo_rootx() + 10
            y_root = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        try:
            self.tooltip_window.attributes("-topmost", True)
        except Exception:
            pass

        if self.theme_mgr:
            if hasattr(self.theme_mgr, "is_dark") and callable(self.theme_mgr.is_dark):
                is_dark = self.theme_mgr.is_dark()
            else:
                is_dark = getattr(self.theme_mgr, "current_theme", "dark") == "dark"
        else:
            is_dark = True

        bg = "#252526" if is_dark else "#ffffe0"
        fg = "#ffffff" if is_dark else "#000000"
        border_color = "#454545" if is_dark else "#999999"

        frame = tk.Frame(self.tooltip_window, bg=border_color, padx=1, pady=1)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(
            frame,
            text=content,
            bg=bg,
            fg=fg,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
            padx=8,
            pady=5,
        )
        lbl.pack()

        self.tooltip_window.geometry(f"+{x_root}+{y_root}")

    def _cancel_after(self) -> None:
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _hide(self) -> None:
        self._cancel_after()
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
            self.tooltip_window = None

    def _on_leave(self, _event=None) -> None:
        self._hide()


class SkeletonOverlay:
    """
    Modern animated skeleton loading overlay rendered directly on top of the video container.
    Provides immediate visual feedback that the application is actively fetching metadata
    and initializing the media engine, preventing perceived app freezes.

    Strictly adheres to specs.md §16.4 ("Xài xong dọn"):
    - Zero resource leakage: all animation timers are cancelled on hide() and destroy()
    - Bounded memory footprint (< 10 KB)
    - Mouse event pass-through to underlying container
    """

    def __init__(self, parent_widget: tk.Widget, on_mouse_event: Optional[Callable[[Any, str], None]] = None):
        self.parent = parent_widget
        self.on_mouse_event = on_mouse_event
        self._is_active: bool = False
        self._anim_timer: Optional[str] = None
        self._pulse_step: int = 0
        self._dot_step: int = 0
        self._sweep_pos: int = 0
        self._sweep_dir: int = 1
        self._base_status_text: str = "Đang tải siêu dữ liệu video"
        self._detail_text: str = "Đang nạp luồng phát qua StreamProxy đa luồng..."

        # Container covering 100% of video surface
        self.frame = tk.Frame(self.parent, bg="#0d0e12")

        # Centered mockup card
        self.card = tk.Frame(
            self.frame,
            bg="#161820",
            bd=1,
            relief=tk.SOLID,
            highlightbackground="#2b2f3d",
            highlightthickness=1,
            padx=28,
            pady=22,
        )
        self.card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # 1. Loading Glyphs & Texts
        self.lbl_icon = tk.Label(
            self.card,
            text="⚡",
            font=("Segoe UI", 28),
            bg="#161820",
            fg="#4cc2ff",
        )
        self.lbl_icon.pack(pady=(0, 6))

        self.lbl_status = tk.Label(
            self.card,
            text="Đang tải siêu dữ liệu video...",
            font=("Segoe UI", 13, "bold"),
            bg="#161820",
            fg="#ffffff",
        )
        self.lbl_status.pack(pady=(0, 4))

        self.lbl_detail = tk.Label(
            self.card,
            text=self._detail_text,
            font=("Segoe UI", 9),
            bg="#161820",
            fg="#8c92a4",
        )
        self.lbl_detail.pack(pady=(0, 16))

        # 2. Sleek Shimmer Bar
        self.shimmer_canvas = tk.Canvas(
            self.card,
            width=260,
            height=4,
            bg="#222634",
            bd=0,
            highlightthickness=0,
        )
        self.shimmer_canvas.pack(pady=(0, 16))
        self.shimmer_bar = self.shimmer_canvas.create_rectangle(0, 0, 80, 4, fill="#0078d4", outline="")

        # 3. Simulated Skeleton Placeholder Bars (Pulsing Preview)
        self.skeleton_title = tk.Frame(self.card, bg="#252a38", width=220, height=8)
        self.skeleton_title.pack(pady=(0, 6))
        self.skeleton_title.pack_propagate(False)

        self.skeleton_sub = tk.Frame(self.card, bg="#1e222e", width=140, height=6)
        self.skeleton_sub.pack(pady=(0, 4))
        self.skeleton_sub.pack_propagate(False)

        # Mouse forwarding to parent video container
        def _forward(event, event_name):
            if self.on_mouse_event:
                try:
                    self.on_mouse_event(event, event_name)
                except Exception:
                    pass
            else:
                try:
                    self.parent.event_generate(event_name, x=event.x, y=event.y)
                except Exception:
                    pass

        for w in (self.frame, self.card, self.lbl_icon, self.lbl_status, self.lbl_detail,
                 self.shimmer_canvas, self.skeleton_title, self.skeleton_sub):
            w.bind("<ButtonPress-1>", lambda e: _forward(e, "<ButtonPress-1>"))
            w.bind("<B1-Motion>", lambda e: _forward(e, "<B1-Motion>"))
            w.bind("<ButtonRelease-1>", lambda e: _forward(e, "<ButtonRelease-1>"))
            w.bind("<Double-Button-1>", lambda e: _forward(e, "<Double-Button-1>"))
            w.bind("<Button-3>", lambda e: _forward(e, "<Button-3>"))

    @property
    def is_active(self) -> bool:
        return self._is_active

    def show(self, status_text: str = "Đang tải siêu dữ liệu video...", detail_text: str = "") -> None:
        """Display skeleton loading overlay and start smooth non-blocking animation."""
        clean_text = status_text.rstrip(".")
        self._base_status_text = clean_text or "Đang tải siêu dữ liệu video"
        if detail_text:
            self._detail_text = detail_text
            try:
                self.lbl_detail.configure(text=detail_text)
            except Exception:
                pass

        self._is_active = True
        try:
            self.frame.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
            self.frame.lift()
        except Exception:
            pass

        if self._anim_timer is None:
            self._tick_anim()

    def set_text(self, status_text: str, detail_text: Optional[str] = None) -> None:
        """Update displayed status message without interrupting animation."""
        clean_text = status_text.rstrip(".")
        self._base_status_text = clean_text or "Đang tải siêu dữ liệu video"
        try:
            self.lbl_status.configure(text=self._base_status_text)
        except Exception:
            pass
        if detail_text is not None:
            self._detail_text = detail_text
            try:
                self.lbl_detail.configure(text=detail_text)
            except Exception:
                pass

    def _tick_anim(self) -> None:
        """Lightweight 50ms animation tick: shimmer sweep, pulsing bars, and animated dots."""
        if not self._is_active:
            self._anim_timer = None
            return
        try:
            if not self.parent.winfo_exists() or not self.frame.winfo_exists():
                self.hide()
                return
        except Exception:
            self.hide()
            return

        # 1. Animate shimmer sweep bar across canvas (width=260, bar=80)
        canvas_w = 260
        bar_w = 80
        self._sweep_pos += self._sweep_dir * 8
        if self._sweep_pos + bar_w >= canvas_w:
            self._sweep_pos = canvas_w - bar_w
            self._sweep_dir = -1
        elif self._sweep_pos <= 0:
            self._sweep_pos = 0
            self._sweep_dir = 1

        try:
            self.shimmer_canvas.coords(
                self.shimmer_bar,
                self._sweep_pos,
                0,
                self._sweep_pos + bar_w,
                4,
            )
        except Exception:
            pass

        # 2. Cycle dynamic dots every ~300ms (every 6 ticks)
        self._dot_step = (self._dot_step + 1) % 24
        dots = "." * ((self._dot_step // 6) + 1)
        try:
            self.lbl_status.configure(text=f"{self._base_status_text}{dots}")
        except Exception:
            pass

        # 3. Subtle pulsing shimmer colors for skeleton bars
        PULSE_COLORS_1 = ["#252a38", "#2a3040", "#31384c", "#384157", "#31384c", "#2a3040"]
        PULSE_COLORS_2 = ["#1e222e", "#222735", "#272d3d", "#2d3446", "#272d3d", "#222735"]
        self._pulse_step = (self._pulse_step + 1) % len(PULSE_COLORS_1)
        try:
            self.skeleton_title.configure(bg=PULSE_COLORS_1[self._pulse_step])
            self.skeleton_sub.configure(bg=PULSE_COLORS_2[self._pulse_step])
        except Exception:
            pass

        try:
            self._anim_timer = self.parent.after(50, self._tick_anim)
        except Exception:
            self._anim_timer = None

    def hide(self) -> None:
        """Stop animation and dismiss skeleton overlay."""
        self._is_active = False
        if self._anim_timer is not None:
            try:
                self.parent.after_cancel(self._anim_timer)
            except Exception:
                pass
            self._anim_timer = None

        try:
            if self.frame.winfo_exists():
                self.frame.place_forget()
        except Exception:
            pass

    def destroy(self) -> None:
        """Cleanly cancel all timers and release UI objects on shutdown (§16.4)."""
        self.hide()
        try:
            if self.frame.winfo_exists():
                self.frame.destroy()
        except Exception:
            pass


