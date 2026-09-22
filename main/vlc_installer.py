"""
VLC Installer module.
Handles detection, download, and silent installation of VLC Media Player.

Responsibilities (§5.2.D separation of concerns):
- Detect whether libvlc is available (platform-agnostic check).
- Download the VLC installer to a temp directory with byte-level progress reporting
  via a callback, so any UI layer can display it without being coupled here.
- Run the installer silently (NSIS /S flag on Windows).
- Re-verify installation success after completion.

All URLs, version strings, and file names are centralized as constants at
the top of this module — zero hardcoding in logic functions.
"""

import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("FBVideoWatcher.VLCInstaller")

# ---------------------------------------------------------------------------
# Constants — update here only when bumping VLC version
# ---------------------------------------------------------------------------

VLC_VERSION = "3.0.23"
VLC_WIN64_FILENAME = f"vlc-{VLC_VERSION}-win64.exe"
VLC_WIN64_DOWNLOAD_URL = (
    f"https://get.videolan.org/vlc/{VLC_VERSION}/win64/{VLC_WIN64_FILENAME}"
)
# NSIS silent-install flag (works for all VLC installers)
VLC_SILENT_FLAG = "/S"

# Type alias for the progress callback: (bytes_downloaded, total_bytes) -> None
ProgressCallback = Callable[[int, int], None]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_vlc_available() -> bool:
    """
    Return True if libvlc can be successfully loaded and instantiated.
    This is the only reliable cross-platform check (registry keys can be stale).
    """
    try:
        import vlc  # type: ignore

        inst = vlc.Instance("--quiet")
        if inst:
            inst.release()
            return True
        return False
    except Exception:
        return False


def get_download_url() -> str:
    """Return the direct download URL for the recommended VLC installer."""
    if sys.platform == "win32":
        return VLC_WIN64_DOWNLOAD_URL
    # Future: add macOS / Linux URLs here
    return VLC_WIN64_DOWNLOAD_URL


def get_installer_filename() -> str:
    """Return the bare filename for the VLC installer on this platform."""
    if sys.platform == "win32":
        return VLC_WIN64_FILENAME
    return VLC_WIN64_FILENAME


def download_vlc(
    dest_path: Path,
    progress_cb: Optional[ProgressCallback] = None,
    chunk_size: int = 65536,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """
    Download the VLC installer to dest_path.

    Args:
        dest_path: Full path where the downloaded file will be saved.
        progress_cb: Called repeatedly with (bytes_downloaded, total_bytes).
                     total_bytes may be -1 if Content-Length is unavailable.
        chunk_size: Download chunk size in bytes (default 64 KB).
        cancel_event: Optional threading.Event; if set, download is aborted
                      and a RuntimeError is raised.

    Returns:
        dest_path on success.

    Raises:
        RuntimeError: On network error, HTTP error, or cancellation.
    """
    try:
        import urllib.request
    except ImportError as exc:
        raise RuntimeError("urllib.request unavailable.") from exc

    url = get_download_url()
    logger.info(f"Bắt đầu tải VLC từ: {url}")

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            total = int(response.headers.get("Content-Length", -1))
            downloaded = 0
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                while True:
                    if cancel_event and cancel_event.is_set():
                        logger.info("Tải VLC bị hủy bởi người dùng.")
                        raise RuntimeError("cancelled")

                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except Exception:
                            pass  # Never let a UI callback crash the download

        logger.info(f"Tải VLC hoàn tất: {dest_path} ({downloaded:,} bytes)")
        return dest_path

    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Không thể tải VLC: {exc}") from exc


def install_vlc_silent(installer_path: Path) -> None:
    """
    Run the VLC installer silently (NSIS /S flag).
    Blocks until the installer process exits.

    Args:
        installer_path: Path to the downloaded .exe installer.

    Raises:
        RuntimeError: If the installer process returns a non-zero exit code
                      or cannot be launched.
    """
    if sys.platform != "win32":
        raise RuntimeError("Silent install is only supported on Windows.")

    if not installer_path.is_file():
        raise RuntimeError(f"Không tìm thấy file installer: {installer_path}")

    logger.info(f"Bắt đầu cài đặt VLC (silent): {installer_path}")
    try:
        result = subprocess.run(
            [str(installer_path), VLC_SILENT_FLAG],
            check=False,
            timeout=300,  # 5-minute timeout for installation
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"VLC installer thoát với mã lỗi: {result.returncode}"
            )
        logger.info("Cài đặt VLC hoàn tất thành công.")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Cài đặt VLC vượt quá thời gian chờ (5 phút).") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"Không thể chạy installer: {exc}") from exc


def make_temp_installer_path() -> Path:
    """Return a safe temporary file path for the VLC installer."""
    tmp_dir = Path(tempfile.gettempdir()) / "fbvw_vlc_setup"
    return tmp_dir / get_installer_filename()


def cleanup_installer(installer_path: Path) -> None:
    """Remove the downloaded installer file (best-effort, no exception raised)."""
    try:
        if installer_path.is_file():
            os.remove(installer_path)
            logger.info(f"Đã xóa file installer tạm: {installer_path}")
    except Exception as exc:
        logger.warning(f"Không thể xóa file installer tạm: {exc}")
