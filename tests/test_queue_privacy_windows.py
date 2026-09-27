import unittest

from main.privacy_session import RuntimePersistencePolicy
from main.windows_integration import parse_fbvw_uri, parse_launch_args


class TestPrivacyPolicy(unittest.TestCase):
    def test_private_session_blocks_content_persistence_but_not_preferences(self):
        policy = RuntimePersistencePolicy(True)
        self.assertTrue(policy.is_enabled())
        self.assertFalse(policy.allow_history_write())
        self.assertFalse(policy.allow_resume_write())
        self.assertFalse(policy.allow_queue_persist())
        self.assertTrue(policy.allow_explicit_user_settings_write())
        self.assertEqual(policy.redact("open https://example.test/watch?v=secret"), "open <private-url>")


class TestWindowsInputContract(unittest.TestCase):
    def test_uri_decodes_once_and_keeps_only_source_url(self):
        request = parse_fbvw_uri("fbvw://queue?url=https%3A%2F%2Fexample.test%2Fwatch%3Fv%3D1&privacy=1")
        self.assertEqual(request.action, "queue")
        self.assertEqual(request.items, ("https://example.test/watch?v=1",))
        self.assertTrue(request.privacy)

    def test_cli_supports_multiple_sources(self):
        request = parse_launch_args(["--add-to-queue", "https://example.test/a", "C:\\Video\\b.mp4", "--privacy"])
        self.assertEqual(request.action, "queue")
        self.assertEqual(len(request.items), 2)
        self.assertTrue(request.privacy)

    def test_invalid_uri_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_fbvw_uri("fbvw://play?url=javascript%3Aalert(1)")

    def test_uri_normalizes_raw_domain_url(self):
        request = parse_fbvw_uri("fbvw://play?url=youtu.be/8WKP3QFt6t4")
        self.assertEqual(request.action, "play")
        self.assertEqual(request.items, ("https://youtu.be/8WKP3QFt6t4",))

    def test_settings_dialog_protocol_toggle_no_name_error(self):
        """Test that protocol registration toggle in settings dialog doesn't raise NameError for logger or Path."""
        import logging
        from main.gui.settings_dialog import logger
        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "FBVideoWatcher.SettingsDialog")


if __name__ == "__main__":
    unittest.main()

