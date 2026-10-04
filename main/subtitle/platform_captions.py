"""
Platform Caption Extractor (YouTube & Facebook).
Extracts creator-uploaded captions and platform-native auto-generated captions,
including YouTube TimedText auto-translation (tlang) without third-party APIs.
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import urllib.parse
import urllib.request

from .manager import TempSubtitleManager
from .core import validate_subtitle_file

logger = logging.getLogger(__name__)


class PlatformCaptionExtractor:
    """Extracts and downloads online subtitles from YouTube and Facebook metadata."""

    @staticmethod
    def _find_preferred_format(formats_list: List[Dict[str, Any]]) -> Optional[str]:
        """Find the best caption format URL, preferring .vtt, then .srt."""
        if not formats_list:
            return None
        # Prefer WebVTT (.vtt)
        for fmt in formats_list:
            if fmt.get("ext") == "vtt" and fmt.get("url"):
                return fmt["url"]
        # Fallback to SRT (.srt)
        for fmt in formats_list:
            if fmt.get("ext") == "srt" and fmt.get("url"):
                return fmt["url"]
        # Fallback to any valid URL
        for fmt in formats_list:
            if fmt.get("url"):
                return fmt["url"]
        return None

    @classmethod
    def extract_youtube_caption_url(
        cls,
        info_dict: Dict[str, Any],
        prefer_original: bool = True,
        auto_translate: bool = True,
        target_lang: str = "vi",
    ) -> Optional[str]:
        """
        Extract caption URL from YouTube yt-dlp info_dict:
        1. If prefer_original: search creator-uploaded 'subtitles' for target_lang or base lang.
        2. If auto_translate and target_lang is requested: construct or find Google TimedText
           auto-translated URL with 'tlang={target_lang}'.
        3. Check 'automatic_captions' for target_lang.
        """
        if not info_dict or not isinstance(info_dict, dict):
            return None

        subtitles = info_dict.get("subtitles") or {}
        auto_captions = info_dict.get("automatic_captions") or {}

        # 1. Creator uploaded subtitles matching target_lang
        if prefer_original and subtitles:
            for lang_code, fmt_list in subtitles.items():
                if lang_code.lower() == target_lang.lower() or lang_code.lower().startswith(f"{target_lang.lower()}-"):
                    url = cls._find_preferred_format(fmt_list)
                    if url:
                        logger.info(f"[PlatformCaptionExtractor] Found creator subtitle for lang '{lang_code}': {url[:60]}...")
                        return url

        # 2. Native YouTube Auto-translate (TimedText tlang)
        # YouTube allows adding &tlang=vi to any timedtext URL to translate automatically on Google's servers
        if auto_translate and (auto_captions or subtitles):
            # Check if there is already an auto caption for target_lang
            if target_lang in auto_captions:
                url = cls._find_preferred_format(auto_captions[target_lang])
                if url:
                    logger.info(f"[PlatformCaptionExtractor] Found direct auto-caption for '{target_lang}'")
                    return url

            # Find base caption URL from auto_captions or subtitles to inject &tlang
            base_url: Optional[str] = None
            source_dict = auto_captions if auto_captions else subtitles
            # Try English first as base, or take first available
            for cand_lang in ["en", "en-US", "en-GB"] + list(source_dict.keys()):
                if cand_lang in source_dict:
                    base_url = cls._find_preferred_format(source_dict[cand_lang])
                    if base_url:
                        break

            if base_url and "timedtext" in base_url:
                parsed = urllib.parse.urlparse(base_url)
                qs = urllib.parse.parse_qs(parsed.query)
                # Ensure fmt=vtt for standard WebVTT parsing
                qs["fmt"] = ["vtt"]
                qs["tlang"] = [target_lang]
                new_query = urllib.parse.urlencode(qs, doseq=True)
                translated_url = urllib.parse.urlunparse(parsed._replace(query=new_query))
                logger.info(f"[PlatformCaptionExtractor] Constructed YouTube native auto-translate URL ({target_lang})")
                return translated_url

        # 3. Fallback to creator-uploaded subtitle in any language if prefer_original
        if prefer_original and subtitles:
            for lang_code, fmt_list in subtitles.items():
                url = cls._find_preferred_format(fmt_list)
                if url:
                    logger.info(f"[PlatformCaptionExtractor] Fallback to creator subtitle '{lang_code}'")
                    return url

        # 4. Fallback to any automatic caption
        if auto_captions:
            for lang_code, fmt_list in auto_captions.items():
                url = cls._find_preferred_format(fmt_list)
                if url:
                    logger.info(f"[PlatformCaptionExtractor] Fallback to automatic caption '{lang_code}'")
                    return url

        return None

    @classmethod
    def extract_facebook_caption_url(
        cls,
        info_dict: Dict[str, Any],
        prefer_original: bool = True,
        target_lang: str = "vi",
    ) -> Optional[str]:
        """Extract caption URL from Facebook video info_dict."""
        if not info_dict or not isinstance(info_dict, dict):
            return None

        subtitles = info_dict.get("subtitles") or {}
        auto_captions = info_dict.get("automatic_captions") or {}

        # 1. Look for target_lang in subtitles
        for src in ([subtitles, auto_captions] if prefer_original else [auto_captions, subtitles]):
            for lang_code, fmt_list in src.items():
                if lang_code.lower() == target_lang.lower() or lang_code.lower().startswith(f"{target_lang.lower()}-"):
                    url = cls._find_preferred_format(fmt_list)
                    if url:
                        return url

        # 2. Fallback to first available subtitle
        for src in ([subtitles, auto_captions] if prefer_original else [auto_captions, subtitles]):
            for lang_code, fmt_list in src.items():
                url = cls._find_preferred_format(fmt_list)
                if url:
                    return url

        return None

    @classmethod
    def download_caption(
        cls,
        caption_url: str,
        video_id: str,
        tag: str = "web",
        timeout_sec: int = 10,
    ) -> Optional[Path]:
        """
        Download caption file from URL and save to temp directory.
        Returns Path to the downloaded file if valid, None otherwise.
        """
        if not caption_url:
            return None

        try:
            req = urllib.request.Request(
                caption_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FB-Video-Watching Subtitles"},
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw_bytes = resp.read()

            content: Optional[str] = None
            for enc in ["utf-8-sig", "utf-8", "latin-1"]:
                try:
                    content = raw_bytes.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue

            if not content:
                logger.warning("[PlatformCaptionExtractor] Failed to decode downloaded caption text.")
                return None

            # Determine extension
            ext = ".vtt" if "WEBVTT" in content or "-->" in content else ".srt"

            # Save to temporary subtitle manager
            temp_mgr = TempSubtitleManager.get_instance()
            target_path = temp_mgr.save_temp_subtitle(
                video_id=video_id,
                content=content,
                ext=ext,
                tag=tag,
            )

            # Validate that it is a recognized subtitle
            is_valid, fmt, msg = validate_subtitle_file(target_path)
            if is_valid:
                logger.info(f"[PlatformCaptionExtractor] Successfully downloaded and validated {fmt}: {target_path.name}")
                return target_path
            else:
                logger.warning(f"[PlatformCaptionExtractor] Downloaded file validation failed: {msg}")
                return None

        except Exception as e:
            logger.warning(f"[PlatformCaptionExtractor] Error downloading caption from {caption_url[:60]}: {e}")
            return None
