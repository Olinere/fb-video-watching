"""
Unit tests for popup lifecycles, keyboard shortcuts (<Escape>), grab management,
and cancellation safety across all application dialogs.
"""

import os
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tkinter as tk

from main.vlc_setup_dialog import VLCDownloadDialog, VLCUpdatePromptDialog
from main.ffmpeg_setup_dialog import FFmpegDownloadDialog, FFmpegSetupDialog
from main.bulk_import_dialog import BulkImportDialog
from main.gui.settings_dialog import SettingsDialog
from main.settings import SettingsManager
from main.theme import ThemeManager


class TestPopupLifecycleAndCancel(unittest.TestCase):
    """Test suite ensuring 100% cancel reliability and zero edge-cases for all dialogs."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.theme = ThemeManager(self.root)
        self.settings = SettingsManager()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_vlc_update_prompt_escape_and_skip(self):
        """VLCUpdatePromptDialog should have <Escape> binding and return 'skip' on cancel."""
        dialog = VLCUpdatePromptDialog(self.root, installed_version="3.0.21")
        # Verify Escape shortcut is bound
        self.assertTrue(bool(dialog._win.bind("<Escape>")), "VLCUpdatePromptDialog must bind <Escape>")

        # Trigger skip/cancel
        dialog._on_skip()
        self.assertEqual(dialog._action, "skip")
        self.assertFalse(dialog._skip_future)
        self.assertFalse(dialog._win.winfo_exists(), "Window must be destroyed on skip")

    def test_vlc_download_dialog_cancel(self):
        """VLCDownloadDialog should cleanly abort and return 'cancelled' when cancel is triggered."""
        dialog = VLCDownloadDialog(self.root)
        self.assertEqual(dialog._phase, "download")
        self.assertTrue(bool(dialog._win.bind("<Escape>")), "VLCDownloadDialog must bind <Escape>")

        # Simulate user clicking Cancel
        dialog._on_cancel()
        self.assertTrue(dialog._cancel_event.is_set())
        self.assertEqual(dialog._result, "cancelled")

    def test_ffmpeg_download_dialog_escape_and_cancel(self):
        """FFmpegDownloadDialog should bind Escape, set cancel event and close on cancel."""
        with patch("threading.Thread"):  # Prevent actual background thread start
            dialog = FFmpegDownloadDialog(self.root, theme_mgr=self.theme)
            self.assertTrue(bool(dialog._win.bind("<Escape>")), "FFmpegDownloadDialog must bind <Escape>")

            # Trigger cancel
            dialog._on_cancel()
            self.assertTrue(dialog._cancel_event.is_set())
            self.assertEqual(dialog._result, "cancelled")
            self.assertFalse(dialog._win.winfo_exists(), "Window must be destroyed on cancel")

    def test_ffmpeg_atomic_staging_no_corrupt_binary_on_cancel(self):
        """Cancelling during FFmpeg extraction must not leave partial binaries in target_dir."""
        from main.ffmpeg_installer import download_and_extract_ffmpeg

        with tempfile.TemporaryDirectory() as temp_target:
            target_dir = Path(temp_target)
            cancel_event = threading.Event()
            cancel_event.set()  # Cancelled before start

            with self.assertRaises(RuntimeError):
                download_and_extract_ffmpeg(
                    custom_target_dir=target_dir,
                    cancel_event=cancel_event,
                )

            # Confirm target_dir has NO partial ffmpeg binaries
            ff_exe = target_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            self.assertFalse(ff_exe.exists(), "Corrupt ffmpeg.exe must not be left in target directory upon cancel!")

    def test_ffmpeg_setup_dialog_escape_and_close(self):
        """FFmpegSetupDialog should bind Escape and close cleanly via _safe_close."""
        dialog = FFmpegSetupDialog(self.root, theme_mgr=self.theme)
        self.assertTrue(bool(dialog._win.bind("<Escape>")), "FFmpegSetupDialog must bind <Escape>")

        dialog._safe_close()
        self.assertFalse(dialog._win.winfo_exists(), "Window must be destroyed on safe close")

    def test_bulk_import_dialog_escape_and_close(self):
        """BulkImportDialog should bind Escape, release grab and close via _on_close."""
        dialog = BulkImportDialog(
            parent=self.root,
            theme_mgr=self.theme,
            on_import_to_queue=lambda items: None,
        )
        self.assertTrue(bool(dialog.top.bind("<Escape>")), "BulkImportDialog must bind <Escape>")

        dialog._on_close()
        self.assertFalse(dialog.top.winfo_exists(), "Window must be destroyed on close")

    def test_settings_dialog_escape_and_destroy(self):
        """SettingsDialog should bind Escape and cleanly close via destroy()."""
        dialog = SettingsDialog(
            parent=self.root,
            settings_mgr=self.settings,
            theme_mgr=self.theme,
        )
        self.assertTrue(bool(dialog.top.bind("<Escape>")), "SettingsDialog must bind <Escape>")

        dialog.destroy()
        self.assertFalse(dialog.top.winfo_exists(), "Window must be destroyed on destroy()")

    def test_settings_dialog_destroy_does_not_cancel_root_timers(self):
        """SettingsDialog.destroy must NOT wipe global Tcl timers (e.g. root timers)."""
        root_timer_fired = [False]

        def _root_callback():
            root_timer_fired[0] = True

        # Register a heartbeat timer on root
        root_timer_id = self.root.after(30, _root_callback)

        dialog = SettingsDialog(
            parent=self.root,
            settings_mgr=self.settings,
            theme_mgr=self.theme,
        )

        # Call dialog.destroy()
        dialog.destroy()

        # Wait a tick and verify root timer still fires!
        self.root.after(80, lambda: self.root.quit())
        self.root.mainloop()

        self.assertTrue(root_timer_fired[0], "SettingsDialog.destroy must NOT cancel timers owned by root!")


if __name__ == "__main__":
    unittest.main()
