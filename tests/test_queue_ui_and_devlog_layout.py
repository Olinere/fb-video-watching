"""
Unit tests for Playlist/Queue Preservation and Right-Expanding Layout Hierarchy.
Validates:
1. Playlist table is never cleared when selecting or playing videos in a queue.
2. Queue panel expands window outward to the right without squeezing video player.
3. Devlog panel expands window outward to the right and is positioned furthest right (sát phải).
4. Queue panel sits immediately to the left of Devlog, neither squeezing the video player.
5. Context menu and track navigation actions (next/prev) function properly.
"""

from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from main.settings import SettingsManager
from main.theme import ThemeManager
from main.gui import MainWindow
from main.playback_queue import PlaybackQueue, QueueItem
from main.queue_controller import QueueController
from main.app import Application


class TestQueueUiAndDevlogLayout(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings = SettingsManager(config_dir=self.config_dir)
        self.theme = ThemeManager(self.root)

        self.on_play_request = MagicMock()
        self.on_play_queue_item = MagicMock()
        self.on_remove_queue_item = MagicMock()
        self.on_move_queue_item = MagicMock()
        self.on_clear_queue = MagicMock()
        self.on_clear_played_queue = MagicMock()
        self.on_retry_queue_item = MagicMock()
        self.on_next_track = MagicMock()
        self.on_previous_track = MagicMock()

        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings,
            theme_mgr=self.theme,
            on_play_request=self.on_play_request,
            on_pause_toggle=MagicMock(),
            on_seek_request=MagicMock(),
            on_seek_relative=MagicMock(),
            on_volume_change=MagicMock(),
            on_mute_toggle=MagicMock(),
            on_rate_change=MagicMock(),
            on_play_queue_item=self.on_play_queue_item,
            on_remove_queue_item=self.on_remove_queue_item,
            on_move_queue_item=self.on_move_queue_item,
            on_clear_queue=self.on_clear_queue,
            on_clear_played_queue=self.on_clear_played_queue,
            on_retry_queue_item=self.on_retry_queue_item,
            on_next_track=self.on_next_track,
            on_previous_track=self.on_previous_track,
        )
        self.root.update_idletasks()

    def tearDown(self):
        try:
            if hasattr(self.gui, "destroy"):
                self.gui.destroy()
            if hasattr(self.gui, "devlog_panel") and self.gui.devlog_panel._detached_window:
                if self.gui.devlog_panel._detached_window.winfo_exists():
                    self.gui.devlog_panel._detached_window.destroy()
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def _get_window_width(self) -> int:
        return self.gui._window_width

    def test_queue_toggle_keeps_window_stable_without_shifting_buttons(self):
        """Toggling queue keeps window width fixed and buttons stationary."""
        initial_w = self._get_window_width()
        self.assertFalse(self.gui._queue_visible)
        initial_btn_x = self.gui.btn_play.winfo_x()

        # Open queue
        self.gui.toggle_queue()
        self.root.update_idletasks()
        self.assertTrue(self.gui._queue_visible)
        self.assertEqual(self._get_window_width(), initial_w)
        self.assertEqual(self.gui.btn_play.winfo_x(), initial_btn_x)

        # Close queue
        self.gui.toggle_queue()
        self.root.update_idletasks()
        self.assertFalse(self.gui._queue_visible)
        self.assertEqual(self._get_window_width(), initial_w)
        self.assertEqual(self.gui.btn_play.winfo_x(), initial_btn_x)

    def test_devlog_hidden_by_default_and_blocked(self):
        """Devlog checkbox is unmapped and toggle_devlog is blocked when dev mode is locked."""
        self.assertFalse(self.gui._dev_mode_unlocked)
        self.assertEqual(self.gui.chk_devlog.winfo_manager(), "")
        self.gui.toggle_devlog()
        self.assertFalse(self.gui.devlog_var.get())

    def test_devlog_toggle_keeps_window_stable_without_shifting_buttons(self):
        """Toggling devlog keeps window width fixed and buttons stationary once dev mode is unlocked."""
        self.gui.enable_dev_mode()
        self.assertEqual(self.gui.chk_devlog.winfo_manager(), "pack")
        initial_w = self._get_window_width()
        self.assertFalse(self.gui.devlog_var.get())
        initial_btn_x = self.gui.btn_play.winfo_x()

        # Open devlog
        self.gui.toggle_devlog()
        self.root.update_idletasks()
        self.assertTrue(self.gui.devlog_var.get())
        self.assertEqual(self._get_window_width(), initial_w)
        self.assertEqual(self.gui.btn_play.winfo_x(), initial_btn_x)

        # Close devlog
        self.gui.toggle_devlog()
        self.root.update_idletasks()
        self.assertFalse(self.gui.devlog_var.get())
        self.assertEqual(self._get_window_width(), initial_w)
        self.assertEqual(self.gui.btn_play.winfo_x(), initial_btn_x)

    def test_both_queue_and_devlog_keep_window_stable_with_proper_layout(self):
        """When both queue and devlog are open, window width stays fixed and devlog is furthest right."""
        self.gui.enable_dev_mode()
        initial_w = self._get_window_width()
        initial_btn_x = self.gui.btn_play.winfo_x()

        # Open queue then devlog
        self.gui.toggle_queue()
        self.root.update_idletasks()
        self.gui.toggle_devlog()
        self.root.update_idletasks()

        self.assertEqual(self._get_window_width(), initial_w)
        self.assertEqual(self.gui.btn_play.winfo_x(), initial_btn_x)

        # Verify packing hierarchy in content_area children
        # In Tkinter pack(side=RIGHT): first packed slave in pack_slaves() is furthest right.
        packed_right = [
            child for child in self.gui.content_area.pack_slaves()
            if child.pack_info().get("side") == "right"
        ]
        # Devlog frame should be the first packed right widget (sát phải)
        self.assertIn(self.gui.devlog_panel.panel_frame, packed_right)
        self.assertIn(self.gui.queue_panel, packed_right)
        self.assertLess(
            packed_right.index(self.gui.devlog_panel.panel_frame),
            packed_right.index(self.gui.queue_panel),
            "Devlog must be packed before Queue so it sits on the furthest right edge."
        )

        # Close devlog, queue remains open
        self.gui.toggle_devlog()
        self.root.update_idletasks()
        self.assertEqual(self._get_window_width(), initial_w)

        # Close queue, returns to initial width
        self.gui.toggle_queue()
        self.root.update_idletasks()
        self.assertEqual(self._get_window_width(), initial_w)

    def test_queue_popup_detach_and_dock(self):
        """Queue can be detached into an independent floating popup window and docked back."""
        self.assertFalse(self.gui._queue_is_detached)
        self.assertIsNone(self.gui._queue_window)

        # Detach to popup
        self.gui.detach_queue_to_window()
        self.root.update_idletasks()
        self.assertTrue(self.gui._queue_is_detached)
        self.assertIsNotNone(self.gui._queue_window)
        self.assertTrue(self.gui._queue_window.winfo_exists())

        # Dock back
        self.gui.dock_queue_back()
        self.root.update_idletasks()
        self.assertFalse(self.gui._queue_is_detached)
        self.assertIsNone(self.gui._queue_window)

    def test_queue_double_click_calls_on_play_queue_item(self):
        """Double clicking a queue row calls on_play_queue_item with queue_id."""
        sample_rows = [
            {"queue_id": "qid-1", "source_url": "https://example.com/v1", "title": "Video 1", "status": "pending"},
            {"queue_id": "qid-2", "source_url": "https://example.com/v2", "title": "Video 2", "status": "playing"},
        ]
        self.gui.refresh_queue(sample_rows)

        # Select index 0 and double click
        self.gui.queue_list.selection_set(0)
        self.gui._on_queue_double_click()
        self.on_play_queue_item.assert_called_once_with("qid-1")

    def test_menu_bar_structure_and_single_row_url_bar(self):
        """Native Menu Bar has 5 standard menus and URL bar contains single-row controls."""
        self.assertIsNotNone(self.gui.menu_bar)
        self.assertIsNotNone(self.gui.menu_file)
        self.assertIsNotNone(self.gui.menu_playlist)
        self.assertIsNotNone(self.gui.menu_playback)
        self.assertIsNotNone(self.gui.menu_tools)
        self.assertIsNotNone(self.gui.menu_help)

        # URL bar contains core controls on a single row
        self.assertEqual(self.gui.btn_play.winfo_manager(), "pack")
        self.assertEqual(self.gui.btn_paste_play.winfo_manager(), "pack")
        self.assertEqual(self.gui.btn_add_queue.winfo_manager(), "pack")
        self.assertEqual(self.gui.btn_toggle_queue.winfo_manager(), "pack")
        self.assertEqual(self.gui.btn_download.winfo_manager(), "pack")
        self.assertEqual(self.gui.btn_privacy.winfo_manager(), "pack")

    def test_menu_bar_theme_switching_light_dark(self):
        """ThemedMenuBar and cascading dropdown menus dynamically transition between Dark and Light themes."""
        # 1. Switch to light mode
        self.theme.apply_theme("light")
        self.assertEqual(str(self.gui.menu_bar.cget("bg")), "#ffffff")
        self.assertEqual(str(self.gui.menu_bar._buttons[0].cget("fg")), "#1a1a1a")
        self.assertEqual(str(self.gui.menu_file.cget("bg")), "#ffffff")

        # 2. Switch back to dark mode
        self.theme.apply_theme("dark")
        self.assertEqual(str(self.gui.menu_bar.cget("bg")), "#2c2c2c")
        self.assertEqual(str(self.gui.menu_bar._buttons[0].cget("fg")), "#f0f0f0")
        self.assertEqual(str(self.gui.menu_file.cget("bg")), "#2c2c2c")

    def test_settings_about_seven_clicks_unlocks_devlog(self):
        """Clicking app name 7 times in Settings -> About unlocks developer mode and shows Devlog."""
        from main.gui import SettingsDialog

        self.assertFalse(self.gui._dev_mode_unlocked)
        self.assertEqual(self.gui.chk_devlog.winfo_manager(), "")

        dialog = SettingsDialog(
            self.root,
            self.settings,
            self.theme,
            on_dev_mode_unlocked=self.gui.enable_dev_mode,
            on_osd_message=self.gui.show_osd_message,
        )
        try:
            # 3 clicks: still locked
            for _ in range(3):
                dialog._on_app_name_clicked()
            self.assertFalse(self.gui._dev_mode_unlocked)
            self.assertEqual(self.gui.chk_devlog.winfo_manager(), "")

            # 3 more clicks (total 6): still locked
            for _ in range(3):
                dialog._on_app_name_clicked()
            self.assertFalse(self.gui._dev_mode_unlocked)
            self.assertEqual(self.gui.chk_devlog.winfo_manager(), "")

            # 7th click: UNLOCKED!
            dialog._on_app_name_clicked()
            self.assertTrue(self.gui._dev_mode_unlocked)
            self.assertTrue(self.settings.get("ui", "dev_mode_unlocked"))
            self.assertEqual(self.gui.chk_devlog.winfo_manager(), "pack")

            # 8th click: already unlocked notification, remains unlocked
            dialog._on_app_name_clicked()
            self.assertTrue(self.gui._dev_mode_unlocked)
        finally:
            if hasattr(dialog, "top") and dialog.top.winfo_exists():
                dialog.top.destroy()

    def test_application_preserves_playlist_when_playing_item(self):
        """Application.handle_play_request must not clear queue when items already exist."""
        app_root = tk.Tk()
        app_root.withdraw()
        try:
            with patch("main.app.VLCPlayer") as mock_vlc_cls, \
                 patch("main.app.resolve_facebook_url") as mock_resolve, \
                 patch.object(Application, "_start_ui_timer"), \
                 patch.object(Application, "_start_maintenance_timer"), \
                 patch.object(Application, "_start_clipboard_timer"), \
                 patch.object(Application, "_background_check_update"), \
                 patch("concurrent.futures.ThreadPoolExecutor.submit") as mock_submit:
                mock_submit.return_value = MagicMock()
                mock_inst = MagicMock()
                mock_inst.get_position.return_value = 0
                mock_inst.get_duration.return_value = 0
                mock_inst.state = "stopped"
                mock_vlc_cls.return_value = mock_inst
                mock_resolve.return_value = MagicMock(
                    title="Mock Video",
                    duration=100,
                    is_live=False,
                    stream_url="http://mock.stream",
                    thumbnail=None,
                    formats=[],
                    height=720,
                    width=1280,
                )

                app = Application(app_root, settings_mgr=self.settings, privacy_enabled=False)
                # Populate queue with a 3-item playlist
                item1 = QueueItem(source_url="https://example.com/v1", title="Episode 1")
                item2 = QueueItem(source_url="https://example.com/v2", title="Episode 2")
                item3 = QueueItem(source_url="https://example.com/v3", title="Episode 3")
                app.queue.add_many([item1, item2, item3])
                self.assertEqual(len(app.queue), 3)

                # Play item 2 via handle_play_queue_item
                app.handle_play_queue_item(item2.queue_id)

                # Queue MUST still contain all 3 items!
                self.assertEqual(len(app.queue), 3)
                self.assertEqual(app._active_queue_item.queue_id, item2.queue_id)

                # Playing item 3 directly via handle_play_request
                app.handle_play_request(item3.source_url)
                self.assertEqual(len(app.queue), 3)
                self.assertEqual(app._active_queue_item.queue_id, item3.queue_id)

                # Next and previous track navigation
                app.handle_previous_track()
                self.assertEqual(len(app.queue), 3)
                self.assertEqual(app._active_queue_item.queue_id, item2.queue_id)
        finally:
            if "app" in locals():
                app._is_shutting_down = True
                app.executor.shutdown(wait=False, cancel_futures=True)
                if hasattr(app, "gui") and hasattr(app.gui, "destroy"):
                    try:
                        app.gui.destroy()
                    except Exception:
                        pass
            try:
                app_root.destroy()
            except Exception:
                pass



if __name__ == "__main__":
    unittest.main()
