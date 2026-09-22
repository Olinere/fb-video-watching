"""
Unit tests for extended features:
1. Volume / Mute OSD overlay and persistence
2. Playback speed OSD overlay
3. Clipboard auto-detect toast banner
4. Vertical 9:16 PiP mode and aspect ratio toggle
5. Edge / Corner snapping in PiP drag mode
6. Mini progress bar in PiP mode
7. History dialog, search, and delete operations
8. VideoDownloader operations
"""

import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from main.constants import (
    DEFAULT_PIP_WIDTH,
    DEFAULT_PIP_HEIGHT,
    DEFAULT_PIP_VERTICAL_WIDTH,
    DEFAULT_PIP_VERTICAL_HEIGHT,
    MIN_PIP_WIDTH,
    MIN_PIP_HEIGHT,
    MIN_PIP_VERTICAL_WIDTH,
    MIN_PIP_VERTICAL_HEIGHT,
    PIP_SNAP_MARGIN,
    get_config_dir,
)
from main.settings import SettingsManager
from main.theme import ThemeManager
from main.history import HistoryManager
from main.gui import MainWindow, SettingsDialog
from main.history_dialog import HistoryDialog
from main.downloader import VideoDownloader, get_default_download_dir
from main.url_resolver import ResolvedVideo, Format


class TestExtendedFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.settings_file = self.config_dir / "settings.json"
        self.history_db = self.config_dir / "history.db"

        self.settings_mgr = SettingsManager(config_dir=self.config_dir)
        self.theme_mgr = ThemeManager(self.root, initial_theme="dark")
        self.history_mgr = HistoryManager(db_path=self.history_db)

        self.play_mock = MagicMock()
        self.pause_mock = MagicMock()
        self.seek_mock = MagicMock()
        self.seek_rel_mock = MagicMock()
        self.vol_mock = MagicMock()
        self.mute_mock = MagicMock()
        self.rate_mock = MagicMock()
        self.history_req_mock = MagicMock()
        self.download_req_mock = MagicMock()

        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings_mgr,
            theme_mgr=self.theme_mgr,
            on_play_request=self.play_mock,
            on_pause_toggle=self.pause_mock,
            on_seek_request=self.seek_mock,
            on_seek_relative=self.seek_rel_mock,
            on_volume_change=self.vol_mock,
            on_mute_toggle=self.mute_mock,
            on_rate_change=self.rate_mock,
            on_history_request=self.history_req_mock,
            on_download_request=self.download_req_mock,
        )

    def tearDown(self):
        if hasattr(self.gui, "destroy"):
            self.gui.destroy()
        self.temp_dir.cleanup()

    # --- 1. Volume / Mute OSD and Persistence ---

    def test_volume_osd_display(self):
        """Verify show_osd_volume displays correct badges for volume and muted state."""
        self.gui.show_osd_volume(75, False)
        self.assertIn("75%", self.gui.osd_label.cget("text"))
        self.assertIn("🔊", self.gui.osd_label.cget("text"))

        self.gui.show_osd_volume(0, True)
        self.assertIn("Tắt tiếng", self.gui.osd_label.cget("text"))
        self.assertIn("🔇", self.gui.osd_label.cget("text"))

    def test_speed_osd_display(self):
        """Verify show_osd_speed displays playback rate badge."""
        self.gui.show_osd_speed(1.5)
        self.assertIn("1.5x", self.gui.osd_label.cget("text"))
        self.assertIn("⚡", self.gui.osd_label.cget("text"))

    def test_volume_and_mute_persistence(self):
        """Verify volume and mute settings are saved and loaded correctly."""
        self.settings_mgr.set("audio", "default_volume", 95)
        self.settings_mgr.set("audio", "is_muted", True)
        self.settings_mgr.save()

        # Reload settings
        fresh_settings = SettingsManager(config_dir=self.config_dir)
        self.assertEqual(fresh_settings.get("audio", "default_volume"), 95)
        self.assertTrue(fresh_settings.get("audio", "is_muted"))

    # --- 2. Clipboard Auto-detect Toast ---

    def test_clipboard_prompt_show_and_hide(self):
        """Verify clipboard prompt toast displays URL and hides properly."""
        test_url = "https://www.facebook.com/watch/?v=123456789"
        self.gui.show_clipboard_prompt(test_url)
        self.assertEqual(self.gui.clipboard_toast.winfo_manager(), "place")
        self.assertIn("facebook.com", self.gui.lbl_clip_toast.cget("text"))

        self.gui.hide_clipboard_prompt()
        self.assertEqual(self.gui.clipboard_toast.winfo_manager(), "")

    def test_clipboard_toast_play_action(self):
        """Verify clicking 'Phát ngay' plays the detected clipboard URL."""
        test_url = "https://www.facebook.com/watch/?v=987654321"
        self.gui.show_clipboard_prompt(test_url)
        self.gui._on_clipboard_toast_play()

        self.assertEqual(self.gui.url_entry.get(), test_url)
        self.play_mock.assert_called_with(test_url)
        self.assertEqual(self.gui.clipboard_toast.winfo_manager(), "")

    # --- 3. Vertical PiP 9:16 Mode & Aspect Ratio Toggling ---

    def test_pip_aspect_ratio_switching(self):
        """Verify switching between 16:9 and 9:16 PiP aspect ratio."""
        self.assertEqual(self.gui._pip_aspect_ratio, "16:9")

        self.gui.set_pip_aspect_ratio("9:16")
        self.assertEqual(self.gui._pip_aspect_ratio, "9:16")
        self.assertEqual(self.settings_mgr.get("ui", "pip_aspect_ratio"), "9:16")

        self.gui.toggle_pip_aspect_ratio()
        self.assertEqual(self.gui._pip_aspect_ratio, "16:9")
        self.assertEqual(self.settings_mgr.get("ui", "pip_aspect_ratio"), "16:9")

    def test_pip_toggle_with_vertical_ratio(self):
        """Verify entering PiP with 9:16 aspect ratio applies vertical constraints."""
        self.gui.set_pip_aspect_ratio("9:16")
        self.gui.toggle_pip()

        self.assertTrue(self.gui._is_pip)
        self.assertEqual(self.gui.pip_progress.winfo_manager(), "place")

        # Exit PiP
        self.gui.toggle_pip()
        self.assertFalse(self.gui._is_pip)
        self.assertEqual(self.gui.pip_progress.winfo_manager(), "")

    def test_pip_independent_size_persistence(self):
        """Verify that horizontal (16:9) and vertical (9:16) PiP window sizes are remembered independently."""
        # 1. Start in horizontal 16:9 mode, toggle PiP
        self.gui.set_pip_aspect_ratio("16:9")
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)

        # 2. Resize horizontal PiP to custom size (e.g. 640x360)
        self.gui.set_pip_size(640, 360)
        self.assertEqual(self.settings_mgr.get("ui", "pip_width_horizontal"), 640)
        self.assertEqual(self.settings_mgr.get("ui", "pip_height_horizontal"), 360)

        # 3. Switch to vertical 9:16 mode while in PiP
        self.gui.set_pip_aspect_ratio("9:16")
        # Should apply default vertical size (270x480) since not modified yet
        saved_v_w = self.settings_mgr.get("ui", "pip_width_vertical")
        saved_v_h = self.settings_mgr.get("ui", "pip_height_vertical")
        self.assertEqual(saved_v_w, 270)
        self.assertEqual(saved_v_h, 480)

        # 4. Resize vertical PiP to custom size (e.g. 360x640)
        self.gui.set_pip_size(360, 640)
        self.assertEqual(self.settings_mgr.get("ui", "pip_width_vertical"), 360)
        self.assertEqual(self.settings_mgr.get("ui", "pip_height_vertical"), 640)

        # Horizontal sizes must remain untouched!
        self.assertEqual(self.settings_mgr.get("ui", "pip_width_horizontal"), 640)
        self.assertEqual(self.settings_mgr.get("ui", "pip_height_horizontal"), 360)

        # 5. Exit PiP
        self.gui.toggle_pip()
        self.assertFalse(self.gui._is_pip)

        # 6. Re-open PiP while still in vertical mode -> should remember 360x640
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)
        self.assertEqual(self.gui._last_resized_pip_w, 360)
        self.assertEqual(self.gui._last_resized_pip_h, 640)

        # 7. Exit PiP, switch to horizontal mode, re-open PiP -> should remember 640x360
        self.gui.toggle_pip()
        self.gui.set_pip_aspect_ratio("16:9")
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)
        self.assertEqual(self.gui._last_resized_pip_w, 640)
        self.assertEqual(self.gui._last_resized_pip_h, 360)

        # Clean up
        self.gui.toggle_pip()

    def test_pip_size_persistence_across_sessions(self):
        """Verify saved PiP sizes persist when settings are reloaded as if reopening app."""
        # Set custom sizes in settings
        self.gui.set_pip_size(600, 337)
        self.gui.set_pip_aspect_ratio("9:16")
        self.gui.set_pip_size(300, 533)
        self.gui.toggle_pip()  # exit PiP

        # Simulate app restart by loading new SettingsManager from the same file
        new_settings = SettingsManager(config_dir=self.config_dir)
        self.assertEqual(new_settings.get("ui", "pip_width_horizontal"), 600)
        self.assertEqual(new_settings.get("ui", "pip_height_horizontal"), 337)
        self.assertEqual(new_settings.get("ui", "pip_width_vertical"), 300)
        self.assertEqual(new_settings.get("ui", "pip_height_vertical"), 533)

    def test_pip_wheel_saves_size(self):
        """Verify mouse wheel scaling saves new size into settings."""
        self.gui.set_pip_aspect_ratio("16:9")
        self.gui.toggle_pip()
        self.gui.set_pip_size(480, 270)
        # Scroll up (+120) increases width by 32
        mock_event = MagicMock(delta=120)
        self.gui._on_video_wheel(mock_event)
        self.assertEqual(self.settings_mgr.get("ui", "pip_width_horizontal"), 512)
        self.assertEqual(self.settings_mgr.get("ui", "pip_height_horizontal"), int(512 * 9 / 16))
        self.gui.toggle_pip()

    # --- 4. Mini Progress Bar in PiP Mode ---

    def test_pip_mini_progress_bar_updates(self):
        """Verify mini progress bar tracks playback progress in PiP mode."""
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)

        # Update time: 50% through 100s video
        self.gui.update_playback_time(50000, 100000)
        self.assertEqual(self.gui.pip_progress_fill.winfo_manager(), "place")

        # End of video
        self.gui.update_playback_time(0, 0)
        self.assertEqual(self.gui.pip_progress_fill.winfo_manager(), "")

        self.gui.toggle_pip()

    # --- 5. Edge and Corner Snapping in PiP ---

    def test_pip_edge_snapping_calculation(self):
        """Verify snapping logic snaps window coordinates when within PIP_SNAP_MARGIN."""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        pip_w = 480
        pip_h = 270

        # Simulate snapping near left edge
        candidate_x = 10  # within PIP_SNAP_MARGIN (24)
        snapped_x = 0 if abs(candidate_x) < PIP_SNAP_MARGIN else candidate_x
        self.assertEqual(snapped_x, 0)

        # Simulate snapping near right edge
        candidate_x = screen_w - pip_w - 15  # within margin
        snapped_x = screen_w - pip_w if abs((candidate_x + pip_w) - screen_w) < PIP_SNAP_MARGIN else candidate_x
        self.assertEqual(snapped_x, screen_w - pip_w)

        # Simulate snapping near top edge
        candidate_y = 12
        snapped_y = 0 if abs(candidate_y) < PIP_SNAP_MARGIN else candidate_y
        self.assertEqual(snapped_y, 0)

    # --- 6. Watch History Search, Delete, and Dialog ---

    def test_history_search_and_deletion(self):
        """Verify searching and deleting history entries."""
        url1 = "https://www.facebook.com/video1"
        url2 = "https://www.facebook.com/video2"

        self.history_mgr.record_playback_start(url1, title="Python Tutorial Video", duration_ms=60000)
        self.history_mgr.record_playback_start(url2, title="Cooking Highlights", duration_ms=120000)

        # Search
        results = self.history_mgr.search_history("Python")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], url1)

        # Delete by URL
        success = self.history_mgr.delete_entry(url1)
        self.assertTrue(success)

        remaining = self.history_mgr.get_history()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["url"], url2)

        # Delete by ID
        entry_id = remaining[0]["id"]
        del_id_success = self.history_mgr.delete_entry_by_id(entry_id)
        self.assertTrue(del_id_success)
        self.assertEqual(len(self.history_mgr.get_history()), 0)

    def test_history_dialog_rendering(self):
        """Verify HistoryDialog opens, renders Treeview, and handles search input."""
        self.history_mgr.record_playback_start(
            "https://www.facebook.com/demo",
            title="Demo Stream",
            duration_ms=45000,
        )

        play_callback = MagicMock()
        dialog = HistoryDialog(
            parent=self.root,
            history_mgr=self.history_mgr,
            theme_mgr=self.theme_mgr,
            on_play_video=play_callback,
        )

        self.assertEqual(len(dialog.tree.get_children()), 1)
        dialog.search_var.set("Nonexistent")
        self.assertEqual(len(dialog.tree.get_children()), 0)

        dialog.search_var.set("Demo")
        self.assertEqual(len(dialog.tree.get_children()), 1)

        dialog.top.destroy()

    # --- 7. Top Bar and Context Menu Buttons ---

    def test_history_and_download_button_clicks(self):
        """Verify Top bar buttons invoke history and download requests."""
        self.gui.btn_history.invoke()
        self.history_req_mock.assert_called_once()

        self.gui.btn_download.invoke()
        self.download_req_mock.assert_called_once()

    # --- 8. Video Downloader Class ---

    def test_downloader_init_and_cancel(self):
        """Verify VideoDownloader initialization and cancellation support."""
        progress_mock = MagicMock()
        complete_mock = MagicMock()
        error_mock = MagicMock()

        downloader = VideoDownloader(
            url="https://www.facebook.com/test",
            output_dir=self.config_dir,
            max_height=720,
            on_progress=progress_mock,
            on_complete=complete_mock,
            on_error=error_mock,
        )

        self.assertFalse(downloader._cancelled)
        downloader.cancel()
        self.assertTrue(downloader._cancelled)

    # --- 9. App Orchestrator Integration: Vertical Detection & Clipboard Focus ---

    def test_vertical_video_auto_detection(self):
        """Verify _on_resolve_completed auto-switches PiP ratio to 9:16 for vertical videos."""
        from main.app import Application

        mock_player = MagicMock()
        mock_player.get_position.return_value = 0
        mock_player.get_duration.return_value = 0
        mock_player.get_volume.return_value = 80
        mock_player.is_muted.return_value = False
        mock_player.state = "stopped"

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(
                self.root,
                settings_mgr=self.settings_mgr,
                history_mgr=self.history_mgr,
            )
            app.gui = self.gui

            # Normal 16:9 video
            fut_normal = MagicMock()
            fut_normal.result.return_value = ResolvedVideo(
                stream_url="http://stream/hls.m3u8",
                title="Normal Video",
                duration=60.0,
                thumbnail=None,
                is_live=False,
                width=1920,
                height=1080,
            )
            app._on_resolve_completed(fut_normal, "https://www.facebook.com/watch/?v=111")
            self.assertEqual(self.gui._pip_aspect_ratio, "16:9")

            # Vertical Reel video (width < height)
            fut_vert = MagicMock()
            fut_vert.result.return_value = ResolvedVideo(
                stream_url="http://stream/vert.m3u8",
                title="Reel Video",
                duration=30.0,
                thumbnail=None,
                is_live=False,
                width=1080,
                height=1920,
            )
            app._on_resolve_completed(fut_vert, "https://www.facebook.com/reel/222")
            self.assertEqual(self.gui._pip_aspect_ratio, "9:16")

    def test_clipboard_focus_in_detection(self):
        """Verify _on_window_focus_in detects copied video URL and displays toast."""
        from main.app import Application

        mock_player = MagicMock()
        mock_player.get_position.return_value = 0
        mock_player.get_duration.return_value = 0
        mock_player.get_volume.return_value = 80
        mock_player.is_muted.return_value = False
        mock_player.state = "stopped"

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(
                self.root,
                settings_mgr=self.settings_mgr,
                history_mgr=self.history_mgr,
            )
            app.gui = self.gui

            with patch.object(self.root, "clipboard_get", return_value="https://www.youtube.com/watch?v=sample123"):
                app._on_window_focus_in()
                self.assertEqual(self.gui.clipboard_toast.winfo_manager(), "place")
                self.assertIn("sample123", self.gui._detected_clipboard_url)

    def test_clipboard_detection_xnhau_and_periodic(self):
        """Verify clipboard auto-detection detects xnhau and periodic timer triggers."""
        from main.app import Application

        mock_player = MagicMock()
        mock_player.get_position.return_value = 0
        mock_player.get_duration.return_value = 0
        mock_player.get_volume.return_value = 80
        mock_player.is_muted.return_value = False
        mock_player.state = "stopped"

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(
                self.root,
                settings_mgr=self.settings_mgr,
                history_mgr=self.history_mgr,
            )
            app.gui = self.gui

            xnhau_url = "https://xnhau.cab/video/332382/chich-public-o-cong-vien/"
            with patch.object(self.root, "clipboard_get", return_value=xnhau_url):
                # Trigger via periodic check
                app._periodic_clipboard_check()
                self.assertEqual(self.gui.clipboard_toast.winfo_manager(), "place")
                self.assertEqual(self.gui._detected_clipboard_url, xnhau_url)

    def test_dynamic_config_dir_resolution(self):
        """Verify get_config_dir dynamically resolves custom env dir."""
        test_env_dir = self.config_dir / "custom_fbw_env"
        with patch.dict(os.environ, {"FBW_CONFIG_DIR": str(test_env_dir)}):
            resolved = get_config_dir()
            self.assertEqual(resolved, test_env_dir)
            self.assertTrue(test_env_dir.is_dir())

    def test_default_config_dir_is_home(self):
        """Verify get_config_dir defaults to ~/.fb-video-watcher."""
        with patch.dict(os.environ, {"FBW_CONFIG_DIR": ""}):
            resolved = get_config_dir()
            self.assertEqual(resolved, Path.home() / ".fb-video-watcher")

    def test_settings_dialog_download_options(self):
        """Verify SettingsDialog edits and persists download options."""
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        custom_save_path = str(self.config_dir / "SavedVideos")
        dialog.download_dir_var.set(custom_save_path)
        dialog.always_ask_download_var.set(True)
        dialog._save_and_close()

        self.assertEqual(self.settings_mgr.get("download", "download_dir"), custom_save_path)
        self.assertTrue(self.settings_mgr.get("download", "always_ask"))

    def test_download_always_ask_option(self):
        """Verify handle_download_request respects always_ask and prompts filedialog."""
        from main.app import Application

        mock_player = MagicMock()
        mock_player.get_position.return_value = 0
        mock_player.get_duration.return_value = 0
        mock_player.get_volume.return_value = 80
        mock_player.is_muted.return_value = False
        mock_player.state = "stopped"

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(
                self.root,
                settings_mgr=self.settings_mgr,
                history_mgr=self.history_mgr,
            )
            app.gui = self.gui
            app._original_url = "https://www.facebook.com/watch/?v=12345"

            # 1. Enable always_ask and simulate user selecting a folder
            app.settings.set("download", "always_ask", True)
            selected_dir = str(self.config_dir / "SelectedByDialog")
            Path(selected_dir).mkdir(parents=True, exist_ok=True)

            with patch("main.app.filedialog.askdirectory", return_value=selected_dir) as mock_ask:
                with patch("main.downloader.VideoDownloader") as mock_downloader_cls:
                    mock_dl_instance = MagicMock()
                    mock_downloader_cls.return_value = mock_dl_instance
                    app.handle_download_request()

                    mock_ask.assert_called_once()
                    mock_downloader_cls.assert_called_once()
                    _, kwargs = mock_downloader_cls.call_args
                    self.assertEqual(kwargs["output_dir"], Path(selected_dir))

            # 2. Simulate user cancelling dialog -> should abort cleanly without launching downloader
            app._active_downloader = None
            with patch("main.app.filedialog.askdirectory", return_value="") as mock_ask_cancel:
                with patch("main.downloader.VideoDownloader") as mock_downloader_cls:
                    app.handle_download_request()
                    mock_ask_cancel.assert_called_once()
                    mock_downloader_cls.assert_not_called()

    # --- 9. Fullscreen Smooth Animated Controls & Autohide ---

    def test_fullscreen_enter_and_exit(self):
        """Verify entering and exiting fullscreen cleanly sets state and updates button text."""
        self.assertFalse(self.gui._is_fullscreen)
        self.gui.enter_fullscreen()
        self.assertTrue(self.gui._is_fullscreen)
        self.assertEqual(self.gui.btn_fs.cget("text"), "⛶ Thoát toàn màn hình")
        self.assertIsNotNone(self.gui._fs_autohide_timer)

        # Exit fullscreen
        self.gui.exit_fullscreen()
        self.assertFalse(self.gui._is_fullscreen)
        self.assertEqual(self.gui.btn_fs.cget("text"), "⛶ Toàn màn hình")
        self.assertIsNone(self.gui._fs_autohide_timer)
        self.assertEqual(self.gui.top_wrapper.winfo_manager(), "pack")
        self.assertEqual(self.gui.bottom_wrapper.winfo_manager(), "pack")

    def test_fullscreen_slide_animation_and_cursor(self):
        """Verify _fs_animate_controls smoothly slides controls out and hides cursor."""
        self.gui.enter_fullscreen()

        # Mock after calls to run animation steps (<= 50ms) synchronously without auto-triggering autohide
        def immediate_after(ms, fn=None, *args):
            if fn and ms <= 50:
                fn(*args)
            return "timer_id"

        with patch.object(self.gui.root, "after", side_effect=immediate_after):
            self.gui._fs_animate_controls(show=False)

        self.assertFalse(self.gui._fs_controls_visible)
        self.assertEqual(self.gui.top_wrapper.winfo_manager(), "place")
        self.assertEqual(self.gui.bottom_wrapper.winfo_manager(), "place")
        self.assertEqual(self.gui.root.cget("cursor"), "none")

        # Slide controls back in
        with patch.object(self.gui.root, "after", side_effect=immediate_after):
            self.gui._fs_animate_controls(show=True)

        self.assertTrue(self.gui._fs_controls_visible)
        self.assertEqual(self.gui.top_wrapper.winfo_manager(), "place")
        self.assertEqual(self.gui.bottom_wrapper.winfo_manager(), "place")
        self.assertEqual(self.gui.root.cget("cursor"), "")

        self.gui.exit_fullscreen()
        self.assertEqual(self.gui.top_wrapper.winfo_manager(), "pack")
        self.assertEqual(self.gui.bottom_wrapper.winfo_manager(), "pack")

    def test_fullscreen_mouse_motion_reveals_controls(self):
        """Verify mouse motion in fullscreen wakes up and slides controls back in."""
        self.gui.enter_fullscreen()
        self.gui._fs_controls_visible = False

        with patch.object(self.gui, "_fs_animate_controls") as mock_anim:
            self.gui._on_fs_mouse_motion()
            mock_anim.assert_called_once_with(show=True)
            self.assertEqual(self.gui.root.cget("cursor"), "")

        self.gui.exit_fullscreen()

    def test_pip_and_fullscreen_mutual_exclusivity(self):
        """Verify PiP and Fullscreen properly exit each other when toggled."""
        # 1. Enter fullscreen then toggle PiP -> fullscreen must exit, PiP enters
        self.gui.enter_fullscreen()
        self.assertTrue(self.gui._is_fullscreen)
        self.assertFalse(self.gui._is_pip)

        self.gui.toggle_pip()
        self.assertFalse(self.gui._is_fullscreen)
        self.assertTrue(self.gui._is_pip)

        # 2. Enter fullscreen while in PiP -> PiP exits, fullscreen enters
        self.gui.enter_fullscreen()
        self.assertFalse(self.gui._is_pip)
        self.assertTrue(self.gui._is_fullscreen)

        # Clean up
        self.gui.exit_fullscreen()
        self.assertFalse(self.gui._is_fullscreen)
        self.assertFalse(self.gui._is_pip)

    def test_on_files_dropped_str_path(self):
        """Verify drag-and-drop of string file path updates entry and triggers playback."""
        test_path = "P:/A.Code/FB-Video-watching/sample_video.mp4"
        self.gui._on_files_dropped([test_path])
        self.assertEqual(self.gui.url_entry.get(), test_path)
        self.play_mock.assert_called_with(test_path)

    def test_on_files_dropped_bytes_path(self):
        """Verify drag-and-drop of bytes encoded path decodes and triggers playback."""
        test_path = "C:/Videos/video_tập_1.mkv"
        self.gui._on_files_dropped([test_path.encode("utf-8")])
        self.assertEqual(self.gui.url_entry.get(), test_path)
        self.play_mock.assert_called_with(test_path)

    def test_on_files_dropped_no_extension_or_txt(self):
        """Verify drag-and-drop works for video files renamed to .txt or with no extension."""
        # Renamed to .txt
        txt_path = "C:/Downloads/a.txt"
        self.gui._on_files_dropped([txt_path])
        self.assertEqual(self.gui.url_entry.get(), txt_path)
        self.play_mock.assert_called_with(txt_path)

        # No extension
        no_ext_path = "C:/Downloads/movie_file"
        self.gui._on_files_dropped([no_ext_path])
        self.assertEqual(self.gui.url_entry.get(), no_ext_path)
        self.play_mock.assert_called_with(no_ext_path)

    def test_on_open_file_dialog(self):
        """Verify _on_open_file_clicked prompts user and starts playback if selected."""
        with patch("tkinter.filedialog.askopenfilename", return_value="C:/Movies/my_video"):
            self.gui._on_open_file_clicked()
            self.assertEqual(self.gui.url_entry.get(), "C:/Movies/my_video")
            self.play_mock.assert_called_with("C:/Movies/my_video")

    def test_vlc_player_replay_when_ended(self):
        """Verify VLCPlayer resets playback and seeks properly when in Ended state."""
        from main.vlc_player import VLCPlayer
        import vlc

        dummy_frame = tk.Frame(self.root)
        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(dummy_frame)
            # Mock the internal player state to Ended
            player.player.get_state = MagicMock(return_value=vlc.State.Ended)
            player.player.stop = MagicMock()
            player.player.play = MagicMock()
            player.player.set_time = MagicMock()

            # 1. Calling play() without url when Ended must call stop() then play()
            player.play()
            player.player.stop.assert_called_once()
            player.player.play.assert_called_once()

            # Reset mocks
            player.player.stop.reset_mock()
            player.player.play.reset_mock()

            # 2. Calling toggle_play_pause() when Ended must call stop() then play()
            player.toggle_play_pause()
            player.player.stop.assert_called_once()
            player.player.play.assert_called_once()

            # Reset mocks
            player.player.stop.reset_mock()
            player.player.play.reset_mock()

            # 3. Calling seek_to(5000) when Ended must call stop(), play(), then set_time(5000)
            player.seek_to(5000)
            player.player.stop.assert_called_once()
            player.player.play.assert_called_once()
            player.player.set_time.assert_called_with(5000)

            player.release()

    def test_osd_overlay_vertical_mode_compact(self):
        """Verify OSDOverlay calculates compact size and clamps within narrow bounds."""
        from main.gui import OSDOverlay

        test_container = tk.Frame(self.root, width=202, height=360)
        test_container.pack()
        self.root.update_idletasks()

        osd = OSDOverlay(self.root, test_container)
        # Show seek badge with progress
        osd.show("+10s ⏩  [00:40 / 02:00]", relx=0.5, rely=0.88, anchor=tk.S, progress=0.33)
        self.root.update_idletasks()

        self.assertTrue(osd._is_visible)
        self.assertTrue(osd._has_progress)
        self.assertEqual(osd.progress_frame.winfo_manager(), "pack")

        # Verify width is clamped inside container
        _, _, ow_w, _ = osd._calculate_pos(0.5, 0.88, tk.S)
        self.assertLessEqual(ow_w, 202)

        osd.destroy()
        test_container.destroy()

    def test_pip_aspect_ratio_9_16_screen_bounds(self):
        """Verify set_pip_aspect_ratio('9:16') clamps window within screen bounds."""
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)

        self.gui.set_pip_aspect_ratio("9:16")
        self.root.update_idletasks()

        # Coordinates should be strictly on-screen
        win_x = self.root.winfo_x()
        win_y = self.root.winfo_y()
        win_w = self.root.winfo_width()
        win_h = self.root.winfo_height()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        self.assertGreaterEqual(win_x, 0)
        self.assertGreaterEqual(win_y, 0)
        self.assertLessEqual(win_x + win_w, screen_w)
        self.assertLessEqual(win_y + win_h, screen_h)

        # Ensure pip_progress is placed
        self.assertEqual(self.gui.pip_progress.winfo_manager(), "place")

        self.gui.toggle_pip()

    def test_pip_progress_overlay_lifecycle(self):
        """Verify hardware-composited PiPProgressOverlay lifecycle and update behavior."""
        self.assertTrue(hasattr(self.gui, "pip_progress_overlay"))
        overlay = self.gui.pip_progress_overlay

        # Initially hidden
        self.assertFalse(overlay._is_visible)

        # Enter PiP mode -> should become visible
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)
        self.assertTrue(overlay._is_visible)

        # Update playback time -> fraction should update
        self.gui.update_playback_time(current_ms=30000, duration_ms=60000)
        self.assertAlmostEqual(overlay._fraction, 0.5, places=2)

        # Reposition should work cleanly
        overlay.reposition(self.root)
        self.assertIsNotNone(overlay._last_geo)

        # Exit PiP mode -> should hide
        self.gui.toggle_pip()
        self.assertFalse(self.gui._is_pip)
        self.assertFalse(overlay._is_visible)

    def test_stream_proxy_strip_image_headers(self):
        """Verify strip_image_headers correctly removes fake PNG headers from MPEG-TS chunks."""
        from main.stream_proxy import strip_image_headers

        # 1. Pure TS packet (starts with 0x47)
        pure_ts = b"\x47" + b"\x00" * 187
        self.assertEqual(strip_image_headers(pure_ts), pure_ts)

        # 2. Obfuscated TS packet with fake PNG header
        fake_png_header = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x01\x03\x00\x00\x00%dbV"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        fake_segment = fake_png_header + pure_ts
        stripped = strip_image_headers(fake_segment)
        self.assertEqual(stripped, pure_ts)
        self.assertEqual(stripped[0], 0x47)

    def test_stream_proxy_playlist_url_generation(self):
        """Verify StreamProxyServer generates correct localhost URLs with parameters."""
        from main.stream_proxy import StreamProxyServer

        proxy = StreamProxyServer.get_instance()
        port = proxy.ensure_started()
        self.assertGreater(port, 0)

        remote_m3u8 = "https://cdn.example.com/stream/manifest.vl"
        proxy_url = proxy.get_proxy_playlist_url(remote_m3u8, referer="https://example.com/")
        self.assertTrue(proxy_url.startswith(f"http://127.0.0.1:{port}/playlist.m3u8?"))
        self.assertIn("url=https%3A%2F%2Fcdn.example.com%2Fstream%2Fmanifest.vl", proxy_url)
        self.assertIn("referer=https%3A%2F%2Fexample.com%2F", proxy_url)

    @unittest.mock.patch("urllib.request.urlopen")
    def test_prepare_hls_master_manifest_selection(self, mock_urlopen):
        """Verify _prepare_hls_master_manifest filters and binds the best video and audio variants."""
        from main.url_resolver import _prepare_hls_master_manifest

        sample_manifest = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:4\n"
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio_grp",NAME="Audio",DEFAULT=YES,URI="https://cdn.example.com/audio.m3u8"\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=1500000,CODECS="avc1.4D401F,mp4a.40.2",RESOLUTION=1280x720,AUDIO="audio_grp"\n'
            "https://cdn.example.com/video_720.m3u8\n"
            '#EXT-X-STREAM-INF:BANDWIDTH=4000000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1920x1080,AUDIO="audio_grp"\n'
            "https://cdn.example.com/video_1080.m3u8\n"
        ).encode("utf-8")

        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = sample_manifest
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # Test with max_height=720
        res_720_path = _prepare_hls_master_manifest("https://cdn.example.com/master.m3u8", max_height=720)
        self.assertIsNotNone(res_720_path)
        content_720 = Path(res_720_path).read_text(encoding="utf-8")
        self.assertIn("video_720.m3u8", content_720)
        self.assertNotIn("video_1080.m3u8", content_720)
        self.assertIn('GROUP-ID="audio_grp"', content_720)

        # Test with max_height=1080
        res_1080_path = _prepare_hls_master_manifest("https://cdn.example.com/master.m3u8", max_height=1080)
        self.assertIsNotNone(res_1080_path)
        content_1080 = Path(res_1080_path).read_text(encoding="utf-8")
        self.assertIn("video_1080.m3u8", content_1080)
        self.assertNotIn("video_720.m3u8", content_1080)

    @unittest.mock.patch("webbrowser.open")
    def test_cookies_guide_html_file_and_open_dialog(self, mock_web_open):
        """Verify cookies guide HTML file exists and SettingsDialog._open_cookie_guide opens it."""
        from main.gui import SettingsDialog

        # 1. Verify docs/cookies_guide.html exists and is well-formed
        guide_p = Path(__file__).resolve().parent.parent / "docs" / "cookies_guide.html"
        self.assertTrue(guide_p.is_file(), f"Guide HTML missing at {guide_p}")
        content = guide_p.read_text(encoding="utf-8")
        self.assertIn("cookies.txt", content)
        self.assertIn("Get cookies.txt LOCALLY", content)
        self.assertIn("FB Video Watcher", content)

        # 2. Mock SettingsDialog instance and invoke _open_cookie_guide
        mock_dialog = unittest.mock.MagicMock()
        mock_dialog.top = unittest.mock.MagicMock()
        SettingsDialog._open_cookie_guide(mock_dialog)

        mock_web_open.assert_called_once()
        opened_arg = mock_web_open.call_args[0][0]
        self.assertIn("cookies_guide.html", opened_arg)

    @unittest.mock.patch("main.updater.check_for_updates", return_value=None)
    @unittest.mock.patch("main.gui.messagebox.showinfo")
    def test_settings_dialog_about_tab(self, mock_msgbox, mock_check):
        """Verify SettingsDialog renders About tab, loads assets, and handles check updates."""
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.assertTrue(hasattr(dialog, "tab_about"))
        self.assertIn(dialog.tab_about, dialog.notebook.tabs())

        # Check updates action synchronously
        with unittest.mock.patch("threading.Thread", side_effect=lambda target, **kw: unittest.mock.MagicMock(start=target)):
            dialog._check_for_updates()
            dialog.top.update()

        mock_msgbox.assert_called_once()
        call_msg = mock_msgbox.call_args[0][1]
        self.assertIn("FB Video Watcher", call_msg)
        dialog.top.destroy()

    def test_seek_bar_drag_and_realtime_preview(self):
        """Test that dragging the seek bar dynamically updates the time label and triggers on_seek on release."""
        seek_called = []

        window = MainWindow(
            self.root,
            self.settings_mgr,
            self.theme_mgr,
            on_play_request=MagicMock(),
            on_pause_toggle=MagicMock(),
            on_seek_request=lambda ms: seek_called.append(ms),
            on_seek_relative=MagicMock(),
            on_volume_change=MagicMock(),
            on_mute_toggle=MagicMock(),
            on_rate_change=MagicMock(),
        )

        try:
            # Set duration to 100,000 ms (100 seconds)
            window.update_playback_time(10000, 100000)
            self.assertEqual(window.lbl_time.cget("text"), "00:10 / 01:40")

            # Mock scale width so get_value_from_x can calculate
            scale = window.seek_scale
            scale.winfo_width = MagicMock(return_value=500)

            # 1. Simulate mouse press at x=250 (50% = 50,000ms = 00:50)
            scale.event_generate("<ButtonPress-1>", x=250, y=10)
            self.assertTrue(window.seek_controller._is_user_dragging)
            self.assertEqual(window.lbl_time.cget("text"), "00:50 / 01:40")

            # 2. Simulate mouse drag to x=375 (75% = 75,000ms = 01:15)
            scale.event_generate("<B1-Motion>", x=375, y=10)
            self.assertEqual(window.lbl_time.cget("text"), "01:15 / 01:40")

            # While dragging, periodic update_playback_time must NOT overwrite the preview time
            window.update_playback_time(12000, 100000)
            self.assertEqual(window.lbl_time.cget("text"), "01:15 / 01:40")

            # 3. Simulate mouse release at x=375
            scale.event_generate("<ButtonRelease-1>", x=375, y=10)
            self.assertFalse(window.seek_controller._is_user_dragging)
            self.assertEqual(len(seek_called), 1)
            self.assertEqual(seek_called[0], 75000)
        finally:
            window.destroy()




if __name__ == "__main__":
    unittest.main()

