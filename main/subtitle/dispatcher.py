"""
Subtitle Dispatcher: Central coordinator enforcing mutually exclusive source selection.
At any time, exactly ONE subtitle source is active:
1. Local File (.srt, .vtt, .ass...)
2. Platform Captions (YouTube/Facebook)
3. AI Translation (OpenAI completion)
Or None (Subtitles disabled).
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .core import validate_subtitle_file
from .cue_parser import CueParser
from .manager import TempSubtitleManager
from .platform_captions import PlatformCaptionExtractor
from .translator import OpenAICompatibleTranslator

logger = logging.getLogger(__name__)


class SubtitleDispatcher:
    """Dispatches subtitle requests based on active settings and media metadata."""

    @classmethod
    def resolve_subtitle_for_stream(
        cls,
        video_url: str,
        info_dict: Optional[Dict[str, Any]],
        sub_settings: Dict[str, Any],
        video_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Resolve and prepare subtitle file path for the active stream according to
        mutually exclusive source options: 'local' | 'web' | 'ai' | 'none'.
        Returns absolute path to the ready subtitle file, or None if disabled/unavailable.
        """
        if not sub_settings or not sub_settings.get("enabled", True):
            return None

        source_option = sub_settings.get("source_option", "web")
        vid = video_id or (info_dict.get("id") if info_dict else None) or "stream"

        # --- OPTION 1: Local File ---
        if source_option == "local":
            local_path = sub_settings.get("local_file", "")
            if isinstance(local_path, dict):
                local_path = local_path.get("path", "")
            if local_path and Path(local_path).is_file():
                is_valid, fmt, _ = validate_subtitle_file(local_path)
                if is_valid:
                    logger.info(f"[SubtitleDispatcher] Using local subtitle: {local_path}")
                    return str(Path(local_path).resolve())
            return None

        # --- OPTION 2: Web Platform Captions ---
        if source_option == "web":
            if not info_dict:
                return None

            web_cfg = sub_settings.get("web_captions", {})
            target_lang = web_cfg.get("target_lang", "vi")
            caption_url: Optional[str] = None

            # YouTube
            if "youtube" in video_url.lower() or "youtu.be" in video_url.lower():
                caption_url = PlatformCaptionExtractor.extract_youtube_caption_url(
                    info_dict,
                    prefer_original=web_cfg.get("youtube_prefer_original", True),
                    auto_translate=web_cfg.get("youtube_auto_translate", True),
                    target_lang=target_lang,
                )
            # Facebook
            elif "facebook" in video_url.lower() or "fb.watch" in video_url.lower():
                caption_url = PlatformCaptionExtractor.extract_facebook_caption_url(
                    info_dict,
                    prefer_original=web_cfg.get("facebook_prefer_original", True),
                    target_lang=target_lang,
                )
            # Generic fallback
            else:
                caption_url = PlatformCaptionExtractor.extract_youtube_caption_url(
                    info_dict,
                    prefer_original=True,
                    auto_translate=False,
                    target_lang=target_lang,
                )

            if caption_url:
                dl_path = PlatformCaptionExtractor.download_caption(
                    caption_url=caption_url,
                    video_id=vid,
                    tag=f"web_{target_lang}",
                )
                if dl_path and dl_path.is_file():
                    logger.info(f"[SubtitleDispatcher] Ready platform subtitle: {dl_path}")
                    return str(dl_path.resolve())

            return None

        # --- OPTION 3: AI Translation ---
        if source_option == "ai":
            ai_cfg = sub_settings.get("ai_translator", {})
            target_lang = ai_cfg.get("target_lang", "vi")

            # 1. Obtain base subtitle text first (from web captions if online stream, or local file)
            base_sub_path: Optional[Path] = None
            if info_dict:
                # Try getting base web subtitle (original language)
                cap_url = PlatformCaptionExtractor.extract_youtube_caption_url(
                    info_dict,
                    prefer_original=True,
                    auto_translate=False,
                    target_lang="en",
                )
                if cap_url:
                    base_sub_path = PlatformCaptionExtractor.download_caption(
                        cap_url, vid, tag="base_for_ai"
                    )

            if not base_sub_path:
                local_path = sub_settings.get("local_file", "")
                if isinstance(local_path, dict):
                    local_path = local_path.get("path", "")
                if local_path and Path(local_path).is_file():
                    base_sub_path = Path(local_path)

            if not base_sub_path or not base_sub_path.is_file():
                logger.warning("[SubtitleDispatcher] No base subtitle found to feed into AI translator.")
                return None

            # 2. Parse cues
            cues = CueParser.parse_file(base_sub_path)
            if not cues:
                return None

            # 3. Translate via OpenAI-compatible endpoint
            endpoint = ai_cfg.get("endpoint", "https://api.openai.com/v1")
            api_key = ai_cfg.get("api_key", "")
            model = ai_cfg.get("model", "gpt-4o-mini")

            translator = OpenAICompatibleTranslator(
                endpoint=endpoint,
                api_key=api_key,
                model=model,
            )

            translated_cues = translator.translate_cues(cues, target_lang=target_lang)
            serialized_vtt = CueParser.serialize_vtt(translated_cues)

            # 4. Save to temporary manager
            temp_mgr = TempSubtitleManager.get_instance()
            target_ai_path = temp_mgr.save_temp_subtitle(
                video_id=vid,
                content=serialized_vtt,
                ext=".vtt",
                tag=f"ai_{target_lang}",
            )
            logger.info(f"[SubtitleDispatcher] Ready AI translated subtitle: {target_ai_path}")
            return str(target_ai_path.resolve())

        # Fallback / none
        return None
