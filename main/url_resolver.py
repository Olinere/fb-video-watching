"""
Module for resolving Facebook and universal video URLs into direct stream URLs.
Acts as the public façade and dispatch layer for the main.extractors architecture.
Strictly adheres to specs.md §4.1 and handles Edge Cases §7.1.
"""

import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import urllib.parse
import urllib.request

from main.constants import (
    FB_URL_PATTERN,
    RESOLVE_TIMEOUT,
    RESOLVE_RETRIES,
    FAKE_USER_AGENT,
    MAX_VIDEO_HEIGHT,
    MAX_COLLECTION_ENTRIES,
)
from main.extractors import (
    BaseExtractor,
    Format,
    ResolvedVideo,
    ResolverError,
    URLValidationError,
    VideoNotFoundError,
    AuthRequiredError,
    NetworkError,
    LocalFileExtractor,
    TelegramExtractor,
    VLXXExtractor,
    SexVietNewExtractor,
    XNhauExtractor,
    YouTubeExtractor,
    GenericExtractor,
    get_extractor,
    is_local_media_file,
    _prepare_hls_master_manifest,
)
from main.collection import ResolvedCollection

logger = logging.getLogger("FBVideoWatcher.URLResolver")


def validate_facebook_url(url: str) -> str:
    """
    Validate and clean video URL or local media path.

    Args:
        url: Raw input URL string or local file path.

    Returns:
        str: Stripped valid URL or file path.

    Raises:
        URLValidationError: If input is empty or does not match valid formats.
    """
    if not isinstance(url, str):
        raise URLValidationError("URL phải là chuỗi văn bản.")

    cleaned = url.strip().strip('"').strip("'")
    if not cleaned:
        raise URLValidationError("URL không được để trống.")

    if is_local_media_file(cleaned):
        return cleaned

    if not FB_URL_PATTERN.match(cleaned):
        raise URLValidationError(
            "URL không hợp lệ. Vui lòng nhập liên kết video bắt đầu bằng http://, https:// hoặc chọn file video từ máy tính."
        )

    return cleaned


# Function aliases for universal video support
validate_video_url = validate_facebook_url


def is_potential_video_url(url: str) -> bool:
    """
    Check whether a text/URL is likely a playable video link or local media file.
    Used for clipboard auto-detection across all supported platforms.
    """
    if not isinstance(url, str):
        return False
    if is_local_media_file(url):
        return True
    u = url.strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False

    try:
        parsed = urllib.parse.urlparse(u)
    except Exception:
        return False

    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()

    if not host or "." not in host:
        return False

    # 1. Video hosting & streaming platforms
    known_platforms = (
        "facebook.com", "fb.watch", "fb.gg", "fb.com",
        "youtube.com", "youtu.be",
        "tiktok.com", "douyin.com",
        "bilibili.com", "b23.tv",
        "twitter.com", "x.com",
        "instagram.com", "threads.net",
        "twitch.tv", "vimeo.com", "dailymotion.com", "rumble.com",
        "t.me", "telegram.org", "telegram.me",
        # Adult platforms
        "vlxx", "sexvietnew", "xnhau",
        "pornhub.com", "xvideos.com", "xnxx.com", "spankbang.com",
        "redtube.com", "youporn.com", "beeg.com", "xhamster.com",
        "doodstream", "streamtape", "filemoon", "streamwish", "luluvdo",
    )
    if any(p in host for p in known_platforms):
        return True

    # 2. Direct video/audio/playlist extensions
    video_exts = (
        ".mp4", ".m3u8", ".webm", ".mkv", ".flv", ".mov",
        ".avi", ".ts", ".mpd", ".m4v", ".vl",
    )
    if any(path.endswith(ext) or (ext + "?" in u.lower()) for ext in video_exts):
        return True

    # 3. Common video URL path segments
    video_path_keywords = (
        "/video/", "/watch", "/reel/", "/reels/", "/shorts/",
        "/clip/", "/clips/", "/embed/", "/tv/", "/media/",
        "/play/", "/stream/", "/v/",
    )
    if any(kw in path for kw in video_path_keywords):
        return True

    # 4. Query parameters indicating video ID
    if any(k in query for k in ("v=", "video_id=", "vid=", "mid=")):
        return True

    return False


def is_collection_url(url: str) -> bool:
    """Cheap, side-effect-free check used before scheduling collection listing."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return False
    query = urllib.parse.parse_qs(parsed.query)
    path = parsed.path.lower()
    return bool(query.get("list") or "/playlist/" in path or "/album/" in path)


def _preprocess_special_url(url: str, timeout: int = 8) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Bridge method for backward compatibility.
    Delegates to specialized extractors (VLXX, SexVietNew, XNhau).
    """
    u_lower = url.lower()
    if "vlxx" in u_lower:
        vlxx_ext = VLXXExtractor()
        stream_url, title, thumb = vlxx_ext.resolve_vlxx_url(url, timeout=timeout)
        return stream_url or url, title, thumb
    elif "sexvietnew" in u_lower:
        svn_ext = SexVietNewExtractor()
        stream_url, title, thumb = svn_ext.resolve_sexvietnew_url(url, timeout=timeout)
        return stream_url or url, title, thumb
    elif "xnhau" in u_lower:
        xnhau_ext = XNhauExtractor()
        stream_url, title, thumb = xnhau_ext.resolve_xnhau_url(url, timeout=timeout)
        return stream_url or url, title, thumb
    return url, None, None


def resolve_facebook_url(
    url: str,
    cookie_file: Optional[str] = None,
    max_height: int = MAX_VIDEO_HEIGHT,
    timeout: int = RESOLVE_TIMEOUT,
    retries: int = RESOLVE_RETRIES,
) -> ResolvedVideo:
    """
    Resolve video URL into a direct playable stream URL.
    Dispatches to the optimal extractor in main.extractors architecture.

    Args:
        url: Facebook or universal video URL / local file path.
        cookie_file: Optional path to cookies.txt for private/authenticated videos.
        max_height: Max video resolution height (0 = best available).
        timeout: Socket timeout in seconds.
        retries: Number of retries on transient errors.

    Returns:
        ResolvedVideo: Container with direct stream URL and video metadata.

    Raises:
        URLValidationError: URL not recognized as valid video URL.
        VideoNotFoundError: Video removed, deleted, or post contains no video.
        AuthRequiredError: Private video requiring cookies.
        NetworkError: Transient network connection failure.
        ResolverError: Other resolution failures.
    """
    cleaned_url = validate_facebook_url(url)
    extractor = get_extractor(cleaned_url)
    logger.debug("Dispatching source to extractor %s", extractor.__class__.__name__)
    return extractor.extract(
        cleaned_url,
        cookie_file=cookie_file,
        max_height=max_height,
        timeout=timeout,
        retries=retries,
    )


def resolve_collection(
    url: str,
    cookie_file: Optional[str] = None,
    timeout: int = RESOLVE_TIMEOUT,
    max_entries: int = MAX_COLLECTION_ENTRIES,
) -> ResolvedCollection:
    """List collection metadata without resolving any direct media stream.

    Extractors may reject a URL that is not a collection.  Callers can then
    safely fall back to :func:`resolve_facebook_url` for the single-video path.
    """
    cleaned_url = validate_facebook_url(url)
    extractor = get_extractor(cleaned_url)
    if not extractor.supports_collections():
        raise ResolverError("Liên kết này không phải playlist được hỗ trợ.")
    return extractor.extract_collection(
        cleaned_url,
        cookie_file=cookie_file,
        timeout=timeout,
        max_entries=max(1, min(int(max_entries), MAX_COLLECTION_ENTRIES)),
    )


# Descriptive alias for callers that prefer the video-oriented public name.
resolve_video_collection = resolve_collection
