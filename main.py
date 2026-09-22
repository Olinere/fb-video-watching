"""
Entry point for FB Video Watcher desktop application.
Strictly adheres to specs.md §8 (Startup & Initialization Flow).
"""

import sys
import tkinter as tk
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.constants import CONFIG_DIR, APP_NAME
from main.vlc_installer import is_vlc_available
from main.vlc_setup_dialog import run_vlc_setup
from main.app import Application
from main.windows_integration import parse_launch_args
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(APP_NAME)


def main() -> None:
    """Main startup sequence."""
    launch_request = parse_launch_args(sys.argv[1:])
    # 1. Ensure configuration directory exists
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # 2. Check VLC; if missing, offer auto-install
    if not is_vlc_available():
        result = run_vlc_setup()

        if result == "installed":
            # VLC was just installed — restart the app so libvlc loads cleanly
            logger.info("VLC vừa được cài đặt. Đang khởi động lại ứng dụng...")
            import os
            os.execv(sys.executable, [sys.executable] + sys.argv)
            return  # unreachable on POSIX; on Windows execv replaces the process

        elif result == "skipped":
            logger.info("Người dùng từ chối cài VLC. Thoát ứng dụng.")
            sys.exit(0)

        else:  # "failed" or "cancelled"
            logger.warning(f"Thiết lập VLC kết thúc với trạng thái: {result}. Thoát.")
            sys.exit(1)

    # 3. Set Windows AppUserModelID early so taskbar icon binds immediately
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fbvideowatcher.desktop.app")
        except Exception:
            pass

    # 4. Launch GUI Mainloop
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception as e:
        logger.warning(f"Không thể tải TkinterDnD ({e}). Dùng tk.Tk tiêu chuẩn.")
        root = tk.Tk()
    app = Application(root, privacy_enabled=launch_request.privacy)

    # External inputs use the same application callbacks as the GUI.  The
    # contract carries source URLs only; direct stream URLs are never accepted.
    if launch_request.items:
        def _consume_launch_request() -> None:
            if launch_request.action == "queue":
                for item in launch_request.items:
                    app.handle_add_to_queue(item)
            else:
                app.handle_play_request(launch_request.items[0])
                for item in launch_request.items[1:]:
                    app.handle_add_to_queue(item)
        root.after(0, _consume_launch_request)

    root.mainloop()


if __name__ == "__main__":
    main()
