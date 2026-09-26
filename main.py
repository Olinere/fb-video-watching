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
from main.platform_utils import send_to_existing_instance, start_ipc_server, stop_ipc_server
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

    # If launched with items/protocol, attempt forwarding to an existing active instance first
    if launch_request.items:
        payload = {
            "action": launch_request.action,
            "items": list(launch_request.items),
            "privacy": launch_request.privacy,
        }
        if send_to_existing_instance(payload):
            logger.info("Đã chuyển yêu cầu mở video tới tiến trình đang chạy.")
            sys.exit(0)

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

    # Hide window immediately during startup so Windows Explorer does not
    # cache the default Tk feather icon on the taskbar before our icon is bound.
    root.withdraw()
    from main.constants import ICON_FILE
    from main.platform_utils import apply_window_icon
    apply_window_icon(root, ICON_FILE)

    app = Application(root, privacy_enabled=launch_request.privacy)
    root.deiconify()
    apply_window_icon(root, ICON_FILE)

    # Listen for incoming requests from other instances via Named Pipe
    def _on_ipc_payload(payload: dict) -> None:
        action = payload.get("action", "play")
        items = payload.get("items", [])
        privacy = payload.get("privacy", False)
        if privacy and not app.persistence_policy.is_enabled():
            app.persistence_policy.enabled = True
            root.after(0, lambda: app.gui.set_privacy_state(True))
        if items:
            def _dispatch() -> None:
                from main.platform_utils import bring_window_to_front
                bring_window_to_front(root)
                if action == "queue":
                    for item in items:
                        app.handle_add_to_queue(item)
                else:
                    app.handle_play_request(items[0])
                    for item in items[1:]:
                        app.handle_add_to_queue(item)
            root.after(0, _dispatch)

    start_ipc_server(_on_ipc_payload)

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

    try:
        root.mainloop()
    finally:
        stop_ipc_server()


if __name__ == "__main__":
    main()
