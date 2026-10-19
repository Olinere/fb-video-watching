"""
Unit tests for Universal Web Video Extractor Deep Enhancements:
- Multi-layer script deobfuscator (Packer -> Base64 concatenation -> Nested Packer -> JWPlayer)
- Iterative BFS Crawler for deep iframe/embed hierarchies (3 to 5 levels)
- Bidirectional Dual-Fallback orchestration in url_resolver.py
- Memory cleanup and bounded deadline timeout budgets
"""

import base64
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from main.extractors.generic_web import (
    GenericWebExtractor,
    unpack_packer,
    deobfuscate_script_deep,
)
from main.extractors import (
    get_extractor,
    GenericExtractor,
    ResolvedVideo,
    ResolverError,
    URLValidationError,
    VideoNotFoundError,
)
from main.url_resolver import resolve_facebook_url, is_potential_video_url


class TestUniversalWebDeepExtractor(unittest.TestCase):
    """Test suite for deep extraction mechanisms and dual-fallback."""

    def setUp(self):
        self.extractor = GenericWebExtractor()

    def test_single_layer_packer(self):
        """Test unpack_packer on standard Dean Edwards packer."""
        packed = (
            "eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}"
            "('0 1 = \\'2\\';',3,3,'var|x|https://cdn.example.com/master.m3u8'.split('|')))"
        )
        res = deobfuscate_script_deep(packed)
        self.assertTrue(len(res) > 0)
        self.assertIn("https://cdn.example.com/master.m3u8", res[0])

    def test_base64_concatenation_cookie_run(self):
        """Test deobfuscation of Cookie.Run Base64 chunked concatenation."""
        raw_target = "jwplayer('player').setup({ file: 'https://cdn.stream.com/hls/live.m3u8' });"
        encoded = base64.b64encode(raw_target.encode("utf-8")).decode("utf-8")
        mid = len(encoded) // 2
        chunk1 = encoded[:mid]
        chunk2 = encoded[mid:]

        obfuscated = f'Cookie.Run("{chunk1}" + "{chunk2}");'
        res = deobfuscate_script_deep(obfuscated)
        self.assertTrue(any("https://cdn.stream.com/hls/live.m3u8" in s for s in res))

    def test_nested_three_layer_obfuscation(self):
        """
        Test 3-layer nested obfuscation:
        Layer 1: Dean Edwards Packer ->
        Layer 2: Base64 concatenation in Cookie.Run ->
        Layer 3: Nested Dean Edwards Packer -> JWPlayer source.
        """
        inner_js = "var player = jwplayer('video').setup({ sources: [{ file: 'https://aki-h.stream/file/12345/index.m3u8' }] });"
        # Pack inner_js with Dean Edwards
        inner_packed = (
            "eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}"
            f"('0 1 = \\'2\\';',3,3,'var|media|{inner_js}'.split('|')))"
        )

        # Wrap into Base64 chunks
        b64_inner = base64.b64encode(inner_packed.encode("utf-8")).decode("utf-8")
        p1 = b64_inner[:30]
        p2 = b64_inner[30:]
        cookie_run_code = f'Cookie.Run("{p1}" + "{p2}");'

        # Outer Dean Edwards Packer
        outer_packed = (
            "eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}"
            f"('0 1 = \\'2\\';',3,3,'var|stub|{cookie_run_code}'.split('|')))"
        )

        res = deobfuscate_script_deep(outer_packed, max_layers=3)
        self.assertTrue(any("https://aki-h.stream/file/12345/index.m3u8" in s for s in res))

    def test_extract_embed_candidates(self):
        """Test extracting and prioritizing candidate embed URLs while ignoring ads."""
        html = """
        <html>
            <iframe src="https://ads.doubleclick.net/ad/123"></iframe>
            <iframe src="https://v.aki-h.com/v/39550"></iframe>
            <div data-source="https://streaming.aki.today/playback/v/123"></div>
            <script>
                var url = web_uri + "video2/" + v + "/";
            </script>
            <a id="play" href="/f/rFca0M4ycF">Play</a>
        </html>
        """
        cands = self.extractor._extract_embed_candidates(html, "https://aki-h.com/videos/rFca0M4ycF/")
        self.assertNotIn("doubleclick", "".join(cands))
        self.assertTrue(any("v.aki-h.com" in c for c in cands))
        self.assertTrue(any("streaming.aki.today" in c for c in cands))
        self.assertTrue(any("/video2/" in c for c in cands))
        self.assertTrue(any("/f/rFca0M4ycF" in c for c in cands))

    def test_bidirectional_dual_fallback_yt_dlp_to_generic_web(self):
        """When GenericExtractor (yt-dlp) raises Unsupported URL, url_resolver falls back to GenericWebExtractor."""
        dummy_url = "https://custom-portal.org/videos/abc123"

        with patch("main.url_resolver.get_extractor") as mock_get_ext, \
             patch.object(GenericWebExtractor, "extract") as mock_web_extract:

            mock_generic_ext = MagicMock(spec=GenericExtractor)
            mock_generic_ext.extract.side_effect = URLValidationError("Unsupported URL")
            mock_get_ext.return_value = mock_generic_ext

            mock_resolved = ResolvedVideo(
                stream_url="https://cdn.custom-portal.org/master.m3u8",
                title="Custom Video",
                duration=None,
                thumbnail=None,
                is_live=False,
            )
            mock_web_extract.return_value = mock_resolved

            result = resolve_facebook_url(dummy_url)
            self.assertEqual(result.stream_url, "https://cdn.custom-portal.org/master.m3u8")
            mock_web_extract.assert_called_once()

    def test_bidirectional_dual_fallback_generic_web_to_yt_dlp(self):
        """When GenericWebExtractor raises VideoNotFoundError, url_resolver falls back to GenericExtractor."""
        dummy_url = "https://custom-site.com/videos/test"

        with patch("main.url_resolver.get_extractor") as mock_get_ext, \
             patch.object(GenericExtractor, "extract") as mock_gen_extract:

            mock_web_ext = MagicMock(spec=GenericWebExtractor)
            mock_web_ext.extract.side_effect = VideoNotFoundError("No stream found")
            mock_get_ext.return_value = mock_web_ext

            mock_resolved = ResolvedVideo(
                stream_url="https://youtube.com/stream.m3u8",
                title="YT Video",
                duration=None,
                thumbnail=None,
                is_live=False,
            )
            mock_gen_extract.return_value = mock_resolved

            result = resolve_facebook_url(dummy_url)
            self.assertEqual(result.stream_url, "https://youtube.com/stream.m3u8")
            mock_gen_extract.assert_called_once()

    def test_universal_domain_and_subdomain_suitable(self):
        """GenericWebExtractor is suitable for arbitrary domains/sub-domains with video signals, and rejects non-media sites."""
        # Arbitrary domains with media paths/queries
        self.assertTrue(GenericWebExtractor.suitable("https://arbitrary-site.xyz/watch/ep123"))
        self.assertTrue(GenericWebExtractor.suitable("https://stream.new-portal.org/item/456"))
        self.assertTrue(GenericWebExtractor.suitable("https://sub.anime-club.cc/movie/details"))
        self.assertTrue(GenericWebExtractor.suitable("https://custom-service.io/play/sample"))

        # Non-media web portals without video indicators
        self.assertFalse(GenericWebExtractor.suitable("https://google.com/search?q=test"))
        self.assertFalse(GenericWebExtractor.suitable("https://github.com/torvalds/linux"))

    def test_route_proxy_if_needed_domain_agnostic(self):
        """StreamProxy routing operates purely on media type and cross-origin referer without domain whitelists."""
        # Cross-origin HLS stream with referer
        stream = "https://cdn.unknown-host.net/playlist/master.m3u8"
        referer = "https://my-portal.org/watch/1"
        proxied = self.extractor._route_proxy_if_needed(stream, referer)
        self.assertTrue(proxied.startswith("http://127.0.0.1:"))
        self.assertIn("playlist.m3u8", proxied)
        self.assertIn("referer=https%3A%2F%2Fmy-portal.org", proxied)

        # Cross-origin protected MP4 with referer
        mp4_stream = "https://cdn.video-host.com/files/video.mp4"
        mp4_proxied = self.extractor._route_proxy_if_needed(mp4_stream, referer)
        self.assertTrue(mp4_proxied.startswith("http://127.0.0.1:"))
        self.assertIn("/stream.mp4", mp4_proxied)


if __name__ == "__main__":
    unittest.main()
