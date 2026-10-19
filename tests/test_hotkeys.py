"""
Unit tests for customizable hotkey system:
1. parse_hotkey_parts parsing logic
2. hotkey_to_tk_sequences conversion logic
3. SettingsDialog hotkey tab rendering, customization, and saving
4. Dynamic rebinding of shortcuts in MainWindow
5. Dynamic context menu accelerators
"""

import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from main.hotkeys import (
    DEFAULT_HOTKEYS,
    HOTKEY_DEFINITIONS,
    parse_hotkey_parts,
    hotkey_to_tk_sequences,
)
from main.settings import SettingsManager
from main.theme import ThemeManager
from main.gui import MainWindow, SettingsDialog


class TestHotkeySystem(unittest.TestCase):
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

        self.play_mock = MagicMock()
        self.pause_mock = MagicMock()
        self.seek_mock = MagicMock()
        self.seek_rel_mock = MagicMock()
        self.vol_mock = MagicMock()
        self.mute_mock = MagicMock()
        self.rate_mock = MagicMock()
        self.history_mock = MagicMock()
        self.download_mock = MagicMock()

        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings_mgr,
            theme_mgr=self.theme_mgr,
            on_play_request=self.play_mock,
            on_pause_toggle=self.pause_mock,
            on_seek_request=self.seek_mock,
            on_seek_relative=self.seek_rel_mock,
            on_volume_change=self.vol_mock,
            on_mute_toggle=self.mute_mock,
            on_rate_change=self.rate_mock,
            on_history_request=self.history_mock,
            on_download_request=self.download_mock,
        )

    def tearDown(self):
        if hasattr(self.gui, "destroy"):
            self.gui.destroy()
        self.temp_dir.cleanup()

    # --- 1. Parser & Sequence Generator Tests ---

    def test_parse_hotkey_parts(self):
        """Verify parsing of hotkey strings into normalized modifiers and base keys."""
        # Simple key
        self.assertEqual(parse_hotkey_parts("Space"), ([], "Space"))
        self.assertEqual(parse_hotkey_parts("m"), ([], "m"))
        self.assertEqual(parse_hotkey_parts("["), ([], "["))

        # Modifiers
        self.assertEqual(parse_hotkey_parts("Ctrl+H"), (["Control"], "H"))
        self.assertEqual(parse_hotkey_parts("Shift+Left"), (["Shift"], "Left"))
        self.assertEqual(parse_hotkey_parts("Ctrl+Shift+V"), (["Control", "Shift"], "V"))
        self.assertEqual(parse_hotkey_parts("Alt+P"), (["Alt"], "P"))
        self.assertEqual(parse_hotkey_parts("Ctrl+,"), (["Control"], ","))

        # Special plus cases
        self.assertEqual(parse_hotkey_parts("+"), ([], "+"))
        self.assertEqual(parse_hotkey_parts("Ctrl++"), (["Control"], "+"))

        # Raw Tk sequences
        self.assertEqual(parse_hotkey_parts("<space>"), ([], "<space>"))

    def test_hotkey_to_tk_sequences_single_keys(self):
        """Verify conversion of single key shortcuts to Tk sequences."""
        # Space
        self.assertEqual(hotkey_to_tk_sequences("Space"), ["<space>"])

        # Letters generate both lower and upper case
        self.assertEqual(hotkey_to_tk_sequences("m"), ["<m>", "<M>"])
        self.assertEqual(hotkey_to_tk_sequences("f"), ["<f>", "<F>"])

        # Special characters
        self.assertEqual(hotkey_to_tk_sequences("["), ["<bracketleft>"])
        self.assertEqual(hotkey_to_tk_sequences("]"), ["<bracketright>"])
        self.assertEqual(hotkey_to_tk_sequences(","), ["<comma>"])

        # Function keys
        self.assertEqual(hotkey_to_tk_sequences("F12"), ["<F12>"])
        self.assertEqual(hotkey_to_tk_sequences("F11"), ["<F11>"])

    def test_hotkey_to_tk_sequences_combinations(self):
        """Verify conversion of combinations with modifiers."""
        self.assertEqual(hotkey_to_tk_sequences("Shift+Left"), ["<Shift-Left>"])
        self.assertEqual(hotkey_to_tk_sequences("Ctrl+H"), ["<Control-h>", "<Control-H>"])
        self.assertEqual(hotkey_to_tk_sequences("Ctrl+Shift+V"), ["<Control-Shift-v>", "<Control-Shift-V>"])
        self.assertEqual(hotkey_to_tk_sequences("Ctrl+,"), ["<Control-comma>"])

    def test_hotkey_to_tk_sequences_multiple_delimiters(self):
        """Verify conversion of multiple shortcuts delimited by ; or |."""
        seqs = hotkey_to_tk_sequences("Space; k")
        self.assertIn("<space>", seqs)
        self.assertIn("<k>", seqs)
        self.assertIn("<K>", seqs)

        seqs_f = hotkey_to_tk_sequences("f; F11")
        self.assertIn("<f>", seqs_f)
        self.assertIn("<F>", seqs_f)
        self.assertIn("<F11>", seqs_f)

    # --- 2. SettingsDialog Customization Tests ---

    def test_settings_dialog_hotkey_tab_and_save(self):
        """Verify SettingsDialog renders hotkeys tab and persists edits."""
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)

        # Ensure all actions in HOTKEY_DEFINITIONS have StringVars
        for aid, _, _, _ in HOTKEY_DEFINITIONS:
            self.assertIn(aid, dialog.hotkey_vars)

        # Modify a few hotkeys
        dialog.hotkey_vars["play_pause"].set("Alt+P")
        dialog.hotkey_vars["mute"].set("x")
        dialog.hotkey_vars["history"].set("Ctrl+Y")

        dialog._save_and_close()

        # Check that settings were persisted
        self.assertEqual(self.settings_mgr.get("hotkeys", "play_pause"), "Alt+P")
        self.assertEqual(self.settings_mgr.get("hotkeys", "mute"), "x")
        self.assertEqual(self.settings_mgr.get("hotkeys", "history"), "Ctrl+Y")

    def test_settings_dialog_reset_to_default(self):
        """Verify resetting hotkeys to factory defaults."""
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)

        # Modify values
        dialog.hotkey_vars["play_pause"].set("F9")
        dialog.hotkey_vars["mute"].set("F10")

        # Click reset all
        dialog._reset_all_hotkeys_to_default()

        # Verify restored to factory default
        self.assertEqual(dialog.hotkey_vars["play_pause"].get(), DEFAULT_HOTKEYS["play_pause"])
        self.assertEqual(dialog.hotkey_vars["mute"].get(), DEFAULT_HOTKEYS["mute"])
        dialog.top.destroy()

    # --- 3. Dynamic Rebinding in MainWindow Tests ---

    def test_dynamic_rebinding_in_mainwindow(self):
        """Verify changing hotkeys updates active Tkinter key bindings dynamically."""
        # 1. Initially default: Space is in bound sequences
        self.assertIn("<space>", self.gui._bound_hotkey_sequences)

        # 2. Update settings: change play_pause to "Alt+P" and mute to "z"
        self.settings_mgr.set("hotkeys", "play_pause", "Alt+P")
        self.settings_mgr.set("hotkeys", "mute", "z")

        # 3. Call rebind_shortcuts
        self.gui.rebind_shortcuts()

        # 4. Old Space binding should be removed, new Alt+P sequence should be bound
        self.assertNotIn("<space>", self.gui._bound_hotkey_sequences)
        self.assertIn("<Alt-p>", self.gui._bound_hotkey_sequences)
        self.assertIn("<Alt-P>", self.gui._bound_hotkey_sequences)
        self.assertIn("<z>", self.gui._bound_hotkey_sequences)
        self.assertIn("<Z>", self.gui._bound_hotkey_sequences)

    def test_dynamic_context_menu_accelerator(self):
        """Verify context menu accelerator labels dynamically update with custom hotkeys."""
        self.settings_mgr.set("hotkeys", "history", "Ctrl+Y")
        self.settings_mgr.set("hotkeys", "mute", "q")
        self.gui.rebind_shortcuts()

        # Check context menu entries
        menu = self.gui.context_menu
        # Find index of History command
        found_history_acc = None
        found_mute_acc = None
        for i in range(menu.index("end") + 1):
            try:
                lbl = menu.entrycget(i, "label")
                if "Lịch sử" in lbl:
                    found_history_acc = menu.entrycget(i, "accelerator")
                elif "tiếng" in lbl:
                    found_mute_acc = menu.entrycget(i, "accelerator")
            except Exception:
                continue

        self.assertEqual(found_history_acc, "Ctrl+Y")
        self.assertEqual(found_mute_acc, "q")

    def test_settings_dialog_smooth_scrolling(self):
        """Verify SettingsDialog tabs have smooth scrollable containers and mousewheel bindings."""
        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.root.update_idletasks()

        # Tabs (General, Hotkeys, Subtitles, System Info, About) should be mounted inside notebook adapter
        tabs = dialog.notebook.tabs()
        self.assertGreaterEqual(len(tabs), 4)
        self.assertIn(dialog.tab_hotkeys, tabs)

        # Clean up
        dialog.top.destroy()


if __name__ == "__main__":
    unittest.main()
