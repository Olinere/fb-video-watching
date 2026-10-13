"""
Unit tests verifying the Queue Transition Freeze and Not Responding fixes:
1. Natural End vs Premature Disconnect detection using effective position.
2. Background resolution of streams and subtitles (_resolve_stream_and_subtitles).
3. Backwards-compatible tuple unpacking in _on_resolve_completed.
4. Non-blocking state handling in VLCPlayer.play() when player is already Ended.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import MagicMock, patch
import concurrent.futures
import tempfile
import tkinter as tk

from main.app import Application
from main.settings import SettingsManager
from main.theme import ThemeManager
from main.playback_queue import QueueItem
from main.extractors.base import ResolvedVideo
from main.vlc_player import VLCPlayer


class TestQueueTransitionFix(unittest.TestCase):
    """Test suite covering the 4 solution pillars of queue transition stability."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings_mgr = SettingsManager(config_dir=self.config_dir)
        self.theme_mgr = ThemeManager(self.root, initial_theme="dark")

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_end_reached_with_zero_pos_advances_queue_naturally(self):
        """When video ends, VLC resets get_position() to 0/-1.
        The application must use _last_known_playback_pos_ms to correctly detect Natural End
        and advance to the next queue item instead of falsely diagnosing a premature stream error."""
        mock_player = MagicMock()
        mock_player.state = "ended"
        mock_player.get_position.return_value = 0
        mock_player.get_duration.return_value = 60000  # 60s video

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(self.root, settings_mgr=self.settings_mgr)
            app._original_url = "https://example.com/video_a"
            app._current_stream_url = "https://cdn.example.com/stream_a.mp4"
            app._last_known_playback_pos_ms = 59500  # Player reached 59.5s before EndReached
            app._last_known_duration_ms = 60000

            # Add two items to queue and mark item_a as currently playing
            item_a = QueueItem(source_url="https://example.com/video_a", title="Video A")
            item_b = QueueItem(source_url="https://example.com/video_b", title="Video B")
            app.queue.add_many([item_a, item_b])
            app._active_queue_item = item_a
            app.queue_controller.begin(item_a)

            app._handle_playback_error_safe = MagicMock()
            app._start_next_queue_item = MagicMock()

            # Execute end handler
            app._handle_playback_ended_safe()

            # Must NOT trigger premature disconnect error
            app._handle_playback_error_safe.assert_not_called()
            # Must advance to next item (Video B)
            app._start_next_queue_item.assert_called_once()
            called_item = app._start_next_queue_item.call_args[0][0]
            self.assertEqual(called_item.source_url, "https://example.com/video_b")

            app._is_shutting_down = True
            app.executor.shutdown(wait=False, cancel_futures=True)

    def test_genuine_premature_disconnect_triggers_reconnect(self):
        """If playback truly stopped mid-stream early on (e.g. at 10s of a 60s video),
        it must still be diagnosed as a premature disconnect and trigger reconnect."""
        mock_player = MagicMock()
        mock_player.state = "ended"
        mock_player.get_position.return_value = 0
        mock_player.get_duration.return_value = 60000

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(self.root, settings_mgr=self.settings_mgr)
            app._original_url = "https://example.com/video_a"
            app._current_stream_url = "https://cdn.example.com/stream_a.mp4"
            app._last_known_playback_pos_ms = 10000  # Stopped prematurely at 10s
            app._last_known_duration_ms = 60000

            app._handle_playback_error_safe = MagicMock()
            app._start_next_queue_item = MagicMock()

            app._handle_playback_ended_safe()

            app._handle_playback_error_safe.assert_called_once_with("Stream bị ngắt kết nối giữa chừng.")
            app._start_next_queue_item.assert_not_called()

            app._is_shutting_down = True
            app.executor.shutdown(wait=False, cancel_futures=True)

    def test_worker_resolves_stream_and_subtitles_off_ui_thread(self):
        """_resolve_stream_and_subtitles must run in the background worker and bundle
        both ResolvedVideo and active subtitle path together."""
        dummy_resolved = ResolvedVideo(
            stream_url="https://cdn.example.com/video.mp4",
            title="Test Video",
            duration=45.0,
            thumbnail=None,
            is_live=False,
            content_id="test123",
        )

        with patch("main.app.resolve_facebook_url", return_value=dummy_resolved), \
             patch("main.subtitle.SubtitleDispatcher.resolve_subtitle_for_stream", return_value="/tmp/sub.vtt"):
            res, sub = Application._resolve_stream_and_subtitles(
                url="https://example.com/video",
                cookie_file=None,
                max_height=1080,
                sub_cfg={"enabled": True, "source_option": "web"},
            )
            self.assertEqual(res.stream_url, "https://cdn.example.com/video.mp4")
            self.assertEqual(sub, "/tmp/sub.vtt")

    def test_on_resolve_completed_backward_compatibility(self):
        """_on_resolve_completed must seamlessly unpack both a 2-tuple (resolved, sub)
        and a legacy naked ResolvedVideo object without throwing ValueError."""
        dummy_resolved = ResolvedVideo(
            stream_url="https://cdn.example.com/video.mp4",
            title="Test Video",
            duration=45.0,
            thumbnail=None,
            is_live=False,
            content_id="test123",
        )

        mock_player = MagicMock()
        mock_player.current_url = "http://127.0.0.1:8888/old"

        with patch("main.app.VLCPlayer", return_value=mock_player):
            app = Application(self.root, settings_mgr=self.settings_mgr)
            app.gui.speed_var = MagicMock()

            # Case A: 2-tuple return from worker
            fut_tuple = concurrent.futures.Future()
            fut_tuple.set_result((dummy_resolved, "/tmp/sub.vtt"))
            app._on_resolve_completed(fut_tuple, "https://example.com/video")
            mock_player.play.assert_called_with(
                dummy_resolved.stream_url,
                audio_url=None,
                subtitle_file="/tmp/sub.vtt",
                http_headers=None,
                network_caching_ms=unittest.mock.ANY,
            )

            # Case B: Legacy naked ResolvedVideo (e.g. from existing test mocks)
            fut_naked = concurrent.futures.Future()
            fut_naked.set_result(dummy_resolved)
            app._on_resolve_completed(fut_naked, "https://example.com/video")
            mock_player.play.assert_called_with(
                dummy_resolved.stream_url,
                audio_url=None,
                subtitle_file=None,
                http_headers=None,
                network_caching_ms=unittest.mock.ANY,
            )

            app._is_shutting_down = True
            app.executor.shutdown(wait=False, cancel_futures=True)

    def test_vlc_player_avoids_stop_on_ended_state(self):
        """VLCPlayer.play() must NOT invoke synchronous player.stop() if player is already Ended,
        preventing Win32 D3D11 Vout deadlocks on the UI thread."""
        mock_frame = MagicMock()
        mock_frame.winfo_id.return_value = 999

        with patch("main.vlc_player.embed_vlc_in_frame"):
            player = VLCPlayer(mock_frame)
            player._current_url = "https://cdn.example.com/old_video.mp4"
            mock_media = MagicMock()
            player._current_media = mock_media
            player.player = MagicMock()
            player.instance = MagicMock()
            # Simulate player in Ended state
            import vlc
            player.player.get_state.return_value = vlc.State.Ended

            player.play("https://cdn.example.com/new_video.mp4")

            # player.stop() must NOT be called when state is Ended
            player.player.stop.assert_not_called()
            # Media must still be released and transition scheduled
            mock_media.release.assert_called_once()
            mock_frame.after.assert_called_once()


if __name__ == "__main__":
    unittest.main()
