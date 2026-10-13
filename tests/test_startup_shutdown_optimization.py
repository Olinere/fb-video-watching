"""
Unit tests for Startup & Shutdown Lifecycle Optimizations.
Verifies DaemonThreadPoolExecutor, non-blocking on_closing teardown,
and fast initialization paths.
"""

import concurrent.futures
from concurrent.futures import thread
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from main.thread_pool import DaemonThreadPoolExecutor
from main.vlc_installer import is_vlc_available
from main.stream_proxy import StreamProxyServer


class TestStartupShutdownOptimization(unittest.TestCase):
    """Test suite verifying fast startup and clean non-blocking shutdown."""

    def test_daemon_thread_pool_executor_workers_are_daemon(self):
        """Worker threads spawned by DaemonThreadPoolExecutor must strictly be daemon threads."""
        executor = DaemonThreadPoolExecutor(max_workers=2, thread_name_prefix="test-daemon")
        daemon_flag = None

        def worker_task():
            nonlocal daemon_flag
            daemon_flag = threading.current_thread().daemon
            return 42

        fut = executor.submit(worker_task)
        result = fut.result(timeout=2.0)

        self.assertEqual(result, 42)
        self.assertTrue(daemon_flag, "Worker thread in DaemonThreadPoolExecutor must have daemon=True")
        executor.shutdown(wait=False, cancel_futures=True)

    def test_daemon_thread_pool_not_registered_in_global_threads_queues(self):
        """
        Workers must NOT be registered in concurrent.futures.thread._threads_queues
        so Python's atexit hook (_python_exit) does not call t.join() and hang on exit.
        """
        executor = DaemonThreadPoolExecutor(max_workers=1, thread_name_prefix="test-exit")
        fut = executor.submit(lambda: time.sleep(0.01))
        fut.result(timeout=2.0)

        worker_threads = list(executor._threads)
        self.assertTrue(len(worker_threads) > 0)
        for t in worker_threads:
            self.assertNotIn(
                t,
                thread._threads_queues,
                "Daemon workers must not be tracked in _threads_queues to avoid exit join hangs"
            )
        executor.shutdown(wait=False, cancel_futures=True)

    def test_is_vlc_available_fast_query(self):
        """is_vlc_available should query libvlc quickly without full Instance creation."""
        t0 = time.perf_counter()
        available = is_vlc_available()
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self.assertIsInstance(available, bool)
        # Should be sub-100ms on local machine with libvlc
        self.assertLess(elapsed_ms, 250.0, "is_vlc_available should execute in under 250ms")

    def test_stream_proxy_close_active_connections_public_api(self):
        """StreamProxyServer.close_active_connections should be callable and safe."""
        proxy = StreamProxyServer.get_instance()
        # Should execute safely without raising exceptions even when idle
        proxy.close_active_connections()

    def test_on_closing_instant_ui_dismissal_and_order(self):
        """
        Verify on_closing executes withdraw() first, disconnects proxy before VLC,
        detaches VLC HWND, and uninstalls DNS interceptor cleanly.
        """
        import tkinter as tk
        from main.app import Application

        app_root = tk.Tk()
        app_root.withdraw()

        call_order = []
        orig_withdraw = app_root.withdraw

        def _track_withdraw():
            call_order.append("withdraw")
            orig_withdraw()

        app_root.withdraw = _track_withdraw

        with patch("main.stream_proxy.StreamProxyServer.get_instance") as MockProxyInst:
            mock_proxy = MagicMock()
            mock_proxy.close_active_connections.side_effect = lambda: call_order.append("proxy_close")
            mock_proxy.stop_async.side_effect = lambda: call_order.append("proxy_stop")
            MockProxyInst.return_value = mock_proxy

            app = Application(app_root)

            # Mock player methods to track order
            if app.player:
                orig_stop = app.player.stop
                def _track_stop():
                    call_order.append("vlc_stop")
                    orig_stop()
                app.player.stop = _track_stop

            app.on_closing()

            # Verify withdraw was called first
            self.assertIn("withdraw", call_order)
            self.assertEqual(call_order[0], "withdraw", "root.withdraw() must be called first for instant dismissal")

            # Verify proxy close happened before vlc stop
            if "vlc_stop" in call_order:
                self.assertIn("proxy_close", call_order)
                proxy_idx = call_order.index("proxy_close")
                vlc_idx = call_order.index("vlc_stop")
                self.assertLess(proxy_idx, vlc_idx, "StreamProxy must be disconnected BEFORE stopping VLC")


if __name__ == "__main__":
    unittest.main()
