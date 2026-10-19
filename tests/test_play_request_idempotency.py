"""
Unit tests for Play Request Idempotency, Duplicate IPC Trigger Protection,
Stale Future Guard, and URL Entry Synchronization.
Strictly verifies that:
1. Duplicate play requests for the same in-flight URL do not cancel the resolving future.
2. New play requests for a different URL cancel the previous future properly.
3. Stale futures from earlier superseded tasks are safely discarded in _on_resolve_completed.
4. CancelledError cleanly resets resolving state and loading overlay when active.
5. GUI url_entry is synchronized as the Single Source of Truth from handle_play_request.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import concurrent.futures
import unittest
from unittest.mock import MagicMock, patch
import tkinter as tk
import tempfile

from main.app import Application
from main.settings import SettingsManager


class TestPlayRequestIdempotency(unittest.TestCase):
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

    def test_duplicate_play_request_same_url_preserves_inflight_future(self):
        """When an in-flight resolution is running for URL A, receiving URL A again must NOT cancel the future."""
        app = self._create_mock_app()
        test_url = "https://www.youtube.com/watch?v=duplicate123"

        with patch.object(app.executor, "submit") as mock_submit, \
             patch("main.platform_utils.bring_window_to_front") as mock_bring_front:

            mock_future = MagicMock()
            mock_future.done.return_value = False
            mock_submit.return_value = mock_future

            # 1. First trigger
            app.handle_play_request(test_url)
            self.assertEqual(app._resolving_url, test_url)
            self.assertIs(app._active_future, mock_future)
            self.assertEqual(mock_submit.call_count, 1)

            # 2. Second trigger with identical URL (from duplicate IPC trigger or double click)
            app.handle_play_request(test_url)

            # Future must NOT be cancelled
            mock_future.cancel.assert_not_called()
            # Must NOT submit a second worker task
            self.assertEqual(mock_submit.call_count, 1)
            # Window brought to front
            mock_bring_front.assert_called_once_with(app.root)

    def test_play_request_different_url_cancels_previous_future(self):
        """When receiving a different URL while resolving URL A, URL A's future must be cancelled."""
        app = self._create_mock_app()
        url_a = "https://www.youtube.com/watch?v=video_A"
        url_b = "https://www.youtube.com/watch?v=video_B"

        with patch.object(app.executor, "submit") as mock_submit:
            mock_future_a = MagicMock()
            mock_future_a.done.return_value = False

            mock_future_b = MagicMock()
            mock_future_b.done.return_value = False

            mock_submit.side_effect = [mock_future_a, mock_future_b]

            # 1. First URL
            app.handle_play_request(url_a)
            self.assertEqual(app._resolving_url, url_a)
            self.assertIs(app._active_future, mock_future_a)

            # 2. Second (different) URL
            app.handle_play_request(url_b)

            # Future A must be cancelled
            mock_future_a.cancel.assert_called_once()
            # Future B takes over as active future
            self.assertEqual(app._resolving_url, url_b)
            self.assertIs(app._active_future, mock_future_b)
            self.assertEqual(mock_submit.call_count, 2)

    def test_stale_future_discarded_in_on_resolve_completed(self):
        """When an older future completes after a newer future has taken over, its result must be ignored."""
        app = self._create_mock_app()
        url_old = "https://www.youtube.com/watch?v=old_url"

        mock_old_future = MagicMock()
        mock_newer_future = MagicMock()

        # Set active future to the newer one
        app._active_future = mock_newer_future
        app._resolving_url = "https://www.youtube.com/watch?v=new_url"

        # Old future finishes and callback fires
        app._on_resolve_completed(mock_old_future, url_old)

        # Old future's result must never be queried or played
        mock_old_future.result.assert_not_called()
        app.player.play.assert_not_called()
        # Active future remains the newer one
        self.assertIs(app._active_future, mock_newer_future)

    def test_clean_cancellation_resets_state_and_overlay(self):
        """When active future is cancelled, state is cleanly cleared and loading overlay hidden."""
        app = self._create_mock_app()
        test_url = "https://www.youtube.com/watch?v=cancelled_url"

        mock_future = MagicMock()
        mock_future.result.side_effect = concurrent.futures.CancelledError()

        app._active_future = mock_future
        app._resolving_url = test_url

        app._on_resolve_completed(mock_future, test_url)

        # State must be cleanly reset
        self.assertIsNone(app._active_future)
        self.assertIsNone(app._resolving_url)
        app.gui.hide_overlay.assert_called_once()
        app.gui.set_status.assert_called_with("Đã hủy phân giải video.")

    def test_url_entry_synchronization_from_handle_play_request(self):
        """handle_play_request must update url_entry if incoming URL differs from entry text."""
        app = self._create_mock_app()
        test_url = "https://www.youtube.com/watch?v=sync_test"

        app.gui.url_entry = MagicMock()
        app.gui.url_entry.get.return_value = "https://previous-url.com"

        with patch.object(app.executor, "submit"):
            app.handle_play_request(test_url)

            app.gui.url_entry.delete.assert_called_with(0, tk.END)
            app.gui.url_entry.insert.assert_called_with(0, test_url)


if __name__ == "__main__":
    unittest.main()
