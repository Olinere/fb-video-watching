"""
Video Extractors package for FB Video Watcher.
Provides a modular extractor architecture with BaseExtractor, specialized protocol extractors,
GenericWebExtractor (mechanism-based), and GenericExtractor for universal platform coverage.
"""

from typing import List, Type

from main.extractors.base import (
    BaseExtractor,
    Format,
    ResolvedVideo,
    ResolverError,
    URLValidationError,
    VideoNotFoundError,
    AuthRequiredError,
    NetworkError,
    NotSupportedError,
    get_js_runtimes,
    isolated_cookie_file,
)
from main.collection import CollectionEntry, ResolvedCollection
from main.chapters import Chapter
from main.extractors.generic import GenericExtractor
from main.extractors.generic_web import GenericWebExtractor, unpack_packer
from main.extractors.local import LocalFileExtractor, is_local_media_file
from main.extractors.telegram import TelegramExtractor
from main.extractors.youtube import YouTubeExtractor, _prepare_hls_master_manifest

# Priority-ordered 5-layer extractor registry.
# Specific protocols and mechanisms are evaluated in strict priority order before yt-dlp fallback.
EXTRACTOR_REGISTRY: List[Type[BaseExtractor]] = [
    LocalFileExtractor,     # Layer 1: Local file / URI
    TelegramExtractor,      # Layer 2: Telegram MTProto DC protocol
    YouTubeExtractor,       # Layer 3: YouTube adaptive HD streaming
    GenericWebExtractor,    # Layer 4: Mechanism-based Web Video Engine (players, embeds, packers)
    GenericExtractor,       # Layer 5: Fallback yt-dlp for universal platforms (FB, TikTok, etc.)
]

# Backward compatibility aliases for deprecated site-specific extractor classes.
# Re-routed to the unified GenericWebExtractor engine.
VLXXExtractor = GenericWebExtractor
SexVietNewExtractor = GenericWebExtractor
XNhauExtractor = GenericWebExtractor
HentaiZExtractor = GenericWebExtractor


def get_extractor(url: str) -> BaseExtractor:
    """
    Find and return an instantiated extractor suitable for the given URL.
    Falls back to GenericExtractor if no specialized extractor matches.
    """
    for extractor_cls in EXTRACTOR_REGISTRY:
        if extractor_cls.suitable(url):
            return extractor_cls()
    return GenericExtractor()


__all__ = [
    "BaseExtractor",
    "Format",
    "ResolvedVideo",
    "Chapter",
    "CollectionEntry",
    "ResolvedCollection",
    "ResolverError",
    "URLValidationError",
    "VideoNotFoundError",
    "AuthRequiredError",
    "NetworkError",
    "NotSupportedError",
    "LocalFileExtractor",
    "TelegramExtractor",
    "YouTubeExtractor",
    "GenericWebExtractor",
    "GenericExtractor",
    "VLXXExtractor",
    "SexVietNewExtractor",
    "XNhauExtractor",
    "HentaiZExtractor",
    "EXTRACTOR_REGISTRY",
    "get_extractor",
    "get_js_runtimes",
    "isolated_cookie_file",
    "is_local_media_file",
    "unpack_packer",
    "_prepare_hls_master_manifest",
]
