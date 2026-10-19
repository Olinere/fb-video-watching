"""
VLC Setup Dialog module.
Provides a Tkinter progress-bar dialog that drives the VLC download + silent install
sequence defined in vlc_installer.py.

Responsibilities (pure UI, zero download/install logic):
- Ask the user whether to auto-install VLC.
- Show a labelled progress bar while vlc_installer.download_vlc() runs in a thread.
- Show a "Installing..." indeterminate bar while vlc_installer.install_vlc_silent() runs.
- Display success / failure messages and drive the main.py flow via a result code.

Result codes returned by VLCSetupDialog.run():
    "installed"  — VLC was downloaded and installed; caller should re-check and launch.
    "skipped"    — User declined; caller should exit or show manual instructions.
    "failed"     — Download or install failed; caller should show error and exit.
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, Callable, Any

from main.vlc_installer import (
    VLC_VERSION,
    VLC_DIRECT_DOWNLOAD_URL,
    download_vlc,
    install_vlc_silent,
    make_temp_installer_path,
    cleanup_installer,
    is_vlc_available,
)
from main.platform_utils import apply_window_icon, set_windows_dark_titlebar

logger = logging.getLogger("FBVideoWatcher.VLCSetupDialog")

# ---------------------------------------------------------------------------
# Human-readable string constants (easy to localise)
# ---------------------------------------------------------------------------

_STR = {
    "title": "Thiết lập VLC Media Player",
    "prompt_title": "Chưa cài đặt VLC Media Player",
    "prompt_body": (
        "Ứng dụng cần VLC Media Player (64-bit) để phát video.\n\n"
        f"Phiên bản khuyến nghị: VLC {VLC_VERSION} (64-bit)\n"
        f"Nguồn tải: {VLC_DIRECT_DOWNLOAD_URL}\n\n"
        "Bạn có muốn tải và cài đặt VLC tự động không?\n"
        "(Khoảng ~45 MB, cần kết nối Internet)"
    ),
    "btn_install": "✅ Tải & Cài tự động",
    "btn_skip": "❌ Thoát",
    "label_downloading": "Đang tải VLC...",
    "label_installing": "Đang cài đặt VLC (có thể mất 1-2 phút)...",
    "label_done": "✅ Cài đặt VLC thành công! Đang khởi động ứng dụng...",
    "label_failed": "❌ Cài đặt thất bại. Vui lòng cài VLC thủ công.",
    "label_cancelled": "Đã hủy tải VLC.",
    "btn_cancel": "Hủy tải",
    "err_download": "Không thể tải VLC:\n{error}\n\nVui lòng tải thủ công tại:\n{url}",
    "err_install": "Không thể cài VLC:\n{error}",
    "err_verify": (
        "VLC đã cài nhưng ứng dụng vẫn chưa nhận diện được.\n"
        "Vui lòng khởi động lại máy tính rồi mở lại ứng dụng."
    ),
}

# ---------------------------------------------------------------------------
# Confirmation dialog (before download starts)
# ---------------------------------------------------------------------------


def ask_auto_install(parent: Optional[tk.Tk] = None) -> bool:
    """
    Show a yes/no dialog asking the user whether to auto-install VLC.
    Returns True if the user agreed, False otherwise.
    This function is intentionally decoupled from VLCDownloadDialog so it
    can be unit-tested without running a full dialog event loop.
    """
    root = parent or tk.Tk()
    if parent is None:
        root.withdraw()
        apply_window_icon(root)

    result = messagebox.askyesno(
        _STR["prompt_title"],
        _STR["prompt_body"],
        icon="question",
        parent=root if parent else None,
    )

    if parent is None:
        root.destroy()

    return bool(result)


# ---------------------------------------------------------------------------
# Optional Update prompt dialog (when VLC is installed but older)
# ---------------------------------------------------------------------------


class VLCUpdatePromptDialog:
    """
    Dialog presented when an existing compatible VLC installation is detected
    (e.g. 3.0.21), but a newer recommended release (3.0.23) is available.
    User can choose:
      - "update": Proceeds to VLCDownloadDialog to install update.
      - "skip": Continues launching application normally with current VLC.
    """

    def __init__(self, parent: tk.Tk, installed_version: str):
        self._parent = parent
        self._action = "skip"  # "update" | "skip"
        self._skip_future = False

        self._win = tk.Toplevel(parent)
        self._win.title("Cập nhật VLC Media Player")
        self._win.resizable(False, False)
        self._win.grab_set()
        self._win.protocol("WM_DELETE_WINDOW", self._on_skip)
        self._win.configure(bg="#1e1e2e", padx=24, pady=20)

        apply_window_icon(self._win)
        try:
            set_windows_dark_titlebar(self._win, dark=True)
        except Exception:
            pass

        self._win.bind("<Escape>", lambda _e: self._on_skip())

        self._win.update_idletasks()
        w, h = 480, 230
        x = (self._win.winfo_screenwidth() - w) // 2
        y = (self._win.winfo_screenheight() - h) // 2
        self._win.geometry(f"{w}x{h}+{x}+{y}")

        title_lbl = tk.Label(
            self._win,
            text=f"Đã có phiên bản VLC Media Player mới ({VLC_VERSION})",
            font=("Segoe UI", 10, "bold"),
            bg="#1e1e2e",
            fg="#cdd6f4",
            anchor="w",
        )
        title_lbl.pack(fill=tk.X, pady=(0, 6))

        body_text = (
            f"Bạn đang sử dụng VLC {installed_version} (hoạt động tốt với ứng dụng).\n"
            f"Hiện đã có bản phát hành VLC {VLC_VERSION} mới hơn.\n\n"
            "Bạn có muốn cập nhật lên phiên bản mới nhất không?"
        )
        desc_lbl = tk.Label(
            self._win,
            text=body_text,
            font=("Segoe UI", 9),
            bg="#1e1e2e",
            fg="#a6adc8",
            justify=tk.LEFT,
            anchor="w",
            wraplength=430,
        )
        desc_lbl.pack(fill=tk.X, pady=(0, 10))

        # Checkbox "Không nhắc lại cho phiên bản này"
        self._dont_show_var = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(
            self._win,
            text=f"Không nhắc lại cho phiên bản {VLC_VERSION}",
            variable=self._dont_show_var,
            bg="#1e1e2e",
            fg="#cdd6f4",
            activebackground="#1e1e2e",
            activeforeground="#ffffff",
            selectcolor="#313244",
            font=("Segoe UI", 8),
        )
        chk.pack(anchor="w", pady=(0, 12))

        # Button row
        btn_frame = tk.Frame(self._win, bg="#1e1e2e")
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        btn_skip = tk.Button(
            btn_frame,
            text="Để sau (Tiếp tục)",
            command=self._on_skip,
            bg="#313244",
            fg="#cdd6f4",
            activebackground="#45475a",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            cursor="hand2",
        )
        btn_skip.pack(side=tk.RIGHT, padx=(8, 0))

        btn_update = tk.Button(
            btn_frame,
            text="✅ Cập nhật ngay",
            command=self._on_update,
            bg="#0067c0",
            fg="#ffffff",
            activebackground="#0078d4",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )
        btn_update.pack(side=tk.RIGHT)

    def _on_update(self) -> None:
        self._action = "update"
        self._skip_future = self._dont_show_var.get()
        try:
            self._win.grab_release()
        except Exception:
            pass
        self._win.destroy()

    def _on_skip(self) -> None:
        self._action = "skip"
        self._skip_future = self._dont_show_var.get()
        try:
            self._win.grab_release()
        except Exception:
            pass
        self._win.destroy()

    def run(self) -> tuple[str, bool]:
        """Returns (action, skip_future) where action is 'update' or 'skip'."""
        self._parent.wait_window(self._win)
        return self._action, self._skip_future


def prompt_vlc_update(installed_version: str, parent: Optional[tk.Tk] = None) -> tuple[str, bool]:
    """
    Show optional VLC update dialog.
    Returns (action, skip_future) where action is 'update' or 'skip'.
    """
    own_root = False
    if parent is None:
        parent = tk.Tk()
        parent.withdraw()
        apply_window_icon(parent)
        own_root = True

    try:
        dialog = VLCUpdatePromptDialog(parent, installed_version)
        return dialog.run()
    finally:
        if own_root:
            try:
                parent.destroy()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Download + Install progress dialog
# ---------------------------------------------------------------------------


class VLCDownloadDialog:
    """
    Modal Tk window showing a labelled progress bar while VLC is downloaded
    and installed in a background thread.

    Usage:
        dialog = VLCDownloadDialog(parent_root)
        result = dialog.run()   # "installed" | "failed" | "cancelled"
    """

    # Internal event identifiers posted via root.after()
    _EVT_PROGRESS = "<<VLCProgress>>"
    _EVT_PHASE = "<<VLCPhase>>"
    _EVT_DONE = "<<VLCDone>>"
    _EVT_ERROR = "<<VLCError>>"

    def __init__(self, parent: tk.Tk):
        self._parent = parent
        self._result: str = "failed"
        self._phase: str = "download"
        self._cancel_event = threading.Event()
        self._installer_path: Optional[Path] = None

        # --- Build the dialog window ---
        self._win = tk.Toplevel(parent)
        self._win.title(_STR["title"])
        self._win.resizable(False, False)
        self._win.grab_set()  # modal
        self._win.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._win.bind("<Escape>", lambda _e: self._on_cancel())
        self._win.configure(bg="#1e1e2e", padx=24, pady=20)

        apply_window_icon(self._win)
        try:
            set_windows_dark_titlebar(self._win, dark=True)
        except Exception:
            pass

        # Centre on screen
        self._win.update_idletasks()
        w, h = 460, 170
        x = (self._win.winfo_screenwidth() - w) // 2
        y = (self._win.winfo_screenheight() - h) // 2
        self._win.geometry(f"{w}x{h}+{x}+{y}")

        # Status label
        self._label_var = tk.StringVar(value=_STR["label_downloading"])
        lbl = tk.Label(
            self._win,
            textvariable=self._label_var,
            font=("Segoe UI", 10),
            bg="#1e1e2e",
            fg="#cdd6f4",
            anchor="w",
            wraplength=420,
        )
        lbl.pack(fill=tk.X, pady=(0, 8))

        # Progress bar - starts indeterminate while connecting to mirror
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            self._win,
            orient="horizontal",
            length=420,
            mode="indeterminate",
            variable=self._progress_var,
            maximum=100.0,
        )
        self._progress_bar.pack(fill=tk.X, pady=(0, 6))
        self._progress_bar.start(10)

        # Byte counter label
        self._bytes_var = tk.StringVar(value="Đang kết nối tới máy chủ tải...")
        tk.Label(
            self._win,
            textvariable=self._bytes_var,
            font=("Segoe UI", 8),
            bg="#1e1e2e",
            fg="#6c7086",
        ).pack(anchor="w")

        # Cancel button
        self._btn_cancel = tk.Button(
            self._win,
            text=_STR["btn_cancel"],
            command=self._on_cancel,
            bg="#313244",
            fg="#cdd6f4",
            activebackground="#45475a",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            cursor="hand2",
        )
        self._btn_cancel.pack(anchor="e", pady=(10, 0))

        # Thread-safe UI communication queue & main-thread poller
        self._ui_queue: queue.Queue = queue.Queue()
        self._polling_active: bool = True
        self._win.after(50, self._poll_ui_queue)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> str:
        """
        Start the background download/install thread and enter the Tk event loop.
        Returns "installed", "cancelled", or "failed".
        """
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()
        self._parent.wait_window(self._win)
        return self._result

    # ------------------------------------------------------------------
    # Main-thread Queue Poller
    # ------------------------------------------------------------------

    def _poll_ui_queue(self) -> None:
        """
        Runs on the main UI thread via after(50) to drain messages from worker thread.
        Never calls Tkinter methods from secondary threads.
        """
        if not self._polling_active or not (self._win and self._win.winfo_exists()):
            return

        latest_progress = None
        try:
            while not self._ui_queue.empty():
                msg_type, payload = self._ui_queue.get_nowait()
                if msg_type == "progress":
                    latest_progress = payload  # Coalesce: only keep latest progress to avoid UI lag
                elif msg_type == "phase":
                    self._on_phase_update(payload)
                elif msg_type == "done":
                    self._polling_active = False
                    self._on_done_update()
                    return
                elif msg_type == "error":
                    self._polling_active = False
                    self._on_error_update(payload)
                    return

            if latest_progress:
                downloaded, total = latest_progress
                self._on_progress_update(downloaded, total)
        except Exception as exc:
            logger.warning(f"Lỗi khi xử lý UI queue: {exc}")

        if self._polling_active and self._win and self._win.winfo_exists():
            self._win.after(50, self._poll_ui_queue)

    # ------------------------------------------------------------------
    # Background worker (runs in worker thread; purely Python, zero Tk calls)
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Download then install VLC; post messages to the thread-safe UI queue."""
        try:
            installer_path = make_temp_installer_path()
            self._installer_path = installer_path

            # --- Phase 1: Download ---
            try:
                download_vlc(
                    dest_path=installer_path,
                    progress_cb=self._on_progress_cb,
                    cancel_event=self._cancel_event,
                )
            except (RuntimeError, Exception) as exc:
                if str(exc) in ("cancelled", "cancelled_by_user"):
                    self._result = "cancelled"
                    self._ui_queue.put(("phase", _STR["label_cancelled"]))
                    self._safe_destroy_after(400)
                    return
                self._pending_error = _STR["err_download"].format(
                    error=exc, url=VLC_DIRECT_DOWNLOAD_URL
                )
                self._ui_queue.put(("error", self._pending_error))
                return

            # --- Phase 2: Silent Install ---
            self._phase = "installing"
            self._ui_queue.put(("phase", _STR["label_installing"]))

            try:
                install_vlc_silent(installer_path)
            except (RuntimeError, Exception) as exc:
                if str(exc) in ("cancelled", "cancelled_by_user"):
                    self._result = "cancelled"
                    self._ui_queue.put(("phase", _STR["label_cancelled"]))
                    self._safe_destroy_after(400)
                    return
                self._pending_error = _STR["err_install"].format(error=exc)
                self._ui_queue.put(("error", self._pending_error))
                return
            finally:
                cleanup_installer(installer_path)

            # --- Phase 3: Verify with retry ---
            self._phase = "done"
            import time
            vlc_ok = False
            for _ in range(3):
                if is_vlc_available():
                    vlc_ok = True
                    break
                time.sleep(0.5)

            if not vlc_ok:
                self._pending_error = _STR["err_verify"]
                self._ui_queue.put(("error", self._pending_error))
                return

            self._result = "installed"
            self._ui_queue.put(("done", None))
        except Exception as exc:
            logger.error(f"Ngoại lệ không lường trước trong worker tải VLC: {exc}")
            self._pending_error = f"Lỗi không xác định: {exc}"
            self._ui_queue.put(("error", self._pending_error))

    def _on_progress_cb(self, downloaded: int, total: int) -> None:
        """Called from the download thread; queues progress payload (100% thread-safe)."""
        self._ui_queue.put(("progress", (downloaded, total)))

    # ------------------------------------------------------------------
    # Event handlers (always run on the main thread via _poll_ui_queue)
    # ------------------------------------------------------------------

    def _on_progress_update(self, downloaded: int, total: int) -> None:
        if downloaded > 0 and str(self._progress_bar.cget("mode")) == "indeterminate":
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate")

        if total > 0:
            pct = min(downloaded / total * 100, 100)
            self._progress_var.set(pct)
            dl_mb = downloaded / 1_048_576
            tot_mb = total / 1_048_576
            self._bytes_var.set(f"{dl_mb:.1f} MB / {tot_mb:.1f} MB  ({pct:.0f}%)")
        else:
            dl_mb = downloaded / 1_048_576
            self._bytes_var.set(f"{dl_mb:.1f} MB đã tải...")

    def _on_phase_update(self, label: str) -> None:
        self._label_var.set(label)
        if label == _STR["label_cancelled"]:
            self._progress_bar.stop()
            self._btn_cancel.configure(state=tk.DISABLED)
        else:
            # Switch to indeterminate for install phase
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start(12)
            self._btn_cancel.configure(state=tk.DISABLED)

    def _on_done_update(self) -> None:
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_var.set(100)
        self._label_var.set(_STR["label_done"])
        self._bytes_var.set("")
        self._safe_destroy_after(1200)

    def _on_error_update(self, error_msg: str) -> None:
        self._progress_bar.stop()
        self._label_var.set(_STR["label_failed"])
        self._btn_cancel.configure(state=tk.DISABLED)
        messagebox.showerror(
            _STR["title"],
            error_msg,
            parent=self._win,
        )
        self._result = "failed"
        self._safe_destroy()

    def _safe_destroy(self) -> None:
        """Safely release modal grab and destroy dialog window."""
        self._polling_active = False
        try:
            if self._win and self._win.winfo_exists():
                self._win.grab_release()
                self._win.destroy()
        except Exception:
            pass

    def _safe_destroy_after(self, ms: int = 400) -> None:
        """Schedule safe window destruction via Tk after timer."""
        try:
            if self._win and self._win.winfo_exists():
                self._win.after(ms, self._safe_destroy)
        except Exception:
            pass

    def _on_cancel(self) -> None:
        if getattr(self, "_phase", "download") == "installing":
            return
        self._polling_active = False
        self._cancel_event.set()
        self._result = "cancelled"
        self._label_var.set(_STR["label_cancelled"])
        try:
            self._progress_bar.stop()
        except Exception:
            pass
        self._btn_cancel.configure(state=tk.DISABLED)
        self._safe_destroy_after(400)


# ---------------------------------------------------------------------------
# High-level convenience function used by main.py
# ---------------------------------------------------------------------------


def run_vlc_setup(parent: Optional[tk.Tk] = None, skip_prompt: bool = False) -> str:
    """
    Full VLC setup flow:
      1. Ask user whether to auto-install (unless skip_prompt=True).
      2. Show download + install dialog.
      3. Return result code: "installed" | "skipped" | "failed" | "cancelled".

    Args:
        parent: Optional existing Tk root (used as dialog parent).
                If None, a temporary hidden Tk root is created internally.
        skip_prompt: If True, bypasses the initial confirmation dialog and
                     proceeds immediately to downloading/installing.
    """
    own_root = False
    if parent is None:
        parent = tk.Tk()
        parent.withdraw()
        apply_window_icon(parent)
        own_root = True

    try:
        if not skip_prompt:
            agreed = ask_auto_install(parent)
            if not agreed:
                return "skipped"

        dialog = VLCDownloadDialog(parent)
        return dialog.run()
    finally:
        if own_root:
            try:
                parent.destroy()
            except Exception:
                pass
