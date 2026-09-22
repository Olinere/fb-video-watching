"""
Extractor for xNhau video portals (xnhau.cab, xnhau.com, etc.).
"""

import html
import logging
import re
from typing import Optional, Tuple
import urllib.request

from main.constants import FAKE_USER_AGENT
from main.extractors.base import BaseExtractor, ResolvedVideo, VideoNotFoundError, _SSL_CTX

logger = logging.getLogger("FBVideoWatcher.Extractors.XNhau")


class XNhauExtractor(BaseExtractor):
    """Extractor for xNhau video portals."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        if not url:
            return False
        try:
            return "xnhau" in url.lower()
        except Exception:
            return False

    def extract(
        self,
        url: str,
        cookie_file: Optional[str] = None,
        max_height: int = 1080,
        timeout: int = 10,
        retries: int = 2,
    ) -> ResolvedVideo:
        stream_url, title, thumbnail = self.resolve_xnhau_url(url, timeout=timeout)
        if not stream_url:
            raise VideoNotFoundError("Không tìm thấy luồng phát video cho liên kết xNhau này.")

        return ResolvedVideo(
            stream_url=stream_url,
            title=title or "xNhau Video",
            duration=None,
            thumbnail=thumbnail,
            is_live=False,
        )

    def resolve_xnhau_url(self, url: str, timeout: int = 10) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": FAKE_USER_AGENT,
                    "Referer": url,
                },
            )
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
                page_html = resp.read().decode("utf-8", errors="ignore")

            custom_title = None
            vt_m = re.search(r"video_title:\s*['\"]([^'\"]+)['\"]", page_html)
            if vt_m:
                custom_title = html.unescape(vt_m.group(1)).strip()
            if not custom_title:
                t_m = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE)
                if t_m:
                    custom_title = re.sub(
                        r"\s*[-–|]\s*xnhau.*$", "", html.unescape(t_m.group(1)), flags=re.IGNORECASE
                    ).strip()

            custom_thumb = None
            vp_m = re.search(r"preview_url:\s*['\"]([^'\"]+)['\"]", page_html)
            if vp_m:
                custom_thumb = vp_m.group(1)
            if not custom_thumb:
                og_m = re.search(
                    r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                    page_html,
                    re.IGNORECASE,
                )
                if og_m:
                    custom_thumb = og_m.group(1)

            # Extract highest quality direct stream from KVS flashvars
            candidates = []
            for key in ["video_alt_url4", "video_alt_url3", "video_alt_url2", "video_alt_url", "video_url"]:
                m = re.search(rf"{key}:\s*['\"]([^'\"]+)['\"]", page_html)
                if m:
                    val = m.group(1).replace(r"\/", "/")
                    if (
                        val
                        and not any(bad in val.lower() for bad in ["login", "redirect", "signup"])
                        and any(good in val.lower() for good in ["/get_file/", ".mp4", ".m3u8"])
                    ):
                        candidates.append(val)

            if candidates:
                return candidates[0], custom_title, custom_thumb

            # Fallback to direct media links if any
            direct_m = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*', page_html, re.IGNORECASE)
            media_clean = [
                u for u in direct_m
                if not any(x in u.lower() for x in [".jpg", ".png", "preview", "timeline", "adv"])
            ]
            if media_clean:
                return media_clean[0], custom_title, custom_thumb

            return None, custom_title, custom_thumb
        except Exception as exc:
            logger.warning("Error extracting xNhau video: %s", exc)
            return None, None, None
