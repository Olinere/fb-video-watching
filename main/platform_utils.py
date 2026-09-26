"""
Platform-specific utilities for window embedding, theme styling, and OS integration.
Strictly isolates platform dependencies as mandated by Agent.md §5.2.D.
"""

import sys
import ctypes
from pathlib import Path
from typing import Any, Optional, Tuple, Callable


class PlatformNotSupportedError(Exception):
    """Raised when an unsupported platform is encountered."""
    pass


def embed_vlc_in_frame(player: Any, frame: Any) -> None:
    """
    Embed VLC MediaPlayer into a Tkinter frame across Windows, Linux, and macOS.
    On Windows, applies WS_CLIPCHILDREN style to eliminate black-screen flickering during resizing.

    Args:
        player: vlc.MediaPlayer instance.
        frame: tkinter.Frame or ttk.Frame widget (must have winfo_id()).
    """
    handle = frame.winfo_id()

    if sys.platform == "win32":
        # Apply WS_CLIPCHILDREN to eliminate flickering when resizing window on Windows
        try:
            import win32gui
            import win32con
            style = win32gui.GetWindowLong(handle, win32con.GWL_STYLE)
            win32gui.SetWindowLong(handle, win32con.GWL_STYLE, style | win32con.WS_CLIPCHILDREN)
        except ImportError:
            # Fallback using ctypes if pywin32 is not installed
            try:
                GWL_STYLE = -16
                WS_CLIPCHILDREN = 0x02000000
                user32 = ctypes.windll.user32
                style = user32.GetWindowLongW(handle, GWL_STYLE)
                user32.SetWindowLongW(handle, GWL_STYLE, style | WS_CLIPCHILDREN)
            except Exception:
                pass

        player.set_hwnd(handle)

    elif sys.platform.startswith("linux"):
        player.set_xwindow(handle)

    elif sys.platform == "darwin":
        player.set_nsobject(handle)

    else:
        raise PlatformNotSupportedError(f"Unsupported operating system: {sys.platform}")


def set_windows_dark_titlebar(window: Any, dark: bool = True) -> None:
    """
    Apply dark or light theme to the Windows native Title Bar (Windows 10 Build 17763+ and Windows 11).

    Args:
        window: tkinter.Tk or tkinter.Toplevel instance.
        dark: True for dark titlebar, False for light titlebar.
    """
    if sys.platform != "win32":
        return

    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()

        DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20

        value = ctypes.c_int(1 if dark else 0)

        # Try standard Windows 11 / modern Windows 10 attribute (ID 20)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if res != 0:
            # Fallback to older attribute (ID 19)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
    except Exception:
        pass


def check_vlc_installed() -> bool:
    """Check if libvlc is available and can be loaded."""
    try:
        import vlc
        inst = vlc.Instance("--quiet")
        if inst:
            inst.release()
            return True
        return False
    except Exception:
        return False


def apply_window_icon(window: Any, icon_path: Any) -> None:
    """
    Set window, taskbar, and Alt+Tab icon from an image file (ICO/PNG).
    Uses SetCurrentProcessExplicitAppUserModelID, native iconbitmap, iconphoto,
    and Win32 WM_SETICON for both ICON_BIG and ICON_SMALL so the application
    icon shows immediately on launch without requiring a fullscreen toggle.
    """
    import os
    import tkinter as tk

    icon_p = Path(str(icon_path)).resolve()
    if not icon_p.is_file():
        return

    # Find companion .ico or .png in the same directory
    ico_p = icon_p if icon_p.suffix.lower() == ".ico" else (icon_p.parent / "app_icon.ico")
    png_p = icon_p if icon_p.suffix.lower() == ".png" else (icon_p.parent / "icon-192.png")

    if sys.platform == "win32":
        try:
            myappid = "fbvideowatcher.desktop.app"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    # 1. Apply native .ico via iconbitmap (best for Windows Titlebar & Taskbar)
    if ico_p.is_file():
        try:
            window.iconbitmap(default=str(ico_p))
        except Exception:
            pass
        try:
            window.iconbitmap(str(ico_p))
        except Exception:
            pass

    # 2. Apply .png via iconphoto
    if png_p.is_file():
        try:
            icon_img = tk.PhotoImage(file=str(png_p))
            window.iconphoto(True, icon_img)
            window._app_icon_ref = icon_img
        except Exception:
            pass

    # 3. On Windows, explicitly send WM_SETICON messages to top-level HWND and register class icon
    if sys.platform == "win32" and ico_p.is_file():
        def _set_win32_icons():
            try:
                if not hasattr(window, "winfo_exists") or not window.winfo_exists():
                    return
                import win32gui
                import win32con

                hwnd = window.winfo_id()
                top_hwnd = None
                if hasattr(window, "wm_frame"):
                    try:
                        frame_str = window.wm_frame()
                        if frame_str:
                            top_hwnd = int(frame_str, 16)
                    except Exception:
                        pass
                if not top_hwnd:
                    top_hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT) or hwnd

                IMAGE_ICON = 1
                LR_LOADFROMFILE = 0x00000010

                hicon_sm = win32gui.LoadImage(0, str(ico_p), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
                hicon_lg = win32gui.LoadImage(0, str(ico_p), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)

                if hicon_sm:
                    win32gui.SendMessage(top_hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon_sm)
                if hicon_lg:
                    win32gui.SendMessage(top_hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon_lg)

                if hwnd and hwnd != top_hwnd:
                    if hicon_sm:
                        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon_sm)
                    if hicon_lg:
                        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon_lg)

                # Bind to window class so taskbar/explorer gets icon directly
                try:
                    user32 = ctypes.windll.user32
                    set_class_long = getattr(user32, "SetClassLongPtrW", getattr(user32, "SetClassLongW", None))
                    if set_class_long:
                        GCLP_HICON = -14
                        GCLP_HICONSM = -34
                        if hicon_lg:
                            set_class_long(top_hwnd, GCLP_HICON, hicon_lg)
                        if hicon_sm:
                            set_class_long(top_hwnd, GCLP_HICONSM, hicon_sm)
                except Exception:
                    pass
            except Exception:
                pass

        # Execute immediately and re-assert after 50ms and 200ms when OS window manager finishes mapping
        _set_win32_icons()
        if "unittest" in sys.modules:
            return

        try:
            is_withdrawn = False
            try:
                is_withdrawn = (getattr(window, "state", lambda: "")() == "withdrawn")
            except Exception:
                pass

            if not is_withdrawn and hasattr(window, "winfo_exists") and window.winfo_exists():
                t_ids = []

                def _cleanup_icon_timers(event=None):
                    if event is not None and getattr(event, "widget", None) != window:
                        return
                    for t in list(t_ids):
                        try:
                            window.after_cancel(t)
                        except Exception:
                            pass
                    t_ids.clear()

                window.bind("<Destroy>", _cleanup_icon_timers, add="+")
                t_ids.append(window.after(50, _set_win32_icons))
                t_ids.append(window.after(200, _set_win32_icons))
        except Exception:
            pass



def show_windows_toast(title: str, message: str) -> bool:
    """
    Display native Windows Toast Notification (Windows 10/11) asynchronously.
    Runs completely in the background without opening a console window.
    """
    if sys.platform != "win32":
        return False

    import base64
    import subprocess

    safe_title = title.replace('"', '`"').replace("$", "`$")
    safe_msg = message.replace('"', '`"').replace("$", "`$")

    ps_code = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $template.GetElementsByTagName("text")
$nodes.Item(0).InnerText = "{safe_title}"
$nodes.Item(1).InnerText = "{safe_msg}"
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe").Show($toast)
"""
    try:
        enc = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        return False


def hook_drop_files(widget: Any, on_drop_callback: Any) -> bool:
    """
    Enable native drag-and-drop of files onto a Tkinter widget.
    Uses tkinterdnd2 (TkDND extension) to safely integrate directly with Tk's event loop
    without dangerous Win32 window procedure subclassing.

    Args:
        widget: A Tkinter widget.
        on_drop_callback: Callable accepting a list of file paths (str).

    Returns:
        bool: True if successfully hooked, False otherwise.
    """
    try:
        from tkinterdnd2 import DND_FILES

        # Ensure widget has drop target registration capabilities
        if not hasattr(widget, "drop_target_register"):
            try:
                from tkinterdnd2 import TkinterDnD
                root = widget.winfo_toplevel()
                TkinterDnD._require(root)
            except Exception:
                pass

        if hasattr(widget, "drop_target_register"):
            def _on_drop(event):
                try:
                    data = getattr(event, "data", None)
                    if not data:
                        return
                    if isinstance(data, (list, tuple)):
                        raw_list = data
                    else:
                        try:
                            raw_list = widget.tk.splitlist(str(data))
                        except Exception:
                            raw_list = [str(data)]
                    cleaned = [p.strip().strip('"').strip("'") for p in raw_list if p.strip()]
                    if cleaned and on_drop_callback:
                        widget.after(0, lambda: on_drop_callback(cleaned))
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Lỗi xử lý file thả vào: %s", e)

            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", _on_drop)
            return True
    except Exception as ex:
        import logging
        logging.getLogger(__name__).debug("Không thể khởi tạo tkinterdnd2 cho widget %s: %s", widget, ex)

    return False


# --- Windows Process Power Throttling (EcoQoS) Integration ---

def disable_process_power_throttling() -> bool:
    """
    Disable Windows Power Throttling (EcoQoS / Efficiency Mode) for the current process.
    Prevents background or PiP video playback from dropping frames or being downclocked
    by the Windows scheduler when the user is multitasking or playing games.
    Returns True if successful, False otherwise.
    """
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32

        ProcessPowerThrottling = 4
        PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
        PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1

        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.ULONG),
                ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG),
            ]

        throttle = PROCESS_POWER_THROTTLING_STATE()
        throttle.Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION
        throttle.ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        throttle.StateMask = 0  # 0 turns off execution speed throttling

        hProcess = kernel32.GetCurrentProcess()
        SetProcessInformation = getattr(kernel32, "SetProcessInformation", None)
        if not SetProcessInformation:
            return False

        SetProcessInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        SetProcessInformation.restype = wintypes.BOOL

        ret = SetProcessInformation(
            hProcess,
            ProcessPowerThrottling,
            ctypes.byref(throttle),
            ctypes.sizeof(throttle),
        )
        return bool(ret)
    except Exception:
        return False


# --- Windows High-Precision Multimedia Timer Integration ---

_timer_period_active = False


def enable_high_precision_timer() -> bool:
    """
    Request 1ms timer resolution via winmm.timeBeginPeriod(1) on Windows.
    Reduces frame pacing jitter and eliminates 15.6ms default tick granularity.
    """
    global _timer_period_active
    if sys.platform != "win32":
        return False
    try:
        res = ctypes.windll.winmm.timeBeginPeriod(1)
        if res == 0:  # TIMERR_NOERROR
            _timer_period_active = True
            return True
        return False
    except Exception:
        return False


def disable_high_precision_timer() -> bool:
    """
    Restore default Windows timer resolution via winmm.timeEndPeriod(1).
    Should be called when the application closes.
    """
    global _timer_period_active
    if sys.platform != "win32" or not _timer_period_active:
        return False
    try:
        res = ctypes.windll.winmm.timeEndPeriod(1)
        if res == 0:
            _timer_period_active = False
            return True
        return False
    except Exception:
        return False


# --- CPU Core Affinity & Scheduling Integration ---

def apply_cpu_affinity(mode: str, sys_info: Any = None) -> bool:
    """
    Apply CPU Core Affinity to the current process.

    Modes:
        - "p_cores": Pin all threads to Performance Cores (P-cores) only.
                     Avoids scheduling any playback or decoding threads on slower E-cores.
        - "all": Utilize all logical cores (both P-cores and E-cores).
        - "auto": Allow all logical cores while relying on decoder thread bounding and EcoQoS disable.

    Returns True if successfully applied, False otherwise.
    """
    try:
        import psutil
        p = psutil.Process()
        total_cores = psutil.cpu_count(logical=True) or 4
        all_cores = list(range(total_cores))

        if mode == "p_cores" and sys_info and getattr(sys_info, "is_hybrid_cpu", False):
            target_cores = getattr(sys_info, "p_core_logical_indices", [])
            if target_cores:
                p.cpu_affinity(target_cores)
                return True

        # "all", "auto", or non-hybrid fallback
        p.cpu_affinity(all_cores)
        return True
    except Exception:
        return False


def get_monitor_bounds_for_window(window: Any) -> Optional[Tuple[int, int, int, int]]:
    """
    Get (left, top, width, height) of the physical monitor where the given window currently resides.
    Accurately handles multi-monitor configurations on Windows using MonitorFromWindow / MonitorFromPoint.
    Returns (left, top, width, height) or None.
    """
    if sys.platform != "win32":
        try:
            return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
        except Exception:
            return None

    try:
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        window.update_idletasks()
        wid = window.winfo_id()
        hwnd = user32.GetAncestor(wid, 2) or user32.GetParent(wid) or wid

        # MONITOR_DEFAULTTONEAREST = 2
        hMonitor = user32.MonitorFromWindow(hwnd, 2)
        if not hMonitor:
            # Fallback using center point of window
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            rect = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
            else:
                cx = window.winfo_rootx() + window.winfo_width() // 2
                cy = window.winfo_rooty() + window.winfo_height() // 2
            hMonitor = user32.MonitorFromPoint(POINT(cx, cy), 2)

        if hMonitor:
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi)):
                rc = mi.rcMonitor
                return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)

    except Exception:
        pass

    try:
        return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
    except Exception:
        return None


def is_rect_visible_on_any_monitor(x: int, y: int, w: int, h: int) -> bool:
    """
    Check if the given rectangle (x, y, w, h) intersects with any currently active physical monitor.
    Uses Win32 user32.MonitorFromRect(..., MONITOR_DEFAULTTONULL).
    Returns False if the rectangle is off-screen (e.g. on a disconnected monitor).
    """
    if sys.platform != "win32":
        return True

    try:
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        user32 = ctypes.windll.user32
        rect = RECT(int(x), int(y), int(x + w), int(y + h))
        # MONITOR_DEFAULTTONULL = 0
        h_monitor = user32.MonitorFromRect(ctypes.byref(rect), 0)
        return bool(h_monitor)
    except Exception:
        return True


def get_monitor_work_area_for_window(window: Any) -> Tuple[int, int, int, int]:
    """
    Get (left, top, width, height) of the physical monitor work area (excluding taskbar)
    where the given window currently resides.
    Falls back to (0, 0, screenwidth, screenheight) on failure or non-Windows.
    """
    if sys.platform != "win32":
        try:
            return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
        except Exception:
            return (0, 0, 1920, 1080)

    try:
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        window.update_idletasks()
        wid = window.winfo_id()
        hwnd = user32.GetAncestor(wid, 2) or user32.GetParent(wid) or wid

        h_monitor = user32.MonitorFromWindow(hwnd, 2)
        if not h_monitor:
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            rect = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
            else:
                cx = window.winfo_rootx() + window.winfo_width() // 2
                cy = window.winfo_rooty() + window.winfo_height() // 2
            h_monitor = user32.MonitorFromPoint(POINT(cx, cy), 2)

        if h_monitor:
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(h_monitor, ctypes.byref(mi)):
                rc = mi.rcWork
                return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
    except Exception:
        pass

    try:
        return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
    except Exception:
        return (0, 0, 1920, 1080)


def get_monitor_work_area_for_rect(x: int, y: int, w: int, h: int) -> Tuple[int, int, int, int]:
    """
    Get (left, top, width, height) of the physical monitor work area (excluding taskbar)
    nearest to or intersecting the given rectangle.
    Useful for multi-monitor edge snapping and clamping when moving/resizing PiP.
    """
    if sys.platform != "win32":
        return (0, 0, 1920, 1080)

    try:
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        rect = RECT(int(x), int(y), int(x + w), int(y + h))
        # MONITOR_DEFAULTTONEAREST = 2
        h_monitor = user32.MonitorFromRect(ctypes.byref(rect), 2)
        if h_monitor:
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(h_monitor, ctypes.byref(mi)):
                rc = mi.rcWork
                return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
    except Exception:
        pass

    return (0, 0, 1920, 1080)


def trim_process_memory() -> None:
    """
    Yêu cầu Windows thu hồi các trang nhớ vật lý nhàn rỗi (stale working set pages)
    trả về lại RAM của hệ thống. An toàn tuyệt đối, không ảnh hưởng tiến trình.
    Chỉ gọi sau các tác vụ nặng đã hoàn thành (resolve, đóng dialog lớn, dừng media, sau khi tua/seek).
    - KHÔNG BAO GIỜ gọi trong vòng lặp UI timer 250ms.
    """
    if sys.platform == "win32":
        try:
            from ctypes import wintypes
            handle = ctypes.windll.kernel32.GetCurrentProcess()

            # 1. Thử EmptyWorkingSet từ psapi / kernel32 (Chuẩn Win32 API)
            try:
                psapi = ctypes.windll.psapi
                psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
                psapi.EmptyWorkingSet.restype = wintypes.BOOL
                if psapi.EmptyWorkingSet(handle):
                    return
            except Exception:
                pass

            try:
                k32 = ctypes.windll.kernel32
                k32.K32EmptyWorkingSet.argtypes = [wintypes.HANDLE]
                k32.K32EmptyWorkingSet.restype = wintypes.BOOL
                if k32.K32EmptyWorkingSet(handle):
                    return
            except Exception:
                pass

            # 2. Fallback sang SetProcessWorkingSetSize với SIZE_T 64-bit chuẩn
            k32 = ctypes.windll.kernel32
            k32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
            k32.SetProcessWorkingSetSize.restype = wintypes.BOOL
            size_t_max = ctypes.c_size_t(-1).value
            k32.SetProcessWorkingSetSize(handle, size_t_max, size_t_max)
        except Exception:
            pass


def apply_fullscreen_on_monitor(window: Any, mon_bounds: Optional[Tuple[int, int, int, int]] = None) -> None:
    """
    Ensure the window is positioned on the given monitor bounds during fullscreen.
    On Windows, Tkinter's attributes('-fullscreen', True) forces the window to the primary
    display (0, 0, SM_CXSCREEN, SM_CYSCREEN) and ignores root.geometry(). We reposition the
    Win32 top-level window via SetWindowPos directly to the target monitor bounds.
    """
    if sys.platform != "win32" or not mon_bounds:
        return
    try:
        user32 = ctypes.windll.user32
        try:
            keep_withdrawn = window.state() == "withdrawn"
        except Exception:
            keep_withdrawn = False
        window.update_idletasks()
        wid = window.winfo_id()
        hwnd = user32.GetAncestor(wid, 2) or user32.GetParent(wid) or wid
        mx, my, mw, mh = mon_bounds
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        SWP_SHOWWINDOW = 0x0040
        flags = SWP_NOZORDER | SWP_FRAMECHANGED
        if not keep_withdrawn:
            flags |= SWP_SHOWWINDOW
        user32.SetWindowPos(hwnd, 0, mx, my, mw, mh, flags)

        def _recheck():
            try:
                cur_hwnd = user32.GetAncestor(wid, 2) or user32.GetParent(wid) or wid
                user32.SetWindowPos(cur_hwnd, 0, mx, my, mw, mh, flags)
            except Exception:
                pass

        window.after(30, _recheck)
        window.after(100, _recheck)
    except Exception:
        pass


def get_app_launch_command() -> str:
    """Return command string for launching FB Video Watcher with an argument."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    project_root = Path(__file__).resolve().parent.parent
    main_py = project_root / "main.py"
    py_exec = sys.executable
    if py_exec.lower().endswith("python.exe"):
        pyw = Path(py_exec).with_name("pythonw.exe")
        if pyw.is_file():
            py_exec = str(pyw)
    return f'"{py_exec}" "{main_py}" "%1"'


def is_fbvw_protocol_registered() -> bool:
    """Check if fbvw:// URI protocol handler is registered in HKCU."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\fbvw\shell\open\command") as key:
            val, _ = winreg.QueryValueEx(key, "")
            return bool(val)
    except OSError:
        return False


def register_fbvw_protocol() -> bool:
    """Register fbvw:// protocol in HKCU (no admin rights required)."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        cmd = get_app_launch_command()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\fbvw") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:FB Video Watcher Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\fbvw\shell\open\command") as cmd_key:
            winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)
        return True
    except OSError:
        return False


def unregister_fbvw_protocol() -> bool:
    """Unregister fbvw:// protocol from HKCU."""
    if sys.platform != "win32":
        return False
    import winreg

    def _delete_key_tree(root, subkey):
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                        _delete_key_tree(root, f"{subkey}\\{child}")
                    except OSError:
                        break
            winreg.DeleteKey(root, subkey)
        except OSError:
            pass

    _delete_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\fbvw")
    return not is_fbvw_protocol_registered()


def _get_ipc_pipe_name() -> str:
    import getpass
    username = getpass.getuser()
    return rf"\\.\pipe\fbvw_ipc_{username}"


_ipc_listener = None


def send_to_existing_instance(payload: dict) -> bool:
    """Attempt to forward launch request payload to an active instance via Named Pipe."""
    if sys.platform != "win32":
        return False
    from multiprocessing.connection import Client
    try:
        pipe_name = _get_ipc_pipe_name()
        conn = Client(pipe_name, "AF_PIPE", authkey=b"fbvw_ipc")
        conn.send(payload)
        conn.close()
        return True
    except Exception:
        return False


def start_ipc_server(on_payload_callback: Callable[[dict], None]) -> Optional[Any]:
    """Start Named Pipe listener in background thread to receive payloads from other instances."""
    if sys.platform != "win32":
        return None
    global _ipc_listener
    from multiprocessing.connection import Listener
    import threading

    try:
        pipe_name = _get_ipc_pipe_name()
        listener = Listener(pipe_name, "AF_PIPE", authkey=b"fbvw_ipc")
        _ipc_listener = listener
    except Exception:
        return None

    def _loop():
        while True:
            try:
                conn = listener.accept()
            except Exception:
                break
            try:
                payload = conn.recv()
                conn.close()
                if isinstance(payload, dict):
                    on_payload_callback(payload)
            except Exception:
                pass

    t = threading.Thread(target=_loop, name="FBVW-IPC-Server", daemon=True)
    t.start()
    return listener


def stop_ipc_server() -> None:
    """Close the IPC listener on app exit."""
    global _ipc_listener
    if _ipc_listener:
        try:
            _ipc_listener.close()
        except Exception:
            pass
        _ipc_listener = None


def bring_window_to_front(window: Any) -> None:
    """Bring the Tkinter root window to the foreground on Windows."""
    try:
        window.deiconify()
        window.lift()
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            wid = window.winfo_id()
            hwnd = user32.GetAncestor(wid, 2) or user32.GetParent(wid) or wid
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def apply_windows_gpu_preference(
    target_executable: Optional[str] = None,
    mode: str = "power_saving",
) -> bool:
    """
    Register application graphics preference in Windows UserGpuPreferences.
    Path: HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences

    Modes:
        - "power_saving": GpuPreference=1 (Route to integrated GPU in CPU / QuickSync).
        - "high_performance": GpuPreference=2 (Route to discrete GPU).
        - "default": GpuPreference=0 (Let Windows decide).

    Returns True if successfully written, False otherwise.
    """
    if sys.platform != "win32":
        return False

    exe_path = target_executable or sys.executable
    if not exe_path:
        return False

    pref_code = 1
    if mode == "high_performance":
        pref_code = 2
    elif mode == "default":
        pref_code = 0
    elif mode == "power_saving":
        pref_code = 1

    try:
        import winreg
        key_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ) as k:
            val_data = f"GpuPreference={pref_code};"
            winreg.SetValueEx(k, exe_path, 0, winreg.REG_SZ, val_data)
        return True
    except Exception:
        return False


def get_windows_gpu_preference(target_executable: Optional[str] = None) -> Optional[str]:
    """
    Query current application graphics preference from Windows UserGpuPreferences.
    Returns: "power_saving", "high_performance", "default", or None.
    """
    if sys.platform != "win32":
        return None

    exe_path = target_executable or sys.executable
    if not exe_path:
        return None

    try:
        import winreg
        key_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, exe_path)
            if "GpuPreference=1;" in val:
                return "power_saving"
            elif "GpuPreference=2;" in val:
                return "high_performance"
            elif "GpuPreference=0;" in val:
                return "default"
    except Exception:
        return None
    return None



