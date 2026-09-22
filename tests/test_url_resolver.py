"""
Unit tests for main/url_resolver.py.
Verifies URL validation, regex filtering, and data structures.
"""

import unittest
from unittest import mock
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.url_resolver import (
    validate_facebook_url,
    ResolvedVideo,
    Format,
    URLValidationError,
    VideoNotFoundError,
    AuthRequiredError,
    NetworkError,
)


class TestURLResolver(unittest.TestCase):
    """Test URL validation and error handling."""

    def test_valid_video_urls(self):
        valid_urls = [
            "https://www.facebook.com/reel/123456789",
            "https://www.facebook.com/watch/?v=123456789",
            "https://fb.watch/abc123/",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://b23.tv/abc123",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.tiktok.com/@user/video/123456789",
            "https://twitter.com/user/status/123456",
            "  https://www.bilibili.com/video/BV1xx411c7mD  ",  # with spaces
        ]
        for url in valid_urls:
            with self.subTest(url=url):
                cleaned = validate_facebook_url(url)
                self.assertEqual(cleaned, url.strip())

    def test_invalid_urls(self):
        invalid_urls = [
            "",
            "   ",
            "not_a_url",
            "ftp://fileserver/video.mp4",
            "http://",
            "https://",
            None,
            123,
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(URLValidationError):
                    validate_facebook_url(url)  # type: ignore

    def test_resolved_video_dataclass(self):
        fmt = Format(
            format_id="hd",
            height=1080,
            width=1920,
            ext="mp4",
            vcodec="h264",
            acodec="aac",
            filesize=10485760,
        )
        resolved = ResolvedVideo(
            stream_url="https://video.xx.fbcdn.net/v/test.mp4",
            title="Sample FB Reel",
            duration=45.0,
            thumbnail="https://scontent.xx.fbcdn.net/thumb.jpg",
            is_live=False,
            formats=[fmt],
            audio_url="https://audio.xx.fbcdn.net/v/audio.mp4",
        )
        self.assertEqual(resolved.title, "Sample FB Reel")
        self.assertEqual(resolved.duration, 45.0)
        self.assertFalse(resolved.is_live)
        self.assertEqual(len(resolved.formats), 1)
        self.assertEqual(resolved.formats[0].height, 1080)
        self.assertEqual(resolved.audio_url, "https://audio.xx.fbcdn.net/v/audio.mp4")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_preprocess_special_url_vlxx(self, mock_urlopen):
        from main.url_resolver import _preprocess_special_url
        
        page_html = (
            '<html><head><title>Test Adult Video - VLXX.COM</title></head>'
            '<body><div id="video" data-id="12345" data-sv="1"></div></body></html>'
        ).encode('utf-8')
        ajax_json = (
            '{"player":"<iframe src=\\"https://play.vlstream.net/embed/test123/s1\\"></iframe>"}'
        ).encode('utf-8')
        
        mock_resp1 = unittest.mock.MagicMock()
        mock_resp1.read.return_value = page_html
        mock_resp1.__enter__.return_value = mock_resp1
        
        mock_resp2 = unittest.mock.MagicMock()
        mock_resp2.read.return_value = ajax_json
        mock_resp2.__enter__.return_value = mock_resp2
        
        mock_urlopen.side_effect = [mock_resp1, mock_resp2]
        
        target_url, title, thumb = _preprocess_special_url("https://vlxx.phd/video/test-video/12345/")
        self.assertEqual(target_url, "https://play.vlstream.net/embed/test123/s1")
        self.assertEqual(title, "Test Adult Video")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_preprocess_special_url_sexvietnew(self, mock_urlopen):
        from main.url_resolver import _preprocess_special_url

        page_html = (
            '<html><head><title>Test SVN Video - Sex Việt Mới</title>'
            '<meta property="og:image" content="https://sexvietnew.world/thumb.jpg" />'
            '<meta itemprop="contentUrl" content="https://sexvietnew.world/video.mp4" />'
            '</head><body></body></html>'
        ).encode('utf-8')

        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = page_html
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        target_url, title, thumb = _preprocess_special_url("https://sexvietnew.world/test-video/")
        self.assertEqual(target_url, "https://sexvietnew.world/video.mp4")
        self.assertEqual(title, "Test SVN Video")
        self.assertEqual(thumb, "https://sexvietnew.world/thumb.jpg")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_preprocess_special_url_xnhau(self, mock_urlopen):
        from main.url_resolver import _preprocess_special_url

        page_html = (
            '<html><head><title>Test xNhau Video - xNhau</title></head><body>'
            "<script>var flashvars = { video_title: 'Chịch ở công viên', preview_url: 'https://xnhau.cab/preview.jpg', "
            "video_url: 'https://xnhau.cab/get_file/video_480p.mp4', video_alt_url: 'https://xnhau.cab/get_file/video_720p.mp4' };</script>"
            '</body></html>'
        ).encode('utf-8')

        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = page_html
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        target_url, title, thumb = _preprocess_special_url("https://xnhau.cab/video/123/test/")
        self.assertEqual(target_url, "https://xnhau.cab/get_file/video_720p.mp4")
        self.assertEqual(title, "Chịch ở công viên")
        self.assertEqual(thumb, "https://xnhau.cab/preview.jpg")

    def test_is_potential_video_url(self):
        from main.url_resolver import is_potential_video_url

        self.assertTrue(is_potential_video_url("https://xnhau.cab/video/332382/chich-public-o-cong-vien/"))
        self.assertTrue(is_potential_video_url("https://vlxx.phd/video/test/3216/"))
        self.assertTrue(is_potential_video_url("https://sexvietnew.world/public-cung-gai-xinh/"))
        self.assertTrue(is_potential_video_url("https://www.youtube.com/watch?v=sample123"))
        self.assertTrue(is_potential_video_url("https://fb.watch/12345/"))
        self.assertTrue(is_potential_video_url("https://example.com/video.mp4"))
        self.assertTrue(is_potential_video_url("https://example.com/live/stream.m3u8?token=123"))
        self.assertFalse(is_potential_video_url("https://google.com"))
        self.assertFalse(is_potential_video_url("https://vnexpress.net/thoi-su"))
        self.assertFalse(is_potential_video_url("just text"))
        self.assertFalse(is_potential_video_url(""))

    def test_resolve_local_media_file(self):
        from main.url_resolver import resolve_facebook_url, is_local_media_file
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"dummy video data")
            tmp_path = tf.name

        try:
            self.assertTrue(is_local_media_file(tmp_path))
            resolved = resolve_facebook_url(tmp_path)
            self.assertEqual(resolved.stream_url, str(Path(tmp_path).resolve()))
            self.assertEqual(resolved.title, Path(tmp_path).name)
            self.assertFalse(resolved.is_live)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_resolve_local_media_file_renamed_to_txt_or_no_ext(self):
        from main.url_resolver import resolve_facebook_url, is_local_media_file, is_potential_video_url
        import tempfile
        from pathlib import Path

        # 1. Renamed to .txt (e.g. a.mp4 renamed to a.txt)
        with tempfile.NamedTemporaryFile(suffix=".txt", prefix="a_", delete=False) as tf:
            tf.write(b"fake mp4 header bytes")
            txt_path = tf.name

        try:
            self.assertTrue(is_local_media_file(txt_path))
            self.assertTrue(is_potential_video_url(txt_path))
            resolved = resolve_facebook_url(txt_path)
            self.assertEqual(resolved.stream_url, str(Path(txt_path).resolve()))
            self.assertEqual(resolved.title, Path(txt_path).name)
        finally:
            Path(txt_path).unlink(missing_ok=True)

        # 2. File with no extension (e.g. 'a' or 'myvideo')
        with tempfile.NamedTemporaryFile(suffix="", prefix="my_video_no_ext_", delete=False) as tf:
            tf.write(b"fake media bytes")
            no_ext_path = tf.name

        try:
            self.assertTrue(is_local_media_file(no_ext_path))
            self.assertTrue(is_potential_video_url(no_ext_path))
            resolved = resolve_facebook_url(no_ext_path)
            self.assertEqual(resolved.stream_url, str(Path(no_ext_path).resolve()))
            self.assertEqual(resolved.title, Path(no_ext_path).name)
        finally:
            Path(no_ext_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
