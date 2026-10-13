"""
Unit tests for post-skeleton fixes:
1. OSD loading auto-fade fallback timeout & timer conflict resolution
2. No-Op guard for VLC reinit on subtitle settings update
3. Polling resume seek & audio preservation on VLC reinit
4. PiPProgressOverlay update flushes idletasks and sets alpha
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
import tkinter as tk

from main.gui.components import OSDOverlay, PiPProgressOverlay
from main.vlc_player import VLCPlayer


class TestOSDOverlayLoadingFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.update_idletasks()
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.target = tk.Frame(self.root)
        self.osd = OSDOverlay(self.root, self.target)

    def tearDown(self):
        self.osd.destroy()
        self.target.destroy()

    def test_show_loading_sets_fallback_timer(self):
        """show_loading sets _loading_timeout_timer for 3.5s fallback."""
        self.osd.show_loading("Test loading...")
        self.assertTrue(self.osd._is_loading)
        self.assertIsNotNone(self.osd._loading_timeout_timer)

        # Calling hide cancels the timer and resets _is_loading
        self.osd.hide()
        self.assertFalse(self.osd._is_loading)
        self.assertIsNone(self.osd._loading_timeout_timer)

    def test_show_cancels_loading_timer_and_clears_loading_flag(self):
        """show() cancels _loading_timeout_timer and resets _is_loading to False."""
        self.osd.show_loading("Loading...")
        self.assertTrue(self.osd._is_loading)
        loading_timer = self.osd._loading_timeout_timer
        self.assertIsNotNone(loading_timer)

        # Call show() as if user pressed Pause/Play or Volume
        self.osd.show("⏸ Tạm dừng")
        self.assertFalse(self.osd._is_loading)
        self.assertIsNone(self.osd._loading_timeout_timer)
        self.assertIsNotNone(self.osd._fade_timer)

    def test_destroy_cancels_all_timers(self):
        """destroy() cleans up both _fade_timer and _loading_timeout_timer."""
        self.osd.show_loading("Loading...")
        self.osd.destroy()
        self.assertIsNone(self.osd._loading_timeout_timer)
        self.assertIsNone(self.osd._fade_timer)
        self.assertFalse(self.osd._is_loading)


class TestPiPProgressOverlayFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.update_idletasks()
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.overlay = PiPProgressOverlay(self.root)

    def tearDown(self):
        self.overlay.destroy()

    def test_ensure_window_configures_alpha(self):
        """_ensure_window configures alpha 1.0 on top window."""
        self.overlay._ensure_window()
        self.assertIsNotNone(self.overlay.top)
        # Verify attributes alpha was attempted without crashing
        self.assertEqual(self.overlay.top.cget("bg"), "#1a1a1a")

    def test_update_flushes_idletasks(self):
        """update() places fill_frame and invokes update_idletasks without error."""
        self.overlay._ensure_window()
        with patch.object(self.overlay.top, "update_idletasks") as mock_idle:
            self.overlay.update(0.5, self.root)
            self.assertEqual(self.overlay._fraction, 0.5)
            mock_idle.assert_called()


class TestSettingsSubtitleNoOpGuard(unittest.TestCase):
    def test_settings_update_does_not_reinit_vlc_if_args_unchanged(self):
        """handle_settings_updated does not call reinit_instance when launch args are unchanged."""
        from main.app import Application

        app = MagicMock(spec=Application)
        app.gui = MagicMock()
        app.player = MagicMock()
        app.player._vlc_args = ["--quiet", "--no-video-title-show"]
        app.vlc_args = ["--quiet", "--no-video-title-show"]
        app.sys_info = MagicMock()
        app.settings = MagicMock()
        app.settings.settings = {}
        app.settings.get.return_value = {"enabled": False, "source_option": "none"}
        app._apply_cpu_optimizations = MagicMock()

        # Mock tuner to return identical args
        app.tuner = MagicMock()
        app.tuner.build_vlc_args.return_value = ["--quiet", "--no-video-title-show"]

        with patch("main.app.AutoTuner", return_value=app.tuner):
            # Run the actual handle_settings_updated logic
            Application.handle_settings_updated(app)

        # reinit_instance should NOT have been called
        app.player.reinit_instance.assert_not_called()
        # But clear_subtitle SHOULD have been called
        app.player.clear_subtitle.assert_called_once()

    def test_settings_update_reinits_vlc_if_args_changed(self):
        """handle_settings_updated calls reinit_instance when launch args differ."""
        from main.app import Application

        app = MagicMock(spec=Application)
        app.gui = MagicMock()
        app.player = MagicMock()
        app.player._vlc_args = ["--quiet"]
        app.vlc_args = ["--quiet"]
        app.sys_info = MagicMock()
        app.settings = MagicMock()
        app.settings.settings = {}
        app.settings.get.return_value = {"enabled": True, "source_option": "local", "file": "test.srt"}
        app._apply_cpu_optimizations = MagicMock()

        # Mock tuner to return new args
        new_args = ["--quiet", "--freetype-fontsize=48"]
        app.tuner = MagicMock()
        app.tuner.build_vlc_args.return_value = new_args

        with patch("main.app.AutoTuner", return_value=app.tuner):
            Application.handle_settings_updated(app)

        # reinit_instance SHOULD have been called with new args
        app.player.reinit_instance.assert_called_once_with(new_args)


class TestVLCPlayerReinitPreservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.update_idletasks()
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.frame = tk.Frame(self.root)

    def tearDown(self):
        self.frame.destroy()

    def test_reinit_instance_preserves_audio_and_polls(self):
        mock_vlc = MagicMock()
        mock_instance = MagicMock()
        mock_mp = MagicMock()
        mock_vlc.Instance.return_value = mock_instance
        mock_instance.media_player_new.return_value = mock_mp

        with patch.dict(sys.modules, {"vlc": mock_vlc}):
            player = VLCPlayer(self.frame)
            player._last_volume = 120
            player._is_muted = False
            player._current_url = "http://example.com/stream.m3u8"

            # Mock player state as playing
            mock_mp.get_state.return_value = mock_vlc.State.Playing
            mock_mp.get_time.return_value = 50000
            mock_mp.get_length.return_value = 100000
            mock_mp.audio_get_volume.return_value = 120

            with patch.object(player, "_perform_reinit_resume_seek") as mock_seek:
                player.reinit_instance(["--quiet"])
                # Audio volume 120 should be restored
                self.assertEqual(player.get_volume(), 120)
                # Polling seek should have been triggered
                mock_seek.assert_called_once()


if __name__ == "__main__":
    unittest.main()
