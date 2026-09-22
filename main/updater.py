"""
Auto-updater module for FB Video Watcher.
Handles checking for new releases via GitHub Releases API,
background non-blocking downloading with progress callback,
and seamless in-place updating with state preservation across restarts.
"""

import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional, Callable, Tuple, Dict, Any
import urllib.request
import urllib.error

from main.constants import APP_VERSION, get_config_dir

logger = logging.getLogger("FBVideoWatcher.Updater")

GITHUB_REPO = "Olinere/fb-video-watching"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = "FB-Video-Watcher-Updater"


class UpdateInfo:
    """Encapsulates release metadata discovered from GitHub."""

    def __init__(
        self,
        version: str,
        tag_name: str,
        title: str,
        release_notes: str,
        download_url: str,
        asset_name: str,
        asset_size: int,
        published_at: str,
    ):
        self.version = version
        self.tag_name = tag_name
        self.title = title
        self.release_notes = release_notes
        self.download_url = download_url
        self.asset_name = asset_name
        self.asset_size = asset_size
        self.published_at = published_at

    def __repr__(self) -> str:
        return f"<UpdateInfo v{self.version} ({self.asset_name})>"


def parse_semver(version_str: str) -> Tuple[int, ...]:
    """
    Parse version string into a comparable tuple of integers.
    e.g. 'v1.0.1' -> (1, 0, 1), '1.2' -> (1, 2, 0).
    """
    cleaned = version_str.strip().lstrip("vV")
    # Extract leading numbers
    parts = re.findall(r"\d+", cleaned)
    nums = [int(p) for p in parts]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def check_for_updates(
    current_version: str = APP_VERSION,
    repo_api_url: str = GITHUB_API_URL,
    timeout: float = 8.0,
) -> Optional[UpdateInfo]:
    """
    Query GitHub Releases API to detect if a newer version is available.
    Returns UpdateInfo if newer release exists and contains a .zip asset, else None.
    """
    try:
        req = urllib.request.Request(
            repo_api_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))

        tag_name = str(data.get("tag_name", "")).strip()
        if not tag_name:
            return None

        remote_ver_str = tag_name.lstrip("vV")
        remote_semver = parse_semver(remote_ver_str)
        local_semver = parse_semver(current_version)

        if remote_semver <= local_semver:
            logger.info("Current version (%s) is up to date (remote: %s)", current_version, tag_name)
            return None

        # Look for suitable asset: prioritize .zip, fallback to .exe
        assets = data.get("assets", [])
        chosen_asset = None

        # 1. First priority: .zip
        for asset in assets:
            name = str(asset.get("name", "")).lower()
            if name.endswith(".zip"):
                chosen_asset = asset
                break

        # 2. Fallback: .exe
        if not chosen_asset:
            for asset in assets:
                name = str(asset.get("name", "")).lower()
                if name.endswith(".exe"):
                    chosen_asset = asset
                    break

        if not chosen_asset:
            logger.warning("Release %s found, but no .zip or .exe asset attached.", tag_name)
            return None

        download_url = chosen_asset.get("browser_download_url")
        asset_name = chosen_asset.get("name", "update.zip")
        asset_size = int(chosen_asset.get("size", 0))

        if not download_url:
            return None

        return UpdateInfo(
            version=remote_ver_str,
            tag_name=tag_name,
            title=str(data.get("name", tag_name)),
            release_notes=str(data.get("body", "Không có ghi chú phát hành.")),
            download_url=download_url,
            asset_name=asset_name,
            asset_size=asset_size,
            published_at=str(data.get("published_at", "")),
        )

    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("No releases found on GitHub repo %s.", GITHUB_REPO)
        else:
            logger.warning("GitHub API returned HTTP %d: %s", exc.code, exc.reason)
        return None
    except Exception as exc:
        logger.debug("Failed to check for updates: %s", exc)
        return None


def download_update(
    update_info: UpdateInfo,
    progress_callback: Optional[Callable[[float, int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Path]:
    """
    Download release asset into a temporary update cache directory with progress reporting.
    Returns Path to downloaded file on success, None if cancelled or failed.
    """
    temp_dir = Path(tempfile.gettempdir()) / "fbw_update" / f"v{update_info.version}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_path = temp_dir / update_info.asset_name

    logger.info("Downloading update v%s to %s...", update_info.version, target_path)

    try:
        req = urllib.request.Request(
            update_info.download_url,
            headers={"User-Agent": USER_AGENT},
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            total_size = int(resp.headers.get("Content-Length", update_info.asset_size))
            downloaded = 0
            chunk_size = 64 * 1024  # 64 KB chunks

            with open(target_path, "wb") as out_f:
                while True:
                    if cancel_event and cancel_event.is_set():
                        logger.info("Update download cancelled by user.")
                        try:
                            target_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        return None

                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break

                    out_f.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback:
                        percent = (downloaded / total_size * 100.0) if total_size > 0 else 0.0
                        progress_callback(percent, downloaded, total_size)

        logger.info("Update v%s downloaded successfully (%d bytes).", update_info.version, downloaded)
        return target_path

    except Exception as exc:
        logger.error("Error downloading update: %s", exc)
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def get_resume_state_path() -> Path:
    """Path to temporary resume state file used across updates."""
    return get_config_dir() / "resume_state.json"


def save_resume_state(state: Dict[str, Any]) -> None:
    """Save current playback snapshot before restarting."""
    try:
        p = get_resume_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Could not save resume state: %s", exc)


def load_and_clear_resume_state() -> Optional[Dict[str, Any]]:
    """
    Read saved resume state and immediately delete the file to prevent re-resuming.
    Returns state dict or None.
    """
    p = get_resume_state_path()
    if not p.is_file():
        return None

    try:
        with open(p, "r", encoding="utf-8") as f:
            state = json.load(f)
        p.unlink(missing_ok=True)
        return state
    except Exception as exc:
        logger.warning("Could not read resume state: %s", exc)
        p.unlink(missing_ok=True)
        return None


def apply_update_and_restart(downloaded_file: Path, resume_state: Optional[Dict[str, Any]] = None) -> bool:
    """
    Spawns a detached PowerShell helper to:
    1. Wait for current process to exit cleanly.
    2. Extract update files into a temporary directory.
    3. Rename running FB-Video-Watcher.exe -> .old (bypassing Windows file lock).
    4. Move new FB-Video-Watcher.exe into the original location.
    5. Start the updated application with state restored.
    6. Delete the .old file and purge the update cache.
    """
    import base64

    if resume_state:
        save_resume_state(resume_state)

    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        exe_path = Path(sys.executable).resolve()
        app_dir = exe_path.parent
    else:
        app_dir = Path(__file__).resolve().parent.parent
        exe_path = app_dir / "FB-Video-Watcher.exe"

    current_pid = os.getpid()
    temp_update_dir = downloaded_file.parent.resolve()
    temp_extracted = temp_update_dir / "extracted"
    is_zip = downloaded_file.suffix.lower() == ".zip"

    # Generate PowerShell update script
    script_path = temp_update_dir / "update_runner.ps1"

    ps1_content = f"""# PowerShell Auto-Update Runner
$ErrorActionPreference = "Continue"

$currentPid = {current_pid}
$isFrozen = "{is_frozen}"
$exePath = "{str(exe_path).replace('"', '`"')}"
$appDir = "{str(app_dir).replace('"', '`"')}"
$downloadedFile = "{str(downloaded_file).replace('"', '`"')}"
$tempDir = "{str(temp_update_dir).replace('"', '`"')}"
$tempExtracted = "{str(temp_extracted).replace('"', '`"')}"
$isZip = "{is_zip}"

# 1. Wait for current application process to completely exit
try {{
    Wait-Process -Id $currentPid -Timeout 10 -ErrorAction SilentlyContinue
}} catch {{}}

$procName = [System.IO.Path]::GetFileNameWithoutExtension("$exePath")
$waitCount = 0
while ($waitCount -lt 30) {{
    $p = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if (-not $p) {{ break }}
    Start-Sleep -Milliseconds 300
    $waitCount++
}}
$remaining = Get-Process -Name $procName -ErrorAction SilentlyContinue
if ($remaining) {{
    $remaining | Stop-Process -Force -ErrorAction SilentlyContinue
}}
Start-Sleep -Milliseconds 500

# 2. Extract or locate new executable in temp folder
if (Test-Path "$tempExtracted") {{
    Remove-Item -Path "$tempExtracted" -Recurse -Force -ErrorAction SilentlyContinue
}}
New-Item -ItemType Directory -Path "$tempExtracted" -Force | Out-Null

if ($isZip -eq "True") {{
    Expand-Archive -Path "$downloadedFile" -DestinationPath "$tempExtracted" -Force
    $newExe = Get-ChildItem -Path "$tempExtracted" -Filter "*.exe" -Recurse | Select-Object -First 1
    if (-not $newExe) {{
        exit 1
    }}
    $newExePath = $newExe.FullName
}} else {{
    $newExePath = "$downloadedFile"
}}

# 3. Rename old executable to .old, then Copy new executable into place
$oldBackupName = [System.IO.Path]::GetFileName("$exePath") + ".old"
$oldBackupPath = Join-Path $appDir $oldBackupName

if ($isFrozen -eq "True") {{
    if (Test-Path "$oldBackupPath") {{
        Remove-Item -Path "$oldBackupPath" -Force -ErrorAction SilentlyContinue
    }}

    # Rename current running .exe to .old (Bypasses Windows file lock)
    for ($i = 0; $i -lt 15; $i++) {{
        try {{
            if (Test-Path "$exePath") {{
                Rename-Item -Path "$exePath" -NewName "$oldBackupName" -Force -ErrorAction Stop
            }}
            break
        }} catch {{
            Start-Sleep -Milliseconds 300
        }}
    }}

    # Copy new executable to destination
    Copy-Item -Path "$newExePath" -Destination "$exePath" -Force
}} else {{
    Copy-Item -Path (Join-Path $tempExtracted "*") -Destination "$appDir" -Recurse -Force -ErrorAction SilentlyContinue
}}

# 4. Wait for file flush and Antivirus/OneDrive scan lock to be released
$ready = $false
for ($j = 0; $j -lt 30; $j++) {{
    try {{
        $stream = [System.IO.File]::Open("$exePath", [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        if ($stream) {{
            $stream.Close()
            $stream.Dispose()
            $ready = $true
            break
        }}
    }} catch {{
        Start-Sleep -Milliseconds 400
    }}
}}
Start-Sleep -Milliseconds 1200

# Clear any PyInstaller environment variables so new process performs a clean extraction
Remove-Item -Path "Env:\_MEIPASS2" -ErrorAction SilentlyContinue
Remove-Item -Path "Env:\_MEIPASS" -ErrorAction SilentlyContinue
$env:PYINSTALLER_RESET_ENVIRONMENT = "1"

# Launch updated application
if ($isFrozen -eq "True") {{
    Start-Process -FilePath "$exePath"
}} else {{
    Start-Process -FilePath "{str(sys.executable).replace('"', '`"')}" -ArgumentList '"{str(app_dir / "main.py").replace('"', '`"')}"'
}}

# 5. Cleanup temporary cache and .old file
Start-Sleep -Seconds 3
if (Test-Path "$oldBackupPath") {{
    Remove-Item -Path "$oldBackupPath" -Force -ErrorAction SilentlyContinue
}}
Remove-Item -Path "$tempDir" -Recurse -Force -ErrorAction SilentlyContinue
"""

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(ps1_content)

        enc_script = base64.b64encode(ps1_content.encode("utf-16le")).decode("ascii")

        # Strip PyInstaller env vars from spawned environment
        updater_env = os.environ.copy()
        updater_env.pop("_MEIPASS2", None)
        updater_env.pop("_MEIPASS", None)
        updater_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

        # Launch background PowerShell process with hidden window and independent process group
        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                enc_script,
            ],
            env=updater_env,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        logger.info("Detached updater process spawned successfully.")
        return True
    except Exception as exc:
        logger.error("Failed to launch updater process: %s", exc)
        return False


def cleanup_updater_leftovers() -> None:
    """
    Dọn dẹp file .old và file update tạm còn sót lại từ lần cập nhật trước.
    Xử lý tình huống OneDrive/Windows Defender lock khiến PowerShell không xóa được
    file .old (~100MB) hoặc thư mục fbw_update trong %TEMP%.
    Gọi một lần duy nhất trên background thread lúc khởi động.
    """
    import shutil
    try:
        # 1. Tìm và xóa file .old của executable hiện tại
        exe_path = Path(sys.executable).resolve()
        old_file = exe_path.with_name(exe_path.name + ".old")
        if old_file.is_file():
            try:
                old_file.unlink(missing_ok=True)
                logger.info("Đã dọn dẹp file cập nhật cũ: %s", old_file)
            except Exception:
                pass

        # 2. Dọn các thư mục và file update tạm trong %TEMP%
        temp_dir = Path(tempfile.gettempdir())
        for pattern in ("fbw_update_*", "fbw_update"):
            for temp_f in temp_dir.glob(pattern):
                try:
                    if temp_f.is_file():
                        temp_f.unlink(missing_ok=True)
                    elif temp_f.is_dir():
                        shutil.rmtree(temp_f, ignore_errors=True)
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("Lỗi khi dọn dẹp file update thừa: %s", exc)
