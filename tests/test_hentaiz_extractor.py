"""
Unit tests for HentaiZExtractor (supporting hentaivietsub.* and hentaiz.*).
"""

import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from main.extractors import get_extractor, HentaiZExtractor, VideoNotFoundError
from main.url_resolver import is_potential_video_url


class TestHentaiZExtractor(unittest.TestCase):
    """Test suite for HentaiZExtractor."""

    def setUp(self):
        self.extractor = HentaiZExtractor()

    def test_suitable_matching_various_domains_and_tlds(self):
        """Must match hentaivietsub and hentaiz across any TLD or subdomain."""
        positive_urls = [
            "https://hentaivietsub.com/hentai/fella-pure-mitarashi-san-chi-no-jijou-the-animation-1",
            "https://hentaiz.bot/hentai/fella-pure-mitarashi-san-chi-no-jijou-the-animation-1",
            "https://hentaivietsub.net/hentai/sample-video-1",
            "https://hentaiz.tv/hentai/sample-video-1",
            "https://hentaivietsub.org/hentai/test-title",
            "https://hentaiz.cc/hentai/test-title",
            "https://sub.hentaivietsub.vip/hentai/video-slug",
            "https://sub.hentaiz.moe/hentai/video-slug",
            "http://hentaivietsub.tv/hentai/episode-1",
        ]
        for url in positive_urls:
            with self.subTest(url=url):
                self.assertTrue(self.extractor.suitable(url), f"Should match {url}")
                self.assertTrue(is_potential_video_url(url), f"Should be potential video {url}")
                ext = get_extractor(url)
                self.assertIsInstance(ext, HentaiZExtractor, f"get_extractor must return HentaiZExtractor for {url}")

    def test_suitable_negative_cases(self):
        """Must NOT match unrelated websites."""
        negative_urls = [
            "https://www.youtube.com/watch?v=12345",
            "https://facebook.com/reel/123",
            "https://vlxx.phd/video/123",
            "https://google.com/",
            "https://example.com/video/hentai",
            "",
            None,
        ]
        for url in negative_urls:
            with self.subTest(url=url):
                self.assertFalse(self.extractor.suitable(url))

    def test_extract_vcast_source_success(self):
        """Verify extraction from page containing vcast player source."""
        mock_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Fella Pure Episode 1 - HentaiVietsub.com</title>
            <meta property="og:image" content="https://hentaivietsub.com/img/thumb.jpg" />
        </head>
        <body>
            <div id="player-wrapper"></div>
            <button class="set-player-source" data-source="https://vcast.name/videos/6698d6a274a38ba3960cf302/play">Server 1</button>
        </body>
        </html>
        """
        page_resp = MagicMock()
        page_resp.__enter__.return_value = page_resp
        page_resp.read.return_value = mock_html.encode("utf-8")
        page_resp.geturl.return_value = "https://hentaivietsub.com/hentai/fella-pure-1"
        page_resp.status = 200

        vcast_head_resp = MagicMock()
        vcast_head_resp.__enter__.return_value = vcast_head_resp
        vcast_head_resp.status = 200

        def fake_urlopen(req, *args, **kwargs):
            url_str = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
            if "hentaivietsub.com" in url_str:
                return page_resp
            if "vcast.name" in url_str:
                return vcast_head_resp
            raise URLError(f"Unknown mock URL: {url_str}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = self.extractor.extract("https://hentaivietsub.com/hentai/fella-pure-1")
            self.assertEqual(res.title, "Fella Pure Episode 1")
            self.assertEqual(res.thumbnail, "https://hentaivietsub.com/img/thumb.jpg")
            self.assertIn("127.0.0.1", res.stream_url)
            self.assertIn("playlist.m3u8", res.stream_url)
            self.assertIn("vcast.name", res.stream_url)

    def test_extract_embed_config_api_fallback(self):
        """Verify extraction when vcast is unavailable and embed page uses config API."""
        mock_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Sample Hentai - HentaiZ.bot</title>
            <meta property="og:image" content="https://hentaiz.bot/img/thumb.jpg" />
        </head>
        <body>
            <button class="set-player-source" data-source="https://e.streamforester.name/videos/6698d6a274a38ba3960cf302/play">Server 1</button>
        </body>
        </html>
        """
        page_resp = MagicMock()
        page_resp.__enter__.return_value = page_resp
        page_resp.read.return_value = mock_html.encode("utf-8")
        page_resp.geturl.return_value = "https://hentaiz.bot/hentai/sample"
        page_resp.status = 200

        embed_html = """
        <script>
        window.videoData = {"id":"6698d6a274a38ba3960cf302","domain":"hentaiz.bot"};
        </script>
        """
        embed_resp = MagicMock()
        embed_resp.__enter__.return_value = embed_resp
        embed_resp.read.return_value = embed_html.encode("utf-8")
        embed_resp.geturl.return_value = "https://wogplayer.top/videos/6698d6a274a38ba3960cf302/play"

        config_json = """
        {"sources":[{"label":"HLS","file":"https://wogplayer.top/videos/6698d6a274a38ba3960cf302/master.m3u8"}]}
        """
        config_resp = MagicMock()
        config_resp.__enter__.return_value = config_resp
        config_resp.read.return_value = config_json.encode("utf-8")
        config_resp.status = 200

        def fake_urlopen(req, *args, **kwargs):
            url_str = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
            if "hentaiz.bot" in url_str and "/videos/" not in url_str:
                return page_resp
            if "vcast.name" in url_str:
                raise URLError("vcast unavailable")
            if "streamforester.name" in url_str or "/play" in url_str:
                return embed_resp
            if "/config" in url_str:
                return config_resp
            raise URLError(f"Unknown mock URL: {url_str}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = self.extractor.extract("https://hentaiz.bot/hentai/sample")
            self.assertEqual(res.title, "Sample Hentai")
            self.assertEqual(res.thumbnail, "https://hentaiz.bot/img/thumb.jpg")
            self.assertIn("127.0.0.1", res.stream_url)
            self.assertIn("playlist.m3u8", res.stream_url)
            self.assertIn("wogplayer.top", res.stream_url)

    def test_extract_video_not_found(self):
        """When no video sources or IDs can be found, raises VideoNotFoundError."""
        mock_html = "<html><head><title>No Video</title></head><body>Empty page</body></html>"
        page_resp = MagicMock()
        page_resp.__enter__.return_value = page_resp
        page_resp.read.return_value = mock_html.encode("utf-8")
        page_resp.geturl.return_value = "https://hentaivietsub.com/hentai/empty"

        with patch("urllib.request.urlopen", return_value=page_resp):
            with self.assertRaises(VideoNotFoundError):
                self.extractor.extract("https://hentaivietsub.com/hentai/empty")


if __name__ == "__main__":
    unittest.main()
