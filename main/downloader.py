"""
Video downloader module for FB Video Watcher.
Downloads videos directly to local storage (Downloads folder) using yt-dlp.
Runs safely in background threads with progress hooks and cancellation support.
"""

from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Callable, Optional, Dict, Any
import logging
import os
import sys
import urllib.parse

from main.constants import FAKE_USER_AGENT
from main.extractors import isolated_cookie_file, get_js_runtimes
from main.ffmpeg_utils import build_download_opts, get_ffmpeg_path

logger = logging.getLogger("FBVideoWatcher.Downloader")


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
                # Quét file .tg_temp dở dang
                for tg_temp in self.output_dir.glob("*.tg_temp*"):
                    try:
                        if now - tg_temp.stat().st_mtime < 60:
                            tg_temp.unlink(missing_ok=True)
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
        # 1. Telegram URLs: route directly to MTProto Telethon downloader
        from main.telegram_manager import TelegramManager
        parsed_tg = TelegramManager.parse_telegram_url(self.url)
        if not parsed_tg and "/telegram/stream" in self.url:
            parsed_u = urllib.parse.urlparse(self.url)
            params = urllib.parse.parse_qs(parsed_u.query)
            if "channel" in params and "msg" in params:
                parsed_tg = {
                    "peer": params["channel"][0],
                    "msg_id": int(params["msg"][0]),
                    "is_private": True,
                }
                if "acc" in params:
                    try:
                        parsed_tg["acc_idx"] = int(params["acc"][0])
                    except (ValueError, TypeError):
                        pass

        if parsed_tg:
            self._run_telegram_download(parsed_tg)
            return

        # 2. Standard video platforms: use yt-dlp
        try:
            import yt_dlp
        except ImportError:
            if self.on_error:
                self.on_error("Thư viện yt-dlp chưa được cài đặt.")
            return

        ext = (self.audio_format or "mp3") if self.audio_only else "mp4"
        outtmpl = str(self.output_dir / f"%(title)s [%(id)s].{ext}") if self.audio_only else str(self.output_dir / "%(title)s [%(id)s].%(ext)s")

        ydl_opts, ffmpeg_notice = build_download_opts(
            output_tmpl=outtmpl,
            max_height=self.max_height,
            audio_only=self.audio_only,
            audio_format=self.audio_format or "mp3",
        )
        ydl_opts["progress_hooks"] = [self._progress_hook]
        ydl_opts["http_headers"] = {
            "User-Agent": FAKE_USER_AGENT,
        }
        if ffmpeg_notice:
            logger.info("Downloader: %s", ffmpeg_notice)

        js_runtimes = get_js_runtimes()
        if js_runtimes:
            ydl_opts["js_runtimes"] = js_runtimes
        ydl_opts["remote_components"] = ["ejs:github"]

        # In-App Proxy integration
        try:
            from main.network import NetworkManager
            proxy_url = NetworkManager.get_instance().get_proxy_url()
            if proxy_url:
                ydl_opts["proxy"] = proxy_url
        except Exception:
            pass

        with isolated_cookie_file(self.cookie_file) as safe_cookie:
            if safe_cookie:
                ydl_opts["cookiefile"] = safe_cookie

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=True)
                    if not info:
                        if self.on_error:
                            self.on_error("Không thể trích xuất thông tin video (Video có thể ở chế độ riêng tư, đã bị xóa hoặc liên kết không hợp lệ).")
                        return

                    if not self._downloaded_file:
                        fn = ydl.prepare_filename(info)
                        target = Path(fn)
                        expected_ext = f".{self.audio_format}" if self.audio_only else ".mp4"
                        candidates_to_check = [
                            target,
                            target.with_suffix(expected_ext),
                            target.with_suffix(".mp4"),
                            target.with_suffix(".m4a"),
                            target.with_suffix(".webm"),
                        ]
                        for c in candidates_to_check:
                            if c.exists():
                                self._downloaded_file = c
                                break

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

    def _run_telegram_download(self, parsed_tg: Dict[str, Any]) -> None:
        """Directly download video/audio from Telegram via MTProto Telethon."""
        try:
            from main.telegram_manager import TelegramManager
            from main.extractors.base import (
                AuthRequiredError,
                VideoNotFoundError,
                URLValidationError,
                NetworkError,
            )

            tg_mgr = TelegramManager.get_instance()
            if not tg_mgr.is_configured():
                if self.on_error:
                    self.on_error(
                        "Telegram API ID và API Hash chưa được cấu hình. "
                        "Vui lòng vào Cài đặt -> Tab Telegram để cấu hình."
                    )
                return

            active_accounts = tg_mgr.get_active_accounts()
            if not active_accounts:
                if self.on_error:
                    self.on_error(
                        "Chưa có tài khoản Telegram nào được kích hoạt để tải file. "
                        "Vui lòng vào Cài đặt -> Tab Telegram để kích hoạt tài khoản."
                    )
                return

            # Check if specific account index was requested
            selected_account = None
            if "acc_idx" in parsed_tg:
                accounts = tg_mgr.get_accounts()
                idx = parsed_tg["acc_idx"]
                if 0 <= idx < len(accounts):
                    selected_account = accounts[idx]

            peer = str(parsed_tg["peer"])
            msg_id = int(parsed_tg["msg_id"])

            if self.on_progress:
                self.on_progress({
                    "status": "downloading",
                    "percent": 0.0,
                    "speed_str": "",
                    "eta_str": "",
                    "size_str": "Đang kết nối Telegram...",
                    "filename": "",
                })

            if selected_account:
                info = tg_mgr.get_media_info(peer, msg_id, account=selected_account)
            else:
                info = tg_mgr.get_media_info_multi(peer, msg_id, selected_accounts=active_accounts)

            # Determine safe output filename
            file_name = info.get("file_name")
            title = info.get("title") or file_name or f"Telegram_{peer}_{msg_id}"

            safe_name = re.sub(r'[\\/*?:"<>|]', '_', title).strip(". \t\r\n")
            if not safe_name:
                safe_name = f"Telegram_video_{msg_id}"

            orig_suffix = Path(safe_name).suffix.lower()
            if orig_suffix in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4a", ".mp3"):
                stem = Path(safe_name).stem
            else:
                stem = safe_name
                orig_suffix = ".mp4"
                if file_name and Path(file_name).suffix:
                    orig_suffix = Path(file_name).suffix.lower()
                elif info.get("mime_type") == "video/webm":
                    orig_suffix = ".webm"
                elif info.get("mime_type") == "video/x-matroska":
                    orig_suffix = ".mkv"

            if self.audio_only:
                target_filename = f"{stem}.{self.audio_format}"
                download_dest = self.output_dir / f"{stem}.tg_temp{orig_suffix}"
            else:
                target_filename = f"{stem}{orig_suffix}"
                download_dest = self.output_dir / target_filename

            final_target = self.output_dir / target_filename
            counter = 1
            while final_target.exists():
                if self.audio_only:
                    target_filename = f"{stem} ({counter}).{self.audio_format}"
                else:
                    target_filename = f"{stem} ({counter}){orig_suffix}"
                final_target = self.output_dir / target_filename
                counter += 1

            if not self.audio_only:
                download_dest = final_target

            self._downloaded_file = download_dest

            last_time = [time.time()]
            last_bytes = [0]
            last_update = [0.0]

            def _progress_cb(current: int, total: int):
                if self._cancelled:
                    raise RuntimeError("Người dùng đã hủy quá trình tải.")
                now = time.time()
                dt = now - last_update[0]
                if dt < 0.35 and current < total:
                    return

                time_diff = now - last_time[0]
                bytes_diff = current - last_bytes[0]
                speed = (bytes_diff / time_diff) if time_diff > 0 else 0
                last_time[0] = now
                last_bytes[0] = current
                last_update[0] = now

                pct = (current / total * 100.0) if total > 0 else 0.0
                eta = ((total - current) / speed) if speed > 0 else 0
                speed_str = f"{speed / (1024 * 1024):.1f} MB/s" if speed > 0 else "-- MB/s"
                eta_str = f"{int(eta)}s" if eta > 0 else "--s"
                size_str = (
                    f"{current / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MB"
                    if total > 0
                    else f"{current / (1024 * 1024):.1f} MB"
                )

                if self.on_progress:
                    self.on_progress({
                        "status": "downloading",
                        "percent": pct,
                        "speed_str": speed_str,
                        "eta_str": eta_str,
                        "size_str": size_str,
                        "filename": final_target.name,
                    })

            actual_downloaded = tg_mgr.download_media_file(
                peer_str=peer,
                msg_id=msg_id,
                destination_file=download_dest,
                account=info.get("account") or selected_account,
                progress_callback=_progress_cb,
                cancel_check=lambda: self._cancelled,
            )

            if self._cancelled:
                self._cleanup_partial_files()
                try:
                    if download_dest.exists():
                        download_dest.unlink(missing_ok=True)
                except Exception:
                    pass
                if self.on_error:
                    self.on_error("Đã hủy tải video.")
                return

            if self.audio_only:
                if self.on_progress:
                    self.on_progress({
                        "status": "processing",
                        "percent": 100.0,
                        "speed_str": "",
                        "eta_str": "",
                        "size_str": f"Đang chuyển đổi âm thanh {self.audio_format.upper()}...",
                        "filename": final_target.name,
                    })

                ffmpeg_bin = get_ffmpeg_path()
                if ffmpeg_bin:
                    cmd = [
                        ffmpeg_bin,
                        "-y",
                        "-i", str(actual_downloaded),
                        "-vn",
                        "-acodec", "libmp3lame" if self.audio_format == "mp3" else "aac",
                        "-q:a", "2",
                        str(final_target),
                    ]
                    creationflags = 0x08000000 if sys.platform == "win32" else 0
                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=creationflags,
                    )
                    try:
                        actual_downloaded.unlink(missing_ok=True)
                    except Exception:
                        pass

                    if res.returncode != 0:
                        logger.warning(
                            "Lỗi trích xuất audio bằng FFmpeg: %s",
                            res.stderr.decode("utf-8", errors="ignore"),
                        )
                        final_target = actual_downloaded
                else:
                    logger.warning("Không tìm thấy FFmpeg để chuyển đổi MP3; giữ nguyên file video.")
                    final_target = actual_downloaded

            self._downloaded_file = final_target
            if self.on_complete:
                self.on_complete(final_target)

        except Exception as exc:
            self._cleanup_partial_files()
            try:
                if self._downloaded_file and self._downloaded_file.exists():
                    self._downloaded_file.unlink(missing_ok=True)
            except Exception:
                pass
            if self._cancelled:
                if self.on_error:
                    self.on_error("Đã hủy tải video.")
            else:
                err_msg = str(exc)
                if self.on_error:
                    self.on_error(f"Lỗi tải video từ Telegram: {err_msg}")

