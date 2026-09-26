"""
GUI package for FB Video Watcher.
Modularized architecture for clean maintainability.
Provides backward-compatible imports for MainWindow, SettingsDialog,
components, and standard dialog helpers.
"""

from tkinter import messagebox, filedialog, simpledialog, colorchooser
from main.theme import ThemeManager

from main.gui.components import (
    SeekBarController,
    OSDOverlay,
    PiPProgressOverlay,
    ListboxTooltip,
)
from main.gui.menu_bar import ThemedMenuBar
from main.gui.settings_dialog import SettingsDialog
from main.gui.main_window import MainWindow

__all__ = [
    "MainWindow",
    "SettingsDialog",
    "ThemedMenuBar",
    "SeekBarController",
    "OSDOverlay",
    "PiPProgressOverlay",
    "ListboxTooltip",
    "ThemeManager",
    "messagebox",
    "filedialog",
    "simpledialog",
    "colorchooser",
]
