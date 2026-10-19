"""
Unit tests for Universal Dynamic AJAX and Blogger Extractor.
Tests mechanism-driven abstractions:
1. Suitable heuristic keyword expansion (domain-agnostic)
2. Dynamic AJAX prober with placeholder attributes and endpoint detection
3. Multi-tier embed API resolution (/api/get-video?id=...)
4. Google Blogger c-wiz RPC array decoding (data-p="%.@....")
5. Transparent error handling in url_resolver dual fallback
"""

import html
import json
import unittest
from unittest.mock import MagicMock, patch

from main.extractors.base import VideoNotFoundError
from main.extractors.generic_web import GenericWebExtractor
from main.url_resolver import resolve_facebook_url


class TestDynamicAjaxAndBloggerExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = GenericWebExtractor()

    def test_suitable_expanded_domain_and_path_keywords(self):
        """Test suitable() correctly identifies video portals without hardcoded domain lists."""
        # Host keywords
        self.assertTrue(self.extractor.suitable("https://viet69.be/hai-chi-em-cuc-pham/"))
        self.assertTrue(self.extractor.suitable("https://phimmoi.net/xem-phim/tap-1"))
        self.assertTrue(self.extractor.suitable("https://javhd.porn/movie/12345"))
        self.assertTrue(self.extractor.suitable("https://cliphot.club/detail/item"))
        self.assertTrue(self.extractor.suitable("https://streamflix.vip/watch/abc"))

        # Path keywords
        self.assertTrue(self.extractor.suitable("https://example.org/post/amazing-video-stream"))
        self.assertTrue(self.extractor.suitable("https://example.org/archives/special-clip"))
        self.assertTrue(self.extractor.suitable("https://example.org/bai-viet/phim-hay"))

        # Non-video websites
        self.assertFalse(self.extractor.suitable("https://google.com/search?q=test"))
        self.assertFalse(self.extractor.suitable("https://github.com/torvalds/linux"))

    def test_extract_google_cwiz_stream_from_streaming_data(self):
        """Test decoding Google Blogger c-wiz RPC array with streamingData."""
        mock_formats = [
            {
                "itag": 18,
                "height": 360,
                "url": "https://rr1---sn-test.googlevideo.com/videoplayback?itag\\u003d18\\u0026expire\\u003d12345",
            },
            {
                "itag": 22,
                "height": 720,
                "url": "https://rr1---sn-test.googlevideo.com/videoplayback?itag\\u003d22\\u0026expire\\u003d12345",
            },
        ]
        sd_json = json.dumps({"streamingData": {"formats": mock_formats}})
        rpc_array = ["token123", None, False, None, "https://blogger.com/...", sd_json]
        raw_p = "%.@." + json.dumps(rpc_array)[1:]
        escaped_p = html.escape(raw_p)

        mock_html = f'<html><body><c-wiz data-p="{escaped_p}"></c-wiz></body></html>'

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            stream_url, referer = self.extractor._extract_google_cwiz_stream(
                "https://www.blogger.com/video.g?token=abc",
                referer="https://embed.test.com/",
            )

        self.assertIsNotNone(stream_url)
        # Verify 720p stream selected
        self.assertIn("itag=22", stream_url)
        # Verify unicode escapes are converted
        self.assertNotIn(r"\u003d", stream_url)
        self.assertNotIn(r"\u0026", stream_url)
        self.assertEqual(referer, "https://embed.test.com/")

    def test_extract_google_cwiz_stream_from_direct_link(self):
        """Test extraction when googlevideo link is embedded directly in HTML."""
        mock_html = (
            '<html><body>'
            '<c-wiz data-p="%.@.null,null"></c-wiz>'
            '<script>var url = "https://rr2---sn-abc.googlevideo.com/videoplayback?expire\\u003d999\\u0026id\\u003d1";</script>'
            '</body></html>'
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            stream_url, _ = self.extractor._extract_google_cwiz_stream(
                "https://www.blogger.com/video.g?token=xyz",
                referer="https://embed.test.com/",
            )

        self.assertIsNotNone(stream_url)
        self.assertIn("googlevideo.com/videoplayback", stream_url)
        self.assertIn("expire=999&id=1", stream_url)

    def test_probe_dynamic_ajax_player_with_placeholder(self):
        """Test probing dynamic AJAX player attributes and script endpoint."""
        html_page = """
        <html>
        <head><title>Test Movie Portal</title></head>
        <body>
            <div class="movieLoader" data-movie="MjhjODgzZTYtYWE4MS00YTZhLTg3OWYtYjUyOWM2N2I4MmZl" data-type="25"></div>
            <script>
                let urlVideo = "/get.video.php";
                function playCoverVideo() {
                    $.ajax({
                        url: urlVideo,
                        data: 'movie_id=' + movieId + '&type=' + type,
                    });
                }
            </script>
        </body>
        </html>
        """
        ajax_resp_html = '<iframe src="https://embed.example.org/embed/28c883e6-aa81-4a6a-879f-b529c67b82fe"></iframe>'

        # Mock AJAX response
        mock_ajax_resp = MagicMock()
        mock_ajax_resp.read.return_value = ajax_resp_html.encode("utf-8")
        mock_ajax_resp.__enter__.return_value = mock_ajax_resp

        # Mock embed resolver to simulate finding stream
        with patch("urllib.request.urlopen", return_value=mock_ajax_resp), \
             patch.object(self.extractor, "_resolve_single_embed", return_value=("https://cdn.example.org/stream.m3u8", "https://embed.example.org/")):
            stream_url, ref = self.extractor._probe_ajax_player(html_page, "https://testportal.com/movie-item/")

        self.assertEqual(stream_url, "https://cdn.example.org/stream.m3u8")
        self.assertEqual(ref, "https://embed.example.org/")

    def test_resolve_single_embed_with_api_and_blogger(self):
        """Test _resolve_single_embed querying /api/get-video and resolving Blogger stream."""
        embed_html = """
        <html>
        <head>
            <script>window.videoId = 'uuid-12345';</script>
            <script src="/assets/main-bundle.js"></script>
        </head>
        <body><div id="player"></div></body>
        </html>
        """
        api_json = json.dumps({"url": "https://www.blogger.com/video.g?token=tok123"})

        def mock_urlopen(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else req
            m = MagicMock()
            if "/api/get-video" in url:
                m.read.return_value = api_json.encode("utf-8")
            elif "embed" in url:
                m.read.return_value = embed_html.encode("utf-8")
                m.geturl.return_value = url
            m.__enter__.return_value = m
            return m

        with patch("urllib.request.urlopen", side_effect=mock_urlopen), \
             patch.object(self.extractor, "_extract_google_cwiz_stream", return_value=("https://rr.googlevideo.com/videoplayback?test", "https://embed.test/")):
            stream_url, ref = self.extractor._resolve_single_embed("https://embed.test/embed/uuid-12345", referer="https://portal.test/")

        self.assertEqual(stream_url, "https://rr.googlevideo.com/videoplayback?test")
        self.assertEqual(ref, "https://embed.test/")

    def test_url_resolver_transparent_error_message(self):
        """Test url_resolver does not mask GenericWebExtractor error with yt-dlp Unsupported URL."""
        from main.extractors.generic import GenericExtractor
        from main.extractors.generic_web import GenericWebExtractor as RealWebExtractor

        class FakeGenExtractor(GenericExtractor):
            def extract(self, *args, **kwargs):
                raise VideoNotFoundError("ERROR: Unsupported URL: https://custom-web.com/item")

        with patch("main.url_resolver.get_extractor", return_value=FakeGenExtractor()), \
             patch.object(RealWebExtractor, "extract", side_effect=VideoNotFoundError("Không tìm thấy luồng phát video cho liên kết web này.")):
            with self.assertRaises(VideoNotFoundError) as ctx:
                resolve_facebook_url("https://custom-web.com/item")

            err_msg = str(ctx.exception)
            self.assertIn("Không tìm thấy luồng phát video cho liên kết web này", err_msg)


if __name__ == "__main__":
    unittest.main()
