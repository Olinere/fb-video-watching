"""
VLC Installer module.
Handles detection, download, and silent installation of VLC Media Player.

Responsibilities (separation of concerns):
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
import re
import subprocess
import sys
import tempfile
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("FBVideoWatcher.VLCInstaller")

# ---------------------------------------------------------------------------
# Constants — update here only when bumping VLC version
# ---------------------------------------------------------------------------

VLC_VERSION = "3.0.23"
VLC_MIN_SUPPORTED_VERSION = (3, 0, 0)
VLC_WIN64_FILENAME = f"vlc-{VLC_VERSION}-win64.exe"

# Official direct binary download URLs (never use get.videolan.org which serves HTML landing pages)
VLC_DIRECT_DOWNLOAD_URL = (
    f"https://download.videolan.org/vlc/{VLC_VERSION}/win64/{VLC_WIN64_FILENAME}"
)
VLC_FALLBACK_MIRRORS = [
    f"https://mirror.freedif.org/videolan/vlc/{VLC_VERSION}/win64/{VLC_WIN64_FILENAME}",
    f"https://mirror.kku.ac.th/videolan/vlc/{VLC_VERSION}/win64/{VLC_WIN64_FILENAME}",
    f"https://download.videolan.org/vlc/{VLC_VERSION}/win64/{VLC_WIN64_FILENAME}",
]

# NSIS silent-install flag (works for all VLC installers)
VLC_SILENT_FLAG = "/S"

# Minimum valid size for VLC win64 installer (approx 45 MB; threshold 30 MB)
MIN_INSTALLER_SIZE_BYTES = 30 * 1024 * 1024

# Type alias for the progress callback: (bytes_downloaded, total_bytes) -> None
ProgressCallback = Callable[[int, int], None]


class VLCStatus(str, Enum):
    """Classification of VLC installation status on the host system."""
    MISSING = "missing"                      # No VLC installed or unqueryable
    UNSUPPORTED = "unsupported"              # Installed version is too old (< 3.0.0)
    SUPPORTED_OUTDATED = "supported_outdated"# Installed version >= 3.0.0 but < VLC_VERSION (runs normally, prompt optional)
    UP_TO_DATE = "up_to_date"                # Installed version >= VLC_VERSION (recommended latest)


# ---------------------------------------------------------------------------
# Version & Environment Helpers
# ---------------------------------------------------------------------------


def parse_version_tuple(version_str: Optional[str]) -> tuple[int, ...]:
    """Extract numeric components into a tuple for clean version comparisons."""
    if not version_str:
        return ()
    parts = re.findall(r"\d+", str(version_str))
    return tuple(int(p) for p in parts)


def setup_vlc_dll_paths() -> Optional[Path]:
    """
    Ensure the directory containing libvlc.dll and libvlccore.dll is in the DLL search path.
    Checks Windows registry and standard paths. Returns directory Path if found, None otherwise.
    """
    if sys.platform != "win32":
        return None

    candidate_dirs: list[Path] = []

    # 1. Check registry
    try:
        import winreg
        for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub_key in (r"Software\VideoLAN\VLC", r"Software\WOW6432Node\VideoLAN\VLC"):
                try:
                    with winreg.OpenKey(root_key, sub_key) as k:
                        install_dir, _ = winreg.QueryValueEx(k, "InstallDir")
                        if install_dir:
                            p = Path(install_dir)
                            if (p / "libvlc.dll").is_file() and p not in candidate_dirs:
                                candidate_dirs.append(p)
                except OSError:
                    pass
    except Exception:
        pass

    # 2. Check standard Program Files
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for base in (prog_files, prog_files_x86):
        p = Path(base) / "VideoLAN" / "VLC"
        if (p / "libvlc.dll").is_file() and p not in candidate_dirs:
            candidate_dirs.append(p)

    for cdir in candidate_dirs:
        # Add to os.add_dll_directory (Python 3.8+)
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(cdir))
            except Exception:
                pass
        # Add to PATH
        cur_path = os.environ.get("PATH", "")
        if str(cdir) not in cur_path:
            os.environ["PATH"] = str(cdir) + os.pathsep + cur_path
        # Set python-vlc environment hints
        if "PYTHON_VLC_MODULE_PATH" not in os.environ and (cdir / "plugins").is_dir():
            os.environ["PYTHON_VLC_MODULE_PATH"] = str(cdir / "plugins")
        if "PYTHON_VLC_LIB_PATH" not in os.environ:
            os.environ["PYTHON_VLC_LIB_PATH"] = str(cdir / "libvlc.dll")
        return cdir

    return None


def get_installed_vlc_version() -> Optional[str]:
    """
    Detect the installed VLC version string.
    Checks Windows registry first (safe, fast < 1ms, zero DLL lock),
    then falls back to libvlc query.
    Returns e.g. "3.0.21" or None if not found.
    """
    # 1. Registry check first (prevents loading libvlc.dll and locking it during install)
    if sys.platform == "win32":
        try:
            import winreg
            for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for sub_key in (r"Software\VideoLAN\VLC", r"Software\WOW6432Node\VideoLAN\VLC"):
                    try:
                        with winreg.OpenKey(root_key, sub_key) as k:
                            version_val, _ = winreg.QueryValueEx(k, "Version")
                            if version_val:
                                return str(version_val).split()[0]
                    except OSError:
                        pass
        except Exception:
            pass

    # 2. libvlc fallback query
    setup_vlc_dll_paths()
    try:
        import vlc  # type: ignore
        ver = vlc.libvlc_get_version()
        if ver:
            if isinstance(ver, bytes):
                ver_str = ver.decode("utf-8", errors="ignore")
            else:
                ver_str = str(ver)
            return ver_str.split()[0]
    except Exception:
        pass

    return None


def get_vlc_status() -> tuple[VLCStatus, Optional[str]]:
    """
    Analyze current VLC installation and return (status, installed_version_str).
    Statuses:
      - UP_TO_DATE: >= VLC_VERSION (e.g. >= 3.0.23)
      - SUPPORTED_OUTDATED: >= (3, 0, 0) but < VLC_VERSION (e.g. 3.0.21) -> RUNS NORMALLY!
      - UNSUPPORTED: < (3, 0, 0) (too old)
      - MISSING: not found or unqueryable
    """
    ver_str = get_installed_vlc_version()
    if not ver_str:
        return VLCStatus.MISSING, None

    ver_tuple = parse_version_tuple(ver_str)
    min_tuple = VLC_MIN_SUPPORTED_VERSION
    rec_tuple = parse_version_tuple(VLC_VERSION)

    if ver_tuple < min_tuple:
        return VLCStatus.UNSUPPORTED, ver_str
    if ver_tuple >= rec_tuple:
        return VLCStatus.UP_TO_DATE, ver_str
    return VLCStatus.SUPPORTED_OUTDATED, ver_str


def validate_pe_executable(file_path: Path) -> bool:
    """
    Validate that file_path is a genuine Windows PE executable:
    - Must exist and be a regular file
    - Size must be at least MIN_INSTALLER_SIZE_BYTES (30 MB)
    - First 2 bytes must strictly be b"MZ"
    """
    try:
        if not file_path.is_file():
            return False
        if file_path.stat().st_size < MIN_INSTALLER_SIZE_BYTES:
            return False
        with open(file_path, "rb") as f:
            magic = f.read(2)
            return magic == b"MZ"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_vlc_available() -> bool:
    """
    Return True if libvlc is available and supported (>= 3.0.0).
    Allows both UP_TO_DATE and SUPPORTED_OUTDATED versions to run smoothly.
    """
    status, _ = get_vlc_status()
    return status in (VLCStatus.UP_TO_DATE, VLCStatus.SUPPORTED_OUTDATED)


def get_download_url() -> str:
    """Return the direct download URL for the recommended VLC installer."""
    return VLC_DIRECT_DOWNLOAD_URL


def get_installer_filename() -> str:
    """Return the bare filename for the VLC installer on this platform."""
    return VLC_WIN64_FILENAME


def download_vlc(
    dest_path: Path,
    progress_cb: Optional[ProgressCallback] = None,
    chunk_size: int = 65536,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """
    Download the VLC installer to dest_path with mirror failover and PE header validation.
    """
    try:
        import urllib.request
    except ImportError as exc:
        raise RuntimeError("urllib.request unavailable.") from exc

    mirrors = VLC_FALLBACK_MIRRORS
    last_error: Optional[Exception] = None
    tmp_path = dest_path.with_suffix(".tmp")

    for url in mirrors:
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("cancelled")

        logger.info(f"Đang thử tải VLC từ: {url}")
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
            with urllib.request.urlopen(req, timeout=15) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type:
                    raise RuntimeError(f"Máy chủ trả về trang HTML thay vì tệp nhị phân ({content_type})")

                total = int(response.headers.get("Content-Length", -1))
                downloaded = 0
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                with open(tmp_path, "wb") as f:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            logger.info("Tải VLC bị hủy bởi người dùng.")
                            if tmp_path.exists():
                                tmp_path.unlink()
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
                                pass

            # Validate downloaded PE executable
            if not validate_pe_executable(tmp_path):
                file_size = tmp_path.stat().st_size if tmp_path.exists() else 0
                raise RuntimeError(
                    f"Tệp tải về không hợp lệ hoặc bị lỗi (kích thước: {file_size} bytes, thiếu PE header MZ)"
                )

            # Move verified file to final destination
            if dest_path.exists():
                dest_path.unlink()
            tmp_path.replace(dest_path)
            logger.info(f"Tải VLC hoàn tất và đã xác thực PE header: {dest_path} ({downloaded:,} bytes)")
            return dest_path

        except RuntimeError as exc:
            if str(exc) == "cancelled":
                raise
            last_error = exc
            logger.warning(f"Lỗi tải từ mirror {url}: {exc}. Thử mirror kế tiếp...")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
        except Exception as exc:
            last_error = exc
            logger.warning(f"Không thể kết nối tới mirror {url}: {exc}. Thử mirror kế tiếp...")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    raise RuntimeError(f"Tất cả các nguồn tải VLC đều thất bại. Lỗi cuối cùng: {last_error}")


def install_vlc_silent(installer_path: Path) -> None:
    """
    Run the VLC installer silently with administrator elevation (NSIS /S flag).
    Blocks until the installer process exits.
    Uses ShellExecuteExW with verb 'runas' to trigger Windows UAC elevation.
    """
    if sys.platform != "win32":
        raise RuntimeError("Silent install is only supported on Windows.")

    if not installer_path.is_file():
        raise RuntimeError(f"Không tìm thấy file installer: {installer_path}")

    # Validate PE header before executing to prevent "Unsupported 16-bit application" error
    if not validate_pe_executable(installer_path):
        raise RuntimeError(
            f"File installer {installer_path.name} bị hỏng hoặc không phải tệp PE 64-bit hợp lệ."
        )

    logger.info(f"Bắt đầu cài đặt VLC (silent, elevated): {installer_path}")

    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x00000102
    ERROR_CANCELLED = 1223

    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32

    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.hwnd = None
    sei.lpVerb = "runas"
    sei.lpFile = str(installer_path.resolve())
    sei.lpParameters = VLC_SILENT_FLAG
    sei.lpDirectory = str(installer_path.parent.resolve())
    sei.nShow = SW_HIDE

    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = kernel32.GetLastError()
        if err == ERROR_CANCELLED:
            logger.info("Người dùng đã từ chối cấp quyền Administrator trên hộp thoại UAC.")
            raise RuntimeError("cancelled_by_user")
        raise RuntimeError(f"Không thể khởi chạy installer với quyền Administrator (Mã lỗi: {err}).")

    h_process = sei.hProcess
    if not h_process:
        logger.warning("ShellExecuteExW không trả về process handle. Cài đặt được kích hoạt nền.")
        return

    try:
        # Wait up to 300,000 ms (5 minutes)
        wait_res = kernel32.WaitForSingleObject(h_process, 300000)
        if wait_res == WAIT_TIMEOUT:
            raise RuntimeError("Cài đặt VLC vượt quá thời gian chờ (5 phút).")
        elif wait_res != WAIT_OBJECT_0:
            raise RuntimeError(f"Lỗi chờ tiến trình cài đặt kết thúc (Wait code: {wait_res}).")

        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(h_process, ctypes.byref(exit_code)):
            code = exit_code.value
            # NSIS installer returncodes: 0 is success, 2 is success with reboot requested
            if code not in (0, 2):
                raise RuntimeError(f"VLC installer thoát với mã lỗi: {code}")
            logger.info(f"Cài đặt VLC hoàn tất thành công (exit code: {code}).")
        else:
            logger.warning("Không thể đọc mã thoát của tiến trình cài đặt VLC.")
    finally:
        kernel32.CloseHandle(h_process)


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

