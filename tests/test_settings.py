"""
Unit tests for SettingsManager module.
Verifies setting persistence, schema validation, and seek configuration.
"""

import json
import tempfile
import unittest
from pathlib import Path

from main.settings import SettingsManager


class TestSettingsManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.manager = SettingsManager(config_dir=self.config_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_seek_settings(self):
        self.assertEqual(self.manager.get("ui", "seek_short"), 5)
        self.assertEqual(self.manager.get("ui", "seek_long"), 30)

    def test_update_and_persist_seek_settings(self):
        self.manager.set("ui", "seek_short", 10)
        self.manager.set("ui", "seek_long", 60)

        # Reload from same directory
        reloaded = SettingsManager(config_dir=self.config_dir)
        self.assertEqual(reloaded.get("ui", "seek_short"), 10)
        self.assertEqual(reloaded.get("ui", "seek_long"), 60)

    def test_corrupt_settings_recovery(self):
        settings_path = self.config_dir / "settings.json"
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write("{invalid-json::")

        recovered = SettingsManager(config_dir=self.config_dir)
        self.assertEqual(recovered.get("ui", "seek_short"), 5)
        self.assertEqual(recovered.get("ui", "seek_long"), 30)

    def test_telegram_settings_persistence(self):
        self.assertEqual(self.manager.get("telegram", "api_id"), "")
        self.assertEqual(self.manager.get("telegram", "api_hash"), "")
        self.manager.set("telegram", "api_id", "12345678")
        self.manager.set("telegram", "api_hash", "abcdef1234567890abcdef")
        self.manager.set("telegram", "accounts", [
            {"session_file": "telegram_account_0.session", "label": "Test 1", "active": True},
            {"session_file": "telegram_account_1.session", "label": "Test 2", "active": False},
        ])

        reloaded = SettingsManager(config_dir=self.config_dir)
        self.assertEqual(reloaded.get("telegram", "api_id"), "12345678")
        self.assertEqual(reloaded.get("telegram", "api_hash"), "abcdef1234567890abcdef")
        accounts = reloaded.get("telegram", "accounts")
        self.assertIsInstance(accounts, list)
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]["label"], "Test 1")
        self.assertTrue(accounts[0]["active"])
        self.assertEqual(accounts[1]["label"], "Test 2")
        self.assertFalse(accounts[1]["active"])


if __name__ == "__main__":
    unittest.main()
