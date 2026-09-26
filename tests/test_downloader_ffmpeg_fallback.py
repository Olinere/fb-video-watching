"""Unit tests for FFmpeg detection and progressive download fallback."""

import unittest
from unittest.mock import patch

from main.ffmpeg_utils import (
    build_download_opts,
    get_ffmpeg_path,
    is_ffmpeg_available,
    YtDlpLogFilter,
)


class TestDownloaderFFmpegFallback(unittest.TestCase):
    def test_log_filter_suppresses_python_310_warning(self):
        log_filter = YtDlpLogFilter()
        # Should not raise exception
        log_filter.warning("Deprecated Feature: Support for Python version 3.10 has been deprecated and will be removed.")
        log_filter.error("Deprecated Feature: Support for Python version 3.10 has been deprecated.")
        log_filter.info("Normal message")
        log_filter.debug("Debug message")

    def test_build_download_opts_without_ffmpeg_video(self):
        opts, notice = build_download_opts(
            output_tmpl="%(title)s.%(ext)s",
            max_height=720,
            audio_only=False,
            has_ffmpeg=False,
        )
        self.assertIsNotNone(notice)
        self.assertIn("FFmpeg chưa được cài đặt", notice)
        # format should prioritize progressive streams
        self.assertIn("best[ext=mp4]", opts["format"])
        # merge_output_format MUST NOT be present
        self.assertNotIn("merge_output_format", opts)
        # ffmpeg_location must not be present or is None
        self.assertNotIn("ffmpeg_location", opts)

    def test_build_download_opts_without_ffmpeg_audio(self):
        opts, notice = build_download_opts(
            output_tmpl="%(title)s.mp3",
            audio_only=True,
            audio_format="mp3",
            has_ffmpeg=False,
        )
        self.assertIsNotNone(notice)
        self.assertIn(".m4a", notice)
        # Should NOT have FFmpegExtractAudio postprocessor
        self.assertEqual(opts.get("postprocessors"), [])
        self.assertIn("bestaudio[ext=m4a]", opts["format"])

    def test_build_download_opts_with_ffmpeg_video(self):
        opts, notice = build_download_opts(
            output_tmpl="%(title)s.%(ext)s",
            max_height=1080,
            audio_only=False,
            has_ffmpeg=True,
            ffmpeg_path="C:\\ffmpeg\\bin\\ffmpeg.exe",
        )
        self.assertIsNone(notice)
        self.assertEqual(opts["ffmpeg_location"], "C:\\ffmpeg\\bin\\ffmpeg.exe")
        self.assertEqual(opts["merge_output_format"], "mp4")
        self.assertIn("bestvideo", opts["format"])
        self.assertIn("bestaudio", opts["format"])

    def test_build_download_opts_with_ffmpeg_audio(self):
        opts, notice = build_download_opts(
            output_tmpl="%(title)s.mp3",
            audio_only=True,
            audio_format="mp3",
            has_ffmpeg=True,
            ffmpeg_path="C:\\ffmpeg\\bin\\ffmpeg.exe",
        )
        self.assertIsNone(notice)
        self.assertEqual(opts["ffmpeg_location"], "C:\\ffmpeg\\bin\\ffmpeg.exe")
        self.assertIn("postprocessors", opts)
        self.assertEqual(opts["postprocessors"][0]["key"], "FFmpegExtractAudio")
        self.assertEqual(opts["postprocessors"][0]["preferredcodec"], "mp3")


    def test_video_downloader_extract_info_none(self):
        """Test VideoDownloader gracefully handles None info dict from extract_info."""
        from unittest.mock import MagicMock
        from main.downloader import VideoDownloader

        error_msg = []
        downloader = VideoDownloader(
            url="https://example.com/fake",
            on_error=lambda msg: error_msg.append(msg),
        )

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None
        mock_ydl_ctx = MagicMock()
        mock_ydl_ctx.__enter__.return_value = mock_ydl

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl_ctx):
            downloader._run_download()

        self.assertEqual(len(error_msg), 1)
        self.assertIn("Không thể trích xuất thông tin video", error_msg[0])
        # Verify prepare_filename was never called with None
        mock_ydl.prepare_filename.assert_not_called()


if __name__ == "__main__":
    unittest.main()
