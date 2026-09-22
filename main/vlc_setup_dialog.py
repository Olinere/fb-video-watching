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
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional

from main.vlc_installer import (
    VLC_VERSION,
    VLC_WIN64_DOWNLOAD_URL,
    download_vlc,
    install_vlc_silent,
    make_temp_installer_path,
    cleanup_installer,
    is_vlc_available,
)

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
        f"Nguồn tải: {VLC_WIN64_DOWNLOAD_URL}\n\n"
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
        self._cancel_event = threading.Event()
        self._installer_path: Optional[Path] = None

        # --- Build the dialog window ---
        self._win = tk.Toplevel(parent)
        self._win.title(_STR["title"])
        self._win.resizable(False, False)
        self._win.grab_set()  # modal
        self._win.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._win.configure(bg="#1e1e2e", padx=24, pady=20)

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

        # Progress bar
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            self._win,
            orient="horizontal",
            length=420,
            mode="determinate",
            variable=self._progress_var,
            maximum=100.0,
        )
        self._progress_bar.pack(fill=tk.X, pady=(0, 6))

        # Byte counter label
        self._bytes_var = tk.StringVar(value="")
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

        # Bind virtual events dispatched from the worker thread via root.after()
        self._win.bind(self._EVT_PROGRESS, self._on_progress_event)
        self._win.bind(self._EVT_PHASE, self._on_phase_event)
        self._win.bind(self._EVT_DONE, self._on_done_event)
        self._win.bind(self._EVT_ERROR, self._on_error_event)

        # Worker thread state shared across callbacks
        self._pending_progress: tuple[int, int] = (0, 0)
        self._pending_phase: str = ""
        self._pending_error: str = ""

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
    # Background worker
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Download then install VLC; post virtual events for UI updates."""
        installer_path = make_temp_installer_path()
        self._installer_path = installer_path

        # --- Phase 1: Download ---
        try:
            download_vlc(
                dest_path=installer_path,
                progress_cb=self._on_progress_cb,
                cancel_event=self._cancel_event,
            )
        except RuntimeError as exc:
            if str(exc) == "cancelled":
                self._result = "cancelled"
                self._post_event(self._EVT_PHASE, _STR["label_cancelled"])
                self._win.after(800, self._win.destroy)
                return
            self._pending_error = _STR["err_download"].format(
                error=exc, url=VLC_WIN64_DOWNLOAD_URL
            )
            self._post_event(self._EVT_ERROR, "")
            return

        # --- Phase 2: Silent Install ---
        self._post_event(self._EVT_PHASE, _STR["label_installing"])

        try:
            install_vlc_silent(installer_path)
        except RuntimeError as exc:
            self._pending_error = _STR["err_install"].format(error=exc)
            self._post_event(self._EVT_ERROR, "")
            return
        finally:
            cleanup_installer(installer_path)

        # --- Phase 3: Verify ---
        if not is_vlc_available():
            self._pending_error = _STR["err_verify"]
            self._post_event(self._EVT_ERROR, "")
            return

        self._result = "installed"
        self._post_event(self._EVT_DONE, "")

    def _on_progress_cb(self, downloaded: int, total: int) -> None:
        """Called from the download thread; schedules a UI update via after()."""
        self._pending_progress = (downloaded, total)
        self._post_event(self._EVT_PROGRESS, "")

    def _post_event(self, event: str, data: str = "") -> None:
        """Thread-safe way to post a virtual event to the Tk window."""
        try:
            self._win.event_generate(event, when="tail", data=data)
        except Exception:
            pass  # window may have been destroyed already

    # ------------------------------------------------------------------
    # Event handlers (always run on the main thread)
    # ------------------------------------------------------------------

    def _on_progress_event(self, _event: tk.Event) -> None:
        downloaded, total = self._pending_progress
        if total > 0:
            pct = min(downloaded / total * 100, 100)
            self._progress_bar.configure(mode="determinate")
            self._progress_var.set(pct)
            dl_mb = downloaded / 1_048_576
            tot_mb = total / 1_048_576
            self._bytes_var.set(f"{dl_mb:.1f} MB / {tot_mb:.1f} MB  ({pct:.0f}%)")
        else:
            # Unknown total — switch to indeterminate bounce
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.step(2)
            dl_mb = downloaded / 1_048_576
            self._bytes_var.set(f"{dl_mb:.1f} MB đã tải...")

    def _on_phase_event(self, event: tk.Event) -> None:
        label = getattr(event, "data", "") or self._pending_phase
        self._label_var.set(label)
        # Switch to indeterminate for install phase
        self._progress_bar.configure(mode="indeterminate")
        self._progress_bar.start(12)
        self._btn_cancel.configure(state=tk.DISABLED)

    def _on_done_event(self, _event: tk.Event) -> None:
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_var.set(100)
        self._label_var.set(_STR["label_done"])
        self._bytes_var.set("")
        self._win.after(1500, self._win.destroy)

    def _on_error_event(self, _event: tk.Event) -> None:
        self._progress_bar.stop()
        self._label_var.set(_STR["label_failed"])
        self._btn_cancel.configure(state=tk.DISABLED)
        messagebox.showerror(
            _STR["title"],
            self._pending_error,
            parent=self._win,
        )
        self._result = "failed"
        self._win.destroy()

    def _on_cancel(self) -> None:
        self._cancel_event.set()
        self._result = "cancelled"
        self._label_var.set(_STR["label_cancelled"])
        self._btn_cancel.configure(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# High-level convenience function used by main.py
# ---------------------------------------------------------------------------


def run_vlc_setup(parent: Optional[tk.Tk] = None) -> str:
    """
    Full VLC setup flow:
      1. Ask user whether to auto-install.
      2. If yes, show download + install dialog.
      3. Return result code: "installed" | "skipped" | "failed" | "cancelled".

    Args:
        parent: Optional existing Tk root (used as dialog parent).
                If None, a temporary hidden Tk root is created internally.
    """
    own_root = False
    if parent is None:
        parent = tk.Tk()
        parent.withdraw()
        own_root = True

    try:
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
