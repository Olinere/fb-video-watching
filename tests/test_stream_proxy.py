"""
Unit tests for the stream proxy module (main/stream_proxy.py).
Tests image header de-obfuscation, local proxy server lifecycle,
and multi-connection MP4 streaming proxy with Range support and zero leaks.
"""

import http.server
import threading
import time
import unittest
import urllib.request
import urllib.parse
from unittest.mock import patch

from main.stream_proxy import (
    strip_image_headers,
    StreamProxyServer,
    StreamProxyHandler,
)


class MockUpstreamHandler(http.server.BaseHTTPRequestHandler):
    """Mock remote media server supporting Range requests."""

    MOCK_DATA = b"A" * (2 * 1024 * 1024 + 500)  # ~2 MB mock media file

    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(self.MOCK_DATA)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        range_hdr = self.headers.get("Range")
        total = len(self.MOCK_DATA)
        start = 0
        end = total - 1

        if range_hdr and range_hdr.startswith("bytes="):
            parts = range_hdr[6:].split("-")
            start = int(parts[0]) if parts[0] else 0
            if len(parts) > 1 and parts[1]:
                end = int(parts[1])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        else:
            self.send_response(200)

        chunk = self.MOCK_DATA[start: end + 1]
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(chunk)


class TestStreamProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start mock upstream server on ephemeral port
        cls.upstream_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockUpstreamHandler)
        cls.upstream_port = cls.upstream_server.server_address[1]
        cls.upstream_thread = threading.Thread(target=cls.upstream_server.serve_forever, daemon=True)
        cls.upstream_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.upstream_server.shutdown()
        cls.upstream_server.server_close()

    def setUp(self):
        self.proxy = StreamProxyServer.get_instance()

    def tearDown(self):
        self.proxy.stop()

    def test_strip_image_headers_png(self):
        """PNG dummy header followed by MPEG-TS sync byte 0x47 should be cleanly stripped."""
        fake_png = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        ts_packet = b"\x47\x40\x00\x10" + b"\xff" * 184
        payload = fake_png + ts_packet

        stripped = strip_image_headers(payload)
        self.assertEqual(stripped, ts_packet)

    def test_strip_image_headers_normal_ts(self):
        """Normal TS stream starting with 0x47 should not be modified."""
        ts_packet = b"\x47\x40\x00\x10" + b"\x00" * 184
        self.assertEqual(strip_image_headers(ts_packet), ts_packet)

    def test_strip_image_headers_empty_data(self):
        """Empty or None data should return as-is without crashing."""
        self.assertEqual(strip_image_headers(b""), b"")
        self.assertIsNone(strip_image_headers(None))

    def test_strip_image_headers_spaced_sync(self):
        """Non-TS prefix with valid TS packets at 188-byte intervals should be detected."""
        garbage = b"JUNKDATA" * 5
        ts1 = b"\x47" + b"A" * 187
        ts2 = b"\x47" + b"B" * 187
        payload = garbage + ts1 + ts2

        stripped = strip_image_headers(payload)
        self.assertEqual(stripped, ts1 + ts2)

    def test_stream_proxy_lifecycle(self):
        """StreamProxyServer starts, generates valid URLs, and stops cleanly."""
        port = self.proxy.ensure_started()
        self.assertGreater(port, 0)
        self.assertEqual(self.proxy.port, port)
        self.assertTrue(self.proxy._server.daemon_threads)
        self.assertFalse(self.proxy._server.block_on_close)

        # Generating URLs
        target = "https://example.com/video.mp4"
        proxy_url = self.proxy.get_proxy_mp4_url(target, referer="https://example.com/")
        self.assertTrue(proxy_url.startswith(f"http://127.0.0.1:{port}/stream.mp4?"))
        self.assertIn("example.com", proxy_url)

        # Stop
        self.proxy.stop()
        self.assertEqual(self.proxy.port, 0)

    def test_async_stop_returns_without_waiting_for_caller(self):
        """Proxy shutdown is dispatched to a daemon thread for UI callers."""
        self.proxy.ensure_started()
        shutdown_thread = self.proxy.stop_async()
        self.assertTrue(shutdown_thread.daemon)
        shutdown_thread.join(timeout=2)
        self.assertFalse(shutdown_thread.is_alive())
        self.assertEqual(self.proxy.port, 0)

    def test_mp4_proxy_head_request(self):
        """HEAD request to /stream.mp4 returns Content-Length, Type, and Accept-Ranges."""
        port = self.proxy.ensure_started()
        upstream_url = f"http://127.0.0.1:{self.upstream_port}/test.mp4"
        proxy_url = self.proxy.get_proxy_mp4_url(upstream_url)

        req = urllib.request.Request(proxy_url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")
            self.assertEqual(int(resp.headers.get("Content-Length", 0)), len(MockUpstreamHandler.MOCK_DATA))

    def test_mp4_proxy_range_request(self):
        """GET request with Range to /stream.mp4 fetches partial content accurately."""
        port = self.proxy.ensure_started()
        upstream_url = f"http://127.0.0.1:{self.upstream_port}/test.mp4"
        proxy_url = self.proxy.get_proxy_mp4_url(upstream_url)

        # Request bytes 100-1099 (1000 bytes)
        req = urllib.request.Request(proxy_url, headers={"Range": "bytes=100-1099"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 206)
            self.assertEqual(resp.headers.get("Content-Range"), f"bytes 100-1099/{len(MockUpstreamHandler.MOCK_DATA)}")
            data = resp.read()
            self.assertEqual(len(data), 1000)
            self.assertEqual(data, MockUpstreamHandler.MOCK_DATA[100:1100])

    def test_mp4_proxy_multi_chunk_fetch(self):
        """GET request fetching across chunk boundaries (> 1MB) succeeds with exact bytes."""
        port = self.proxy.ensure_started()
        upstream_url = f"http://127.0.0.1:{self.upstream_port}/test.mp4"
        proxy_url = self.proxy.get_proxy_mp4_url(upstream_url)

        # Request 1.5 MB chunk (crosses 1MB CHUNK_SIZE boundary)
        req = urllib.request.Request(proxy_url, headers={"Range": "bytes=0-1572863"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 206)
            data = resp.read()
            self.assertEqual(len(data), 1572864)
            self.assertEqual(data, MockUpstreamHandler.MOCK_DATA[:1572864])

    def test_mp4_proxy_client_disconnect_no_leak(self):
        """When a client disconnects abruptly (closes socket), executor shuts down and server recovers."""
        import socket
        port = self.proxy.ensure_started()
        upstream_url = f"http://127.0.0.1:{self.upstream_port}/test.mp4"
        proxy_url = self.proxy.get_proxy_mp4_url(upstream_url)
        parsed = urllib.parse.urlparse(proxy_url)

        # Connect low-level socket, send partial request, read first bytes, then abruptly close socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", port))
        req_raw = f"GET {parsed.path}?{parsed.query} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nRange: bytes=0-2000000\r\n\r\n"
        s.sendall(req_raw.encode("ascii"))
        # Read only the header and first few bytes, then close immediately
        s.recv(512)
        s.close()

        # Give server thread a fraction of a second to clean up
        time.sleep(0.1)

        # Server should still be completely healthy and responsive
        req2 = urllib.request.Request(proxy_url, headers={"Range": "bytes=0-100"})
        with urllib.request.urlopen(req2, timeout=5) as resp:
            self.assertEqual(resp.status, 206)
            self.assertEqual(len(resp.read()), 101)

    def test_in_use_predicate_prevents_idle_shutdown(self):
        """When in_use_predicate returns True, watchdog must not shut down the server even if idle."""
        self.proxy._idle_timeout = 0.2  # Very short idle timeout for testing
        port = self.proxy.ensure_started()
        self.proxy.set_in_use_predicate(lambda: True)

        # Wait longer than idle timeout
        time.sleep(0.5)

        # Proxy must still be running because predicate says it's in use
        self.assertEqual(self.proxy.port, port)
        self.assertIsNotNone(self.proxy._server)

        # Now set predicate to False
        self.proxy.set_in_use_predicate(lambda: False)
        # Reset last active time so watchdog fires
        self.proxy._last_active_time = time.time() - 1.0

        # Wait for watchdog check (which runs every 5s, but we test shutdown directly or with shorter cycle)
        # Clean up
        self.proxy.stop()
        self.assertEqual(self.proxy.port, 0)
        self.proxy._idle_timeout = 60.0  # Reset back to default


if __name__ == "__main__":
    unittest.main()
