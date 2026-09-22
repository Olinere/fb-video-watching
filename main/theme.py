"""
Theme management module for Light, Dark, and System theme modes.
Strictly adheres to specs.md §4.5 and Agent.md §5.2.E (Theme Abstraction).
"""

import sys
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Optional

from main.platform_utils import set_windows_dark_titlebar


class ThemeManager:
    """Manages application-wide theme styling, palette definitions, and OS sync."""

    # Modern color palette (harmonized with Windows 11 Fluent dark/light aesthetics)
    PALETTES: Dict[str, Dict[str, str]] = {
        "light": {
            "bg": "#f3f3f3",
            "fg": "#1a1a1a",
            "surface": "#ffffff",
            "surface_variant": "#e5e5e5",
            "accent": "#0067c0",
            "accent_hover": "#1878d6",
            "border": "#d1d1d1",
            "disabled": "#8a8a8a",
            "video_surface": "#000000",
            "entry_bg": "#ffffff",
            "entry_fg": "#000000",
        },
        "dark": {
            "bg": "#202020",
            "fg": "#f0f0f0",
            "surface": "#2c2c2c",
            "surface_variant": "#383838",
            "accent": "#4cc2ff",
            "accent_hover": "#60cdff",
            "border": "#404040",
            "disabled": "#6e6e6e",
            "video_surface": "#000000",
            "entry_bg": "#2d2d2d",
            "entry_fg": "#ffffff",
        },
    }

    def __init__(self, root: tk.Tk, initial_theme: str = "system"):
        """
        Initialize ThemeManager.

        Args:
            root: Root Tk window.
            initial_theme: 'system' | 'dark' | 'light'.
        """
        self.root = root
        self.mode = initial_theme
        self.current_theme = "dark"  # Resolved theme ('dark' or 'light')
        self.style = ttk.Style(self.root)
        self.apply_theme(self.mode)

    def _detect_system_theme(self) -> str:
        """Query Windows registry to detect OS Dark/Light preference."""
        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if value == 1 else "dark"
            except Exception:
                pass
        return "dark"

    def apply_theme(self, mode: str) -> None:
        """
        Apply theme mode ('system', 'dark', 'light').
        Configures ttk.Style, root background, and native titlebar.
        """
        self.mode = mode.lower()
        if self.mode == "system":
            self.current_theme = self._detect_system_theme()
        elif self.mode in ("dark", "light"):
            self.current_theme = self.mode
        else:
            self.current_theme = "dark"

        colors = self.PALETTES[self.current_theme]
        is_dark = (self.current_theme == "dark")

        # Configure root window background
        self.root.configure(bg=colors["bg"])

        # Configure native Windows Title Bar
        set_windows_dark_titlebar(self.root, dark=is_dark)

        # Apply sv-ttk theme if available (Windows 11 Fluent Design)
        try:
            import sv_ttk
            sv_ttk.set_theme(self.current_theme)
        except Exception:
            self._apply_ttk_styles(colors)

    def _apply_ttk_styles(self, colors: Dict[str, str]) -> None:
        """Update ttk.Style elements with current palette."""
        style = self.style

        # Base Frame & Label
        style.configure("TFrame", background=colors["bg"])
        style.configure("Surface.TFrame", background=colors["surface"])
        style.configure(
            "TLabel",
            background=colors["bg"],
            foreground=colors["fg"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Title.TLabel",
            background=colors["bg"],
            foreground=colors["fg"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=colors["bg"],
            foreground=colors["disabled"],
            font=("Segoe UI", 8),
        )

        # Buttons
        style.configure(
            "TButton",
            font=("Segoe UI", 9),
            padding=(8, 4),
            relief="flat",
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(10, 4),
        )

        # Entry & Combobox
        style.configure(
            "TEntry",
            fieldbackground=colors["entry_bg"],
            foreground=colors["entry_fg"],
            insertcolor=colors["fg"],
            padding=4,
        )
        style.configure(
            "TCombobox",
            fieldbackground=colors["entry_bg"],
            foreground=colors["entry_fg"],
            padding=3,
        )

        # Scale / Sliders
        style.configure(
            "Horizontal.TScale",
            background=colors["bg"],
            troughcolor=colors["surface_variant"],
        )

    def get_color(self, key: str) -> str:
        """Get color code from current active theme palette."""
        return self.PALETTES[self.current_theme].get(key, "#000000")
