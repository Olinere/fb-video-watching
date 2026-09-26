"""FFmpeg Portable Installer module.

Handles downloading, verifying, and extracting portable static builds of FFmpeg
for Windows into %LOCALAPPDATA%/fb-video-watcher/bin/ without requiring admin privileges.
"""

import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Callable, List, Optional
import urllib.request
import zipfile

from main.constants import FAKE_USER_AGENT
from main.ffmpeg_utils import get_ffmpeg_path, is_ffmpeg_available

logger = logging.getLogger("FBVideoWatcher.FFmpegInstaller")

FFMPEG_MIRRORS: List[str] = [
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]

ProgressCallback = Callable[[int, int], None]


def get_ffmpeg_install_dir() -> Path:
    """Return persistent target directory for portable FFmpeg binary."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data) / "fb-video-watcher" / "bin"
    else:
        base_dir = Path.home() / ".fb-video-watcher" / "bin"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def download_and_extract_ffmpeg(
    progress_cb: Optional[ProgressCallback] = None,
    phase_cb: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    custom_target_dir: Optional[Path] = None,
) -> Path:
    """
    Download FFmpeg zip from official mirrors, extract ffmpeg.exe, and return its path.

    Args:
        progress_cb: Called with (bytes_downloaded, total_bytes).
        phase_cb: Called with status description (e.g. 'downloading', 'extracting', 'done').
        cancel_event: threading.Event to abort download.
        custom_target_dir: Optional custom install directory.

    Returns:
        Path to installed ffmpeg.exe.

    Raises:
        RuntimeError on download or extraction failure.
    """
    target_dir = custom_target_dir or get_ffmpeg_install_dir()
    target_ffmpeg = target_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")

    temp_zip_fd, temp_zip_path_str = tempfile.mkstemp(suffix=".zip", prefix="ffmpeg_dl_")
    os.close(temp_zip_fd)
    temp_zip_path = Path(temp_zip_path_str)

    last_error: Optional[Exception] = None

    try:
        download_success = False
        for mirror_url in FFMPEG_MIRRORS:
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("Đã hủy tải FFmpeg.")

            if phase_cb:
                phase_cb(f"Đang tải từ máy chủ ({mirror_url.split('/')[2]})...")

            try:
                req = urllib.request.Request(mirror_url, headers={"User-Agent": FAKE_USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp, open(temp_zip_path, "wb") as f_out:
                    total_bytes = int(resp.headers.get("Content-Length", -1))
                    downloaded = 0
                    chunk_size = 65536

                    while True:
                        if cancel_event and cancel_event.is_set():
                            raise RuntimeError("Đã hủy tải FFmpeg.")

                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)

                        if progress_cb:
                            progress_cb(downloaded, total_bytes)

                download_success = True
                break
            except Exception as exc:
                logger.warning("Thất bại khi tải từ mirror %s: %s", mirror_url, exc)
                last_error = exc
                continue

        if not download_success:
            raise RuntimeError(f"Không thể tải FFmpeg từ tất cả các máy chủ: {last_error}")

        if cancel_event and cancel_event.is_set():
            raise RuntimeError("Đã hủy tải FFmpeg.")

        if phase_cb:
            phase_cb("Đang giải nén tập tin FFmpeg...")

        # Extract ffmpeg.exe (and ffprobe.exe if present) from zip archive
        with zipfile.ZipFile(temp_zip_path, "r") as zf:
            extracted_any = False
            for member in zf.infolist():
                filename = Path(member.filename).name.lower()
                if filename in ("ffmpeg.exe", "ffmpeg", "ffprobe.exe", "ffprobe"):
                    dest_file = target_dir / Path(member.filename).name
                    with zf.open(member) as source, open(dest_file, "wb") as target:
                        shutil.copyfileobj(source, target)
                    try:
                        dest_file.chmod(0o755)
                    except OSError:
                        pass
                    extracted_any = True

            if not extracted_any:
                raise RuntimeError("Tập tin tải về không chứa file thực thi ffmpeg.exe.")

        if not target_ffmpeg.is_file():
            raise RuntimeError(f"Không tìm thấy {target_ffmpeg} sau khi giải nén.")

        if phase_cb:
            phase_cb("✅ Hoàn tất cài đặt FFmpeg!")

        logger.info("Cài đặt thành công FFmpeg tại %s", target_ffmpeg)
        return target_ffmpeg

    finally:
        try:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
        except OSError:
            pass
