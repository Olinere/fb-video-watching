"""Utilities for detecting FFmpeg availability, progressive format fallbacks, and log filtering."""

import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def get_ffmpeg_path() -> Optional[str]:
    """Find ffmpeg binary in PATH, project root bin/, or %LOCALAPPDATA%."""
    # 1. System PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 2. Project local bin directory
    project_bin = Path(__file__).resolve().parent.parent / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if project_bin.is_file():
        return str(project_bin)

    # 3. %LOCALAPPDATA%/fb-video-watcher/bin (Windows standard app data)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        app_bin = Path(local_app_data) / "fb-video-watcher" / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if app_bin.is_file():
            return str(app_bin)

    return None


def is_ffmpeg_available() -> bool:
    """Return True if a usable ffmpeg executable is discovered."""
    return get_ffmpeg_path() is not None


class YtDlpLogFilter:
    """Intercepts yt-dlp logging to suppress harmless deprecation warnings."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        msg_str = str(msg)
        if "Python version" in msg_str and "deprecated" in msg_str:
            return
        logger.warning("yt-dlp: %s", msg_str)

    def error(self, msg: str) -> None:
        msg_str = str(msg)
        if "Python version" in msg_str and "deprecated" in msg_str:
            return
        logger.error("yt-dlp: %s", msg_str)


def build_download_opts(
    output_tmpl: str,
    max_height: Optional[int] = None,
    audio_only: bool = False,
    audio_format: str = "mp3",
    has_ffmpeg: Optional[bool] = None,
    ffmpeg_path: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Construct safe yt-dlp download options.

    If FFmpeg is missing:
    - Video downloads fallback to progressive streams (single container containing both audio and video).
    - Audio downloads skip FFmpegExtractAudio and download native stream (.m4a).
    - merge_output_format is omitted so yt-dlp doesn't abort.

    Returns:
        (ydl_opts_dict, notice_message_if_any)
    """
    if has_ffmpeg is None:
        ffmpeg_location = ffmpeg_path or get_ffmpeg_path()
        has_ffmpeg = ffmpeg_location is not None
    else:
        ffmpeg_location = ffmpeg_path if has_ffmpeg else None

    notice: Optional[str] = None
    ydl_opts: Dict[str, Any] = {
        "outtmpl": output_tmpl,
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpLogFilter(),
        "concurrent_fragment_downloads": 4,
        "buffersize": 1048576,
        "http_chunk_size": 10485760,
        "retries": 10,
        "fragment_retries": 10,
    }

    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location

    if audio_only:
        if has_ffmpeg:
            ydl_opts["format"] = "bestaudio/best"
            ext = audio_format or "mp3"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": ext,
                "preferredquality": "192",
            }]
        else:
            # Fallback to direct native audio without post-conversion
            ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio"
            ydl_opts["postprocessors"] = []
            notice = "FFmpeg chưa được cài đặt. Tải trực tiếp âm thanh gốc (.m4a)."
    else:
        if has_ffmpeg:
            if max_height and max_height > 0:
                ydl_opts["format"] = f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
            else:
                ydl_opts["format"] = "bestvideo+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"
        else:
            # Progressive streams have both audio and video in one file (no ffmpeg merge required)
            if max_height and max_height > 0:
                ydl_opts["format"] = (
                    f"best[ext=mp4][height<={max_height}]/"
                    f"best[vcodec!=none][acodec!=none][height<={max_height}]/"
                    f"best[ext=mp4]/best"
                )
            else:
                ydl_opts["format"] = (
                    "best[ext=mp4]/"
                    "best[vcodec!=none][acodec!=none]/"
                    "best"
                )
            # DO NOT set merge_output_format when ffmpeg is not available!
            notice = "FFmpeg chưa được cài đặt. Tự động chuyển sang tải Progressive MP4 có sẵn cả hình lẫn tiếng."

    return ydl_opts, notice
