"""
Unit tests for VLC Installer enhancements, VLCStatus classification,
PE executable binary validation, and popup icon bindings.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from main.vlc_installer import (
    VLC_VERSION,
    VLC_DIRECT_DOWNLOAD_URL,
    VLC_FALLBACK_MIRRORS,
    MIN_INSTALLER_SIZE_BYTES,
    VLCStatus,
    parse_version_tuple,
    get_vlc_status,
    is_vlc_available,
    validate_pe_executable,
)
from main.platform_utils import apply_window_icon


class TestVLCInstallerAndPopups(unittest.TestCase):
    """Test suite for VLC installer upgrades, version classification, and popups."""

    def test_parse_version_tuple(self):
        """Verify numeric version extraction across various format strings."""
        self.assertEqual(parse_version_tuple("3.0.21 Vetinari"), (3, 0, 21))
        self.assertEqual(parse_version_tuple("3.0.23"), (3, 0, 23))
        self.assertEqual(parse_version_tuple("2.2.8 WeatherWax"), (2, 2, 8))
        self.assertEqual(parse_version_tuple("4.0.0-dev"), (4, 0, 0))
        self.assertEqual(parse_version_tuple(""), ())
        self.assertEqual(parse_version_tuple(None), ())

    def test_vlc_status_classification(self):
        """Test status determination for missing, ancient, compatible older, and up-to-date versions."""
        with patch("main.vlc_installer.get_installed_vlc_version", return_value=None):
            status, ver = get_vlc_status()
            self.assertEqual(status, VLCStatus.MISSING)
            self.assertIsNone(ver)
            self.assertFalse(is_vlc_available())

        with patch("main.vlc_installer.get_installed_vlc_version", return_value="2.2.8"):
            status, ver = get_vlc_status()
            self.assertEqual(status, VLCStatus.UNSUPPORTED)
            self.assertEqual(ver, "2.2.8")
            self.assertFalse(is_vlc_available())

        with patch("main.vlc_installer.get_installed_vlc_version", return_value="3.0.21"):
            status, ver = get_vlc_status()
            self.assertEqual(status, VLCStatus.SUPPORTED_OUTDATED)
            self.assertEqual(ver, "3.0.21")
            # Supported outdated VLC must run normally!
            self.assertTrue(is_vlc_available())

        with patch("main.vlc_installer.get_installed_vlc_version", return_value="3.0.23"):
            status, ver = get_vlc_status()
            self.assertEqual(status, VLCStatus.UP_TO_DATE)
            self.assertEqual(ver, "3.0.23")
            self.assertTrue(is_vlc_available())

        with patch("main.vlc_installer.get_installed_vlc_version", return_value="3.0.24"):
            status, ver = get_vlc_status()
            self.assertEqual(status, VLCStatus.UP_TO_DATE)
            self.assertTrue(is_vlc_available())

    def test_direct_download_urls_avoid_html_landing_page(self):
        """Ensure VLC download URLs strictly use binary distribution domains, not get.videolan.org."""
        self.assertNotIn(
            "get.videolan.org",
            VLC_DIRECT_DOWNLOAD_URL,
            "Direct download URL must not point to get.videolan.org HTML landing page"
        )
        self.assertTrue(VLC_DIRECT_DOWNLOAD_URL.startswith("https://download.videolan.org/"))
        self.assertTrue(VLC_DIRECT_DOWNLOAD_URL.endswith(".exe"))

        for mirror in VLC_FALLBACK_MIRRORS:
            self.assertNotIn("get.videolan.org", mirror)
            self.assertTrue(mirror.endswith(".exe"))

    def test_validate_pe_executable_detects_corrupted_or_html_files(self):
        """Verify that HTML pages, undersized files, or files lacking 'MZ' header are rejected."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 1. HTML file masquerading as .exe (Root cause of 16-bit error)
            html_file = tmp_path / "fake_html.exe"
            html_file.write_text("<!DOCTYPE html><html><body>Error</body></html>", encoding="utf-8")
            self.assertFalse(validate_pe_executable(html_file))

            # 2. Undersized file with MZ header
            small_file = tmp_path / "small.exe"
            small_file.write_bytes(b"MZ" + b"\x00" * 1024)
            self.assertFalse(validate_pe_executable(small_file))

            # 3. Non-existent file
            non_existent = tmp_path / "does_not_exist.exe"
            self.assertFalse(validate_pe_executable(non_existent))

            # 4. Valid mock PE binary (>= 30 MB with MZ header)
            valid_pe = tmp_path / "valid.exe"
            with open(valid_pe, "wb") as f:
                f.write(b"MZ\x90\x00")
                # Fast sparse/zero fill to reach MIN_INSTALLER_SIZE_BYTES
                f.seek(MIN_INSTALLER_SIZE_BYTES + 1024)
                f.write(b"\x00")

            self.assertTrue(validate_pe_executable(valid_pe))

    def test_apply_window_icon_defaults_and_safeguards(self):
        """Verify apply_window_icon handles windows gracefully without raising exceptions."""
        mock_win = MagicMock()
        mock_win._fbvw_window_icon_applied = False
        mock_win.winfo_exists.return_value = True

        # Call with default icon_path=None
        apply_window_icon(mock_win)
        self.assertTrue(getattr(mock_win, "_fbvw_window_icon_applied", False))

        # Idempotent: second call should be a no-op
        apply_window_icon(mock_win)

    def test_install_vlc_silent_elevated_success(self):
        """Verify install_vlc_silent invokes ShellExecuteExW with verb 'runas' and handles returncodes 0 and 2."""
        from main.vlc_installer import install_vlc_silent
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "vlc_test.exe"
            with open(p, "wb") as f:
                f.write(b"MZ")
                f.seek(MIN_INSTALLER_SIZE_BYTES + 100)
                f.write(b"0")

            with patch("ctypes.windll.shell32.ShellExecuteExW") as m_shell, \
                 patch("ctypes.windll.kernel32.WaitForSingleObject", return_value=0), \
                 patch("ctypes.windll.kernel32.GetExitCodeProcess") as m_get_exit, \
                 patch("ctypes.windll.kernel32.CloseHandle") as m_close:

                def fake_shell(byref_sei):
                    sei = byref_sei._obj
                    self.assertEqual(sei.lpVerb, "runas")
                    self.assertEqual(sei.lpParameters, "/S")
                    sei.hProcess = 9999
                    return 1

                m_shell.side_effect = fake_shell

                # Exit code 0 (success)
                def fake_exit_0(h, byref_code):
                    byref_code._obj.value = 0
                    return 1

                m_get_exit.side_effect = fake_exit_0
                install_vlc_silent(p)
                self.assertTrue(m_close.called)

                # Exit code 2 (success with reboot requested)
                def fake_exit_2(h, byref_code):
                    byref_code._obj.value = 2
                    return 1

                m_get_exit.side_effect = fake_exit_2
                install_vlc_silent(p)

    def test_install_vlc_silent_uac_cancelled(self):
        """Verify install_vlc_silent raises 'cancelled_by_user' when UAC is denied (error 1223)."""
        from main.vlc_installer import install_vlc_silent
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "vlc_test.exe"
            with open(p, "wb") as f:
                f.write(b"MZ")
                f.seek(MIN_INSTALLER_SIZE_BYTES + 100)
                f.write(b"0")

            with patch("ctypes.windll.shell32.ShellExecuteExW", return_value=0), \
                 patch("ctypes.windll.kernel32.GetLastError", return_value=1223):
                with self.assertRaises(RuntimeError) as ctx:
                    install_vlc_silent(p)
                self.assertEqual(str(ctx.exception), "cancelled_by_user")

    def test_run_vlc_setup_skip_prompt(self):
        """Verify run_vlc_setup(skip_prompt=True) does not show ask_auto_install."""
        from main.vlc_setup_dialog import run_vlc_setup

        with patch("main.vlc_setup_dialog.ask_auto_install") as mock_ask, \
             patch("main.vlc_setup_dialog.VLCDownloadDialog") as mock_dlg_cls:
            mock_dlg = MagicMock()
            mock_dlg.run.return_value = "installed"
            mock_dlg_cls.return_value = mock_dlg

            res = run_vlc_setup(parent=MagicMock(), skip_prompt=True)
            self.assertEqual(res, "installed")
            mock_ask.assert_not_called()
            mock_dlg_cls.assert_called_once()

    def test_vlc_download_dialog_queue_poller(self):
        """Verify VLCDownloadDialog uses thread-safe queue polling to update UI without RuntimeError."""
        import tkinter as tk
        from main.vlc_setup_dialog import VLCDownloadDialog

        root = tk.Tk()
        root.withdraw()
        try:
            dlg = VLCDownloadDialog(root)
            self.assertTrue(dlg._polling_active)
            self.assertEqual(str(dlg._progress_bar.cget("mode")), "indeterminate")

            # Push multiple progress items to test coalescing
            dlg._ui_queue.put(("progress", (1000000, 10000000)))
            dlg._ui_queue.put(("progress", (5000000, 10000000)))
            dlg._poll_ui_queue()

            # Progress bar must switch to determinate and reflect coalesced progress (50%)
            self.assertEqual(str(dlg._progress_bar.cget("mode")), "determinate")
            self.assertAlmostEqual(dlg._progress_var.get(), 50.0)
            self.assertIn("50%", dlg._bytes_var.get())

            # Test phase change
            dlg._ui_queue.put(("phase", "Đang cài đặt VLC..."))
            dlg._poll_ui_queue()
            self.assertEqual(dlg._label_var.get(), "Đang cài đặt VLC...")

            # Clean up
            dlg._safe_destroy()
            self.assertFalse(dlg._polling_active)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
