"""FFmpeg Setup Dialog module.

Provides a Tkinter progress-bar dialog that drives the FFmpeg portable
download and extraction process without freezing the main application thread.
"""

import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Callable, Optional

from main.ffmpeg_installer import download_and_extract_ffmpeg
from main.platform_utils import set_windows_dark_titlebar
from main.theme import ThemeManager

logger = logging.getLogger("FBVideoWatcher.FFmpegSetupDialog")


class FFmpegDownloadDialog:
    """Modal Tk window showing a live progress bar while portable FFmpeg is downloaded."""

    def __init__(
        self,
        parent: tk.Tk,
        theme_mgr: Optional[ThemeManager] = None,
        on_success: Optional[Callable[[Path], None]] = None,
    ):
        self._parent = parent
        self.theme = theme_mgr
        self.on_success = on_success
        self._result: str = "failed"
        self._cancel_event = threading.Event()
        self._installed_path: Optional[Path] = None

        # Build dialog window
        self._win = tk.Toplevel(parent)
        self._win.title("📥 Tải tiện ích FFmpeg (Add-on)")
        self._win.resizable(False, False)
        self._win.grab_set()
        self._win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        is_dark = getattr(self.theme, "current_theme", "dark") == "dark" if self.theme else True
        bg = "#1e1e2e" if is_dark else "#f3f3f3"
        fg = "#cdd6f4" if is_dark else "#1a1a1a"
        sub_fg = "#a6adc8" if is_dark else "#666666"

        self._win.configure(bg=bg, padx=20, pady=16)

        try:
            set_windows_dark_titlebar(self._win, dark=is_dark)
        except Exception:
            pass

        # Center on screen
        self._win.update_idletasks()
        w, h = 480, 200
        x = (self._win.winfo_screenwidth() - w) // 2
        y = (self._win.winfo_screenheight() - h) // 2
        self._win.geometry(f"{w}x{h}+{x}+{y}")

        # Title / Description
        header_lbl = tk.Label(
            self._win,
            text="Tiện ích ghép video chất lượng cao (FFmpeg Portable)",
            font=("Segoe UI", 10, "bold"),
            bg=bg,
            fg=fg,
            anchor="w",
        )
        header_lbl.pack(fill=tk.X, pady=(0, 4))

        desc_lbl = tk.Label(
            self._win,
            text="Tự động tải bản portable rút gọn (~25-35 MB) để ghép video 1080p+ và trích xuất MP3.",
            font=("Segoe UI", 8),
            bg=bg,
            fg=sub_fg,
            anchor="w",
            wraplength=440,
        )
        desc_lbl.pack(fill=tk.X, pady=(0, 10))

        # Status Label
        self._status_var = tk.StringVar(value="Đang kết nối máy chủ...")
        self._status_lbl = tk.Label(
            self._win,
            textvariable=self._status_var,
            font=("Segoe UI", 9),
            bg=bg,
            fg=fg,
            anchor="w",
        )
        self._status_lbl.pack(fill=tk.X, pady=(0, 4))

        # Progress bar
        self._progress_bar = ttk.Progressbar(
            self._win,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
        )
        self._progress_bar.pack(fill=tk.X, pady=(0, 4))

        # Detail stats (MB / %)
        self._detail_var = tk.StringVar(value="0 MB")
        self._detail_lbl = tk.Label(
            self._win,
            textvariable=self._detail_var,
            font=("Segoe UI", 8),
            bg=bg,
            fg=sub_fg,
            anchor="e",
        )
        self._detail_lbl.pack(fill=tk.X, pady=(0, 10))

        # Cancel / Close button
        btn_frame = tk.Frame(self._win, bg=bg)
        btn_frame.pack(fill=tk.X)

        self._btn_cancel = ttk.Button(
            btn_frame,
            text="Hủy",
            command=self._on_cancel,
        )
        self._btn_cancel.pack(side=tk.RIGHT)

        # Start download thread
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _safe_after(self, fn: Callable) -> None:
        """Safely post a callback to the Tk main loop; silently ignore if loop is inactive."""
        try:
            if self._win and self._win.winfo_exists():
                self._win.after(0, fn)
        except Exception:
            pass

    def _worker(self) -> None:
        def on_progress(downloaded: int, total: int) -> None:
            if total > 0:
                pct = min(100.0, (downloaded / total) * 100)
                dl_mb = downloaded / (1024 * 1024)
                tot_mb = total / (1024 * 1024)
                text = f"{dl_mb:.1f} MB / {tot_mb:.1f} MB ({pct:.0f}%)"
                self._safe_after(lambda p=pct, t=text: self._update_progress(p, t))
            else:
                dl_mb = downloaded / (1024 * 1024)
                text = f"{dl_mb:.1f} MB"
                self._safe_after(lambda t=text: self._update_indeterminate(t))

        def on_phase(msg: str) -> None:
            self._safe_after(lambda m=msg: self._status_var.set(m))

        try:
            target_path = download_and_extract_ffmpeg(
                progress_cb=on_progress,
                phase_cb=on_phase,
                cancel_event=self._cancel_event,
            )
            self._installed_path = target_path
            self._result = "installed"
            if self.on_success:
                try:
                    self.on_success(target_path)
                except Exception as cb_err:
                    logger.warning("Lỗi gọi on_success callback: %s", cb_err)
            self._safe_after(self._on_complete)
        except Exception as exc:
            if self._cancel_event.is_set():
                self._result = "cancelled"
            else:
                self._result = "failed"
                logger.error("Lỗi cài đặt FFmpeg: %s", exc)
                self._safe_after(lambda e=str(exc): self._on_error(e))

    def _update_progress(self, pct: float, text: str) -> None:
        try:
            if self._progress_bar["mode"] != "determinate":
                self._progress_bar.stop()
                self._progress_bar.config(mode="determinate")
            self._progress_bar["value"] = pct
            self._detail_var.set(text)
        except Exception:
            pass

    def _update_indeterminate(self, text: str) -> None:
        try:
            if self._progress_bar["mode"] != "indeterminate":
                self._progress_bar.config(mode="indeterminate")
                self._progress_bar.start(10)
            self._detail_var.set(text)
        except Exception:
            pass

    def _on_complete(self) -> None:
        try:
            self._status_var.set("✅ Cài đặt FFmpeg thành công!")
            self._detail_var.set("Tiện ích đã sẵn sàng sử dụng.")
            self._progress_bar["value"] = 100
            self._btn_cancel.config(text="Đóng", command=self._win.destroy)
            self._win.after(1200, self._win.destroy)
        except Exception:
            pass

    def _on_error(self, err_msg: str) -> None:
        try:
            self._status_var.set("❌ Không thể tải FFmpeg.")
            self._detail_var.set(err_msg[:60])
            self._btn_cancel.config(text="Đóng", command=self._win.destroy)
            messagebox.showerror(
                "Lỗi cài đặt FFmpeg",
                f"Không thể tự động tải FFmpeg:\n{err_msg}\n\nỨng dụng vẫn có thể tiếp tục tải video ở chế độ thường (Progressive MP4).",
                parent=self._win,
            )
        except Exception:
            pass

    def _on_cancel(self) -> None:
        self._cancel_event.set()
        self._result = "cancelled"
        try:
            self._win.destroy()
        except Exception:
            pass


def prompt_and_install_ffmpeg_if_missing(
    parent: tk.Tk,
    theme_mgr: Optional[ThemeManager] = None,
    on_complete: Optional[Callable[[bool], None]] = None,
) -> None:
    """
    Check if FFmpeg is installed; if not, ask user with a friendly prompt.
    If user agrees, open FFmpegDownloadDialog.
    """
    from main.ffmpeg_utils import is_ffmpeg_available

    if is_ffmpeg_available():
        if on_complete:
            on_complete(True)
        return

    confirmed = messagebox.askyesno(
        "Tiện ích FFmpeg (Khuyến nghị)",
        "Ứng dụng cần tiện ích mở rộng FFmpeg để:\n"
        "• Ghép video độ phân giải cao nhất (1080p, 2K, 4K)\n"
        "• Trích xuất âm thanh định dạng chuẩn MP3\n\n"
        "Bạn có muốn tải và cài đặt tự động ngay bây giờ không?\n"
        "(Gói portable ~25-35MB, tải 1 lần dùng mãi mãi)",
        parent=parent,
    )
    if not confirmed:
        if on_complete:
            on_complete(False)
        return

    def on_installed(_path):
        if on_complete:
            on_complete(True)

    FFmpegDownloadDialog(parent, theme_mgr=theme_mgr, on_success=on_installed)


class FFmpegSetupDialog:
    """
    Management and status dialog for portable FFmpeg.
    - If installed: displays installation path, active status, feature summary,
      and provides buttons to open directory or reinstall/update.
    - If not installed: prompts user with benefits and 1-click install button.
    """

    def __init__(
        self,
        parent: tk.Tk,
        theme_mgr: Optional[ThemeManager] = None,
        is_dark: Optional[bool] = None,
        on_change: Optional[Callable[[], None]] = None,
    ):
        self._parent = parent
        self.theme = theme_mgr
        self.on_change = on_change

        if is_dark is not None:
            self._is_dark = is_dark
        elif self.theme:
            self._is_dark = (getattr(self.theme, "current_theme", "dark") == "dark")
        else:
            self._is_dark = True

        self._win = tk.Toplevel(parent)
        self._win.title("🎬 Tiện ích FFmpeg Portable")
        self._win.resizable(False, False)
        self._win.transient(parent)
        self._win.grab_set()

        try:
            set_windows_dark_titlebar(self._win, dark=self._is_dark)
        except Exception:
            pass

        self._render()

        # Center dialog
        self._win.update_idletasks()
        w, h = 520, 360
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        x = max(10, px + max(0, (pw - w) // 2))
        y = max(10, py + max(0, (ph - h) // 2))
        self._win.geometry(f"{w}x{h}+{x}+{y}")

    def _render(self) -> None:
        for child in self._win.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        from main.ffmpeg_utils import is_ffmpeg_available, get_ffmpeg_path
        installed = is_ffmpeg_available()
        ff_path = get_ffmpeg_path()

        bg = "#1e1e2e" if self._is_dark else "#f8f9fa"
        surface = "#252538" if self._is_dark else "#ffffff"
        fg = "#cdd6f4" if self._is_dark else "#1a1a1a"
        sub_fg = "#a6adc8" if self._is_dark else "#666666"
        accent = "#89b4fa" if self._is_dark else "#1a73e8"
        success_fg = "#a6e3a1" if self._is_dark else "#188038"

        self._win.configure(bg=bg, padx=20, pady=16)

        # 1. Header Frame
        hdr_frame = tk.Frame(self._win, bg=bg)
        hdr_frame.pack(fill=tk.X, pady=(0, 12))

        title_text = "✅ FFmpeg Portable Đã Sẵn Sàng" if installed else "⚠️ Tiện Ích FFmpeg Portable Chưa Cài Đặt"
        title_color = success_fg if installed else ("#f9e2af" if self._is_dark else "#e37400")

        lbl_title = tk.Label(
            hdr_frame,
            text=title_text,
            font=("Segoe UI", 12, "bold"),
            bg=bg,
            fg=title_color,
            anchor="w",
        )
        lbl_title.pack(fill=tk.X)

        sub_text = (
            "Tiện ích FFmpeg đang hoạt động bình thường, hỗ trợ tải video 1080p+ và trích xuất MP3."
            if installed
            else "Cần thiết để ghép video chất lượng cao (1080p, 2K, 4K) và trích xuất âm thanh MP3."
        )
        lbl_sub = tk.Label(
            hdr_frame,
            text=sub_text,
            font=("Segoe UI", 9),
            bg=bg,
            fg=sub_fg,
            anchor="w",
            wraplength=480,
            justify=tk.LEFT,
        )
        lbl_sub.pack(fill=tk.X, pady=(4, 0))

        # 2. Main Card Info
        card = tk.Frame(self._win, bg=surface, bd=1, relief=tk.SOLID, padx=14, pady=12)
        card.pack(fill=tk.BOTH, expand=True, pady=(0, 14))

        if installed:
            tk.Label(card, text="Vị trí tệp thực thi (Binary):", font=("Segoe UI", 9, "bold"), bg=surface, fg=fg, anchor="w").pack(fill=tk.X)
            path_entry = tk.Entry(card, font=("Consolas", 8), bg=bg, fg=fg, relief=tk.FLAT, bd=1)
            path_entry.insert(0, str(ff_path or "Chưa xác định"))
            path_entry.configure(state="readonly")
            path_entry.pack(fill=tk.X, pady=(4, 10))

            tk.Label(card, text="Tính năng đang được kích hoạt:", font=("Segoe UI", 9, "bold"), bg=surface, fg=fg, anchor="w").pack(fill=tk.X)
            features = [
                "✔ Ghép tự động hình ảnh và âm thanh cho video 1080p, 2K, 4K",
                "✔ Tải & chuyển đổi âm thanh trực tiếp sang định dạng chuẩn MP3",
                "✔ Hỗ trợ tải luồng phân đoạn m3u8 / DASH không suy giảm chất lượng",
            ]
            for feat in features:
                tk.Label(card, text=feat, font=("Segoe UI", 8), bg=surface, fg=sub_fg, anchor="w").pack(fill=tk.X, pady=1)
        else:
            tk.Label(card, text="Thông tin gói cài đặt:", font=("Segoe UI", 9, "bold"), bg=surface, fg=fg, anchor="w").pack(fill=tk.X)
            info_lines = [
                "• Bản Portable rút gọn (~25-35 MB), tối ưu hóa tốc độ tải.",
                "• Tải tự động và lưu trữ cục bộ, không yêu cầu quyền Administrator.",
                "• Tải 1 lần dùng mãi mãi, không can thiệp vào cài đặt Windows.",
                "• Nếu không cài đặt, video vẫn tải được ở chất lượng thường (Progressive MP4).",
            ]
            for line in info_lines:
                tk.Label(card, text=line, font=("Segoe UI", 8), bg=surface, fg=sub_fg, anchor="w").pack(fill=tk.X, pady=2)

        # 3. Action Buttons Frame
        btn_bar = tk.Frame(self._win, bg=bg)
        btn_bar.pack(fill=tk.X)

        if installed:
            def _open_folder():
                import os
                import subprocess
                if ff_path and os.path.exists(ff_path):
                    folder = os.path.dirname(ff_path)
                    try:
                        if hasattr(os, "startfile"):
                            os.startfile(folder)
                        else:
                            subprocess.Popen(["explorer", folder])
                    except Exception as err:
                        messagebox.showwarning("Thông báo", f"Không thể mở thư mục: {err}", parent=self._win)

            btn_open = tk.Button(
                btn_bar,
                text="📁 Mở thư mục",
                font=("Segoe UI", 9),
                bg=surface,
                fg=fg,
                activebackground=surface,
                activeforeground=accent,
                relief=tk.GROOVE,
                padx=10,
                pady=4,
                cursor="hand2",
                command=_open_folder,
            )
            btn_open.pack(side=tk.LEFT)

            btn_reinstall = tk.Button(
                btn_bar,
                text="🔄 Tải lại / Cập nhật",
                font=("Segoe UI", 9),
                bg=surface,
                fg=fg,
                activebackground=surface,
                activeforeground=accent,
                relief=tk.GROOVE,
                padx=10,
                pady=4,
                cursor="hand2",
                command=self._start_download,
            )
            btn_reinstall.pack(side=tk.LEFT, padx=(8, 0))
        else:
            btn_install = tk.Button(
                btn_bar,
                text="📥 Tải & Cài đặt tự động",
                font=("Segoe UI", 9, "bold"),
                bg=accent,
                fg="#ffffff",
                activebackground=accent,
                activeforeground="#ffffff",
                relief=tk.FLAT,
                padx=12,
                pady=4,
                cursor="hand2",
                command=self._start_download,
            )
            btn_install.pack(side=tk.LEFT)

        btn_close = tk.Button(
            btn_bar,
            text="Đóng",
            font=("Segoe UI", 9),
            bg=surface,
            fg=fg,
            activebackground=surface,
            activeforeground=fg,
            relief=tk.GROOVE,
            padx=14,
            pady=4,
            cursor="hand2",
            command=self._win.destroy,
        )
        btn_close.pack(side=tk.RIGHT)

    def _start_download(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            pass

        def on_done(_path):
            if self.on_change:
                try:
                    self.on_change()
                except Exception:
                    pass
            try:
                FFmpegSetupDialog(self._parent, theme_mgr=self.theme, is_dark=self._is_dark, on_change=self.on_change)
            except Exception:
                pass

        FFmpegDownloadDialog(parent=self._parent, theme_mgr=self.theme, on_success=on_done)
