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

    def test_pip_progress_overlay_lifecycle_and_bounds(self):
        """Test PiPProgressOverlay initialization, explicit bounds positioning, update, and clean destruction."""
        from main.gui.components import PiPProgressOverlay
        overlay = PiPProgressOverlay(self.root, height=3)
        self.assertFalse(overlay._is_visible)
        self.assertIsNone(overlay.top)

        # Show with explicit bounds
        bounds = (150, 250, 480, 270)
        overlay.show(self.root, bounds=bounds)
        self.assertTrue(overlay._is_visible)
        self.assertIsNotNone(overlay.top)
        self.assertEqual(overlay._last_geo, "480x3+150+517")

        # Update progress fraction and verify placement
        overlay.update(0.75, self.root, bounds=bounds)
        self.assertEqual(overlay._fraction, 0.75)

        # Reposition with new bounds
        new_bounds = (200, 300, 320, 180)
        overlay.reposition(self.root, bounds=new_bounds)
        self.assertEqual(overlay._last_geo, "320x3+200+477")

        # Destroy cleans up completely
        overlay.destroy()
        self.assertFalse(overlay._is_visible)
        self.assertIsNone(overlay.top)
        self.assertIsNone(overlay._last_geo)

    def test_pip_toggle_overlay_lifecycle(self):
        """Test toggle_pip integration showing overlay with bounds and destroying on exit."""
        self.gui.btn_pip = MagicMock()
        self.gui.resize_grip = MagicMock()
        self.gui.pip_progress = MagicMock()
        self.gui.pip_progress_fill = MagicMock()

        # Enter PiP
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)
        self.assertTrue(self.gui.pip_progress_overlay._is_visible)
        self.assertIsNotNone(self.gui.pip_progress_overlay.top)

        # Exit PiP
        self.gui.toggle_pip()
        self.assertFalse(self.gui._is_pip)
        self.assertFalse(self.gui.pip_progress_overlay._is_visible)
    def test_pip_position_persistence_and_restore(self):
        """Test that PiP position on secondary monitor (e.g. x=2200) is persisted and faithfully restored."""
        self.gui.btn_pip = MagicMock()
        self.gui.resize_grip = MagicMock()
        self.gui.pip_progress = MagicMock()
        self.gui.pip_progress_fill = MagicMock()

        # Save simulated Monitor 2 position
        self.gui._save_current_pip_geometry(width=500, height=280, x=2200, y=400, ratio="16:9")
        self.assertEqual(self.settings.get("ui", "pip_x_horizontal"), 2200)
        self.assertEqual(self.settings.get("ui", "pip_y_horizontal"), 400)

        with patch("main.gui.main_window.is_rect_visible_on_any_monitor", return_value=True):
            with patch("main.gui.main_window.get_monitor_work_area_for_rect", return_value=(1920, 0, 1920, 1080)):
                w, h, x, y = self.gui._get_saved_pip_geometry("16:9")
                self.assertEqual(x, 2200)
                self.assertEqual(y, 400)
                self.assertEqual(w, 500)
                self.assertEqual(h, 280)

    def test_pip_position_offscreen_fallback(self):
        """Test that if a saved position becomes off-screen (disconnected monitor), it safely falls back."""
        self.settings.set("ui", "pip_x_horizontal", 50000)
        self.settings.set("ui", "pip_y_horizontal", 50000)

        with patch("main.gui.main_window.is_rect_visible_on_any_monitor", return_value=False):
            with patch("main.gui.main_window.get_monitor_work_area_for_window", return_value=(0, 0, 1920, 1040)):
                w, h, x, y = self.gui._get_saved_pip_geometry("16:9")
                # Fallback to bottom-right of active window monitor
                self.assertEqual(x, 1920 - w - 24)
                self.assertEqual(y, 1040 - h - 40)

    def test_pip_drag_release_persists_position(self):
        """Test that releasing mouse after drag/move in PiP persists new position."""
        self.gui.btn_pip = MagicMock()
        self.gui.resize_grip = MagicMock()
        self.gui.pip_progress = MagicMock()
        self.gui.pip_progress_fill = MagicMock()

        self.gui.toggle_pip()
        self.gui._drag_mode = "move"
        self.gui._has_dragged = True

        fake_event = MagicMock()
        with patch.object(self.gui, "_save_current_pip_geometry") as mock_save:
            self.gui._on_video_release(fake_event)
            mock_save.assert_called_once()


class TestMemoryTrimmingAndSeekCleanup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def test_schedule_post_seek_cleanup_debounces(self):
        app = MagicMock(spec=Application)
        app.root = self.root
        app._is_shutting_down = False
        app._seek_cleanup_timer_id = None
        app.executor = MagicMock()
        app._post_task_cleanup = MagicMock()

        app._schedule_post_seek_cleanup = Application._schedule_post_seek_cleanup.__get__(app, Application)
        app._trigger_post_seek_cleanup = Application._trigger_post_seek_cleanup.__get__(app, Application)

        # First call schedules a timer
        app._schedule_post_seek_cleanup(delay_ms=100)
        timer1 = app._seek_cleanup_timer_id
        self.assertIsNotNone(timer1)

        # Rapid consecutive call cancels timer1 and reschedules (debounce)
        app._schedule_post_seek_cleanup(delay_ms=100)
        timer2 = app._seek_cleanup_timer_id
        self.assertIsNotNone(timer2)
        self.assertNotEqual(timer1, timer2)

        # Clean up timer
        self.root.after_cancel(timer2)

        # Trigger cleanup
        app._trigger_post_seek_cleanup()
        self.assertIsNone(app._seek_cleanup_timer_id)
        app.executor.submit.assert_called_once_with(app._post_task_cleanup)

    def test_post_task_cleanup_calls_gc_and_trim(self):
        app = MagicMock(spec=Application)
        app._post_task_cleanup = Application._post_task_cleanup.__get__(app, Application)

        with patch("main.app.gc.collect") as mock_gc, \
             patch("main.platform_utils.trim_process_memory") as mock_trim:
            app._post_task_cleanup()
            mock_gc.assert_called_once()
            mock_trim.assert_called_once()

    def test_periodic_maintenance_upgraded(self):
        app = MagicMock(spec=Application)
        app.root = self.root
        app._is_shutting_down = False
        app.history = MagicMock()
        app.executor = MagicMock()
        app._maint_timer_id = None
        app._post_task_cleanup = MagicMock()
        app._periodic_maintenance = Application._periodic_maintenance.__get__(app, Application)

        with patch("main.app.gc.collect") as mock_gc:
            app._periodic_maintenance()
            mock_gc.assert_called_once_with()
            app.executor.submit.assert_any_call(app.history.checkpoint_wal)
            app.executor.submit.assert_any_call(app._post_task_cleanup)
            if app._maint_timer_id:
                try:
                    self.root.after_cancel(app._maint_timer_id)
                except Exception:
                    pass

    def test_seek_handlers_schedule_cleanup(self):
        app = MagicMock(spec=Application)
        app.player = MagicMock()
        app.gui = MagicMock()
        app._schedule_post_seek_cleanup = MagicMock()
        app.handle_seek_request = Application.handle_seek_request.__get__(app, Application)
        app.handle_seek_relative = Application.handle_seek_relative.__get__(app, Application)

        app.handle_seek_request(15000)
        app.player.seek_to.assert_called_once_with(15000)
        app._schedule_post_seek_cleanup.assert_called_once()

        app._schedule_post_seek_cleanup.reset_mock()
        app.handle_seek_relative(10)
        app.player.seek_relative.assert_called_once_with(10)
        app._schedule_post_seek_cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
