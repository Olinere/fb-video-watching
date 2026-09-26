"""
Unit tests for Telegram integration, TelegramManager, TelegramExtractor, and URL parsing.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from main.extractors.telegram import TelegramExtractor
from main.extractors.base import URLValidationError, AuthRequiredError
from main.telegram_manager import TelegramManager, TelegramAccount
from main.url_resolver import get_extractor, is_potential_video_url


class TestTelegramURLParsing(unittest.TestCase):
    """Test URL parsing for all formats of Telegram links."""

    def test_parse_private_channel_link(self):
        url = "https://t.me/c/1159332137/2989553"
        parsed = TelegramManager.parse_telegram_url(url)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["peer"], "-1001159332137")
        self.assertEqual(parsed["msg_id"], 2989553)
        self.assertTrue(parsed["is_private"])

    def test_parse_public_channel_link(self):
        url = "https://t.me/durov/123"
        parsed = TelegramManager.parse_telegram_url(url)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["peer"], "durov")
        self.assertEqual(parsed["msg_id"], 123)
        self.assertFalse(parsed["is_private"])

    def test_parse_web_k_link(self):
        url = "https://web.telegram.org/k/#-1159332137_2989553"
        parsed = TelegramManager.parse_telegram_url(url)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["peer"], "-1001159332137")
        self.assertEqual(parsed["msg_id"], 2989553)
        self.assertTrue(parsed["is_private"])

    def test_parse_web_a_link(self):
        url = "https://web.telegram.org/a/#-1159332137_2989553"
        parsed = TelegramManager.parse_telegram_url(url)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["peer"], "-1001159332137")
        self.assertEqual(parsed["msg_id"], 2989553)
        self.assertTrue(parsed["is_private"])

    def test_parse_web_public_user_link(self):
        url = "https://web.telegram.org/k/#@my_channel/456"
        parsed = TelegramManager.parse_telegram_url(url)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["peer"], "my_channel")
        self.assertEqual(parsed["msg_id"], 456)
        self.assertFalse(parsed["is_private"])

    def test_parse_invalid_url(self):
        self.assertIsNone(TelegramManager.parse_telegram_url("https://facebook.com/video/123"))
        self.assertIsNone(TelegramManager.parse_telegram_url("https://youtube.com/watch?v=123"))


class TestTelegramExtractor(unittest.TestCase):
    """Test TelegramExtractor suitable and extraction behaviors."""

    def setUp(self):
        self.extractor = TelegramExtractor()

    def test_suitable(self):
        self.assertTrue(self.extractor.suitable("https://t.me/c/1159332137/2989553"))
        self.assertTrue(self.extractor.suitable("https://web.telegram.org/k/d/1639936121"))
        self.assertTrue(self.extractor.suitable("https://web.telegram.org/k/#-1159332137_2989553"))
        self.assertFalse(self.extractor.suitable("https://facebook.com/reel/123"))

    def test_kd_link_raises_clear_error(self):
        url = "https://web.telegram.org/k/d/1639936121"
        with self.assertRaises(URLValidationError) as ctx:
            self.extractor.extract(url)
        self.assertIn("/k/d/", str(ctx.exception))
        self.assertIn("Service Worker", str(ctx.exception))

    def test_unconfigured_api_raises_auth_error(self):
        url = "https://t.me/c/1159332137/2989553"
        with patch.object(TelegramManager, "is_configured", return_value=False):
            with self.assertRaises(AuthRequiredError) as ctx:
                self.extractor.extract(url)
            self.assertIn("API ID", str(ctx.exception))

    def test_no_active_accounts_raises_auth_error(self):
        """When configured but no active accounts, should raise AuthRequiredError."""
        url = "https://t.me/c/1159332137/2989553"
        with patch.object(TelegramManager, "is_configured", return_value=True):
            with patch.object(TelegramManager, "get_active_accounts", return_value=[]):
                with self.assertRaises(AuthRequiredError) as ctx:
                    self.extractor.extract(url)
                self.assertIn("kích hoạt", str(ctx.exception))

    def test_url_resolver_dispatch(self):
        ext = get_extractor("https://t.me/c/1159332137/2989553")
        self.assertIsInstance(ext, TelegramExtractor)

    def test_is_potential_video_url(self):
        self.assertTrue(is_potential_video_url("https://t.me/c/1159332137/2989553"))
        self.assertTrue(is_potential_video_url("https://web.telegram.org/k/#-1159332137_2989553"))


class TestTelegramAccount(unittest.TestCase):
    """Test TelegramAccount data class."""

    def test_to_dict_and_from_dict(self):
        acc = TelegramAccount(session_file="telegram_account_0.session", label="Test", active=True)
        d = acc.to_dict()
        self.assertEqual(d["session_file"], "telegram_account_0.session")
        self.assertEqual(d["label"], "Test")
        self.assertTrue(d["active"])

        acc2 = TelegramAccount.from_dict(d)
        self.assertEqual(acc2.session_file, "telegram_account_0.session")
        self.assertEqual(acc2.label, "Test")
        self.assertTrue(acc2.active)

    def test_from_dict_defaults(self):
        acc = TelegramAccount.from_dict({"session_file": "x.session"})
        self.assertEqual(acc.label, "Tài khoản")
        self.assertTrue(acc.active)

    def test_set_active(self):
        acc = TelegramAccount(session_file="test.session", label="Test", active=True)
        acc.active = False
        self.assertFalse(acc.active)


class TestTelegramMultiAccount(unittest.TestCase):
    """Test multi-account fallback and selection logic in TelegramManager."""

    def setUp(self):
        self.mgr = TelegramManager.get_instance()
        self.mgr._api_id = 123456
        self.mgr._api_hash = "abcdef123456"
        self.mgr._msg_cache.clear()

        self.acc_a = TelegramAccount(session_file="tg_acc_a.session", label="Tài khoản A", active=True)
        self.acc_b = TelegramAccount(session_file="tg_acc_b.session", label="Tài khoản B", active=True)

    def test_get_media_info_multi_fallback_to_account_b(self):
        """When account A has no access (channel_private), should automatically retry with account B."""
        def mock_fetch(account, peer, msg_id):
            if account.label == "Tài khoản A":
                raise Exception("channel_private: Channel is private and user is not a member")
            return {
                "file_size": 1024,
                "duration": 60,
                "mime_type": "video/mp4",
                "title": "Video nhóm kín B",
                "media": MagicMock(),
                "account": account,
            }

        with patch.object(self.mgr, "_fetch_media_info_for_account", side_effect=mock_fetch):
            info = self.mgr.get_media_info_multi("-1001159332137", 123, selected_accounts=[self.acc_a, self.acc_b])
            self.assertEqual(info["title"], "Video nhóm kín B")
            self.assertEqual(info["account"].label, "Tài khoản B")

    def test_get_media_info_multi_user_selected_account_a_only(self):
        """If user selects ONLY account A, and it fails, must NOT silently try account B, but report clear error."""
        def mock_fetch(account, peer, msg_id):
            if account.label == "Tài khoản A":
                raise Exception("chat_admin_required")
            return {"title": "Should not reach", "account": account}

        with patch.object(self.mgr, "_fetch_media_info_for_account", side_effect=mock_fetch):
            with self.assertRaises(AuthRequiredError) as ctx:
                self.mgr.get_media_info_multi("-1001159332137", 123, selected_accounts=[self.acc_a])
            
            err_msg = str(ctx.exception)
            self.assertIn("Không tài khoản Telegram nào được chọn", err_msg)
            self.assertIn("Tài khoản A", err_msg)
            self.assertNotIn("Tài khoản B", err_msg)

    def test_get_media_info_multi_all_accounts_fail(self):
        """When all selected accounts fail, raise AuthRequiredError listing all tried accounts."""
        with patch.object(self.mgr, "_fetch_media_info_for_account", side_effect=Exception("user_banned_in_channel")):
            with self.assertRaises(AuthRequiredError) as ctx:
                self.mgr.get_media_info_multi("-1001159332137", 123, selected_accounts=[self.acc_a, self.acc_b])
            
            err_msg = str(ctx.exception)
            self.assertIn("Tài khoản A", err_msg)
            self.assertIn("Tài khoản B", err_msg)

    def test_get_media_info_multi_no_accounts_active(self):
        """When no accounts are active or selected, raise clear AuthRequiredError."""
        with self.assertRaises(AuthRequiredError) as ctx:
            self.mgr.get_media_info_multi("-1001159332137", 123, selected_accounts=[])
        self.assertIn("kích hoạt", str(ctx.exception))


class TestTelegramExtractorMultiAccount(unittest.TestCase):
    """Test TelegramExtractor integration with multi-accounts."""

    def setUp(self):
        self.extractor = TelegramExtractor()
        self.mgr = TelegramManager.get_instance()
        self.mgr._api_id = 123456
        self.mgr._api_hash = "abcdef123456"

        self.acc_a = TelegramAccount(session_file="tg_acc_a.session", label="Tài khoản A", active=True)
        self.acc_b = TelegramAccount(session_file="tg_acc_b.session", label="Tài khoản B", active=True)

    def test_extractor_passes_correct_account_index_in_stream_url(self):
        """Verify stream_url contains ?acc=<index> corresponding to the successful account."""
        mock_info = {
            "file_size": 2048,
            "duration": 120,
            "mime_type": "video/mp4",
            "title": "Test Video",
            "media": MagicMock(),
            "account": self.acc_b,
        }

        with patch.object(self.mgr, "is_configured", return_value=True):
            with patch.object(self.mgr, "get_active_accounts", return_value=[self.acc_a, self.acc_b]):
                with patch.object(self.mgr, "get_accounts", return_value=[self.acc_a, self.acc_b]):
                    with patch.object(self.mgr, "get_media_info_multi", return_value=mock_info):
                        with patch("main.stream_proxy.StreamProxyServer.get_instance") as mock_proxy:
                            mock_proxy.return_value.ensure_started.return_value = 8888
                            resolved = self.extractor.extract("https://t.me/c/1159332137/2989553")

                            self.assertEqual(resolved.title, "Test Video")
                            self.assertIn("acc=1", resolved.stream_url)
                            self.assertIn("channel=-1001159332137", resolved.stream_url)
                            self.assertIn("msg=2989553", resolved.stream_url)


class TestVideoDownloaderTelegram(unittest.TestCase):
    """Test VideoDownloader routing and downloading for Telegram URLs."""

    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_routing_telegram_url(self):
        from main.downloader import VideoDownloader
        dl = VideoDownloader(
            url="https://t.me/c/2605960058/262",
            output_dir=self.output_dir,
        )
        with patch.object(dl, "_run_telegram_download") as mock_tg_dl:
            dl._run_download()
            mock_tg_dl.assert_called_once()
            args, _ = mock_tg_dl.call_args
            self.assertEqual(args[0]["peer"], "-1002605960058")
            self.assertEqual(args[0]["msg_id"], 262)

    def test_routing_stream_proxy_url(self):
        from main.downloader import VideoDownloader
        dl = VideoDownloader(
            url="http://127.0.0.1:7825/telegram/stream?channel=-1002605960058&msg=262&acc=1",
            output_dir=self.output_dir,
        )
        with patch.object(dl, "_run_telegram_download") as mock_tg_dl:
            dl._run_download()
            mock_tg_dl.assert_called_once()
            args, _ = mock_tg_dl.call_args
            self.assertEqual(args[0]["peer"], "-1002605960058")
            self.assertEqual(args[0]["msg_id"], 262)
            self.assertEqual(args[0]["acc_idx"], 1)

    def test_telegram_download_not_configured(self):
        from main.downloader import VideoDownloader
        errors = []
        dl = VideoDownloader(
            url="https://t.me/c/2605960058/262",
            output_dir=self.output_dir,
            on_error=lambda err: errors.append(err),
        )
        with patch.object(TelegramManager, "get_instance") as mock_mgr_get:
            mock_mgr = MagicMock()
            mock_mgr.is_configured.return_value = False
            mock_mgr_get.return_value = mock_mgr

            dl._run_download()
            self.assertTrue(len(errors) > 0)
            self.assertIn("chưa được cấu hình", errors[0])

    def test_telegram_download_success(self):
        from main.downloader import VideoDownloader
        progress_events = []
        completed_files = []
        dl = VideoDownloader(
            url="https://t.me/c/2605960058/262",
            output_dir=self.output_dir,
            on_progress=lambda info: progress_events.append(info),
            on_complete=lambda p: completed_files.append(p),
        )
        with patch.object(TelegramManager, "get_instance") as mock_mgr_get:
            mock_mgr = MagicMock()
            mock_mgr.is_configured.return_value = True
            mock_acc = TelegramAccount(session_file="acc.session", label="Acc 1", active=True)
            mock_mgr.get_active_accounts.return_value = [mock_acc]
            mock_mgr.get_media_info_multi.return_value = {
                "title": "My Telegram Video",
                "file_name": "My Telegram Video.mp4",
                "mime_type": "video/mp4",
                "file_size": 1024 * 1024,
                "account": mock_acc,
            }

            def fake_download_media(peer_str, msg_id, destination_file, account, progress_callback, cancel_check):
                destination_file.touch()
                if progress_callback:
                    progress_callback(512 * 1024, 1024 * 1024)
                    progress_callback(1024 * 1024, 1024 * 1024)
                return destination_file

            mock_mgr.download_media_file.side_effect = fake_download_media
            mock_mgr_get.return_value = mock_mgr

            dl._run_download()
            self.assertEqual(len(completed_files), 1)
            self.assertEqual(completed_files[0].name, "My Telegram Video.mp4")
            self.assertTrue(len(progress_events) >= 1)

    def test_telegram_download_cancellation(self):
        from main.downloader import VideoDownloader
        errors = []
        dl = VideoDownloader(
            url="https://t.me/c/2605960058/262",
            output_dir=self.output_dir,
            on_error=lambda err: errors.append(err),
        )
        with patch.object(TelegramManager, "get_instance") as mock_mgr_get:
            mock_mgr = MagicMock()
            mock_mgr.is_configured.return_value = True
            mock_acc = TelegramAccount(session_file="acc.session", label="Acc 1", active=True)
            mock_mgr.get_active_accounts.return_value = [mock_acc]
            mock_mgr.get_media_info_multi.return_value = {
                "title": "Cancel Video",
                "file_name": "Cancel Video.mp4",
                "account": mock_acc,
            }

            def fake_download(peer_str, msg_id, destination_file, account, progress_callback, cancel_check):
                dl.cancel()
                if cancel_check and cancel_check():
                    raise RuntimeError("Người dùng đã hủy quá trình tải.")
                return destination_file

            mock_mgr.download_media_file.side_effect = fake_download
            mock_mgr_get.return_value = mock_mgr

            dl._run_download()
            self.assertTrue(any("hủy" in str(e).lower() for e in errors))

    def test_telegram_download_audio_only_with_ffmpeg(self):
        from main.downloader import VideoDownloader
        completed_files = []
        dl = VideoDownloader(
            url="https://t.me/c/2605960058/262",
            output_dir=self.output_dir,
            audio_only=True,
            audio_format="mp3",
            on_complete=lambda p: completed_files.append(p),
        )
        with patch.object(TelegramManager, "get_instance") as mock_mgr_get:
            mock_mgr = MagicMock()
            mock_mgr.is_configured.return_value = True
            mock_acc = TelegramAccount(session_file="acc.session", label="Acc 1", active=True)
            mock_mgr.get_active_accounts.return_value = [mock_acc]
            mock_mgr.get_media_info_multi.return_value = {
                "title": "Music Video",
                "file_name": "Music Video.mp4",
                "mime_type": "video/mp4",
                "account": mock_acc,
            }

            def fake_download_media(peer_str, msg_id, destination_file, account, progress_callback, cancel_check):
                destination_file.touch()
                return destination_file

            mock_mgr.download_media_file.side_effect = fake_download_media
            mock_mgr_get.return_value = mock_mgr

            with patch("main.downloader.get_ffmpeg_path", return_value="fake_ffmpeg"):
                with patch("subprocess.run") as mock_run:
                    mock_res = MagicMock()
                    mock_res.returncode = 0
                    mock_run.return_value = mock_res

                    dl._run_download()
                    self.assertEqual(len(completed_files), 1)
                    self.assertTrue(completed_files[0].name.endswith(".mp3"))
                    mock_run.assert_called_once()


class TestTelegramStreamingRangeAlignment(unittest.TestCase):
    """Test MTProto Range request offset alignment and clean exception lifecycle."""

    def test_stream_range_unaligned_start_and_end(self):
        """Unaligned byte offsets are rounded down to 4KB/1KB multiples without byte distortion."""
        from unittest.mock import AsyncMock
        from telethon.tl.functions.upload import GetFileRequest

        tg_mgr = TelegramManager.get_instance()
        account = TelegramAccount(session_file="test_acc.session", label="Test", active=True)

        file_size = 5 * 1024 * 1024  # 5 MB
        doc = MagicMock(document=None, size=file_size, dc_id=2)

        media_info = {
            "media": doc,
            "file_size": file_size,
            "mime_type": "video/mp4",
            "account": account,
        }

        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.session.dc_id = 2
        mock_client.session.auth_key = b"fake_auth_key"
        mock_client._log = MagicMock()
        mock_client._proxy = None
        mock_client.loop = tg_mgr._loop

        offsets_called = []

        async def fake_call(sender, request):
            if isinstance(request, GetFileRequest):
                offsets_called.append(request.offset)
                return MagicMock(bytes=b"B" * request.limit)
            return MagicMock()

        mock_client._call = fake_call
        mock_client._get_dc = AsyncMock(return_value=MagicMock(ip_address="127.0.0.1", port=443, id=2))

        start_byte = 1050
        end_byte = 2 * 1024 * 1024 + 500
        expected_len = end_byte - start_byte + 1

        with patch.object(tg_mgr, "get_media_info", return_value=media_info):
            with patch.object(tg_mgr, "_get_or_create_client", return_value=mock_client):
                with patch("telethon.utils.get_input_location", return_value=(2, MagicMock())):
                    with patch("telethon.network.MTProtoSender.connect", new_callable=AsyncMock):
                        with patch("telethon.network.MTProtoSender.disconnect", new_callable=AsyncMock):
                            with patch("telethon.network.MTProtoSender.send", new_callable=AsyncMock):
                                chunks = list(tg_mgr.stream_media_range(
                                    "test_channel", 123,
                                    start_byte=start_byte, end_byte=end_byte,
                                    account=account
                                ))

        total_bytes = sum(len(c) for c in chunks)
        self.assertEqual(total_bytes, expected_len)
        self.assertTrue(len(offsets_called) > 0)
        for off in offsets_called:
            self.assertEqual(off % 1024, 0, f"Offset {off} not divisible by 1KB")
            self.assertEqual(off % 4096, 0, f"Offset {off} not divisible by 4KB")

    def test_stream_range_early_abort_no_unhandled_task_exception(self):
        """Early stream cancellation retrieves and cancels all in-flight tasks cleanly."""
        from unittest.mock import AsyncMock

        tg_mgr = TelegramManager.get_instance()
        account = TelegramAccount(session_file="test_acc.session", label="Test", active=True)

        file_size = 50 * 1024 * 1024  # 50 MB
        doc = MagicMock(document=None, size=file_size, dc_id=2)

        media_info = {
            "media": doc,
            "file_size": file_size,
            "mime_type": "video/mp4",
            "account": account,
        }

        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.session.dc_id = 2
        mock_client.session.auth_key = b"fake_auth_key"
        mock_client._log = MagicMock()
        mock_client._proxy = None
        mock_client.loop = tg_mgr._loop

        async def fake_call(sender, request):
            return MagicMock(bytes=b"B" * request.limit)

        mock_client._call = fake_call
        mock_client._get_dc = AsyncMock(return_value=MagicMock(ip_address="127.0.0.1", port=443, id=2))

        with patch.object(tg_mgr, "get_media_info", return_value=media_info):
            with patch.object(tg_mgr, "_get_or_create_client", return_value=mock_client):
                with patch("telethon.utils.get_input_location", return_value=(2, MagicMock())):
                    with patch("telethon.network.MTProtoSender.connect", new_callable=AsyncMock):
                        with patch("telethon.network.MTProtoSender.disconnect", new_callable=AsyncMock):
                            with patch("telethon.network.MTProtoSender.send", new_callable=AsyncMock):
                                gen = tg_mgr.stream_media_range(
                                    "test_channel", 123,
                                    start_byte=1000, end_byte=10000000,
                                    account=account
                                )
                                for chunk in gen:
                                    self.assertTrue(len(chunk) > 0)
                                    break
                                gen.close()


if __name__ == "__main__":
    unittest.main()

