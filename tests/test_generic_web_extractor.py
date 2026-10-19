"""
Unit tests for GenericWebExtractor (Layer 4 Mechanism-Based Engine).
Tests player config hunting, cyberlocker embeds, unpacker, and fallback mechanisms.
"""

import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from main.extractors import (
    get_extractor,
    GenericWebExtractor,
    VideoNotFoundError,
    unpack_packer,
)
from main.url_resolver import is_potential_video_url


class TestGenericWebExtractor(unittest.TestCase):
    """Test suite for GenericWebExtractor."""

    def setUp(self):
        self.extractor = GenericWebExtractor()

    def test_suitable_matching_various_web_video_portals(self):
        """Must match various anime, movie, cyberlocker, and adult web video URLs."""
        positive_urls = [
            "https://hentaivietsub.com/hentai/fella-pure-mitarashi-san-chi-no-jijou-the-animation-1",
            "https://hentaiz.bot/hentai/fella-pure-mitarashi-san-chi-no-jijou-the-animation-1",
            "https://hentaivietsub.net/hentai/sample-video-1",
            "https://hentaiz.tv/hentai/sample-video-1",
            "https://vlxx.phd/video/clip-hay/123/",
            "https://vlxx.sex/video/test/456/",
            "https://sexvietnew.world/video/123/",
            "https://xnhau.cab/video/123/test/",
            "https://animehay.tv/phim/one-piece-tap-1",
            "https://motchill.tv/movie/batman-2022",
            "https://doodstream.com/e/abc12345",
            "https://streamtape.com/v/xyz98765",
            "https://sub.hentaivietsub.vip/hentai/video-slug",
            "https://aki-h.com/videos/rFca0M4ycF/",
            "https://phimmoi.net/film/avatar-2",
        ]
        for url in positive_urls:
            with self.subTest(url=url):
                self.assertTrue(self.extractor.suitable(url), f"Should match {url}")
                self.assertTrue(is_potential_video_url(url), f"Should be potential video {url}")
                ext = get_extractor(url)
                self.assertIsInstance(ext, GenericWebExtractor, f"get_extractor must return GenericWebExtractor for {url}")

    def test_suitable_negative_cases(self):
        """Must NOT match YouTube, Facebook, TikTok, direct manifests, or non-video sites."""
        negative_urls = [
            "https://www.youtube.com/watch?v=12345",
            "https://youtu.be/12345",
            "https://facebook.com/reel/123",
            "https://www.tiktok.com/@user/video/123",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://twitter.com/user/status/123",
            "https://example.com/live/stream.m3u8",
            "https://google.com/",
            "https://github.com/",
            "",
            None,
        ]
        for url in negative_urls:
            with self.subTest(url=url):
                self.assertFalse(self.extractor.suitable(url))

    def test_unpack_packer(self):
        """Test Dean Edwards packer unpacker decoder."""
        # Simple packed javascript: var x = 'https://cdn.example.com/master.m3u8';
        packed = (
            "eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}"
            "('0 1 = \\'2\\';',3,3,'var|x|https://cdn.example.com/master.m3u8'.split('|')))"
        )
        unpacked = unpack_packer(packed)
        self.assertIsNotNone(unpacked)
        self.assertIn("https://cdn.example.com/master.m3u8", unpacked)
        self.assertIn("var x =", unpacked)

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

    def test_extract_window_src_and_streamproxy(self):
        """Verify extraction from page or embed with window.__SRC (VLXX style)."""
        mock_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Sample VLXX Clip - VLXX.phd</title>
            <meta property="og:image" content="https://vlxx.phd/thumb.jpg" />
        </head>
        <body>
            <script>
            window.__SRC = [{"file": "https://byteoversea.com/media/stream.vl"}];
            </script>
        </body>
        </html>
        """
        page_resp = MagicMock()
        page_resp.__enter__.return_value = page_resp
        page_resp.read.return_value = mock_html.encode("utf-8")
        page_resp.geturl.return_value = "https://vlxx.phd/video/test-123"
        page_resp.status = 200

        with patch("urllib.request.urlopen", return_value=page_resp):
            res = self.extractor.extract("https://vlxx.phd/video/test-123")
            self.assertEqual(res.title, "Sample VLXX Clip")
            self.assertEqual(res.thumbnail, "https://vlxx.phd/thumb.jpg")
            # Should be routed through local StreamProxyServer because of .vl and byteoversea
            self.assertIn("127.0.0.1", res.stream_url)
            self.assertIn("playlist.m3u8", res.stream_url)
            self.assertIn("byteoversea.com", res.stream_url)

    def test_extract_flashvars_kvs(self):
        """Verify extraction from KVS player flashvars (xNhau style)."""
        mock_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Sample xNhau Clip - xNhau.cab</title>
            <meta property="og:image" content="https://xnhau.cab/preview.jpg" />
        </head>
        <body>
            <script>
            var flashvars = {
                video_url: 'https://xnhau.cab/get_file/1/video_720p.mp4',
                video_alt_url: 'https://xnhau.cab/get_file/1/video_1080p.mp4'
            };
            </script>
        </body>
        </html>
        """
        page_resp = MagicMock()
        page_resp.__enter__.return_value = page_resp
        page_resp.read.return_value = mock_html.encode("utf-8")
        page_resp.geturl.return_value = "https://xnhau.cab/video/123/sample"
        page_resp.status = 200

        with patch("urllib.request.urlopen", return_value=page_resp):
            res = self.extractor.extract("https://xnhau.cab/video/123/sample")
            self.assertEqual(res.title, "Sample xNhau Clip")
            self.assertEqual(res.thumbnail, "https://xnhau.cab/preview.jpg")
            self.assertIn("video_1080p.mp4", res.stream_url)

    def test_extract_itemprop_contenturl(self):
        """Verify extraction from Schema.org itemprop contentUrl (SexVietNew style)."""
        mock_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Sample SexVietNew Clip - SexVietNew.world</title>
            <meta property="og:image" content="https://sexvietnew.world/thumb.jpg" />
        </head>
        <body>
            <meta itemprop="contentUrl" content="https://cdn.sexvietnew.world/hls/master.m3u8" />
        </body>
        </html>
        """
        page_resp = MagicMock()
        page_resp.__enter__.return_value = page_resp
        page_resp.read.return_value = mock_html.encode("utf-8")
        page_resp.geturl.return_value = "https://sexvietnew.world/video/123/"
        page_resp.status = 200

        with patch("urllib.request.urlopen", return_value=page_resp):
            res = self.extractor.extract("https://sexvietnew.world/video/123/")
            self.assertEqual(res.title, "Sample SexVietNew Clip")
            self.assertIn("cdn.sexvietnew.world", res.stream_url)
            self.assertIn("master.m3u8", res.stream_url)

    def test_extract_video_not_found(self):
        """When no video sources or IDs can be found, raises VideoNotFoundError."""
        mock_html = "<html><head><title>No Video</title></head><body>Empty page</body></html>"
        page_resp = MagicMock()
        page_resp.__enter__.return_value = page_resp
        page_resp.read.return_value = mock_html.encode("utf-8")
        page_resp.geturl.return_value = "https://example.com/video/empty"

        with patch("urllib.request.urlopen", return_value=page_resp):
            with self.assertRaises(VideoNotFoundError):
                self.extractor.extract("https://example.com/video/empty")


if __name__ == "__main__":
    unittest.main()
