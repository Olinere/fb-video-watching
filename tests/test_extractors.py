"""
Unit tests for the modular extractor architecture in main/extractors/.
Verifies extractor selection, inheritance, and dispatching.
"""

import unittest
from pathlib import Path
import tempfile

from main.extractors import (
    BaseExtractor,
    LocalFileExtractor,
    VLXXExtractor,
    SexVietNewExtractor,
    XNhauExtractor,
    YouTubeExtractor,
    GenericExtractor,
    get_extractor,
    EXTRACTOR_REGISTRY,
    ResolvedVideo,
    Format,
)


class TestExtractorArchitecture(unittest.TestCase):
    """Test extractor factory and individual extractor matching."""

    def test_extractor_inheritance(self):
        """All extractors must inherit from BaseExtractor."""
        for extractor_cls in EXTRACTOR_REGISTRY:
            with self.subTest(cls=extractor_cls.__name__):
                self.assertTrue(issubclass(extractor_cls, BaseExtractor))

    def test_local_file_extractor_selection(self):
        """Verify get_extractor selects LocalFileExtractor for local paths."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"video data")
            tmp_path = tf.name

        try:
            ext = get_extractor(tmp_path)
            self.assertIsInstance(ext, LocalFileExtractor)

            file_uri = f"file:///{Path(tmp_path).as_posix()}"
            ext_uri = get_extractor(file_uri)
            self.assertIsInstance(ext_uri, LocalFileExtractor)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_youtube_extractor_selection(self):
        """Verify get_extractor selects YouTubeExtractor for youtube URLs."""
        yt_urls = [
            "https://www.youtube.com/watch?v=LKvBLTYgnJE",
            "https://youtu.be/LKvBLTYgnJE",
            "http://m.youtube.com/watch?v=dQw4w9WgXcQ",
        ]
        for url in yt_urls:
            with self.subTest(url=url):
                ext = get_extractor(url)
                self.assertIsInstance(ext, YouTubeExtractor)

    def test_vlxx_extractor_selection(self):
        """Verify get_extractor selects VLXXExtractor for vlxx URLs."""
        urls = [
            "https://vlxx.phd/video/test/123/",
            "https://vlxx.sex/video/clip-hay/456/",
            "http://vlxx.com/video/sample/",
        ]
        for url in urls:
            with self.subTest(url=url):
                ext = get_extractor(url)
                self.assertIsInstance(ext, VLXXExtractor)

    def test_sexvietnew_extractor_selection(self):
        """Verify get_extractor selects SexVietNewExtractor for sexvietnew URLs."""
        urls = [
            "https://sexvietnew.world/video/123/",
            "https://sexvietnew.com/test/",
        ]
        for url in urls:
            with self.subTest(url=url):
                ext = get_extractor(url)
                self.assertIsInstance(ext, SexVietNewExtractor)

    def test_xnhau_extractor_selection(self):
        """Verify get_extractor selects XNhauExtractor for xnhau URLs."""
        urls = [
            "https://xnhau.cab/video/123/test/",
            "https://xnhau.com/video/456/",
        ]
        for url in urls:
            with self.subTest(url=url):
                ext = get_extractor(url)
                self.assertIsInstance(ext, XNhauExtractor)

    def test_generic_extractor_fallback(self):
        """Verify get_extractor falls back to GenericExtractor for Facebook, TikTok, Pornhub, etc."""
        universal_urls = [
            "https://www.facebook.com/watch/?v=123456789",
            "https://fb.watch/abc12345/",
            "https://www.tiktok.com/@user/video/123456789",
            "https://twitter.com/user/status/123456789",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://www.pornhub.com/view_video.php?viewkey=ph123456",
            "https://example.com/live/stream.m3u8",
        ]
        for url in universal_urls:
            with self.subTest(url=url):
                ext = get_extractor(url)
                self.assertIsInstance(ext, GenericExtractor)

    def test_get_js_runtimes(self):
        """Verify get_js_runtimes detects available runtimes."""
        from main.extractors import get_js_runtimes
        runtimes = get_js_runtimes()
        self.assertIsInstance(runtimes, dict)
        # Verify quickjs is detected if main/bin/qjs.exe exists
        main_bin_qjs = Path(__file__).resolve().parent.parent / "main" / "bin" / "qjs.exe"
        if main_bin_qjs.is_file():
            self.assertIn("quickjs", runtimes)
            self.assertIn("path", runtimes["quickjs"])
            self.assertTrue(Path(runtimes["quickjs"]["path"]).is_file())

    def test_youtube_extractor_uses_js_runtimes(self):
        """Verify YouTubeExtractor populates js_runtimes and remote_components in yt-dlp opts."""
        from unittest.mock import patch, MagicMock
        from main.extractors.youtube import YouTubeExtractor

        ext = YouTubeExtractor()
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_instance = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_instance
            mock_instance.extract_info.return_value = {
                "id": "test_id",
                "title": "Test Title",
                "formats": [{"url": "http://example.com/video.mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 720}],
            }
            res = ext.extract("https://www.youtube.com/watch?v=LKvBLTYgnJE")
            self.assertEqual(res.stream_url, "http://example.com/video.mp4")
            
            # Check options passed to YoutubeDL
            mock_ydl_cls.assert_called_once()
            called_opts = mock_ydl_cls.call_args[0][0]
            self.assertIn("remote_components", called_opts)
            self.assertIn("ejs:github", called_opts["remote_components"])
            if "quickjs" in called_opts.get("js_runtimes", {}):
                self.assertIn("path", called_opts["js_runtimes"]["quickjs"])

    def test_isolated_cookie_file(self):
        """Verify isolated_cookie_file protects original file from writes."""
        from main.extractors import isolated_cookie_file

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as orig:
            orig.write(b"# Original cookie content\nLOGIN_INFO=secret123\n")
            orig_path = orig.name

        try:
            with isolated_cookie_file(orig_path) as safe_cookie:
                self.assertIsNotNone(safe_cookie)
                self.assertNotEqual(safe_cookie, orig_path)
                self.assertTrue(Path(safe_cookie).is_file())
                # Overwrite the temp copy (simulating yt-dlp cookiejar.save())
                Path(safe_cookie).write_text("# Corrupted content without LOGIN_INFO\n", encoding="utf-8")

            # Temp copy should be cleaned up
            self.assertFalse(Path(safe_cookie).is_file())

            # Original file MUST remain intact
            orig_content = Path(orig_path).read_text(encoding="utf-8")
        finally:
            Path(orig_path).unlink(missing_ok=True)

    def test_youtube_extractor_hd_adaptive_selection(self):
        """Verify YouTubeExtractor selects HD adaptive stream over low-res progressive format."""
        from unittest.mock import patch, MagicMock
        from main.extractors.youtube import YouTubeExtractor

        ext = YouTubeExtractor()
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_instance = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_instance
            mock_instance.extract_info.return_value = {
                "id": "test_hd",
                "title": "HD Test Video",
                "formats": [
                    {"format_id": "18", "url": "http://example.com/360p.mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360},
                    {"format_id": "399", "url": "http://example.com/1080p.mp4", "vcodec": "av01", "acodec": "none", "height": 1080},
                    {"format_id": "251", "url": "http://example.com/audio.opus", "vcodec": "none", "acodec": "opus", "height": None},
                ],
                "requested_formats": [
                    {"format_id": "399", "url": "http://example.com/1080p.mp4", "vcodec": "av01", "acodec": "none", "height": 1080},
                    {"format_id": "251", "url": "http://example.com/audio.opus", "vcodec": "none", "acodec": "opus", "height": None},
                ],
            }
            res = ext.extract("https://www.youtube.com/watch?v=LKvBLTYgnJE", max_height=1080)
            self.assertEqual(res.stream_url, "http://example.com/1080p.mp4")
            self.assertEqual(res.audio_url, "http://example.com/audio.opus")

    def test_youtube_extractor_available_at_sync(self):
        """Verify YouTubeExtractor respects available_at time-lock delay before returning."""
        from unittest.mock import patch, MagicMock
        import time
        from main.extractors.youtube import YouTubeExtractor

        ext = YouTubeExtractor()
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls, patch("time.sleep") as mock_sleep:
            mock_instance = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_instance
            target_time = time.time() + 3.0
            mock_instance.extract_info.return_value = {
                "id": "test_lock",
                "title": "Time Lock Test",
                "available_at": target_time,
                "formats": [
                    {"format_id": "18", "url": "http://example.com/video.mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "available_at": target_time},
                ],
            }
            res = ext.extract("https://www.youtube.com/watch?v=LKvBLTYgnJE")
            self.assertEqual(res.stream_url, "http://example.com/video.mp4")
            mock_sleep.assert_called_once()
            slept_duration = mock_sleep.call_args[0][0]
            self.assertGreater(slept_duration, 2.0)
            self.assertLessEqual(slept_duration, 4.0)


if __name__ == "__main__":
    unittest.main()


