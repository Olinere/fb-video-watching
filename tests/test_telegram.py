"""
Unit tests for Telegram integration, TelegramManager, TelegramExtractor, and URL parsing.
"""

import unittest
from unittest.mock import patch, MagicMock

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


if __name__ == "__main__":
    unittest.main()

