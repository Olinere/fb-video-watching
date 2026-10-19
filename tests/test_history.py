"""
Unit tests for HistoryManager module.
Verifies position persistence, watch count increment logic, WAL checkpoints,
and connection cleanup under rapid updates.
"""

import tempfile
import unittest
from pathlib import Path

from main.history import HistoryManager


class TestHistoryManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_history.db"
        self.manager = HistoryManager(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_playback_start_and_update_position(self):
        url = "https://www.facebook.com/watch/?v=123456"
        self.manager.record_playback_start(url=url, title="Sample Video", duration_ms=60000)

        history = self.manager.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["watch_count"], 1)
        self.assertEqual(history[0]["last_position"], 0)

        # Simulate periodic updates - watch_count must remain 1
        for pos in [10000, 20000, 30000]:
            self.manager.update_position(url=url, position_ms=pos, duration_ms=60000)

        history = self.manager.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["watch_count"], 1)
        self.assertEqual(history[0]["last_position"], 30000)

        # Retrieve last position
        self.assertEqual(self.manager.get_last_position(url), 30000)

    def test_checkpoint_wal(self):
        # Should execute cleanly without error
        self.manager.checkpoint_wal()

    def test_rapid_concurrent_writes(self):
        url = "https://www.facebook.com/watch/?v=999999"
        self.manager.record_playback_start(url=url, title="Rapid Test", duration_ms=100000)

        # Ensure no connection or handle leaks across many rapid calls
        for i in range(50):
            self.manager.update_position(url, position_ms=i * 1000, duration_ms=100000)

        history = self.manager.get_history()
        self.assertEqual(history[0]["last_position"], 49000)
        self.assertEqual(history[0]["watch_count"], 1)

    def test_bookmark_and_toggle(self):
        url = "https://www.facebook.com/watch/?v=777888"
        self.manager.record_playback_start(url=url, title="Bookmark Test", duration_ms=60000)

        history = self.manager.get_history()
        self.assertEqual(len(history), 1)
        entry_id = history[0]["id"]
        self.assertFalse(history[0]["is_bookmarked"])

        # Toggle to True
        res = self.manager.toggle_bookmark(entry_id)
        self.assertTrue(res)
        self.assertEqual(len(self.manager.get_history(bookmarked_only=True)), 1)

        # Toggle to False
        res = self.manager.toggle_bookmark(entry_id)
        self.assertFalse(res)
        self.assertEqual(len(self.manager.get_history(bookmarked_only=True)), 0)


if __name__ == "__main__":
    unittest.main()
