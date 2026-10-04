"""
Subtitle Lifecycle & Temp Files Manager.
Enforces Section 16.4 "Xài xong dọn" (clean after use):
- Stores downloaded online / AI-translated subtitles in %TEMP%/fbw_subs/
- Cleans up stale subtitle files upon queue switch or application exit
- Zero memory leaks, zero disk bloat.
"""

import atexit
import logging
from pathlib import Path
import re
import shutil
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

TEMP_SUBTITLE_SUBDIR = "fbw_subs"


class TempSubtitleManager:
    """Singleton manager for managing temporary subtitle files."""

    _instance: Optional["TempSubtitleManager"] = None

    def __init__(self):
        self._temp_dir = Path(tempfile.gettempdir()) / TEMP_SUBTITLE_SUBDIR
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._active_file: Optional[Path] = None
        self._registered_exit = False
        self._register_atexit()

    @classmethod
    def get_instance(cls) -> "TempSubtitleManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _register_atexit(self) -> None:
        if not self._registered_exit:
            atexit.register(self.cleanup_all)
            self._registered_exit = True

    def get_temp_dir(self) -> Path:
        """Return the temporary subtitles directory, ensuring it exists."""
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        return self._temp_dir

    def sanitize_filename(self, name: str) -> str:
        """Sanitize video ID or name for Windows safe file paths."""
        return re.sub(r'[\/:*?"<>|\s]', '_', name)[:64]

    def save_temp_subtitle(
        self,
        video_id: str,
        content: str,
        ext: str = ".vtt",
        tag: str = "web",
    ) -> Path:
        """
        Save temporary subtitle text to %TEMP%/fbw_subs/{sanitized_id}_{tag}.{ext}.
        Cleans up previous active temporary file if it belonged to a different stream.
        """
        safe_id = self.sanitize_filename(video_id or "stream")
        if not ext.startswith("."):
            ext = f".{ext}"

        # Clean prior active file if switching streams
        if self._active_file and self._active_file.exists():
            try:
                self._active_file.unlink()
            except Exception:
                pass
            self._active_file = None

        target_file = self.get_temp_dir() / f"{safe_id}_{tag}{ext}"
        target_file.write_text(content, encoding="utf-8")
        self._active_file = target_file
        logger.debug(f"[TempSubtitleManager] Saved temp subtitle: {target_file}")
        return target_file

    def get_active_temp_file(self) -> Optional[Path]:
        """Return currently active temporary subtitle path."""
        if self._active_file and self._active_file.is_file():
            return self._active_file
        return None

    def cleanup_video(self, video_id: Optional[str] = None) -> None:
        """Clean up subtitle files associated with a specific video or current active."""
        if video_id:
            safe_id = self.sanitize_filename(video_id)
            for f in self.get_temp_dir().glob(f"{safe_id}_*"):
                try:
                    f.unlink()
                except Exception:
                    pass
        elif self._active_file and self._active_file.exists():
            try:
                self._active_file.unlink()
            except Exception:
                pass
            self._active_file = None

    def cleanup_all(self) -> None:
        """Clean up entire temporary subtitle folder on application exit."""
        if self._temp_dir.exists():
            try:
                for item in self._temp_dir.iterdir():
                    try:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass
                logger.debug("[TempSubtitleManager] Cleaned up temporary subtitle directory.")
            except Exception as e:
                logger.debug(f"[TempSubtitleManager] Error during cleanup: {e}")
