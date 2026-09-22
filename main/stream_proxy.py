"""
Stream proxy module for FB Video Watcher.
Provides a local, low-footprint HTTP streaming proxy on localhost (127.0.0.1)
to handle media streams that require custom headers, referers, or on-the-fly
de-obfuscation (such as VLXX / ByteDance image-CDN TS chunks prepended with dummy PNG headers).
"""

import concurrent.futures
import http.server
import logging
import ssl
import socket
import sys
import threading
import time
from typing import Optional, Dict
import urllib.parse
import urllib.request

logger = logging.getLogger("FBVideoWatcher.StreamProxy")

# Create SSL context that allows unverified certs if CDNs use self-signed / expired certs
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


class _NonBlockingThreadingHTTPServer(http.server.ThreadingHTTPServer):
    """Threaded HTTP server that never waits for media request threads on close."""

    daemon_threads = True
    block_on_close = False


def strip_image_headers(data: bytes) -> bytes:
    """
    Detect and strip fake image headers (PNG, JPEG, GIF, WebP) prepended to MPEG-TS chunks.
    Some adult streaming sites (VLXX, SexViet, etc.) prepend a 95-byte dummy PNG image
    to every video segment to evade CDN filters and store segments on image CDNs.
    """
    if not data:
        return data

    # 1. Standard PNG prefix check
    if data.startswith(b"\x89PNG"):
        iend_pos = data.find(b"IEND")
        if iend_pos != -1:
            # IEND chunk is 4 bytes + 4 bytes CRC = 8 bytes
            candidate = data[iend_pos + 8:]
            if candidate and candidate[0] == 0x47:
                return candidate
            # Fallback: search for first 0x47 after IEND
            sync = candidate.find(b"\x47")
            if sync != -1:
                return candidate[sync:]

    # 2. General fallback for any prepended non-TS header (PNG, JPEG, GIF, WebP, etc.)
    # If the file does not start with TS sync byte (0x47)
    if data[0] != 0x47:
        sync_pos = data.find(b"\x47")
        if sync_pos != -1 and sync_pos < 4096:
            # Verify if this 0x47 is followed by another 0x47 at 188 bytes interval
            if (sync_pos + 188 < len(data) and data[sync_pos + 188] == 0x47) or (
                sync_pos + 376 < len(data) and data[sync_pos + 376] == 0x47
            ):
                return data[sync_pos:]

    return data


class StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    """Handles local proxy requests from VLC for m3u8 playlists and ts segments."""

    def setup(self):
        """Register the client socket so shutdown can interrupt active streams."""
        super().setup()
        StreamProxyServer.get_instance().register_connection(self.connection)

    def finish(self):
        """Unregister the client socket after the request handler exits."""
        try:
            StreamProxyServer.get_instance().unregister_connection(self.connection)
        finally:
            super().finish()

    def log_message(self, format, *args):
        # Suppress noisy console log messages
        pass

    def do_HEAD(self):
        StreamProxyServer.get_instance().mark_active()
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path.endswith("telegram/stream"):
            channel = qs.get("channel", [None])[0]
            msg_str = qs.get("msg", [None])[0]
            if not channel or not msg_str:
                self.send_error(400, "Missing channel or msg parameter")
                return
            acc_str = qs.get("acc", [None])[0]
            account_idx = int(acc_str) if acc_str and acc_str.isdigit() else None
            self._handle_telegram_stream(channel, int(msg_str), head_only=True, account_idx=account_idx)
            return

        target_url = qs.get("url", [None])[0]
        referer = qs.get("referer", [None])[0]

        if not target_url:
            self.send_error(400, "Missing target url parameter")
            return

        if parsed.path.endswith("stream.mp4"):
            self._handle_mp4_stream(target_url, referer, head_only=True)
        else:
            self.send_error(405, "Method not allowed")

    def do_GET(self):
        StreamProxyServer.get_instance().mark_active()
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path.endswith("telegram/stream"):
            channel = qs.get("channel", [None])[0]
            msg_str = qs.get("msg", [None])[0]
            if not channel or not msg_str:
                self.send_error(400, "Missing channel or msg parameter")
                return
            acc_str = qs.get("acc", [None])[0]
            account_idx = int(acc_str) if acc_str and acc_str.isdigit() else None
            self._handle_telegram_stream(channel, int(msg_str), head_only=False, account_idx=account_idx)
            return

        target_url = qs.get("url", [None])[0]
        referer = qs.get("referer", [None])[0]

        if not target_url:
            self.send_error(400, "Missing target url parameter")
            return

        if parsed.path.endswith("playlist.m3u8"):
            self._handle_playlist(target_url, referer)
        elif parsed.path.endswith("segment.ts"):
            self._handle_segment(target_url, referer)
        elif parsed.path.endswith("stream.mp4"):
            self._handle_mp4_stream(target_url, referer, head_only=False)
        else:
            self.send_error(404, "Endpoint not found")

    def _handle_playlist(self, target_url: str, referer: Optional[str]):
        """Fetch remote m3u8/vl playlist, rewrite segment URLs to point to local proxy, and serve to VLC."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            if referer:
                headers["Referer"] = referer

            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=10) as resp:
                raw_content = resp.read().decode("utf-8", errors="ignore")

            server_host = self.headers.get("Host", "127.0.0.1")
            out_lines = []
            parsed_target = urllib.parse.urlparse(target_url)
            base_url = f"{parsed_target.scheme}://{parsed_target.netloc}{parsed_target.path.rsplit('/', 1)[0]}/"

            for line in raw_content.splitlines():
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    out_lines.append(line_str)
                    continue

                # Segment URI
                if line_str.startswith("http://") or line_str.startswith("https://"):
                    full_seg_url = line_str
                else:
                    full_seg_url = urllib.parse.urljoin(base_url, line_str)

                # Rewrite segment to route through local proxy
                query_dict = {"url": full_seg_url}
                if referer:
                    query_dict["referer"] = referer
                proxied_seg = f"http://{server_host}/segment.ts?{urllib.parse.urlencode(query_dict)}"
                out_lines.append(proxied_seg)

            body = "\n".join(out_lines).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            try:
                self.send_error(500, f"Error processing playlist: {e}")
            except Exception:
                pass

    def _handle_segment(self, target_url: str, referer: Optional[str]):
        """Fetch remote segment, strip any fake image header, and stream to VLC."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            if referer:
                headers["Referer"] = referer

            # Forward Range header if present
            range_hdr = self.headers.get("Range")
            if range_hdr:
                headers["Range"] = range_hdr

            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=15) as resp:
                data = resp.read()

            # De-obfuscate by stripping fake PNG / image headers
            clean_data = strip_image_headers(data)

            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Content-Length", str(len(clean_data)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(clean_data)
        except Exception as e:
            try:
                self.send_error(500, f"Error fetching segment: {e}")
            except Exception:
                pass

    def _handle_mp4_stream(self, target_url: str, referer: Optional[str], head_only: bool = False):
        """
        Multi-connection sliding-window streaming proxy for remote MP4 files.
        Overcomes CDN per-connection rate-limiting (such as Pornhub's rate=500k)
        by fetching 1MB chunks in parallel using Range requests while maintaining
        a strictly bounded memory footprint (max 4 MB sliding window).
        Zero resource leakage: automatically cancels workers and frees memory when client seeks or disconnects.
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if referer:
            headers["Referer"] = referer

        # Probe remote Content-Length and Range capability
        try:
            probe_req = urllib.request.Request(target_url, headers={**headers, "Range": "bytes=0-1"})
            with urllib.request.urlopen(probe_req, context=_SSL_CTX, timeout=10) as r_probe:
                cr = r_probe.headers.get("Content-Range")
                if cr and "/" in cr:
                    total_len = int(cr.split("/")[-1])
                else:
                    total_len = int(r_probe.headers.get("Content-Length", 0))
                content_type = r_probe.headers.get("Content-Type", "video/mp4")
        except Exception as e:
            try:
                self.send_error(502, f"Bad gateway: {e}")
            except Exception:
                pass
            return

        range_hdr = self.headers.get("Range")
        req_start = 0
        req_end = total_len - 1 if total_len > 0 else 0
        is_partial = False

        if range_hdr and range_hdr.startswith("bytes="):
            parts = range_hdr[6:].split("-")
            req_start = int(parts[0]) if parts[0] else 0
            if len(parts) > 1 and parts[1]:
                req_end = int(parts[1])
            is_partial = True

        try:
            self.send_response(206 if is_partial else 200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            if is_partial and total_len > 0:
                self.send_header("Content-Range", f"bytes {req_start}-{req_end}/{total_len}")
            self.send_header("Content-Length", str(req_end - req_start + 1))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
        except Exception:
            return

        if head_only:
            return

        CHUNK_SIZE = 1 * 1024 * 1024  # 1 MB chunk
        MAX_PREFETCH = 4  # Maximum 4 MB in flight in memory

        def fetch_chunk(start_b: int, end_b: int) -> bytes:
            req_c = urllib.request.Request(target_url, headers={**headers, "Range": f"bytes={start_b}-{end_b}"})
            with urllib.request.urlopen(req_c, context=_SSL_CTX, timeout=12) as res:
                return res.read()

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        curr_offset = req_start
        active_futures = {}

        try:
            while curr_offset <= req_end:
                sched_offset = curr_offset
                while len(active_futures) < MAX_PREFETCH and sched_offset <= req_end:
                    if sched_offset not in active_futures:
                        c_end = min(req_end, sched_offset + CHUNK_SIZE - 1)
                        active_futures[sched_offset] = executor.submit(fetch_chunk, sched_offset, c_end)
                    sched_offset += CHUNK_SIZE

                fut = active_futures.pop(curr_offset, None)
                if not fut:
                    break
                chunk_data = fut.result()
                if not chunk_data:
                    break
                self.wfile.write(chunk_data)
                curr_offset += len(chunk_data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            logger.debug("Error in MP4 stream proxy: %s", exc)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            active_futures.clear()

    def _handle_telegram_stream(self, channel: str, msg_id: int, head_only: bool = False, account_idx: Optional[int] = None):
        """
        Handle streaming of Telegram video chunks via TelegramManager.
        Supports Range requests (206 Partial Content) and pre-buffered multi-chunk streaming.
        account_idx: if provided, use that specific account index; otherwise multi-account fallback.
        """
        from main.telegram_manager import TelegramManager

        tg_mgr = TelegramManager.get_instance()

        # Resolve which account to use
        account = None
        if account_idx is not None:
            accounts = tg_mgr.get_accounts()
            if 0 <= account_idx < len(accounts):
                account = accounts[account_idx]

        try:
            info = tg_mgr.get_media_info(channel, msg_id, account=account)
        except Exception as e:
            try:
                self.send_error(502, f"Bad gateway resolving Telegram media: {e}")
            except Exception:
                pass
            return

        total_len = info.get("file_size", 0)
        mime_type = info.get("mime_type", "video/mp4")
        # Use the account returned from get_media_info (which tracks which succeeded)
        if account is None:
            account = info.get("account")

        range_hdr = self.headers.get("Range")
        req_start = 0
        req_end = total_len - 1 if total_len > 0 else 0
        is_partial = False

        if range_hdr and range_hdr.startswith("bytes="):
            parts = range_hdr[6:].split("-")
            req_start = int(parts[0]) if parts[0] else 0
            if len(parts) > 1 and parts[1]:
                req_end = int(parts[1])
            is_partial = True

        try:
            self.send_response(206 if is_partial else 200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Accept-Ranges", "bytes")
            if is_partial and total_len > 0:
                self.send_header("Content-Range", f"bytes {req_start}-{req_end}/{total_len}")
            self.send_header("Content-Length", str(req_end - req_start + 1))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
        except Exception:
            return

        if head_only:
            return

        try:
            for chunk in tg_mgr.stream_media_range(channel, msg_id, req_start, req_end, account=account):
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            logger.debug("Error in Telegram stream proxy: %s", exc)


class StreamProxyServer:
    """Singleton local HTTP streaming server on 127.0.0.1 with idle auto-shutdown."""

    _instance: Optional["StreamProxyServer"] = None
    _lock = threading.Lock()

    def __init__(self, idle_timeout: float = 60.0):
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._watchdog: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self.port: int = 0
        self._idle_timeout: float = idle_timeout
        self._last_active_time: float = 0.0
        self._in_use_predicate = None
        self._connections_lock = threading.Lock()
        self._active_connections = set()

    def register_connection(self, connection: socket.socket) -> None:
        """Track a client connection so a proxy shutdown can interrupt streaming."""
        with self._connections_lock:
            self._active_connections.add(connection)

    def unregister_connection(self, connection: socket.socket) -> None:
        """Forget a client connection after its request handler has finished."""
        with self._connections_lock:
            self._active_connections.discard(connection)

    def _close_active_connections(self) -> None:
        """Interrupt handlers that are blocked on a VLC/Telegram stream."""
        with self._connections_lock:
            connections = list(self._active_connections)
            self._active_connections.clear()

        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass
            try:
                connection.close()
            except (OSError, ValueError):
                pass

    @classmethod
    def get_instance(cls) -> "StreamProxyServer":
        with cls._lock:
            if cls._instance is None:
                cls._instance = StreamProxyServer()
            return cls._instance

    def set_in_use_predicate(self, predicate) -> None:
        """Register a callback returning bool indicating whether player is still actively playing or paused."""
        with self._lock:
            self._in_use_predicate = predicate

    def mark_active(self) -> None:
        """Update last active timestamp whenever a request is served."""
        self._last_active_time = time.time()

    def _idle_watchdog_loop(self) -> None:
        """Periodic watchdog that automatically shuts down the server when inactive for idle_timeout seconds."""
        while not self._shutdown_event.wait(5.0):
            with self._lock:
                if self._server is None:
                    break
                try:
                    if self._in_use_predicate and self._in_use_predicate():
                        self._last_active_time = time.time()
                        continue
                except Exception:
                    pass

                idle_sec = time.time() - self._last_active_time
                if idle_sec >= self._idle_timeout:
                    logger.info("StreamProxy idle for %.1fs (timeout=%.1fs). Auto-shutting down...", idle_sec, self._idle_timeout)
                    # Run stop in separate thread to avoid deadlock with watchdog
                    threading.Thread(target=self.stop, daemon=True).start()
                    break

    def ensure_started(self) -> int:
        """Start proxy server on 127.0.0.1 with random available port if not already running."""
        with self._lock:
            self._last_active_time = time.time()
            if self._server is not None and self.port > 0:
                return self.port

            self._shutdown_event.clear()
            # Port 0 lets the OS automatically choose an available ephemeral port.
            self._server = _NonBlockingThreadingHTTPServer(("127.0.0.1", 0), StreamProxyHandler)
            self.port = self._server.server_address[1]
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()

            self._watchdog = threading.Thread(target=self._idle_watchdog_loop, daemon=True)
            self._watchdog.start()

            logger.info("StreamProxy running on 127.0.0.1:%d (idle_timeout=%.0fs)", self.port, self._idle_timeout)
            return self.port

    def get_proxy_playlist_url(self, target_url: str, referer: Optional[str] = None) -> str:
        """Return local proxy URL for the given remote playlist."""
        port = self.ensure_started()
        query = {"url": target_url}
        if referer:
            query["referer"] = referer
        return f"http://127.0.0.1:{port}/playlist.m3u8?{urllib.parse.urlencode(query)}"

    def get_proxy_mp4_url(self, target_url: str, referer: Optional[str] = None) -> str:
        """Return local proxy URL for remote MP4 stream with multi-connection acceleration."""
        port = self.ensure_started()
        query = {"url": target_url}
        if referer:
            query["referer"] = referer
        return f"http://127.0.0.1:{port}/stream.mp4?{urllib.parse.urlencode(query)}"

    def stop(self) -> None:
        """Shut down the proxy server and release ports."""
        # Snapshot and clear state while holding the lock, then shut down OUTSIDE the lock.
        # This prevents a deadlock where a handler thread's setup() calls get_instance()
        # (which also needs this lock) while server.shutdown() is blocked waiting for
        # serve_forever() to exit.
        with self._lock:
            if self._server is None:
                return
            self._shutdown_event.set()
            self._close_active_connections()
            server = self._server
            self._server = None
            self.port = 0

        # server.shutdown() blocks until serve_forever() exits (up to poll_interval = 0.5s).
        # Must NOT hold self._lock here.
        try:
            server.shutdown()
            server.server_close()
            logger.info("StreamProxy successfully shut down and released.")
        except Exception:
            pass

    def stop_async(self) -> threading.Thread:
        """Stop the proxy without blocking the Tkinter main thread."""
        shutdown_thread = threading.Thread(
            target=self.stop,
            name="StreamProxyShutdown",
            daemon=True,
        )
        shutdown_thread.start()
        return shutdown_thread
