"""
Unit tests for Network Reconnection and Timeline In-Session Recovery.
Verifies that when network drops and reconnects, playback position is preserved,
timeline display does not jitter to 0:00:00, and in-session recovery works seamlessly.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock, patch
import tkinter as tk

import tempfile

from main.app import Application
from main.settings import SettingsManager
from main.playback_queue import QueueItem


class TestNetworkRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.config_dir = Path(cls.temp_dir.name)
        cls.settings_mgr = SettingsManager(config_dir=cls.config_dir)
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass
        cls.temp_dir.cleanup()

    def _create_mock_app(self):
        with patch("main.app.SystemInfo.detect") as mock_detect, \
             patch("main.app.MainWindow") as mock_gui, \
             patch("main.app.VLCPlayer") as mock_vlc, \
             patch("main.app.AutoTuner") as mock_tuner, \
             patch("main.app.ThemeManager") as mock_theme:

            mock_sys = MagicMock()
            mock_sys.ram_total_gb = 16.0
            mock_sys.cpu_name = "Mock CPU"
            mock_sys.cpu_cores_logical = 8
            mock_sys.is_hybrid_cpu = False
            mock_sys.gpu_name = "Mock GPU"
            mock_detect.return_value = mock_sys

            mock_tuner_inst = MagicMock()
            mock_tuner_inst.build_vlc_args.return_value = ["--quiet"]
            mock_tuner_inst.recommend_thread_pool_size.return_value = 2
            mock_tuner_inst.recommend_gpu_preference.return_value = "default"
            mock_tuner.return_value = mock_tuner_inst

            app = Application(self.root, settings_mgr=self.settings_mgr)
            app.root = MagicMock()
            app.root.winfo_exists.return_value = True
            app.root.after.side_effect = lambda ms, cb: f"timer_{ms}"
            return app

    def test_save_current_position_uses_effective_pos_when_player_stopped(self):
        """When player is stopped due to disconnect, effective position must be saved to SQLite."""
        app = self._create_mock_app()
        app._original_url = "https://www.facebook.com/watch/?v=12345"
        app._last_known_playback_pos_ms = 45000  # 45 seconds
        app._last_known_duration_ms = 120000

        # Player stopped due to disconnect -> get_position returns 0
        app.player.get_position.return_value = 0
        app.player.get_duration.return_value = 0
        app.history.save_position = MagicMock()

        app._save_current_position()

        # Verify save_position was called with effective_pos = 45000
        app.history.save_position.assert_called_once_with(
            url="https://www.facebook.com/watch/?v=12345",
            position_ms=45000,
            duration_ms=120000,
        )

    def test_handle_play_request_preserves_position_for_same_url(self):
        """When reconnecting same URL, do not wipe RAM position and snapshot to _session_resume_pos_ms."""
        app = self._create_mock_app()
        test_url = "https://www.facebook.com/watch/?v=12345"
        app._original_url = test_url
        app._last_known_playback_pos_ms = 60000  # 1 minute
        app._last_known_duration_ms = 180000
        app.player.get_position.return_value = 0  # player stopped

        with patch.object(app.executor, "submit") as mock_submit:
            mock_future = MagicMock()
            mock_submit.return_value = mock_future

            app.handle_play_request(test_url)

            # Verify _session_resume_pos_ms snapshot
            self.assertEqual(app._session_resume_pos_ms, 60000)
            # Verify _last_known_playback_pos_ms not reset to 0
            self.assertEqual(app._last_known_playback_pos_ms, 60000)

    def test_handle_play_request_clears_position_for_different_url(self):
        """When playing different URL, session resume position must be cleared."""
        app = self._create_mock_app()
        app._original_url = "https://www.facebook.com/watch/?v=11111"
        app._last_known_playback_pos_ms = 60000
        app.player.get_position.return_value = 0

        with patch.object(app.executor, "submit") as mock_submit:
            mock_future = MagicMock()
            mock_submit.return_value = mock_future

            app.handle_play_request("https://www.facebook.com/watch/?v=22222")

            # Different URL -> session resume reset to None
            self.assertIsNone(app._session_resume_pos_ms)
            self.assertEqual(app._last_known_playback_pos_ms, 0)

    def test_timeline_ui_frozen_at_last_known_pos_during_disconnect(self):
        """When stream drops, GUI timeline must freeze at last known position rather than jumping to 0:00:00."""
        app = self._create_mock_app()
        app._last_known_playback_pos_ms = 75000  # 1:15
        app._last_known_duration_ms = 300000

        # Simulate VLC in stopped state after disconnect
        app.player.state = "stopped"
        app.player.get_position.return_value = 0
        app.player.get_duration.return_value = 0

        app._update_ui_state()

        # GUI update_playback_time must receive 75000, 300000 instead of 0, 0
        app.gui.update_playback_time.assert_called_with(75000, 300000)

    def test_handle_playback_error_uses_effective_pos(self):
        """When VLC reports playback error, _handle_playback_error_safe uses effective position to retry."""
        app = self._create_mock_app()
        app._original_url = "https://www.facebook.com/watch/?v=12345"
        app._last_known_playback_pos_ms = 90000
        app._re_resolve_attempts = 0
        app.player.get_position.return_value = 0  # player returns 0 on error

        with patch.object(app.executor, "submit") as mock_submit:
            mock_future = MagicMock()
            mock_submit.return_value = mock_future

            app._handle_playback_error_safe("Network disconnect error")

            # Verify re_resolve_attempts incremented
            self.assertEqual(app._re_resolve_attempts, 1)
            # Verify _session_resume_pos_ms saved 90000
            self.assertEqual(app._session_resume_pos_ms, 90000)
            mock_submit.assert_called_once()

    def test_in_session_recovery_overrides_privacy_mode(self):
        """In-session recovery overrides privacy mode to restore position after network drop."""
        app = self._create_mock_app()
        test_url = "https://www.facebook.com/watch/?v=12345"
        app._original_url = test_url
        app._session_resume_pos_ms = 120000  # Watching at 2m when network dropped

        # Simulate Privacy Session: disable history writes/reads
        app.persistence_policy.enabled = True

        mock_future = MagicMock()
        mock_resolved = MagicMock()
        mock_resolved.stream_url = "https://cdn.example.com/video.mp4"
        mock_resolved.audio_url = None
        mock_resolved.subtitles = {}
        mock_resolved.automatic_captions = {}
        mock_resolved.http_headers = None
        mock_resolved.title = "Test Video"
        mock_resolved.duration = 300.0
        mock_resolved.is_live = False
        mock_resolved.content_id = "12345"
        mock_resolved.formats = []
        mock_future.result.return_value = (mock_resolved, None)

        with patch.object(app, "_perform_resume_seek") as mock_resume_seek:
            app._on_resolve_completed(mock_future, test_url)

            # Schedule callbacks in after
            scheduled_cbs = [args[1] for args, _ in app.root.after.call_args_list if len(args) >= 2 and callable(args[1])]
            for cb in scheduled_cbs:
                try:
                    cb()
                except Exception:
                    pass

            mock_resume_seek.assert_called_with(test_url, 120000)

    def test_tier2_soft_reconnect_preserves_playback_position(self):
        """Tier 2 soft reconnect captures current playback position before reconnect."""
        app = self._create_mock_app()
        test_url = "https://www.facebook.com/watch/?v=12345"
        app._original_url = test_url
        app._last_known_playback_pos_ms = 80000
        app.player.get_position.return_value = 80000
        app.player.resync_video.return_value = False
        app._consecutive_resyncs = 2  # Next will be 3

        with patch.object(app, "handle_play_request") as mock_play_req:
            app._handle_video_frozen_resync()

            self.assertEqual(app._session_resume_pos_ms, 80000)
            scheduled_cbs = [args[1] for args, _ in app.root.after.call_args_list if len(args) >= 2 and callable(args[1])]
            for cb in scheduled_cbs:
                try:
                    cb()
                except Exception:
                    pass
            mock_play_req.assert_called_with(test_url)

    def test_perform_resume_seek_polling_state_machine(self):
        """_perform_resume_seek verifies state in ('playing', 'paused') and dur > 0 before seeking."""
        app = self._create_mock_app()
        test_url = "https://www.facebook.com/watch/?v=12345"
        app._original_url = test_url

        # When player not ready (buffering, dur = 0)
        app.player.state = "buffering"
        app.player.get_duration.return_value = 0
        app.player.get_position.return_value = -1

        app._perform_resume_seek(test_url, 50000, attempt=0, max_attempts=60)
        # Should not seek yet
        app.player.seek_to.assert_not_called()

        # When player ready (playing and dur > 0)
        app.player.state = "playing"
        app.player.get_duration.return_value = 180000
        app.player.get_position.return_value = 100

        app._perform_resume_seek(test_url, 50000, attempt=1, max_attempts=60)
        # Ready -> seek_to called with 50000ms
        app.player.seek_to.assert_called_once_with(50000)
        self.assertIsNone(app._session_resume_pos_ms)

    def test_handle_pause_toggle_reconnects_when_stream_stopped(self):
        """When stream stopped due to network drop, pressing Play/Pause reconnects and restores position."""
        app = self._create_mock_app()
        test_url = "https://www.facebook.com/watch/?v=12345"
        app._original_url = test_url
        app._last_known_playback_pos_ms = 95000
        app.player.state = "stopped"
        app.player.get_position.return_value = 0

        with patch.object(app, "handle_play_request") as mock_play_req:
            app.handle_pause_toggle()

            self.assertEqual(app._session_resume_pos_ms, 95000)
            mock_play_req.assert_called_once_with(test_url)


if __name__ == "__main__":
    unittest.main()
