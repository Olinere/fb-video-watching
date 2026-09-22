"""
Subtitle management module.
Supports validation and format identification for all major subtitle formats (.srt, .vtt, .ass, .ssa, .sub, .smi, etc.),
color conversion for libVLC, and dynamic subtitle argument generation.
"""

from pathlib import Path
import re
from typing import Dict, Any, List, Optional, Tuple, Union

SUPPORTED_SUBTITLE_EXTENSIONS = (
    ".srt",
    ".vtt",
    ".ass",
    ".ssa",
    ".sub",
    ".smi",
    ".sami",
    ".idx",
    ".txt",
    ".lrc",
    ".ttml",
    ".dfxp",
)

SUBTITLE_FORMAT_NAMES = {
    ".srt": "SubRip Subtitle (.srt)",
    ".vtt": "WebVTT Subtitle (.vtt)",
    ".ass": "Advanced SubStation Alpha (.ass)",
    ".ssa": "SubStation Alpha (.ssa)",
    ".sub": "MicroDVD / SubViewer (.sub)",
    ".smi": "SAMI Synchronized Caption (.smi)",
    ".sami": "SAMI Synchronized Caption (.sami)",
    ".idx": "VobSub Index (.idx)",
    ".txt": "Text Subtitle (.txt)",
    ".lrc": "LRC Timed Lyrics (.lrc)",
    ".ttml": "Timed Text Markup Language (.ttml)",
    ".dfxp": "DFXP Timed Text (.dfxp)",
}

# Timestamp pattern matching standard SRT/VTT time ranges: 00:00:01,000 --> 00:00:04,000
TIMESTAMP_REGEX = re.compile(
    r"\d{1,2}:\d{2}:\d{2}[,\.]\d{2,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,\.]\d{2,3}"
)
MICRODVD_REGEX = re.compile(r"\{\d+\}\{\d+\}")
LRC_REGEX = re.compile(r"\[\d{1,2}:\d{2}[\.:]\d{2,3}\]")
SAMI_REGEX = re.compile(r"<SYNC\s+Start=\d+", re.IGNORECASE)
ASS_REGEX = re.compile(r"\[(Events|Script Info)\]|Dialogue:", re.IGNORECASE)


def hex_to_vlc_color(hex_str: str) -> int:
    """
    Convert hex color '#RRGGBB' to VLC integer format ((R << 16) | (G << 8) | B).
    Default fallback to white (16777215) if invalid.
    """
    if not hex_str:
        return 16777215
    cleaned = hex_str.strip().lstrip("#")
    if len(cleaned) == 6:
        try:
            r = int(cleaned[0:2], 16)
            g = int(cleaned[2:4], 16)
            b = int(cleaned[4:6], 16)
            return (r << 16) | (g << 8) | b
        except ValueError:
            return 16777215
    return 16777215


def vlc_color_to_hex(color_int: int) -> str:
    """Convert integer ((R << 16) | (G << 8) | B) to hex string '#RRGGBB'."""
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def validate_subtitle_file(file_path: Union[str, Path]) -> Tuple[bool, str, str]:
    """
    Validate whether the specified file is a valid, readable subtitle file.

    Args:
        file_path: Path to the candidate subtitle file.

    Returns:
        Tuple[is_valid: bool, format_name: str, message: str]:
            - is_valid: True if file is a recognized and syntactically valid subtitle.
            - format_name: Human-friendly name of the identified format.
            - message: Success message or detailed error description.
    """
    path = Path(file_path)

    # 1. Existence and file type check
    if not path.exists():
        return False, "Không tồn tại", f"File '{path.name}' không tồn tại trên hệ thống."
    if not path.is_file():
        return False, "Không phải file", f"Đường dẫn '{path.name}' là thư mục, không phải file."

    # 2. File size check (empty file or unreasonably huge binary file)
    size = path.stat().st_size
    if size == 0:
        return False, "File rỗng", "File phụ đề có dung lượng 0 byte (rỗng)."
    if size > 50 * 1024 * 1024:  # > 50MB is almost certainly a video or disk image, not a subtitle
        return False, "File quá lớn", "Dung lượng file vượt quá 50MB, không phải định dạng phụ đề hợp lệ."

    ext = path.suffix.lower()
    if ext not in SUPPORTED_SUBTITLE_EXTENSIONS:
        ext_list = ", ".join(SUPPORTED_SUBTITLE_EXTENSIONS)
        return (
            False,
            "Định dạng không hỗ trợ",
            f"Định dạng '{ext}' không được hỗ trợ. Các định dạng phụ đề được hỗ trợ: {ext_list}",
        )

    # 3. Read content header with encoding fallback
    encodings = ["utf-8-sig", "utf-8", "utf-16", "cp1258", "cp1252", "latin-1"]
    content: Optional[str] = None
    read_bytes = min(size, 64 * 1024)  # Inspect first 64KB

    with open(path, "rb") as f:
        raw = f.read(read_bytes)

    # Binary check: if file contains excessive null bytes (and not UTF-16), reject
    if b"\x00\x00\x00" in raw and not (raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff")):
        return False, "File nhị phân", "File chứa dữ liệu nhị phân, không phải định dạng văn bản phụ đề."

    for enc in encodings:
        try:
            content = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        return False, "Lỗi mã hóa", "Không thể giải mã văn bản của file phụ đề (hãy lưu file với mã hóa UTF-8)."

    # 4. Format-specific syntax verification
    format_name = SUBTITLE_FORMAT_NAMES.get(ext, f"Subtitle ({ext})")

    if ext == ".vtt":
        if "WEBVTT" in content or TIMESTAMP_REGEX.search(content):
            return True, format_name, f"Đã nhận diện thành công phụ đề WebVTT: '{path.name}'."
        return False, format_name, "File .vtt thiếu từ khóa 'WEBVTT' hoặc mốc thời gian (timestamp) chuẩn."

    if ext == ".srt":
        if TIMESTAMP_REGEX.search(content):
            return True, format_name, f"Đã nhận diện thành công phụ đề SubRip: '{path.name}'."
        # Fallback: check if lines have numbers and arrows
        if "-->" in content:
            return True, format_name, f"Đã nhận diện phụ đề SubRip (chứa mốc mũi tên '-->'): '{path.name}'."
        return False, format_name, "File .srt không chứa cấu trúc mốc thời gian chuẩn (00:00:00,000 --> 00:00:00,000)."

    if ext in (".ass", ".ssa"):
        if ASS_REGEX.search(content):
            return True, format_name, f"Đã nhận diện thành công phụ đề Advanced SubStation Alpha: '{path.name}'."
        return False, format_name, "File .ass/.ssa thiếu phần khai báo [Script Info] hoặc [Events]."

    if ext in (".smi", ".sami"):
        if SAMI_REGEX.search(content) or "<SAMI>" in content.upper():
            return True, format_name, f"Đã nhận diện thành công phụ đề SAMI: '{path.name}'."
        return False, format_name, "File .smi không chứa thẻ đánh dấu <SAMI> hoặc <SYNC Start=>."

    if ext == ".sub":
        if MICRODVD_REGEX.search(content) or TIMESTAMP_REGEX.search(content) or "-->" in content:
            return True, format_name, f"Đã nhận diện thành công phụ đề SubViewer/MicroDVD: '{path.name}'."
        return False, format_name, "File .sub không chứa mốc khung hình {start}{end} hoặc thời gian hợp lệ."

    if ext == ".lrc":
        if LRC_REGEX.search(content):
            return True, format_name, f"Đã nhận diện thành công tệp lời bài hát/phụ đề LRC: '{path.name}'."
        return False, format_name, "File .lrc không chứa mốc thời gian [mm:ss.xx] hợp lệ."

    if ext == ".idx":
        # VobSub index file
        if "# VobSub index file" in content or "timestamp:" in content.lower():
            return True, format_name, f"Đã nhận diện thành công chỉ mục phụ đề VobSub: '{path.name}'."
        return False, format_name, "File .idx không phải là chỉ mục VobSub hợp lệ."

    # Generic check for .txt, .ttml, .dfxp
    if TIMESTAMP_REGEX.search(content) or "-->" in content or "<tt" in content.lower():
        return True, format_name, f"Đã nhận diện thành công file phụ đề '{path.name}'."

    return False, format_name, "Nội dung file không chứa mốc thời gian (timestamp) hợp lệ cho phụ đề."


def build_vlc_subtitle_args(sub_cfg: Optional[Dict[str, Any]]) -> List[str]:
    """
    Build libVLC arguments for styling subtitle font, colors, border, background, and typography.
    """
    if not sub_cfg or not isinstance(sub_cfg, dict):
        return []

    args: List[str] = []

    # Font family
    font_fam = sub_cfg.get("font_family", "Segoe UI")
    if font_fam:
        args.append(f"--freetype-font={font_fam}")

    # Font size
    font_size = sub_cfg.get("font_size", 36)
    if isinstance(font_size, int) and font_size > 0:
        args.append("--freetype-rel-fontsize=0")
        args.append(f"--freetype-fontsize={font_size}")

    # Text color
    text_color = sub_cfg.get("text_color", "#ffffff")
    args.append(f"--freetype-color={hex_to_vlc_color(text_color)}")

    # Outline / Border color & thickness
    outline_color = sub_cfg.get("outline_color", "#000000")
    args.append(f"--freetype-outline-color={hex_to_vlc_color(outline_color)}")

    outline_thickness = sub_cfg.get("outline_thickness", 2)
    if isinstance(outline_thickness, int) and outline_thickness >= 0:
        args.append(f"--freetype-outline-thickness={outline_thickness}")

    # Background color and opacity
    bg_enabled = sub_cfg.get("bg_enabled", False)
    if bg_enabled:
        bg_color = sub_cfg.get("bg_color", "#000000")
        args.append(f"--freetype-background-color={hex_to_vlc_color(bg_color)}")
        bg_opacity = sub_cfg.get("bg_opacity", 128)
        args.append(f"--freetype-background-opacity={max(0, min(255, int(bg_opacity)))}")
    else:
        args.append("--freetype-background-opacity=0")

    # Typography styles: Bold & Italic
    if sub_cfg.get("bold", False):
        args.append("--freetype-bold")

    if sub_cfg.get("italic", False):
        args.append("--freetype-italic")

    return args
