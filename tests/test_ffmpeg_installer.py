"""Unit tests for FFmpeg portable installer and setup dialog."""

import io
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from main.ffmpeg_installer import (
    get_ffmpeg_install_dir,
    download_and_extract_ffmpeg,
)
from main.ffmpeg_setup_dialog import FFmpegDownloadDialog
from main.theme import ThemeManager


class TestFFmpegInstallerAndDialog(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.theme = ThemeManager(self.root)

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def test_get_ffmpeg_install_dir(self):
        target = get_ffmpeg_install_dir()
        self.assertTrue(target.is_dir())
        self.assertIn("bin", str(target).lower())

    def test_download_and_extract_mocked_zip(self):
        # Create an in-memory zip archive with a dummy ffmpeg.exe
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("ffmpeg-master/bin/ffmpeg.exe", b"MOCK_FFMPEG_BINARY_DATA")
            zf.writestr("ffmpeg-master/bin/ffprobe.exe", b"MOCK_FFPROBE_BINARY_DATA")

        mock_data = zip_buffer.getvalue()

        # Mock urllib.request.urlopen to return this zip
        class MockResponse:
            def __init__(self, data):
                self.data = io.BytesIO(data)
                self.headers = {"Content-Length": str(len(data))}

            def read(self, size=-1):
                return self.data.read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch("urllib.request.urlopen", return_value=MockResponse(mock_data)):
            installed_ffmpeg = download_and_extract_ffmpeg(
                custom_target_dir=self.target_dir,
            )

        self.assertTrue(installed_ffmpeg.is_file())
        self.assertEqual(installed_ffmpeg.read_bytes(), b"MOCK_FFMPEG_BINARY_DATA")
        ffprobe_path = self.target_dir / "ffprobe.exe"
        self.assertTrue(ffprobe_path.is_file())

    def test_cancel_event_aborts_download(self):
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaises(RuntimeError) as ctx:
            download_and_extract_ffmpeg(
                cancel_event=cancel_event,
                custom_target_dir=self.target_dir,
            )
        self.assertIn("Đã hủy", str(ctx.exception))

    def test_ffmpeg_download_dialog_ui(self):
        on_success = MagicMock()
        # Mock download_and_extract_ffmpeg to return immediately
        dummy_exe = self.target_dir / "ffmpeg.exe"
        dummy_exe.write_bytes(b"dummy")

        with patch("main.ffmpeg_setup_dialog.download_and_extract_ffmpeg", return_value=dummy_exe):
            dialog = FFmpegDownloadDialog(
                parent=self.root,
                theme_mgr=self.theme,
                on_success=on_success,
            )
            # Wait for thread to finish
            dialog._thread.join(timeout=2.0)
            self.root.update_idletasks()

            self.assertEqual(dialog._result, "installed")
            on_success.assert_called_once_with(dummy_exe)

    def test_ffmpeg_setup_dialog_when_installed(self):
        from main.ffmpeg_setup_dialog import FFmpegSetupDialog

        dummy_exe = str(self.target_dir / "ffmpeg.exe")
        with patch("main.ffmpeg_utils.is_ffmpeg_available", return_value=True), \
             patch("main.ffmpeg_utils.get_ffmpeg_path", return_value=dummy_exe):
            dlg = FFmpegSetupDialog(parent=self.root, theme_mgr=self.theme)
            self.root.update_idletasks()
            self.assertTrue(dlg._win.winfo_exists())
            dlg._win.destroy()

    def test_ffmpeg_setup_dialog_when_not_installed(self):
        from main.ffmpeg_setup_dialog import FFmpegSetupDialog

        with patch("main.ffmpeg_utils.is_ffmpeg_available", return_value=False), \
             patch("main.ffmpeg_utils.get_ffmpeg_path", return_value=None):
            dlg = FFmpegSetupDialog(parent=self.root, theme_mgr=self.theme)
            self.root.update_idletasks()
            self.assertTrue(dlg._win.winfo_exists())
            dlg._win.destroy()


if __name__ == "__main__":
    unittest.main()
