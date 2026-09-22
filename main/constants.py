"""
Constants and default configuration for FB Video Watcher.
Centralized configuration: no magic numbers or hardcoded hardware specs.
"""

import os
from pathlib import Path
import re
import sys

from main.hotkeys import DEFAULT_HOTKEYS
from main import __version__

# --- Application Info ---
APP_NAME = "FB Video Watcher"
APP_VERSION = __version__


def get_config_dir() -> Path:
    """
    Dynamically resolve the application configuration directory.
    Default: User home directory (~/.fb-video-watcher -> C:\\Users\\{User}\\.fb-video-watcher).

    Overrides:
    1. Environment variable 'FBW_CONFIG_DIR' (for testing or custom deployments).
    2. Explicit portable mode: ONLY if a 'portable.txt' marker file exists next to the executable / application.
    """
    # 1. Environment variable override
    env_dir = os.environ.get("FBW_CONFIG_DIR", "").strip()
    if env_dir:
        p = Path(env_dir)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            pass

    # 2. Explicit opt-in portable mode ONLY if portable.txt exists next to executable / application
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parent.parent

    portable_marker = app_dir / "portable.txt"
    if portable_marker.is_file():
        portable_data_dir = app_dir / "data"
        try:
            portable_data_dir.mkdir(parents=True, exist_ok=True)
            return portable_data_dir
        except OSError:
            pass

    # 3. Default: User home directory (~/.fb-video-watcher)
    default_dir = Path.home() / ".fb-video-watcher"
    try:
        default_dir.mkdir(parents=True, exist_ok=True)
        # Migrate legacy files from app_dir/data if user previously had them there and home dir is fresh
        legacy_data_dir = app_dir / "data"
        if legacy_data_dir.is_dir() and not (default_dir / "settings.json").is_file():
            import shutil
            for item in ("settings.json", "history.db", "cookies.txt", "telegram.session"):
                src = legacy_data_dir / item
                dst = default_dir / item
                if src.is_file() and not dst.is_file():
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass
        return default_dir
    except OSError:
        pass

    # Fallback to AppData if user home is not writable
    appdata = os.environ.get("APPDATA")
    if appdata and Path(appdata).is_dir():
        fallback = Path(appdata) / "FBVideoWatcher"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except OSError:
            pass

    return default_dir


# --- File Paths ---
CONFIG_DIR = get_config_dir()
SETTINGS_FILE = CONFIG_DIR / "settings.json"
HISTORY_DB = CONFIG_DIR / "history.db"
COOKIE_FILE = CONFIG_DIR / "cookies.txt"
TELEGRAM_SESSION_FILE = CONFIG_DIR / "telegram.session"

# Support both Python script execution and PyInstaller bundled executable
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _ASSET_BASE = Path(sys._MEIPASS) / "main" / "image"
else:
    _ASSET_BASE = Path(__file__).resolve().parent / "image"

ICON_ICO_FILE = _ASSET_BASE / "app_icon.ico"
ICON_FILE = ICON_ICO_FILE if ICON_ICO_FILE.is_file() else (_ASSET_BASE / "icon-192.png")

# --- Window Dimensions ---
DEFAULT_WINDOW_WIDTH = 960
DEFAULT_WINDOW_HEIGHT = 640
MIN_WINDOW_WIDTH = 640
MIN_WINDOW_HEIGHT = 480
DEFAULT_PIP_WIDTH = 480
DEFAULT_PIP_HEIGHT = 270
MIN_PIP_WIDTH = 240
MIN_PIP_HEIGHT = 135

# Vertical PiP Dimensions (9:16 for Reels, TikTok, Shorts)
DEFAULT_PIP_VERTICAL_WIDTH = 270
DEFAULT_PIP_VERTICAL_HEIGHT = 480
MIN_PIP_VERTICAL_WIDTH = 180
MIN_PIP_VERTICAL_HEIGHT = 320

# Snapping margin to screen edges/corners in PiP mode (px)
PIP_SNAP_MARGIN = 24

# --- VLC Dynamic Defaults (fallback when auto-tune is unavailable) ---
# NOTE: Hardware specific parameters must be resolved by AutoTuner, never hardcoded.
VLC_ARGS_DEFAULTS = {
    "network_caching": 3000,     # ms (adjusted by AutoTuner according to available RAM)
    "file_caching": 2000,        # ms
    "live_caching": 3000,        # ms
    "hw_accel": "auto",          # 'auto' | 'd3d11va' | 'dxva2' | 'none'
    "decode_threads": 0,         # 0 = auto (based on CPU logical cores)
}

# --- Playback Settings ---
DEFAULT_VOLUME = 80              # 0-150 (VLC supports amplification >100)
SEEK_SHORT = 5                   # seconds (Arrow keys Left / Right)
SEEK_LONG = 30                   # seconds (Shift + Left / Right)
SPEED_OPTIONS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
MAX_VIDEO_HEIGHT = 1080          # Default max resolution height
UI_UPDATE_INTERVAL_MS = 250      # Seek bar / time label refresh interval (4 FPS UI)
UI_IDLE_INTERVAL_MS = 1000       # Lower-frequency UI polling while stopped/paused
CLIPBOARD_POLL_INTERVAL_MS = 2500
HEALTH_DEGRADED_AFTER_MS = 5000
HEALTH_CRITICAL_AFTER_MS = 15000

# Resource guards.  Queue and collection entries contain only small metadata;
# direct streams are resolved for the active item and are never stored here.
MAX_QUEUE_ITEMS = 500
MAX_COLLECTION_ENTRIES = 200
COLLECTION_PAGE_SIZE = 100

# --- URL Matching Pattern ---
# Supports all web video URLs (Facebook, Bilibili, YouTube, TikTok, Douyin, X/Twitter, etc.)
URL_PATTERN = re.compile(
    r"^https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$",
    re.IGNORECASE
)
FB_URL_PATTERN = URL_PATTERN  # Alias for backward compatibility

# --- Resolver Settings ---
RESOLVE_TIMEOUT = 15             # seconds
RESOLVE_RETRIES = 3
FAKE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# --- Default Application Settings (settings.json schema) ---
DEFAULT_SETTINGS = {
    "video": {
        "max_height": 1080,          # 360 | 480 | 720 | 1080 | 0 (0 = best)
        "default_speed": 1.0,        # 0.25 -> 2.0
    },
    "audio": {
        "default_volume": 80,        # 0-150
        "is_muted": False,           # Persistent mute state
    },
    "streaming": {
        "network_caching": 3000,     # ms
        "hardware_decode": True,     # True / False
        "decode_threads": 0,         # 0 = Auto
    },
    "source_profiles": {
        "global": {
            "mode": "auto",
            "max_height": 1080,
            "network_caching_ms": 3000,
            "hardware_decode": True,
        },
    },
    "ui": {
        "theme": "system",           # "system" | "dark" | "light"
        "seek_short": 5,             # seconds
        "seek_long": 30,             # seconds
        "always_on_top": False,
        "clipboard_auto_detect": True,
        "pip_aspect_ratio": "16:9",  # "16:9" | "9:16"
        "pip_width_horizontal": 480,
        "pip_height_horizontal": 270,
        "pip_width_vertical": 270,
        "pip_height_vertical": 480,
    },
    "advanced": {
        "cookie_file": "",           # path to cookies.txt
    },
    "playback": {
        "last_url": "",              # Remembered URL from last session
        "resume_playback": True,     # Auto-resume from last saved position
        "loop_enabled": False,       # Repeat video playback
        "queue_loop_enabled": False, # Repeat the queue after a natural end
        "queue_persist": False,      # Queue persistence is opt-in
        "skip_failed_items": False,  # Do not skip errors silently by default
    },
    "download": {
        "download_dir": "",          # Default to Downloads folder
        "always_ask": False,         # Ask where to save before downloading
        "format": "video",           # "video" | "audio" | "ask"
        "show_toast": True,          # Show Windows Toast notification when finished
    },
    "subtitle": {
        "file": "",                  # Path to loaded subtitle file
        "font_family": "Segoe UI",   # Font family
        "font_size": 36,             # Default font size
        "text_color": "#ffffff",     # Primary text color
        "bold": True,                # Bold styling
        "italic": False,             # Italic styling
        "underline": False,          # Underline styling
        "outline_color": "#000000",  # Outline / Border color
        "outline_thickness": 2,      # 0 (none), 1 (thin), 2 (medium), 3 (thick)
        "bg_color": "#000000",       # Background box color
        "bg_enabled": False,         # Enable background box
        "bg_opacity": 128,           # 0-255 (128 = 50% opacity)
    },
    "performance": {
        "cpu_affinity_mode": "auto",       # "auto" | "p_cores" | "all"
        "disable_eco_qos": True,           # Disable Windows Power Throttling / Efficiency mode
        "high_precision_timer": True,      # Enable 1ms multimedia timer (timeBeginPeriod)
    },
    "telegram": {
        "api_id": "",                      # Telegram API ID from my.telegram.org (shared across all accounts)
        "api_hash": "",                    # Telegram API Hash from my.telegram.org (shared across all accounts)
        "accounts": [],                    # List of {"session_file": str, "label": str, "active": bool}
    },
    "hotkeys": DEFAULT_HOTKEYS,
}
