"""
Extractor for local video/audio files and file:// URIs.
"""

import os
from pathlib import Path
from typing import Optional
import urllib.request

from main.extractors.base import BaseExtractor, ResolvedVideo, VideoNotFoundError


def is_local_media_file(path_str: str) -> bool:
    """Check if the given string represents an existing local media file or file URI."""
    if not isinstance(path_str, str):
        return False
    s = path_str.strip().strip('"').strip("'")
    if not s:
        return False
    if s.lower().startswith("file:///"):
        local_path = urllib.request.url2pathname(s[7:])
        return os.path.isfile(local_path)
    return os.path.isfile(s)


class LocalFileExtractor(BaseExtractor):
    """Extractor for local filesystem media files."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        return is_local_media_file(url)

    def extract(
        self,
        url: str,
        cookie_file: Optional[str] = None,
        max_height: int = 1080,
        timeout: int = 10,
        retries: int = 2,
    ) -> ResolvedVideo:
        cleaned = url.strip().strip('"').strip("'")
        if cleaned.lower().startswith("file:///"):
            local_path = urllib.request.url2pathname(cleaned[7:])
        else:
            local_path = cleaned

        local_p = Path(local_path).resolve()
        if not local_p.is_file():
            raise VideoNotFoundError(f"File video không tồn tại: {local_path}")

        return ResolvedVideo(
            stream_url=str(local_p),
            title=local_p.name,
            duration=None,
            thumbnail=None,
            is_live=False,
        )
