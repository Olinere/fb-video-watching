"""
Unit tests for updater module (main/updater.py).
Tests semver parsing, GitHub releases API response handling,
non-blocking download with progress, resume state persistence,
and update runner generation.
"""

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

from main.updater import (
    parse_semver,
    check_for_updates,
    download_update,
    save_resume_state,
    load_and_clear_resume_state,
    apply_update_and_restart,
    UpdateInfo,
)


class TestUpdater(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_semver(self):
        """Verify semantic version parsing and comparison."""
        self.assertEqual(parse_semver("v1.0.0"), (1, 0, 0))
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_semver("v2.1"), (2, 1, 0))
        self.assertEqual(parse_semver("v0.9.8-beta"), (0, 9, 8))

        self.assertGreater(parse_semver("v1.1.0"), parse_semver("v1.0.0"))
        self.assertGreater(parse_semver("v1.0.1"), parse_semver("v1.0.0"))
        self.assertGreater(parse_semver("v2.0.0"), parse_semver("v1.9.9"))
        self.assertEqual(parse_semver("v1.0.0"), parse_semver("1.0.0"))

    @patch("urllib.request.urlopen")
    def test_check_for_updates_new_release(self, mock_urlopen):
        """When GitHub API reports a newer release with .zip asset, return UpdateInfo."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_payload = {
            "tag_name": "v1.1.0",
            "name": "Bản cập nhật v1.1.0",
            "body": "Nâng cấp tốc độ phát stream và giao diện mới.",
            "published_at": "2026-09-19T12:00:00Z",
            "assets": [
                {
                    "name": "FB-Video-Watcher-v1.1.0.zip",
                    "browser_download_url": "https://github.com/Olinere/fb-video-watching/releases/download/v1.1.0/FB-Video-Watcher-v1.1.0.zip",
                    "size": 52428800,
                }
            ],
        }
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        info = check_for_updates(current_version="1.0.0")
        self.assertIsNotNone(info)
        self.assertEqual(info.version, "1.1.0")
        self.assertEqual(info.asset_name, "FB-Video-Watcher-v1.1.0.zip")
        self.assertEqual(info.asset_size, 52428800)

    @patch("urllib.request.urlopen")
    def test_check_for_updates_already_latest(self, mock_urlopen):
        """When GitHub API reports current or older version, return None."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_payload = {
            "tag_name": "v1.0.0",
            "assets": [{"name": "app.zip", "browser_download_url": "https://example.com/app.zip"}],
        }
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        info = check_for_updates(current_version="1.0.0")
        self.assertIsNone(info)

    @patch("urllib.request.urlopen")
    def test_check_for_updates_no_zip_asset(self, mock_urlopen):
        """When release exists but has no .zip or .exe asset, return None."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_payload = {
            "tag_name": "v1.2.0",
            "assets": [{"name": "source.tar.gz", "browser_download_url": "https://example.com/source.tar.gz"}],
        }
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        info = check_for_updates(current_version="1.0.0")
        self.assertIsNone(info)

    @patch("main.updater.get_config_dir")
    def test_resume_state_lifecycle(self, mock_get_cfg):
        """Verify saving and consuming resume state is atomic and leaves no residue."""
        mock_get_cfg.return_value = self.config_dir

        state_data = {
            "url": "https://www.youtube.com/watch?v=test",
            "position_ms": 45000,
            "volume": 85,
            "playback_rate": 1.25,
            "loop_enabled": True,
        }

        # 1. Save
        save_resume_state(state_data)
        state_file = self.config_dir / "resume_state.json"
        self.assertTrue(state_file.is_file())

        # 2. Load and verify contents
        loaded = load_and_clear_resume_state()
        self.assertEqual(loaded, state_data)

        # 3. File must be deleted immediately after loading
        self.assertFalse(state_file.is_file())

        # 4. Subsequent load must return None
        self.assertIsNone(load_and_clear_resume_state())

    @patch("subprocess.Popen")
    @patch("main.updater.get_config_dir")
    def test_apply_update_and_restart(self, mock_get_cfg, mock_popen):
        """Verify PowerShell script generation and process detachment."""
        mock_get_cfg.return_value = self.config_dir

        fake_zip = self.config_dir / "update.zip"
        fake_zip.write_bytes(b"PK\x03\x04fakezip")

        state = {"url": "https://example.com", "position_ms": 10000}
        success = apply_update_and_restart(fake_zip, resume_state=state)

        self.assertTrue(success)
        mock_popen.assert_called_once()

        # Check script generated
        script = self.config_dir / "update_runner.ps1"
        self.assertTrue(script.is_file())
        script_content = script.read_text(encoding="utf-8")
        self.assertIn("Wait-Process", script_content)
        self.assertIn("Expand-Archive", script_content)
        self.assertIn("Remove-Item", script_content)


if __name__ == "__main__":
    unittest.main()
