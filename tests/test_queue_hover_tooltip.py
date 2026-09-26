"""Unit tests for QueueItem description, Hover Tooltip, and BulkImportDialog."""

from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock

from main.gui import MainWindow, ListboxTooltip
from main.playback_queue import QueueItem, PlaybackQueue
from main.settings import SettingsManager
from main.theme import ThemeManager
from main.text_parser import ParsedVideoItem
from main.bulk_import_dialog import BulkImportDialog


class TestQueueHoverTooltipAndBulkImport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings = SettingsManager(config_dir=self.config_dir)
        self.theme = ThemeManager(self.root)

        self.on_bulk_import_queue = MagicMock()
        self.on_bulk_replace_and_play = MagicMock()

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
            on_bulk_import_queue=self.on_bulk_import_queue,
            on_bulk_replace_and_play=self.on_bulk_replace_and_play,
        )
        self.root.update_idletasks()

    def tearDown(self):
        try:
            if hasattr(self.gui, "queue_tooltip"):
                self.gui.queue_tooltip._hide()
            if hasattr(self.gui, "destroy"):
                self.gui.destroy()
            self.root.update_idletasks()
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.temp_dir.cleanup()

    def test_queue_item_description_snapshot_roundtrip(self):
        item = QueueItem(
            source_url="https://youtu.be/OiyX7zl1vQA",
            title="Tập 1",
            description="Phần 1-2",
        )
        self.assertEqual(item.description, "Phần 1-2")

        data = item.snapshot()
        self.assertEqual(data.get("description"), "Phần 1-2")

        restored = QueueItem.from_snapshot(data)
        self.assertEqual(restored.description, "Phần 1-2")
        self.assertEqual(restored.source_url, "https://youtu.be/OiyX7zl1vQA")

    def test_queue_item_tooltip_generation(self):
        rows = [
            {
                "queue_id": "q1",
                "source_url": "https://youtu.be/OiyX7zl1vQA",
                "title": "Phần 1-2",
                "description": "Phần 1-2",
                "status": "ready",
            },
            {
                "queue_id": "q2",
                "source_url": "https://youtu.be/iwUonNa2YJM",
                "title": "Video",
                "description": None,
                "status": "pending",
            }
        ]
        self.gui.refresh_queue(rows)

        # Tooltip for row 0 (has description)
        tip_0 = self.gui._get_queue_item_tooltip(0)
        self.assertIsNotNone(tip_0)
        self.assertIn("📌 Ngữ cảnh: Phần 1-2", tip_0)
        self.assertIn("https://youtu.be/OiyX7zl1vQA", tip_0)

        # Tooltip for row 1 (no description)
        tip_1 = self.gui._get_queue_item_tooltip(1)
        self.assertIsNotNone(tip_1)
        self.assertNotIn("Ngữ cảnh", tip_1)
        self.assertIn("https://youtu.be/iwUonNa2YJM", tip_1)

        # Tooltip for out-of-range index
        self.assertIsNone(self.gui._get_queue_item_tooltip(99))

    def test_bulk_import_dialog_parses_and_triggers_callbacks(self):
        sample_text = (
            "Phần 1: https://youtu.be/vid1\n"
            "Phần 2: https://youtu.be/vid2\n"
        )
        import_callback = MagicMock()
        replace_callback = MagicMock()

        dialog = BulkImportDialog(
            parent=self.root,
            theme_mgr=self.theme,
            on_import_to_queue=import_callback,
            on_replace_and_play=replace_callback,
            initial_text=sample_text,
        )
        self.root.update_idletasks()

        self.assertEqual(len(dialog.parsed_items), 2)
        self.assertEqual(dialog.parsed_items[0].description, "Phần 1")
        self.assertEqual(dialog.parsed_items[1].description, "Phần 2")

        # Test import to queue button
        dialog._import_to_queue()
        import_callback.assert_called_once()
        called_items = import_callback.call_args[0][0]
        self.assertEqual(len(called_items), 2)

    def test_listbox_tooltip_show_and_theme_is_dark(self):
        # 1. Verify theme_mgr.is_dark() works directly
        self.assertTrue(self.theme.is_dark())
        self.theme.apply_theme("light")
        self.assertFalse(self.theme.is_dark())
        self.theme.apply_theme("dark")
        self.assertTrue(self.theme.is_dark())

        # 2. Verify ListboxTooltip._show handles popup creation without AttributeError
        rows = [
            {
                "queue_id": "q1",
                "source_url": "https://youtu.be/OiyX7zl1vQA",
                "title": "Phần 1-2",
                "description": "Phần 1-2",
                "status": "ready",
            }
        ]
        self.gui.refresh_queue(rows)
        self.gui.queue_tooltip._show(0, 50, 50)
        self.assertIsNotNone(self.gui.queue_tooltip.tooltip_window)
        self.assertTrue(self.gui.queue_tooltip.tooltip_window.winfo_exists())

        # 3. Verify _hide cleans it up
        self.gui.queue_tooltip._hide()
        self.assertIsNone(self.gui.queue_tooltip.tooltip_window)

    def test_copy_all_queue_links(self):
        rows = [
            {
                "queue_id": "q1",
                "source_url": "https://youtu.be/vid1",
                "title": "Phần 1",
                "description": "Phần 1",
            },
            {
                "queue_id": "q2",
                "source_url": "https://youtu.be/vid2",
                "title": "https://youtu.be/vid2",
                "description": None,
            },
        ]
        self.gui.refresh_queue(rows)
        self.gui._copy_all_queue_links()
        clip_content = self.root.clipboard_get()
        self.assertIn("Phần 1: https://youtu.be/vid1", clip_content)
        self.assertIn("https://youtu.be/vid2", clip_content)

    def test_export_queue_to_file_txt_and_json(self):
        rows = [
            {
                "queue_id": "q1",
                "source_url": "https://youtu.be/vid1",
                "title": "Tập 1",
                "description": "Phần 1-2",
            }
        ]
        self.gui.refresh_queue(rows)

        # Test TXT export
        export_txt = self.config_dir / "exported_playlist.txt"
        with unittest.mock.patch("tkinter.filedialog.asksaveasfilename", return_value=str(export_txt)):
            self.gui._export_queue_to_file()
        self.assertTrue(export_txt.is_file())
        self.assertIn("Phần 1-2: https://youtu.be/vid1", export_txt.read_text(encoding="utf-8"))

        # Test JSON export
        export_json = self.config_dir / "exported_playlist.json"
        with unittest.mock.patch("tkinter.filedialog.asksaveasfilename", return_value=str(export_json)):
            self.gui._export_queue_to_file()
        self.assertTrue(export_json.is_file())
        self.assertIn("Phần 1-2", export_json.read_text(encoding="utf-8"))

    def test_inline_queue_persist_toggle(self):
        self.assertTrue(self.gui.queue_persist_inline_var.get())
        # Toggle off
        self.gui.queue_persist_inline_var.set(False)
        self.gui.settings.set("playback", "queue_persist", False)
        self.assertFalse(self.gui.settings.get("playback", "queue_persist"))


if __name__ == "__main__":
    unittest.main()
