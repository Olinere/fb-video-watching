"""
Themed MenuBar for FB Video Watcher.
Provides a modern in-window desktop Menu Bar that harmonizes completely
with Dark and Light themes, eliminating the glaring white Win32 non-client menubar.
"""

import tkinter as tk
from typing import Optional, Dict, Any, List


class ThemedMenuBar(tk.Frame):
    """
    Sleek themed menu bar rendered in the window client area.
    Eliminates the glaring white Windows Win32 non-client menubar strip
    by drawing directly with the application theme colors.
    """

    def __init__(self, master: tk.Tk, colors: Dict[str, str], **kwargs):
        super().__init__(master, bg=colors.get("surface", "#1e1e1e"), bd=0, height=28, **kwargs)
        self.colors = colors
        self._buttons: List[tk.Label] = []
        self._menus: Dict[tk.Label, tk.Menu] = {}
        self._btn_by_menu: Dict[tk.Menu, tk.Label] = {}
        self._active_btn: Optional[tk.Label] = None
        self._menu_open: bool = False

        # Bottom separator border
        self._sep = tk.Frame(self, bg=colors.get("border", "#2d2d2d"), height=1)
        self._sep.pack(side=tk.BOTTOM, fill=tk.X)

        # Container for menu buttons
        self._btn_container = tk.Frame(self, bg=colors.get("surface", "#1e1e1e"))
        self._btn_container.pack(side=tk.LEFT, fill=tk.Y)

        # Global click to close
        try:
            self._root_bind_id = master.bind("<Button-1>", self._on_root_click, add="+")
            self._esc_bind_id = master.bind("<Escape>", lambda e: self.close_active_menu(), add="+")
        except Exception:
            pass

    def add_cascade(self, label: str, menu: tk.Menu, **kwargs) -> tk.Label:
        """Add a top-level cascade menu button to the menu bar."""
        btn = tk.Label(
            self._btn_container,
            text=f" {label} ",
            bg=self.colors.get("surface", "#1e1e1e"),
            fg=self.colors.get("fg", "#e0e0e0"),
            font=("Segoe UI", 9),
            padx=8,
            pady=3,
            cursor="hand2",
        )
        btn.pack(side=tk.LEFT)
        self._buttons.append(btn)
        self._menus[btn] = menu
        self._btn_by_menu[menu] = btn

        self.style_menu(menu)

        btn.bind("<Enter>", lambda e, b=btn: self._on_btn_enter(b))
        btn.bind("<Leave>", lambda e, b=btn: self._on_btn_leave(b))
        btn.bind("<Button-1>", lambda e, b=btn: self._on_btn_click(b))
        return btn

    def style_menu(self, menu: tk.Menu) -> None:
        """Apply active theme palette to a dropdown menu and its cascades."""
        if not menu or not isinstance(menu, tk.Menu):
            return
        try:
            accent = self.colors.get("accent", "#00d2ff")
            active_fg = "#000000" if str(accent).lower() in ["#00d2ff", "#00bcd4", "#ffffff", "#00e5ff", "#4cc2ff"] else "#ffffff"
            surface_col = self.colors.get("surface", "#ffffff" if self.colors.get("bg", "") == "#f3f3f3" else "#1e1e1e")
            fg_col = self.colors.get("fg", "#1a1a1a" if surface_col == "#ffffff" else "#e0e0e0")
            menu.configure(
                bg=surface_col,
                fg=fg_col,
                activebackground=accent,
                activeforeground=active_fg,
                activeborderwidth=0,
                bd=1,
                relief=tk.SOLID,
                font=("Segoe UI", 9),
            )
            last = menu.index("end")
            if last is not None:
                for i in range(last + 1):
                    try:
                        if menu.type(i) == "cascade":
                            sub_name = menu.entrycget(i, "menu")
                            if sub_name:
                                sub_menu = menu.nametowidget(sub_name)
                                self.style_menu(sub_menu)
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_btn_enter(self, btn: tk.Label) -> None:
        if self._menu_open:
            if self._active_btn != btn:
                self._open_menu(btn)
        else:
            btn.configure(bg=self.colors.get("surface_variant", "#2a2a2a"))

    def _on_btn_leave(self, btn: tk.Label) -> None:
        if not self._menu_open or self._active_btn != btn:
            surface_col = self.colors.get("surface", "#ffffff" if self.colors.get("bg", "") == "#f3f3f3" else "#1e1e1e")
            fg_col = self.colors.get("fg", "#1a1a1a" if surface_col == "#ffffff" else "#e0e0e0")
            btn.configure(bg=surface_col, fg=fg_col)

    def _on_btn_click(self, btn: tk.Label) -> None:
        if self._menu_open and self._active_btn == btn:
            self.close_active_menu()
        else:
            self._open_menu(btn)

    def _open_menu(self, btn: tk.Label) -> None:
        self.close_active_menu()
        menu = self._menus.get(btn)
        if not menu:
            return

        self._active_btn = btn
        self._menu_open = True
        btn.configure(
            bg=self.colors.get("surface_variant", "#2a2a2a"),
            fg=self.colors.get("accent", "#00d2ff"),
        )

        # Position right beneath the button
        try:
            x = btn.winfo_rootx()
            y = btn.winfo_rooty() + btn.winfo_height()
            menu.post(x, y)
        except Exception:
            pass

    def close_active_menu(self) -> None:
        """Close any currently open dropdown menu."""
        if self._active_btn:
            menu = self._menus.get(self._active_btn)
            if menu:
                try:
                    menu.unpost()
                except Exception:
                    pass
            surface_col = self.colors.get("surface", "#ffffff" if self.colors.get("bg", "") == "#f3f3f3" else "#1e1e1e")
            fg_col = self.colors.get("fg", "#1a1a1a" if surface_col == "#ffffff" else "#e0e0e0")
            self._active_btn.configure(bg=surface_col, fg=fg_col)
            self._active_btn = None
        self._menu_open = False

    def _on_root_click(self, event) -> None:
        if self._menu_open:
            w = event.widget
            if w not in self._buttons and w != self and w != self._btn_container:
                self.close_active_menu()

    def apply_theme(self, colors: Dict[str, str]) -> None:
        """Dynamically re-theme menu bar and all cascade dropdown menus."""
        self.colors = colors
        surface_col = colors.get("surface", "#ffffff" if colors.get("bg", "") == "#f3f3f3" else "#1e1e1e")
        fg_col = colors.get("fg", "#1a1a1a" if surface_col == "#ffffff" else "#e0e0e0")
        border_col = colors.get("border", "#d1d1d1" if surface_col == "#ffffff" else "#2d2d2d")

        self.configure(bg=surface_col)
        self._sep.configure(bg=border_col)
        self._btn_container.configure(bg=surface_col)
        for b in self._buttons:
            b.configure(
                bg=surface_col,
                fg=fg_col,
            )
            m = self._menus.get(b)
            if m:
                self.style_menu(m)

    def entryconfigure(self, *args, **kwargs) -> None:
        """Adapter method for menu entry configuration compatibility."""
        pass
