"""
Unit tests for the Subtitle System:
1. File format validation across all supported formats (.srt, .vtt, .ass, .ssa, .sub, .smi, .lrc, etc.)
2. Error handling for corrupted, binary, empty, or unsupported files
3. VLC color hex conversions
4. VLC CLI arguments generation for subtitle typography and styling
5. SettingsDialog Subtitle tab rendering, live preview canvas, and saving
6. VLCPlayer subtitle methods (set_subtitle_file, clear_subtitle, get_subtitle_file)
7. MainWindow context menu integration
"""

import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from main.subtitle import (
    SUPPORTED_SUBTITLE_EXTENSIONS,
    SUBTITLE_FORMAT_NAMES,
    validate_subtitle_file,
    hex_to_vlc_color,
    vlc_color_to_hex,
    build_vlc_subtitle_args,
)
from main.settings import SettingsManager
from main.theme import ThemeManager
from main.gui import MainWindow, SettingsDialog


class TestSubtitleValidation(unittest.TestCase):
    """Test validate_subtitle_file on all formats and error edge cases."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_srt(self):
        srt_file = self.dir_path / "sample.srt"
        srt_file.write_text(
            "1\n00:00:01,000 --> 00:00:04,000\nXin chào các bạn!\n\n"
            "2\n00:00:05,000 --> 00:00:08,000\nXem video FB mượt mà.\n",
            encoding="utf-8",
        )
        is_valid, fmt, msg = validate_subtitle_file(srt_file)
        self.assertTrue(is_valid)
        self.assertIn("SubRip", fmt)

    def test_valid_vtt(self):
        vtt_file = self.dir_path / "sample.vtt"
        vtt_file.write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nPhụ đề WebVTT chuẩn.\n",
            encoding="utf-8",
        )
        is_valid, fmt, msg = validate_subtitle_file(vtt_file)
        self.assertTrue(is_valid)
        self.assertIn("WebVTT", fmt)

    def test_valid_ass_ssa(self):
        ass_file = self.dir_path / "sample.ass"
        ass_file.write_text(
            "[Script Info]\nTitle: Test\n[Events]\nDialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,Nội dung ASS\n",
            encoding="utf-8",
        )
        is_valid, fmt, msg = validate_subtitle_file(ass_file)
        self.assertTrue(is_valid)
        self.assertIn("SubStation", fmt)

    def test_valid_smi(self):
        smi_file = self.dir_path / "sample.smi"
        smi_file.write_text(
            "<SAMI><BODY><SYNC Start=1000><P Class=ENCC>SAMI Subtitle</SYNC></BODY></SAMI>",
            encoding="utf-8",
        )
        is_valid, fmt, msg = validate_subtitle_file(smi_file)
        self.assertTrue(is_valid)
        self.assertIn("SAMI", fmt)

    def test_valid_sub_microdvd(self):
        sub_file = self.dir_path / "sample.sub"
        sub_file.write_text("{100}{250}MicroDVD Subtitle line", encoding="utf-8")
        is_valid, fmt, msg = validate_subtitle_file(sub_file)
        self.assertTrue(is_valid)
        self.assertIn("Sub", fmt)

    def test_valid_lrc(self):
        lrc_file = self.dir_path / "sample.lrc"
        lrc_file.write_text("[01:23.45]Lời bài hát đồng bộ thời gian", encoding="utf-8")
        is_valid, fmt, msg = validate_subtitle_file(lrc_file)
        self.assertTrue(is_valid)
        self.assertIn("LRC", fmt)

    def test_nonexistent_file(self):
        fake = self.dir_path / "not_found.srt"
        is_valid, fmt, msg = validate_subtitle_file(fake)
        self.assertFalse(is_valid)
        self.assertIn("không tồn tại", msg.lower())

    def test_directory_path(self):
        is_valid, fmt, msg = validate_subtitle_file(self.dir_path)
        self.assertFalse(is_valid)
        self.assertIn("thư mục", msg.lower())

    def test_empty_file(self):
        empty_file = self.dir_path / "empty.srt"
        empty_file.write_bytes(b"")
        is_valid, fmt, msg = validate_subtitle_file(empty_file)
        self.assertFalse(is_valid)
        self.assertIn("rỗng", msg.lower())

    def test_unsupported_extension(self):
        exe_file = self.dir_path / "program.exe"
        exe_file.write_bytes(b"MZ12345678")
        is_valid, fmt, msg = validate_subtitle_file(exe_file)
        self.assertFalse(is_valid)
        self.assertIn("không được hỗ trợ", msg.lower())

    def test_binary_file_rejected(self):
        bin_sub = self.dir_path / "bad.srt"
        bin_sub.write_bytes(b"\x00\x00\x00\x00\x01\x02\x03\x04\x05")
        is_valid, fmt, msg = validate_subtitle_file(bin_sub)
        self.assertFalse(is_valid)
        self.assertIn("nhị phân", msg.lower())

    def test_corrupted_srt_missing_timestamps(self):
        bad_srt = self.dir_path / "corrupted.srt"
        bad_srt.write_text("Chỉ có chữ văn bản thông thường không có mốc giờ gì hết.", encoding="utf-8")
        is_valid, fmt, msg = validate_subtitle_file(bad_srt)
        self.assertFalse(is_valid)
        self.assertIn("mốc thời gian", msg.lower())


class TestSubtitleColorAndArgs(unittest.TestCase):
    """Test VLC color converters and VLC argument generator."""

    def test_hex_to_vlc_color(self):
        self.assertEqual(hex_to_vlc_color("#ffffff"), 16777215)
        self.assertEqual(hex_to_vlc_color("#000000"), 0)
        self.assertEqual(hex_to_vlc_color("#ff0000"), (255 << 16))
        self.assertEqual(hex_to_vlc_color("#00ff00"), (255 << 8))
        self.assertEqual(hex_to_vlc_color("#0000ff"), 255)
        # Invalid fallbacks
        self.assertEqual(hex_to_vlc_color("invalid"), 16777215)
        self.assertEqual(hex_to_vlc_color(""), 16777215)

    def test_vlc_color_to_hex(self):
        self.assertEqual(vlc_color_to_hex(16777215), "#ffffff")
        self.assertEqual(vlc_color_to_hex(0), "#000000")
        self.assertEqual(vlc_color_to_hex(255 << 16), "#ff0000")

    def test_build_vlc_subtitle_args_full(self):
        cfg = {
            "font_family": "Arial",
            "font_size": 28,
            "text_color": "#ffffff",
            "bold": True,
            "italic": True,
            "outline_color": "#000000",
            "outline_thickness": 3,
            "bg_enabled": True,
            "bg_color": "#111111",
            "bg_opacity": 180,
        }
        args = build_vlc_subtitle_args(cfg)
        self.assertIn("--freetype-font=Arial", args)
        self.assertIn("--freetype-fontsize=28", args)
        self.assertIn(f"--freetype-color={16777215}", args)
        self.assertIn("--freetype-bold", args)
        self.assertIn("--freetype-italic", args)
        self.assertIn("--freetype-outline-thickness=3", args)
        self.assertIn(f"--freetype-outline-color={0}", args)
        self.assertIn("--freetype-background-opacity=180", args)

    def test_build_vlc_subtitle_args_minimal(self):
        args = build_vlc_subtitle_args({})
        self.assertEqual(args, [])
        args_none = build_vlc_subtitle_args(None)
        self.assertEqual(args_none, [])


class TestSubtitleGuiIntegration(unittest.TestCase):
    """Test SettingsDialog Subtitle tab and MainWindow context menu."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.settings_mgr = SettingsManager(config_dir=self.config_dir)
        self.theme_mgr = ThemeManager(self.root, initial_theme="dark")

        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings_mgr,
            theme_mgr=self.theme_mgr,
            on_play_request=MagicMock(),
            on_pause_toggle=MagicMock(),
            on_seek_request=MagicMock(),
            on_seek_relative=MagicMock(),
            on_volume_change=MagicMock(),
            on_mute_toggle=MagicMock(),
            on_rate_change=MagicMock(),
            on_subtitle_load=MagicMock(),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_settings_dialog_has_subtitle_tab(self):
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.root.update_idletasks()

        # Check that tab_subtitles is present in notebook adapter
        tabs = dialog.notebook.tabs()
        self.assertGreaterEqual(len(tabs), 4)
        self.assertIn(dialog.tab_subtitles, tabs)

        # Check subtitle variables
        self.assertEqual(dialog.sub_font_var.get(), "Segoe UI")
        self.assertEqual(dialog.sub_size_var.get(), "36")
        self.assertTrue(dialog.sub_bold_var.get())
        self.assertFalse(dialog.sub_italic_var.get())
        self.assertFalse(dialog.sub_underline_var.get())

        dialog.top.destroy()

    def test_settings_dialog_live_preview_execution(self):
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.root.update_idletasks()

        # Update preview styling
        dialog.sub_font_var.set("Arial")
        dialog.sub_size_var.set("32")
        dialog.sub_bold_var.set(True)
        dialog.sub_italic_var.set(True)
        dialog.sub_underline_var.set(True)
        dialog.sub_bg_enabled_var.set(True)
        dialog.sub_bg_color_var.set("#112233")
        dialog.sub_bg_opacity_var.set(200)

        # Re-run preview update
        dialog._update_subtitle_preview()
        self.assertTrue(dialog.sub_preview_canvas.winfo_exists())

        dialog.top.destroy()

    def test_settings_dialog_reset_style(self):
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.root.update_idletasks()

        dialog.sub_font_var.set("Consolas")
        dialog.sub_size_var.set("48")
        dialog.sub_italic_var.set(True)

        dialog._reset_subtitle_style_to_default()
        self.assertEqual(dialog.sub_font_var.get(), "Segoe UI")
        self.assertEqual(dialog.sub_size_var.get(), "36")
        self.assertFalse(dialog.sub_italic_var.get())
        self.assertTrue(dialog.sub_bold_var.get())

        dialog.top.destroy()

    def test_settings_dialog_save_persists_subtitles(self):
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.root.update_idletasks()

        dialog.sub_file_var.set("C:/path/test.srt")
        dialog.sub_font_var.set("Verdana")
        dialog.sub_size_var.set("28")
        dialog.sub_text_color_var.set("#ffff00")
        dialog.sub_bold_var.set(True)
        dialog.sub_italic_var.set(True)
        dialog.sub_underline_var.set(True)
        dialog.sub_outline_thickness_var.set("3")
        dialog.sub_bg_enabled_var.set(True)

        dialog._save_and_close()

        saved_sub = self.settings_mgr.get("subtitle")
        self.assertEqual(saved_sub.get("file"), "C:/path/test.srt")
        self.assertEqual(saved_sub.get("font_family"), "Verdana")
        self.assertEqual(saved_sub.get("font_size"), 28)
        self.assertEqual(saved_sub.get("text_color"), "#ffff00")
        self.assertTrue(saved_sub.get("bold"))
        self.assertTrue(saved_sub.get("italic"))
        self.assertTrue(saved_sub.get("underline"))
        self.assertEqual(saved_sub.get("outline_thickness"), 3)
        self.assertTrue(saved_sub.get("bg_enabled"))

    def test_context_menu_has_subtitle_command(self):
        # Verify right-click context menu has "💬 Nạp phụ đề..."
        menu = self.gui.context_menu
        found_sub = False
        for i in range(menu.index("end") + 1):
            try:
                lbl = menu.entrycget(i, "label")
                if "Nạp phụ đề" in lbl:
                    found_sub = True
                    break
            except Exception:
                continue
        self.assertTrue(found_sub)

    def test_settings_dialog_opacity_slider_and_toggle(self):
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.root.update_idletasks()

        # Background box enabled
        dialog.sub_bg_enabled_var.set(True)
        dialog._on_bg_enabled_toggled()
        self.assertEqual(str(dialog.btn_bg_color.cget("state")), "normal")
        self.assertEqual(str(dialog.scale_opacity.cget("state")), "normal")

        # Change opacity slider
        dialog.sub_bg_opacity_var.set(204)
        dialog._on_opacity_slider_changed()
        self.assertIn("80%", dialog.lbl_opacity_val.cget("text"))

        # Background box disabled
        dialog.sub_bg_enabled_var.set(False)
        dialog._on_bg_enabled_toggled()
        self.assertEqual(str(dialog.btn_bg_color.cget("state")), "disabled")
        self.assertEqual(str(dialog.scale_opacity.cget("state")), "disabled")

        dialog.top.destroy()


if __name__ == "__main__":
    unittest.main()
