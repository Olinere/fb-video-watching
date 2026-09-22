"""
Comprehensive unit tests for the 4 newly added features:
1. Ghi nhớ mốc thời gian đang xem dở (Resume Playback)
2. Tự động nhận diện link từ Clipboard (Auto-detect Link with Download action)
3. Lặp lại video & Lặp đoạn A-B (Loop & A-B Repeat)
4. Nâng cấp tính năng Tải xuống (Downloader: Audio extraction & Windows Toast notification)
"""

from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from main.settings import SettingsManager
from main.theme import ThemeManager
from main.gui import MainWindow, SettingsDialog
from main.app import Application
from main.downloader import VideoDownloader
from main.platform_utils import show_windows_toast


class TestResumeLoopDownload(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings_mgr = SettingsManager(config_dir=self.config_dir)
        self.theme_mgr = ThemeManager(self.root, initial_theme="dark")

        self.play_mock = MagicMock()
        self.pause_mock = MagicMock()
        self.seek_mock = MagicMock()
        self.seek_rel_mock = MagicMock()
        self.vol_mock = MagicMock()
        self.mute_mock = MagicMock()
        self.rate_mock = MagicMock()
        self.history_mock = MagicMock()
        self.download_mock = MagicMock()
        self.loop_mock = MagicMock()
        self.ab_mock = MagicMock()

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
            on_history_request=self.history_mock,
            on_download_request=self.download_mock,
            on_loop_toggle=self.loop_mock,
            on_ab_repeat_toggle=self.ab_mock,
        )

    def tearDown(self):
        try:
            if hasattr(self, "gui") and getattr(self.gui, "_osd_timer", None):
                self.root.after_cancel(self.gui._osd_timer)
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    # --- Feature 1: Resume Playback Tests ---

    def test_resume_playback_setting_in_dialog(self):
        """Verify resume_playback checkbox in SettingsDialog persists value."""
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.root.update_idletasks()

        # Check default value is True
        self.assertTrue(dialog.resume_playback_var.get())

        # Toggle to False and save
        dialog.resume_playback_var.set(False)
        dialog._save_and_close()

        self.assertFalse(self.settings_mgr.get("playback", "resume_playback"))

    def test_perform_resume_seek_triggers_seek_and_osd(self):
        """Verify _perform_resume_seek seeks and displays OSD badge when player is ready."""
        mock_player = MagicMock()
        mock_player.state = "playing"
        mock_player.get_position.return_value = 0
        mock_player.get_duration.return_value = 120000

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(self.root, settings_mgr=self.settings_mgr)
            app.gui = self.gui
            app._original_url = "https://www.facebook.com/watch/?v=999"

            app._perform_resume_seek("https://www.facebook.com/watch/?v=999", 45000, max_attempts=5)
            mock_player.seek_to.assert_called_once_with(45000)
            app._is_shutting_down = True
            app.executor.shutdown(wait=False, cancel_futures=True)

    # --- Feature 2: Clipboard Auto-Detect Tests ---

    def test_clipboard_toast_download_action(self):
        """Verify clicking Download on clipboard prompt triggers download request."""
        test_url = "https://www.facebook.com/watch/?v=777888"
        self.gui.show_clipboard_prompt(test_url)
        self.root.update_idletasks()

        self.assertEqual(self.gui._detected_clipboard_url, test_url)

        # Click Download button on toast
        self.gui.btn_clip_download.invoke()
        self.download_mock.assert_called_once()
        self.assertEqual(self.gui.url_entry.get(), test_url)

    # --- Feature 3: Loop & A-B Repeat Tests ---

    def test_loop_mode_toggle_and_playback_ended(self):
        """Verify loop mode toggles properly and restarts playback on end of stream."""
        mock_player = MagicMock()
        mock_player.state = "stopped"
        mock_player.get_position.return_value = 60000
        mock_player.get_duration.return_value = 60000

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(self.root, settings_mgr=self.settings_mgr)
            app.gui = self.gui
            app._original_url = "https://www.facebook.com/watch/?v=111"
            app._current_stream_url = "https://video.cdn.fb.com/live.mp4"

            # 1. Toggle loop on
            self.assertFalse(app._is_loop_enabled)
            app.handle_loop_toggle()
            self.assertTrue(app._is_loop_enabled)
            self.assertTrue(app.settings.get("playback", "loop_enabled"))

            # 2. End of playback triggers play() again
            app._handle_playback_ended_safe()
            mock_player.play.assert_called_with("https://video.cdn.fb.com/live.mp4")

            # 3. Toggle loop off
            app.handle_loop_toggle()
            self.assertFalse(app._is_loop_enabled)
            app._is_shutting_down = True
            app.executor.shutdown(wait=False, cancel_futures=True)

    def test_ab_repeat_state_transitions(self):
        """Verify A-B repeat cycle: Set A -> Set B -> Turn Off."""
        mock_player = MagicMock()
        mock_player.state = "playing"
        mock_player.get_position.return_value = 10000  # 10s
        mock_player.get_duration.return_value = 60000

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(self.root, settings_mgr=self.settings_mgr)
            app.gui = self.gui

            # Step 1: Set Point A
            app.handle_ab_repeat_toggle()
            self.assertEqual(app._ab_point_a, 10000)
            self.assertIsNone(app._ab_point_b)

            # Step 2: Set Point B (invalid when B <= A)
            mock_player.get_position.return_value = 5000
            app.handle_ab_repeat_toggle()
            self.assertIsNone(app._ab_point_b)  # Should reject B <= A

            # Step 2b: Set Point B validly (B > A)
            mock_player.get_position.return_value = 35000  # 35s
            app.handle_ab_repeat_toggle()
            self.assertEqual(app._ab_point_a, 10000)
            self.assertEqual(app._ab_point_b, 35000)

            # Step 3: Turn Off
            app.handle_ab_repeat_toggle()
            self.assertIsNone(app._ab_point_a)
            self.assertIsNone(app._ab_point_b)
            app._is_shutting_down = True
            app.executor.shutdown(wait=False, cancel_futures=True)

    def test_ab_repeat_boundary_seeking_in_ui_update(self):
        """Verify _update_ui_state seeks back to Point A when Point B is reached."""
        mock_player = MagicMock()
        mock_player.state = "playing"
        mock_player.get_position.return_value = 40000  # Past Point B (30s)
        mock_player.get_duration.return_value = 60000

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(self.root, settings_mgr=self.settings_mgr)
            app.gui = self.gui
            app._ab_point_a = 10000
            app._ab_point_b = 30000

            app._update_ui_state()
            mock_player.seek_to.assert_called_with(10000)
            app._is_shutting_down = True
            app.executor.shutdown(wait=False, cancel_futures=True)

    # --- Feature 4: Downloader Audio & Windows Toast Tests ---

    def test_video_downloader_audio_only_configuration(self):
        """Verify VideoDownloader configures audio extraction correctly."""
        dl = VideoDownloader(
            url="https://www.facebook.com/watch/?v=123",
            output_dir=self.config_dir,
            audio_only=True,
            audio_format="mp3",
        )
        self.assertTrue(dl.audio_only)
        self.assertEqual(dl.audio_format, "mp3")

    def test_show_windows_toast_handles_calls_safely(self):
        """Verify show_windows_toast runs without error on Windows or non-Windows."""
        with patch("subprocess.Popen") as mock_popen:
            res = show_windows_toast("Test Title", "Test Message")
            if res:
                mock_popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
