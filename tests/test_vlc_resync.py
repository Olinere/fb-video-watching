import unittest
from unittest.mock import MagicMock, patch

from main.vlc_player import VLCPlayer


class TestVLCResync(unittest.TestCase):
    def test_vlc_player_resync_video_when_playing(self):
        mock_frame = MagicMock()
        mock_frame.winfo_id.return_value = 12345
        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(mock_frame)
            player.player = MagicMock()
            player.is_playing = MagicMock(return_value=True)
            player.get_position = MagicMock(return_value=15000)

            # Test resync_video
            res = player.resync_video()
            self.assertTrue(res)
            player.player.set_time.assert_called_once_with(15000)

    def test_vlc_player_resync_video_when_stopped(self):
        mock_frame = MagicMock()
        mock_frame.winfo_id.return_value = 12345
        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(mock_frame)
            player.player = MagicMock()
            player.is_playing = MagicMock(return_value=False)

            res = player.resync_video()
            self.assertFalse(res)
            player.player.set_time.assert_not_called()

    def test_vlc_player_get_media_stats_safely(self):
        mock_frame = MagicMock()
        mock_frame.winfo_id.return_value = 12345
        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(mock_frame)
            # When no media
            self.assertIsNone(player.get_media_stats())

            # When media present
            mock_media = MagicMock()
            mock_media.get_stats.return_value = True
            player._current_media = mock_media
            stats = player.get_media_stats()
            self.assertIsNotNone(stats)

    def test_application_handle_video_frozen_resync(self):
        from main.app import Application

        mock_root = MagicMock()
        mock_root.winfo_exists.return_value = True
        mock_sys_info = MagicMock()
        mock_sys_info.ram_total_gb = 16.0
        mock_sys_info.cpu_name = "Intel CPU"
        mock_sys_info.cpu_cores_logical = 8
        mock_sys_info.is_hybrid_cpu = False
        mock_sys_info.gpu_name = "GPU"
        mock_tuner = MagicMock()
        mock_tuner.recommend_thread_pool_size.return_value = 2
        mock_tuner.build_vlc_args.return_value = []
        with patch("main.app.SettingsManager"), \
             patch("main.app.ThemeManager"), \
             patch("main.app.HistoryManager"), \
             patch("main.app.SystemInfo.detect", return_value=mock_sys_info), \
             patch("main.app.AutoTuner", return_value=mock_tuner), \
             patch("main.app.MainWindow"), \
             patch("main.app.VLCPlayer"):
            app = Application(mock_root)
            app.player = MagicMock()
            app.player.resync_video.return_value = True
            app.gui = MagicMock()
            app._original_url = "https://youtube.com/watch?v=test"

            # 1. First trigger calls resync_video
            app._handle_video_frozen_resync(displayed=100, lost=50)
            app.player.resync_video.assert_called_once()
            app.gui.show_osd_message.assert_called_with("🔄 Đang đồng bộ lại hình ảnh...")

            # 2. Cooldown prevents immediate re-trigger
            app.player.resync_video.reset_mock()
            app._handle_video_frozen_resync(displayed=100, lost=60)
            app.player.resync_video.assert_not_called()

            # 3. After cooldown passes and triggers 3 times consecutively, soft reconnect is queued
            app._last_resync_time = 0.0
            app._consecutive_resyncs = 2
            with patch.object(app, "handle_play_request"):
                app._handle_video_frozen_resync(displayed=100, lost=100)
                mock_root.after.assert_called()




class TestAsyncQueueTransition(unittest.TestCase):
    """Tests for the 150ms async queue transition fix in VLCPlayer.play()."""

    def test_play_with_url_change_schedules_after_150ms(self):
        """When switching to a different URL, play() must schedule after(150ms) instead of
        calling player directly, giving D3D11 Vout thread time to flush the old swapchain."""
        mock_frame = MagicMock()
        mock_frame.winfo_id.return_value = 12345
        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(mock_frame)
            player._current_url = "http://old_stream_url"
            player._current_media = None
            player.player = MagicMock()
            player.instance = MagicMock()
            player.instance.media_new.return_value = MagicMock()

            player.play("http://new_stream_url")

            player.player.stop.assert_called_once()
            mock_frame.after.assert_called_once()
            call_args = mock_frame.after.call_args
            self.assertEqual(call_args[0][0], 150, "Delay must be exactly 150ms")
            player.player.play.assert_not_called()

    def test_play_with_first_url_calls_load_directly(self):
        """When no previous URL (first play), play() must call _load_and_start_media directly
        without any delay — the 150ms buffer is only needed for queue transitions."""
        mock_frame = MagicMock()
        mock_frame.winfo_id.return_value = 12345
        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(mock_frame)
            player._current_url = None
            player._current_media = None
            player.player = MagicMock()
            player.instance = MagicMock()
            player.instance.media_new.return_value = MagicMock()

            with patch.object(player, "_load_and_start_media") as mock_load:
                player.play("http://first_stream_url")
                mock_load.assert_called_once_with(
                    "http://first_stream_url", None, None, None, None
                )
                mock_frame.after.assert_not_called()

    def test_play_with_same_url_reloads_without_delay(self):
        """When called with the same URL (e.g. stream reconnect), must reload without 150ms delay."""
        mock_frame = MagicMock()
        mock_frame.winfo_id.return_value = 12345
        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(mock_frame)
            player._current_url = "http://same_url"
            player._current_media = None
            player.player = MagicMock()
            player.instance = MagicMock()
            player.instance.media_new.return_value = MagicMock()

            with patch.object(player, "_load_and_start_media") as mock_load:
                player.play("http://same_url")
                mock_load.assert_called_once()
                mock_frame.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()

