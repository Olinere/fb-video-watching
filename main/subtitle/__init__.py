"""
Subtitle package initialization.
Maintains 100% backward compatibility with former main/subtitle.py imports,
while exposing modular sub-components for cue parsing, platform captions,
OpenAI translation, and temp file management.
"""

from .core import (
    SUPPORTED_SUBTITLE_EXTENSIONS,
    SUBTITLE_FORMAT_NAMES,
    TIMESTAMP_REGEX,
    MICRODVD_REGEX,
    LRC_REGEX,
    SAMI_REGEX,
    ASS_REGEX,
    hex_to_vlc_color,
    vlc_color_to_hex,
    validate_subtitle_file,
    build_vlc_subtitle_args,
)

from .cue_parser import (
    SubtitleCue,
    CueParser,
)

from .manager import (
    TempSubtitleManager,
)

from .platform_captions import (
    PlatformCaptionExtractor,
)

from .translator import (
    BaseSubtitleTranslator,
    OpenAICompatibleTranslator,
)

from .dispatcher import (
    SubtitleDispatcher,
)

__all__ = [
    "SUPPORTED_SUBTITLE_EXTENSIONS",
    "SUBTITLE_FORMAT_NAMES",
    "TIMESTAMP_REGEX",
    "MICRODVD_REGEX",
    "LRC_REGEX",
    "SAMI_REGEX",
    "ASS_REGEX",
    "hex_to_vlc_color",
    "vlc_color_to_hex",
    "validate_subtitle_file",
    "build_vlc_subtitle_args",
    "SubtitleCue",
    "CueParser",
    "TempSubtitleManager",
    "PlatformCaptionExtractor",
    "BaseSubtitleTranslator",
    "OpenAICompatibleTranslator",
    "SubtitleDispatcher",
]
