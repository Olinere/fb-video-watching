"""
Hotkey configuration and Tkinter sequence mapping module.
Supports full user customization, multi-key shortcuts, modifiers, and key combinations.
"""

from typing import Dict, List, Tuple
import re

DEFAULT_HOTKEYS: Dict[str, str] = {
    "play_pause": "Space; k",
    "seek_backward": "Left; j",
    "seek_forward": "Right; l",
    "seek_backward_long": "Shift+Left",
    "seek_forward_long": "Shift+Right",
    "speed_down": "[",
    "speed_up": "]",
    "toggle_loop": "Ctrl+L",
    "toggle_ab_repeat": "Ctrl+B",
    "volume_up": "Up",
    "volume_down": "Down",
    "mute": "m",
    "fullscreen": "f; F11",
    "pip": "p",
    "pip_ratio": "Shift+P",
    "history": "Ctrl+H",
    "open_file": "Ctrl+O",
    "download": "Ctrl+S",
    "paste_and_play": "Ctrl+Shift+V",
    "settings": "Ctrl+,",
    "devlog": "F12; Ctrl+Shift+D",
    "queue": "Ctrl+Shift+Q",
    "next_track": "PageDown",
    "previous_track": "PageUp",
}

HOTKEY_DEFINITIONS: List[Tuple[str, str, str, str]] = [
    # (action_id, display_name, category, default_key)
    ("play_pause", "Phát / Tạm dừng", "🎬 Phát & Tua video", "Space; k"),
    ("seek_backward", "Tua lùi (bước ngắn)", "🎬 Phát & Tua video", "Left; j"),
    ("seek_forward", "Tua tới (bước ngắn)", "🎬 Phát & Tua video", "Right; l"),
    ("seek_backward_long", "Tua lùi (bước dài)", "🎬 Phát & Tua video", "Shift+Left"),
    ("seek_forward_long", "Tua tới (bước dài)", "🎬 Phát & Tua video", "Shift+Right"),
    ("speed_down", "Giảm tốc độ phát", "🎬 Phát & Tua video", "["),
    ("speed_up", "Tăng tốc độ phát", "🎬 Phát & Tua video", "]"),
    ("toggle_loop", "Bật / Tắt lặp lại video", "🎬 Phát & Tua video", "Ctrl+L"),
    ("toggle_ab_repeat", "Lặp đoạn A-B (Đặt A / B / Tắt)", "🎬 Phát & Tua video", "Ctrl+B"),
    ("next_track", "Video kế tiếp trong danh sách", "🎬 Phát & Tua video", "PageDown"),
    ("previous_track", "Video trước đó trong danh sách", "🎬 Phát & Tua video", "PageUp"),

    ("volume_up", "Tăng âm lượng (+5%)", "🔊 Âm thanh & Màn hình", "Up"),
    ("volume_down", "Giảm âm lượng (-5%)", "🔊 Âm thanh & Màn hình", "Down"),
    ("mute", "Tắt / Bật tiếng (Mute)", "🔊 Âm thanh & Màn hình", "m"),
    ("fullscreen", "Bật / Tắt Toàn màn hình", "🔊 Âm thanh & Màn hình", "f; F11"),
    ("pip", "Bật / Tắt Thu nhỏ (PiP)", "🔊 Âm thanh & Màn hình", "p"),
    ("pip_ratio", "Đổi tỷ lệ PiP (16:9 / 9:16)", "🔊 Âm thanh & Màn hình", "Shift+P"),

    ("open_file", "Mở file video trong máy", "⚡ Tiện ích & Bảng điều khiển", "Ctrl+O"),
    ("history", "Mở Lịch sử xem video", "⚡ Tiện ích & Bảng điều khiển", "Ctrl+H"),
    ("download", "Tải video về máy", "⚡ Tiện ích & Bảng điều khiển", "Ctrl+S"),
    ("paste_and_play", "Dán link & Phát ngay", "⚡ Tiện ích & Bảng điều khiển", "Ctrl+Shift+V"),
    ("settings", "Mở Bảng Cài đặt", "⚡ Tiện ích & Bảng điều khiển", "Ctrl+,"),
    ("devlog", "Bật / Tắt Bảng Devlog", "⚡ Tiện ích & Bảng điều khiển", "F12; Ctrl+Shift+D"),
    ("queue", "Bật / Tắt Hàng đợi", "⚡ Tiện ích & Bảng điều khiển", "Ctrl+Shift+Q"),
]

TK_KEY_MAP = {
    "space": "space",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "esc": "Escape",
    "escape": "Escape",
    "return": "Return",
    "enter": "Return",
    "tab": "Tab",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "[": "bracketleft",
    "]": "bracketright",
    "{": "braceleft",
    "}": "braceright",
    ",": "comma",
    ".": "period",
    "<": "less",
    ">": "greater",
    "/": "slash",
    "\\": "backslash",
    "-": "minus",
    "=": "equal",
    "+": "plus",
    ";": "semicolon",
    ":": "colon",
    "'": "apostrophe",
    '"': "quotedbl",
    "`": "grave",
    "~": "asciitilde",
}


def parse_hotkey_parts(shortcut: str) -> Tuple[List[str], str]:
    """
    Parse shortcut into list of modifiers and base key.
    E.g.:
      'Ctrl+Shift+V' -> (['Control', 'Shift'], 'V')
      'Shift+Left' -> (['Shift'], 'Left')
      'Space' -> ([], 'Space')
      'Ctrl++' -> (['Control'], '+')
    """
    s = shortcut.strip()
    if not s:
        return [], ""

    # Check if raw Tk sequence like "<space>" or "<Control-h>"
    if s.startswith("<") and s.endswith(">"):
        return [], s

    # Handle trailing '+' key, e.g. "Ctrl++" or just "+"
    if s == "+":
        return [], "+"
    if s.endswith("++"):
        prefix = s[:-2]
        mods = [m.strip() for m in prefix.split("+") if m.strip()]
        mod_norm = []
        for m in mods:
            ml = m.lower()
            if ml in ("ctrl", "control"):
                mod_norm.append("Control")
            elif ml == "shift":
                mod_norm.append("Shift")
            elif ml == "alt":
                mod_norm.append("Alt")
        return mod_norm, "+"

    parts = [p.strip() for p in s.split("+") if p.strip()]
    if not parts:
        return [], ""
    if len(parts) == 1:
        return [], parts[0]

    mod_norm = []
    for m in parts[:-1]:
        ml = m.lower()
        if ml in ("ctrl", "control"):
            mod_norm.append("Control")
        elif ml == "shift":
            mod_norm.append("Shift")
        elif ml == "alt":
            mod_norm.append("Alt")

    return mod_norm, parts[-1]


def hotkey_to_tk_sequences(hotkey_str: str) -> List[str]:
    """
    Convert human-readable shortcut(s) string into Tkinter event sequences.
    Multiple shortcuts can be delimited by ';' or '|'.
    E.g.:
      'Space; k' -> ['<space>', '<k>', '<K>']
      'Shift+Left' -> ['<Shift-Left>']
      'Ctrl+H' -> ['<Control-h>', '<Control-H>']
      'Ctrl+,' -> ['<Control-comma>']
      '[' -> ['<bracketleft>']
      'F12' -> ['<F12>']
    """
    if not hotkey_str:
        return []

    raw_shortcuts = [item.strip() for item in re.split(r"[;|]", hotkey_str) if item.strip()]
    sequences: List[str] = []

    for item in raw_shortcuts:
        if item.startswith("<") and item.endswith(">"):
            if item not in sequences:
                sequences.append(item)
            continue

        mods, raw_key = parse_hotkey_parts(item)
        if not raw_key:
            continue

        key_lower = raw_key.lower()
        if key_lower in TK_KEY_MAP:
            tk_base = TK_KEY_MAP[key_lower]
        elif re.match(r"^f([1-9]|1[0-2])$", key_lower):
            tk_base = raw_key.upper()
        else:
            tk_base = raw_key

        if not mods:
            if len(tk_base) == 1 and tk_base.isalpha():
                seq_low = f"<{tk_base.lower()}>"
                seq_up = f"<{tk_base.upper()}>"
                if seq_low not in sequences:
                    sequences.append(seq_low)
                if seq_up not in sequences:
                    sequences.append(seq_up)
            else:
                seq = f"<{tk_base}>"
                if seq not in sequences:
                    sequences.append(seq)
        else:
            mod_prefix = "-".join(mods)
            if len(tk_base) == 1 and tk_base.isalpha():
                s1 = f"<{mod_prefix}-{tk_base.lower()}>"
                s2 = f"<{mod_prefix}-{tk_base.upper()}>"
                if s1 not in sequences:
                    sequences.append(s1)
                if s2 not in sequences:
                    sequences.append(s2)
            else:
                seq = f"<{mod_prefix}-{tk_base}>"
                if seq not in sequences:
                    sequences.append(seq)

    return sequences
