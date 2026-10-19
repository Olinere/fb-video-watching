"""
Unit tests for jump_entry spacebar auto-colon conversion and WidgetTooltip.
Covers edge cases: pos 0, repeat colon, max colons, cursor advance, selection, unit formats, and tooltips.
"""

import unittest
import sys
import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock, patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.gui.components import WidgetTooltip
from main.gui.main_window import MainWindow
from main.timestamp import SUPPORTED_FORMATS_HELP


class TestJumpEntrySpaceLogic(unittest.TestCase):
    """Test spacebar auto-colon logic on jump_entry in MainWindow."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.entry = ttk.Entry(self.root)
        self.entry.pack()

        # Mock MainWindow minimal structure
        self.mw = MagicMock(spec=MainWindow)
        self.mw.jump_entry = self.entry
        self.mw._on_jump_entry_space = MainWindow._on_jump_entry_space.__get__(self.mw)

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_typing_digits_then_space_inserts_colon(self):
        """Typing digit then space should convert to ':'."""
        self.entry.insert(0, "1")
        self.entry.icursor(1)
        res = self.mw._on_jump_entry_space()
        self.assertEqual(res, "break")
        self.assertEqual(self.entry.get(), "1:")

        self.entry.insert(tk.END, "30")
        self.entry.icursor(len(self.entry.get()))
        res = self.mw._on_jump_entry_space()
        self.assertEqual(res, "break")
        self.assertEqual(self.entry.get(), "1:30:")

    def test_empty_or_pos_zero_does_not_insert_colon(self):
        """Pressing space at start of entry (index 0) must be rejected."""
        self.entry.delete(0, tk.END)
        self.entry.icursor(0)
        res = self.mw._on_jump_entry_space()
        self.assertEqual(res, "break")
        self.assertEqual(self.entry.get(), "")

    def test_repeated_space_after_colon_does_not_insert_second_colon(self):
        """Pressing space when previous char is ':' must be ignored."""
        self.entry.insert(0, "1:")
        self.entry.icursor(2)
        res = self.mw._on_jump_entry_space()
        self.assertEqual(res, "break")
        self.assertEqual(self.entry.get(), "1:")

    def test_cursor_advances_when_next_char_is_colon(self):
        """Cursor placed right before an existing colon should skip past it."""
        self.entry.insert(0, "1:30")
        self.entry.icursor(1)  # between '1' and ':'
        res = self.mw._on_jump_entry_space()
        self.assertEqual(res, "break")
        self.assertEqual(self.entry.get(), "1:30")  # no duplicate colon
        self.assertEqual(self.entry.index(tk.INSERT), 2)  # moved past colon

    def test_maximum_two_colons_enforced(self):
        """Cannot insert a 3rd colon when 2 colons already exist."""
        self.entry.insert(0, "1:20:30")
        self.entry.icursor(len(self.entry.get()))
        res = self.mw._on_jump_entry_space()
        self.assertEqual(res, "break")
        self.assertEqual(self.entry.get(), "1:20:30")

    def test_selection_replacement_clears_selection_cleanly(self):
        """Selecting all and pressing space should clear entry without stray colon."""
        self.entry.insert(0, "1:20:30")
        self.entry.selection_range(0, tk.END)
        res = self.mw._on_jump_entry_space()
        self.assertEqual(res, "break")
        self.assertEqual(self.entry.get(), "")

    def test_unit_format_allows_standard_space(self):
        """Typing '1h' then space must allow space (return None) for unit format."""
        self.entry.insert(0, "1h")
        self.entry.icursor(2)
        res = self.mw._on_jump_entry_space()
        self.assertIsNone(res)  # None allows Tkinter default space insertion

        self.entry.delete(0, tk.END)
        self.entry.insert(0, "30m")
        self.entry.icursor(3)
        res = self.mw._on_jump_entry_space()
        self.assertIsNone(res)


class TestWidgetTooltip(unittest.TestCase):
    """Test WidgetTooltip component."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.btn = ttk.Button(self.root, text="Test")
        self.btn.pack()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_tooltip_init_and_lifecycle(self):
        tip = WidgetTooltip(self.btn, "Test tooltip text", delay_ms=50)
        self.assertEqual(tip.text, "Test tooltip text")
        self.assertIsNone(tip.tooltip_window)

        # Trigger show
        tip._show()
        self.assertIsNotNone(tip.tooltip_window)

        # Trigger hide
        tip._hide()
        self.assertIsNone(tip.tooltip_window)


class TestJumpClickErrorGuidance(unittest.TestCase):
    """Test MainWindow._on_jump_click error display."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.entry = ttk.Entry(self.root)
        self.entry.pack()

        self.mw = MagicMock(spec=MainWindow)
        self.mw.jump_entry = self.entry
        self.mw.root = self.root
        self.mw._on_jump_click = MainWindow._on_jump_click.__get__(self.mw)

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    @patch("main.gui.main_window.messagebox.showwarning")
    def test_jump_click_shows_helpful_formats_on_invalid_input(self, mock_warn):
        self.entry.insert(0, "invalid_time")
        self.mw._on_jump_click()

        mock_warn.assert_called_once()
        title, msg = mock_warn.call_args[0]
        self.assertEqual(title, "Thời gian không hợp lệ")
        self.assertIn("Các định dạng thời gian được chấp nhận", msg)
        self.assertIn("1:30", msg)
        self.assertIn("2 00 50", msg)


if __name__ == "__main__":
    unittest.main()
