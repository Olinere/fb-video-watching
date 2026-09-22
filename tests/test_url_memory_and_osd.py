"""
Unit tests for URL memory restoration and OSD (On-Screen Display) overlay notification.
"""

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from main.settings import SettingsManager
from main.theme import ThemeManager
from main.history import HistoryManager
from main.gui import MainWindow
from main.app import Application


class TestUrlMemoryAndOSD(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings = SettingsManager(config_dir=self.config_dir)
        self.theme = ThemeManager(self.root)

        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings,
            theme_mgr=self.theme,
            on_play_request=MagicMock(),
            on_pause_toggle=MagicMock(),
            on_seek_request=MagicMock(),
            on_seek_relative=MagicMock(),
            on_volume_change=MagicMock(),
            on_mute_toggle=MagicMock(),
            on_rate_change=MagicMock(),
        )

    def tearDown(self):
        try:
            if self.gui._osd_timer:
                self.root.after_cancel(self.gui._osd_timer)
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def test_osd_seek_forward_and_accumulation(self):
        # First forward seek (+5s) -> bottom-right
        self.gui.show_osd_seek(5)
        self.assertEqual(self.gui.osd_label["text"], "+5s ⏩")
        info = self.gui.osd_label.place_info()
        self.assertEqual(info["anchor"], "se")

        # Second forward seek immediately (+5s) -> accumulates to +10s
        self.gui.show_osd_seek(5)
        self.assertEqual(self.gui.osd_label["text"], "+10s ⏩")

        # Third forward seek (+5s) -> accumulates to +15s
        self.gui.show_osd_seek(5)
        self.assertEqual(self.gui.osd_label["text"], "+15s ⏩")

    def test_osd_seek_backward_and_accumulation(self):
        # First backward seek (-5s) -> bottom-left
        self.gui.show_osd_seek(-5)
        self.assertEqual(self.gui.osd_label["text"], "⏪ -5s")
        info = self.gui.osd_label.place_info()
        self.assertEqual(info["anchor"], "sw")

        # Second backward seek immediately (-5s) -> accumulates to -10s
        self.gui.show_osd_seek(-5)
        self.assertEqual(self.gui.osd_label["text"], "⏪ -10s")

    def test_osd_pause_and_play_action(self):
        # Pause action -> bottom center
        self.gui.show_osd_action("pause")
        self.assertEqual(self.gui.osd_label["text"], "⏸ Tạm dừng")
        info = self.gui.osd_label.place_info()
        self.assertEqual(info["anchor"], "s")

        # Play action -> bottom center
        self.gui.show_osd_action("play")
        self.assertEqual(self.gui.osd_label["text"], "▶ Tiếp tục")
        info = self.gui.osd_label.place_info()
        self.assertEqual(info["anchor"], "s")

    def test_osd_fade_steps_and_dismiss(self):
        self.gui.show_osd_action("pause")
        self.assertIsNotNone(self.gui._osd_timer)

        # Run fade steps to completion
        for _ in range(5):
            self.gui._fade_osd_step()

        # Check OSD is hidden and state reset
        self.assertEqual(self.gui.osd_label.place_info(), {})
        self.assertIsNone(self.gui._osd_timer)
        self.assertEqual(self.gui._seek_accum_seconds, 0)

    @patch("main.app.VLCPlayer")
    def test_app_url_memory_restoration_and_save(self, mock_vlc):
        mock_instance = mock_vlc.return_value
        mock_instance.get_position.return_value = 0
        mock_instance.get_duration.return_value = 0
        mock_instance.state = "stopped"

        app_root = tk.Tk()
        app_root.withdraw()

        test_url = "https://www.facebook.com/reel/987654321"
        self.settings.set("playback", "last_url", test_url)

        with patch("main.app.SettingsManager", return_value=self.settings):
            with patch("main.app.HistoryManager") as mock_hist_cls:
                mock_hist = MagicMock()
                mock_hist.get_history.return_value = []
                mock_hist_cls.return_value = mock_hist

                app = Application(app_root)
                # Verify URL was restored into entry
                self.assertEqual(app.gui.url_entry.get(), test_url)

                # Change URL and trigger on_closing
                new_url = "https://www.facebook.com/watch/?v=11223344"
                app.gui.url_entry.delete(0, tk.END)
                app.gui.url_entry.insert(0, new_url)
                app.on_closing()

                # Verify new URL was persisted in settings
                self.assertEqual(self.settings.get("playback", "last_url"), new_url)

    def test_osd_floating_overlay_synchronized(self):
        # Trigger seek overlay
        self.gui.show_osd_seek(10)
        self.assertTrue(hasattr(self.gui, "osd_overlay"))
        self.assertTrue(self.gui.osd_overlay._is_visible)
        self.assertEqual(self.gui.osd_overlay.label["text"], "+10s ⏩")

        # Repositioning call shouldn't crash
        self.gui.osd_overlay.reposition()

        # Hide overlay
        self.gui.osd_overlay.hide()
        self.assertFalse(self.gui.osd_overlay._is_visible)

    def test_shortcut_wrapping_and_break(self):
        mock_action = MagicMock()
        wrapped = self.gui._wrap_shortcut(mock_action)

        # 1. Normal widget focused -> executes action and returns 'break'
        fake_event = MagicMock()
        fake_event.widget = self.gui.btn_play
        res = wrapped(fake_event)
        self.assertEqual(res, "break")
        mock_action.assert_called_once()

        # 2. Text entry focused -> does NOT execute action, returns None
        mock_action.reset_mock()
        fake_event.widget = self.gui.url_entry
        with patch.object(self.root, "focus_get", return_value=self.gui.url_entry):
            res = wrapped(fake_event)
            self.assertIsNone(res)
            mock_action.assert_not_called()

        # 3. Text entry focused, but allow_in_entry=True (e.g. Ctrl+H history dialog)
        mock_action.reset_mock()
        wrapped_entry_allowed = self.gui._wrap_shortcut(mock_action, allow_in_entry=True)
        with patch.object(self.root, "focus_get", return_value=self.gui.url_entry):
            res = wrapped_entry_allowed(fake_event)
            self.assertEqual(res, "break")
            mock_action.assert_called_once()

        # 4. Text entry focused, but event has Control modifier (state=4)
        mock_action.reset_mock()
        fake_ctrl_event = MagicMock()
        fake_ctrl_event.widget = self.gui.url_entry
        fake_ctrl_event.state = 4
        with patch.object(self.root, "focus_get", return_value=self.gui.url_entry):
            res = wrapped(fake_ctrl_event)
            self.assertEqual(res, "break")
            mock_action.assert_called_once()

    def test_osd_seek_with_duration_and_progress(self):
        """Verify that when a video has duration, seek OSD displays timestamps and progress."""
        self.gui.update_playback_time(current_ms=30000, duration_ms=120000)
        self.gui.show_osd_seek(10)
        self.assertIn("+10s ⏩", self.gui.osd_label["text"])
        self.assertIn("00:40 / 02:00", self.gui.osd_label["text"])
        self.assertTrue(self.gui.osd_overlay._has_progress)
        self.assertTrue(self.gui.osd_overlay._is_visible)


if __name__ == "__main__":
    unittest.main()
