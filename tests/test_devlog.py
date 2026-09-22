"""
Unit tests for Devlog sidebar and detachable window functionality.
"""

import logging
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock

from main.settings import SettingsManager
from main.theme import ThemeManager
from main.gui import MainWindow
from main.devlog import DevLogPanel, DevLogHandler


class TestDevLog(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings = SettingsManager(config_dir=self.config_dir)
        self.theme = ThemeManager(self.root)

        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings,
            theme_mgr=self.theme,
            on_play_request=MagicMock(),
            on_pause_toggle=MagicMock(),
            on_seek_request=MagicMock(),
            on_seek_relative=MagicMock(),
            on_volume_change=MagicMock(),
            on_mute_toggle=MagicMock(),
            on_rate_change=MagicMock(),
        )

    def tearDown(self):
        try:
            if self.gui.devlog_panel._detached_window and self.gui.devlog_panel._detached_window.winfo_exists():
                self.gui.devlog_panel._detached_window.destroy()
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def test_devlog_toggle_checkbox(self):
        self.assertFalse(self.gui.devlog_var.get())
        self.assertFalse(self.gui.devlog_panel._is_visible)

        # Toggle on
        self.gui.toggle_devlog()
        self.assertTrue(self.gui.devlog_var.get())
        self.assertTrue(self.gui.devlog_panel._is_visible)

        # Toggle off
        self.gui.toggle_devlog()
        self.assertFalse(self.gui.devlog_var.get())
        self.assertFalse(self.gui.devlog_panel._is_visible)

    def test_devlog_captures_logs(self):
        self.gui.devlog_panel.show()
        test_logger = logging.getLogger("TestLogger")
        test_logger.info("Test message for Devlog")
        self.root.update()

        # Verify message added to log records
        found = any("Test message for Devlog" in msg for msg, lvl in self.gui.devlog_panel._log_records)
        self.assertTrue(found)

    def test_devlog_detach_and_dock(self):
        self.gui.devlog_panel.show()
        self.assertFalse(self.gui.devlog_panel._is_detached)

        # Detach to floating window
        self.gui.devlog_panel.detach_to_window()
        self.assertTrue(self.gui.devlog_panel._is_detached)
        self.assertIsNotNone(self.gui.devlog_panel._detached_window)
        self.assertTrue(self.gui.devlog_panel._detached_window.winfo_exists())

        # Dock back to main sidebar
        self.gui.devlog_panel.dock_back()
        self.assertFalse(self.gui.devlog_panel._is_detached)
        self.assertIsNone(self.gui.devlog_panel._detached_window)

    def test_devlog_clear(self):
        self.gui.devlog_panel.add_log_entry("Log to clear", "INFO")
        self.assertTrue(len(self.gui.devlog_panel._log_records) > 0)
        self.gui.devlog_panel.clear_logs()
        self.assertEqual(len(self.gui.devlog_panel._log_records), 0)


if __name__ == "__main__":
    unittest.main()
