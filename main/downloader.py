"""
Video downloader module for FB Video Watcher.
Downloads videos directly to local storage (Downloads folder) using yt-dlp.
Runs safely in background threads with progress hooks and cancellation support.
"""

from pathlib import Path
import threading
import time
from typing import Callable, Optional, Dict, Any
import os
import sys

from main.constants import FAKE_USER_AGENT
from main.extractors import isolated_cookie_file, get_js_runtimes


def get_default_download_dir() -> Path:
    """Return OS-appropriate standard Downloads directory."""
    downloads = Path.home() / "Downloads"
    try:
        downloads.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return downloads


class VideoDownloader:
    """Handles asynchronous video downloading using yt-dlp."""

    def __init__(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        cookie_file: Optional[str] = None,
        max_height: int = 1080,
        audio_only: bool = False,
        audio_format: str = "mp3",
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[Path], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.url = url
        self.output_dir = output_dir or get_default_download_dir()
        self.cookie_file = cookie_file
        self.max_height = max_height
        self.audio_only = audio_only
        self.audio_format = audio_format.lower()
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error

        self._cancelled = False
        self._thread: Optional[threading.Thread] = None
        self._downloaded_file: Optional[Path] = None

    def start(self) -> None:
        """Start download task in background thread."""
        self._cancelled = False
        self._thread = threading.Thread(target=self._run_download, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Flag task for cancellation."""
        self._cancelled = True

    def _cleanup_partial_files(self) -> None:
        """Xóa các file .part / .ytdl dở dang khi bị hủy hoặc gặp lỗi tải."""
        try:
            if hasattr(self, "output_dir") and self.output_dir.is_dir():
                now = time.time()
                # Quét file .part liên quan - chỉ xóa file được chỉnh sửa trong vòng 60 giây qua
                for part_file in self.output_dir.glob("*.part"):
                    try:
                        if now - part_file.stat().st_mtime < 60:
                            part_file.unlink(missing_ok=True)
                            import logging
                            logging.getLogger(__name__).info("Đã xóa file tải dở dang: %s", part_file)
                    except Exception:
                        pass
                # Quét file .ytdl tương tự
                for ytdl_file in self.output_dir.glob("*.ytdl"):
                    try:
                        if now - ytdl_file.stat().st_mtime < 60:
                            ytdl_file.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass

    def _progress_hook(self, d: Dict[str, Any]) -> None:
        if self._cancelled:
            raise RuntimeError("Người dùng đã hủy quá trình tải.")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0

            percent = (downloaded / total * 100.0) if total > 0 else 0.0

            speed_str = f"{speed / (1024 * 1024):.1f} MB/s" if speed else "-- MB/s"
            eta_str = f"{int(eta)}s" if eta else "--s"
            size_str = f"{downloaded / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MB" if total else ""

            info = {
                "status": "downloading",
                "percent": percent,
                "speed_str": speed_str,
                "eta_str": eta_str,
                "size_str": size_str,
                "filename": d.get("filename", ""),
            }
            if self.on_progress:
                self.on_progress(info)

        elif status == "finished":
            filename = d.get("filename")
            if filename:
                self._downloaded_file = Path(filename)
            if self.on_progress:
                self.on_progress({
                    "status": "processing",
                    "percent": 100.0,
                    "speed_str": "",
                    "eta_str": "",
                    "size_str": "Đang hoàn tất xử lý...",
                    "filename": filename or "",
                })

    def _run_download(self) -> None:
        try:
            import yt_dlp
        except ImportError:
            if self.on_error:
                self.on_error("Thư viện yt-dlp chưa được cài đặt.")
            return

        if self.audio_only:
            format_query = "bestaudio/best"
            ext = self.audio_format or "mp3"
            outtmpl = str(self.output_dir / f"%(title)s [%(id)s].{ext}")
            ydl_opts: Dict[str, Any] = {
                "format": format_query,
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [self._progress_hook],
                "http_headers": {
                    "User-Agent": FAKE_USER_AGENT,
                },
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": ext,
                    "preferredquality": "192",
                }],
            }
        else:
            outtmpl = str(self.output_dir / "%(title)s [%(id)s].%(ext)s")
            if self.max_height and self.max_height > 0:
                format_query = (
                    f"bestvideo[height<={self.max_height}]+bestaudio/best[height<={self.max_height}]/best"
                )
            else:
                format_query = "bestvideo+bestaudio/best"

            ydl_opts: Dict[str, Any] = {
                "format": format_query,
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [self._progress_hook],
                "http_headers": {
                    "User-Agent": FAKE_USER_AGENT,
                },
                "merge_output_format": "mp4",
            }

        js_runtimes = get_js_runtimes()
        if js_runtimes:
            ydl_opts["js_runtimes"] = js_runtimes
        ydl_opts["remote_components"] = ["ejs:github"]

        with isolated_cookie_file(self.cookie_file) as safe_cookie:
            if safe_cookie:
                ydl_opts["cookiefile"] = safe_cookie

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=True)
                    if not self._downloaded_file:
                        fn = ydl.prepare_filename(info)
                        target = Path(fn)
                        expected_ext = f".{self.audio_format}" if self.audio_only else ".mp4"
                        merged_target = target.with_suffix(expected_ext)
                        if merged_target.exists():
                            self._downloaded_file = merged_target
                        elif target.exists():
                            self._downloaded_file = target

                if self._cancelled:
                    self._cleanup_partial_files()
                    if self.on_error:
                        self.on_error("Đã hủy tải video.")
                    return

                if self._downloaded_file and self._downloaded_file.exists():
                    if self.on_complete:
                        self.on_complete(self._downloaded_file)
                else:
                    # Search directory for recently modified file
                    fallback_ext = f"*.{self.audio_format}" if self.audio_only else "*.mp4"
                    pattern = f"*{info.get('id', '')}*" if info else fallback_ext
                    candidates = list(self.output_dir.glob(pattern))
                    if candidates:
                        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                        if self.on_complete:
                            self.on_complete(candidates[0])
                    elif self.on_error:
                        self.on_error("Không tìm thấy file đã tải.")

            except Exception as exc:
                if self._cancelled:
                    self._cleanup_partial_files()
                    if self.on_error:
                        self.on_error("Đã hủy tải video.")
                else:
                    self._cleanup_partial_files()
                    if self.on_error:
                        self.on_error(f"Lỗi tải video: {exc}")

