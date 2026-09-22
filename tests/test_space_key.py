"""
Unit test for Spacebar pause/resume functionality.
Verifies Space triggers pause/resume on root, buttons, and video surface clicks,
while correctly preserving text input in Entry fields and button activations in dialogs.
"""

from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import MagicMock

from main.settings import SettingsManager
from main.theme import ThemeManager
from main.gui import MainWindow


class TestSpaceKeyPause(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings = SettingsManager(config_dir=self.config_dir)
        self.theme = ThemeManager(self.root)
        self.pause_mock = MagicMock()

        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings,
            theme_mgr=self.theme,
            on_play_request=MagicMock(),
            on_pause_toggle=self.pause_mock,
            on_seek_request=MagicMock(),
            on_seek_relative=MagicMock(),
            on_volume_change=MagicMock(),
            on_mute_toggle=MagicMock(),
            on_rate_change=MagicMock(),
        )

    def tearDown(self):
        try:
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def test_space_triggers_pause_on_root(self):
        self.root.focus_set()
        self.root.update()
        self.gui._on_space_pressed(MagicMock(widget=self.root))
        self.pause_mock.assert_called_once()

    def test_space_triggers_pause_on_button(self):
        self.gui.btn_rewind.focus_set()
        self.root.update()
        res = self.gui._on_button_space(MagicMock(widget=self.gui.btn_rewind))
        self.assertEqual(res, "break")
        self.pause_mock.assert_called_once()

    def test_space_ignored_when_typing_in_entry(self):
        self.gui.url_entry.focus_set()
        self.root.update()
        res = self.gui._on_space_pressed(MagicMock(widget=self.gui.url_entry))
        self.assertIsNone(res)
        self.pause_mock.assert_not_called()

    def test_space_in_dialog_invokes_dialog_button(self):
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        btn_dialog = ttk.Button(dlg, text="Save")
        btn_dialog.invoke = MagicMock()
        res = self.gui._on_button_space(MagicMock(widget=btn_dialog))
        self.assertEqual(res, "break")
        btn_dialog.invoke.assert_called_once()
        self.pause_mock.assert_not_called()
        dlg.destroy()

    def test_video_click_toggles_pause(self):
        event = MagicMock(x_root=100, y_root=100)
        self.gui._on_video_press(event)
        self.gui._on_video_release(event)
        # Fast-forward single click execution
        self.gui._execute_video_single_click()
        self.pause_mock.assert_called_once()

    def test_pip_borderless_toggle(self):
        self.assertFalse(self.gui._is_pip)
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)
        # Verify title bar / window decorations removed
        self.assertTrue(self.root.overrideredirect())
        # Toggle exit PiP
        self.gui.toggle_pip()
        self.assertFalse(self.gui._is_pip)
        self.assertFalse(self.root.overrideredirect())

    def test_pip_video_click_does_not_toggle_pause(self):
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)
        event = MagicMock(x_root=100, y_root=100)
        self.gui._on_video_press(event)
        self.gui._on_video_release(event)
        # Verify click timer was not set and pause was NOT invoked
        self.assertIsNone(self.gui._video_click_timer)
        self.pause_mock.assert_not_called()

    def test_pip_space_still_toggles_pause(self):
        self.gui.toggle_pip()
        self.root.focus_set()
        self.root.update()
        self.gui._on_space_pressed(MagicMock(widget=self.root))
        self.pause_mock.assert_called_once()

    def test_pip_edge_detection(self):
        # Corner bottom-right
        mode, cur = self.gui._detect_pip_region(475, 265, win_w=480, win_h=270)
        self.assertEqual(mode, "resize_br")
        self.assertEqual(cur, "size_nw_se")
        # Corner top-left
        mode, cur = self.gui._detect_pip_region(5, 5, win_w=480, win_h=270)
        self.assertEqual(mode, "resize_tl")
        self.assertEqual(cur, "size_nw_se")
        # Right edge
        mode, cur = self.gui._detect_pip_region(475, 100, win_w=480, win_h=270)
        self.assertEqual(mode, "resize_r")
        self.assertEqual(cur, "size_we")
        # Interior
        mode, cur = self.gui._detect_pip_region(240, 135, win_w=480, win_h=270)
        self.assertEqual(mode, "move")
        self.assertEqual(cur, "fleur")

    def test_pip_mouse_wheel_scaling(self):
        self.root.deiconify()
        self.gui.toggle_pip()
        self.gui.set_pip_size(480, 270)
        self.root.update()
        # Scroll up (+120) should increase width
        self.gui._on_video_wheel(MagicMock(delta=120))
        self.root.update()
        self.assertEqual(self.root.winfo_width(), 512)
        self.assertEqual(self.root.winfo_height(), int(512 * 9 / 16))
        self.root.withdraw()

    def test_pip_set_size_presets(self):
        self.root.deiconify()
        self.gui.set_pip_size(640, 360)
        self.root.update()
        self.assertTrue(self.gui._is_pip)
        self.assertEqual(self.root.winfo_width(), 640)
        self.assertEqual(self.root.winfo_height(), 360)
        self.root.withdraw()

    def test_pip_drag_resize_motion(self):
        self.root.deiconify()
        self.gui.set_pip_size(480, 270)
        self.root.update()
        self.gui._win_start_w = 480
        self.gui._win_start_h = 270
        self.gui._win_start_x = 100
        self.gui._win_start_y = 100
        self.gui._drag_start_x = 580
        self.gui._drag_start_y = 370
        self.gui._drag_mode = "resize_br"
        # Drag by +100px width
        motion_event = MagicMock(x_root=680, y_root=470)
        self.gui._on_video_motion(motion_event)
        self.root.update()
        self.assertEqual(self.root.winfo_width(), 580)
        self.assertEqual(self.root.winfo_height(), int(580 * 9 / 16))
        self.root.withdraw()

    def test_pip_corner_grip_press(self):
        self.root.deiconify()
        self.gui.toggle_pip()
        self.root.update()
        self.gui._on_grip_press(MagicMock(x_root=500, y_root=400))
        self.assertEqual(self.gui._drag_mode, "resize_br")
        self.root.withdraw()

    def test_pip_double_click_exits_pip(self):
        self.gui.toggle_pip()
        self.assertTrue(self.gui._is_pip)
        self.gui._on_video_double_click(MagicMock())
        self.assertFalse(self.gui._is_pip)


if __name__ == "__main__":
    unittest.main()
