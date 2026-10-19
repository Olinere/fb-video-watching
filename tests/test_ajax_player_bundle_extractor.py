"""
Unit tests for domain-agnostic AJAX player bundle scanning and image placeholder rejection.
Verifies mechanism-driven handling across any website without hardcoded domains.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

from main.extractors.generic_web import (
    GenericWebExtractor,
    NON_MEDIA_EXTENSIONS,
    _is_valid_media_candidate,
)


class TestAjaxPlayerBundleExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = GenericWebExtractor()

    def test_is_valid_media_candidate_rejects_static_images_and_docs(self):
        # Should reject images
        self.assertFalse(_is_valid_media_candidate("https://example.com/logo.png"))
        self.assertFalse(_is_valid_media_candidate("https://example.com/uploads/photo.jpg?v=2&size=large"))
        self.assertFalse(_is_valid_media_candidate("https://example.com/image.webp#preview"))
        self.assertFalse(_is_valid_media_candidate("https://example.com/icon.svg"))
        self.assertFalse(_is_valid_media_candidate("https://example.com/avatar.ico"))
        # Should reject docs and code
        self.assertFalse(_is_valid_media_candidate("https://example.com/doc.pdf"))
        self.assertFalse(_is_valid_media_candidate("https://example.com/style.css"))
        self.assertFalse(_is_valid_media_candidate("https://example.com/app.js"))
        # Should accept true video/media streams
        self.assertTrue(_is_valid_media_candidate("https://example.com/videos/stream.m3u8"))
        self.assertTrue(_is_valid_media_candidate("https://example.com/videos/clip.mp4"))
        self.assertTrue(_is_valid_media_candidate("https://cdn.example.com/media/manifest.mpd?token=xyz"))
        self.assertTrue(_is_valid_media_candidate("https://example.com/stream.vl"))

    def test_hunt_player_configs_skips_schema_org_logo_image(self):
        # HTML containing both an Organization with logo.png and a genuine VideoObject
        html_page = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Organization",
                        "name": "Portal",
                        "logo": {
                            "@type": "ImageObject",
                            "contentUrl": "https://portal.com/uploads/logo-site.png"
                        }
                    },
                    {
                        "@type": "VideoObject",
                        "name": "Sample Video",
                        "contentUrl": "https://portal.com/hls/real_video.m3u8"
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        stream_url, ref = self.extractor._hunt_player_configs(html_page, "https://portal.com/watch/123/")
        self.assertEqual(stream_url, "https://portal.com/hls/real_video.m3u8")
        self.assertNotEqual(stream_url, "https://portal.com/uploads/logo-site.png")

    def test_probe_ajax_player_discovers_endpoint_in_external_bundle(self):
        html_page = """
        <html>
        <head>
            <script src="https://cdn.portal.com/js/jquery.min.js"></script>
            <script src="/assets/js/main.bundle.js?v=999"></script>
        </head>
        <body>
            <div class="movieLoader" data-video-id="456"></div>
            <button class="server-btn selected" data-server-id="1">Server 1</button>
        </body>
        </html>
        """
        js_bundle = """
        function initPlayer(vid, srv) {
            $.post(window.location.origin + "/api/player", { id: vid, server: srv }, function(res) {
                console.log(res);
            });
        }
        """
        api_json_resp = json.dumps({
            "status": "success",
            "data": {
                "type": "iframe",
                "source": "https://embed.playerhub.com/player/abc-123-uuid",
            }
        })
        embed_html = """
        <html>
        <script>
        window.PLAYER_CONFIG = {
            "source": "https://cdn.playerhub.com/videos/abc-123-uuid/master.m3u8"
        };
        </script>
        </html>
        """

        def mock_urlopen(req, *args, **kwargs):
            url_str = req.full_url if hasattr(req, "full_url") else str(req)
            resp = MagicMock()
            resp.__enter__.return_value = resp
            resp.status = 200

            if "main.bundle.js" in url_str:
                resp.read.return_value = js_bundle.encode("utf-8")
                resp.geturl.return_value = url_str
            elif "/api/player" in url_str:
                resp.read.return_value = api_json_resp.encode("utf-8")
                resp.geturl.return_value = url_str
            elif "/player/abc-123-uuid" in url_str:
                resp.read.return_value = embed_html.encode("utf-8")
                resp.geturl.return_value = url_str
            else:
                resp.read.return_value = b""
                resp.geturl.return_value = url_str
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            stream_url, ref = self.extractor._probe_ajax_player(html_page, "https://anyportal.club/view/456/")
            self.assertEqual(stream_url, "https://cdn.playerhub.com/videos/abc-123-uuid/master.m3u8")

    def test_probe_ajax_player_unwraps_nested_json_direct_stream(self):
        html_page = """
        <html>
        <body>
            <div data-video-id="789"></div>
            <script>
            $.ajax({
                url: "/ajax/get_source",
                type: "POST"
            });
            </script>
        </body>
        </html>
        """
        json_resp = json.dumps({
            "status": "ok",
            "data": {
                "video": "https://cdn.mediahost.net/vod/stream_789.m3u8"
            }
        })

        def mock_urlopen(req, *args, **kwargs):
            resp = MagicMock()
            resp.__enter__.return_value = resp
            resp.status = 200
            resp.read.return_value = json_resp.encode("utf-8")
            resp.geturl.return_value = req.full_url
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            stream_url, ref = self.extractor._probe_ajax_player(html_page, "https://cmsportal.net/watch/789")
            self.assertEqual(stream_url, "https://cdn.mediahost.net/vod/stream_789.m3u8")


if __name__ == "__main__":
    unittest.main()
