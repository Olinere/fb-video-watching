"""
Video Extractors package for FB Video Watcher.
Provides a modular extractor architecture with BaseExtractor, specialized extractors,
and GenericExtractor for universal platform coverage.
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
from main.extractors.local import LocalFileExtractor, is_local_media_file
from main.extractors.sexvietnew import SexVietNewExtractor
from main.extractors.telegram import TelegramExtractor
from main.extractors.vlxx import VLXXExtractor
from main.extractors.xnhau import XNhauExtractor
from main.extractors.youtube import YouTubeExtractor, _prepare_hls_master_manifest

# Priority-ordered extractor registry.
# Specific extractors are evaluated before the fallback GenericExtractor.
EXTRACTOR_REGISTRY: List[Type[BaseExtractor]] = [
    LocalFileExtractor,
    TelegramExtractor,
    VLXXExtractor,
    SexVietNewExtractor,
    XNhauExtractor,
    YouTubeExtractor,
    GenericExtractor,
]


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
    "VLXXExtractor",
    "SexVietNewExtractor",
    "XNhauExtractor",
    "YouTubeExtractor",
    "GenericExtractor",
    "EXTRACTOR_REGISTRY",
    "get_extractor",
    "get_js_runtimes",
    "isolated_cookie_file",
    "is_local_media_file",
    "_prepare_hls_master_manifest",
]
