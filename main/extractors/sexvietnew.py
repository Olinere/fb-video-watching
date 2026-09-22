"""
Extractor for SexVietNew video portals (sexvietnew.world, sexvietnew.com, etc.).
"""

import html
import json
import logging
import re
from typing import Optional, Tuple
import urllib.parse
import urllib.request

from main.constants import FAKE_USER_AGENT
from main.extractors.base import BaseExtractor, ResolvedVideo, VideoNotFoundError, _SSL_CTX

logger = logging.getLogger("FBVideoWatcher.Extractors.SexVietNew")


class SexVietNewExtractor(BaseExtractor):
    """Extractor for SexVietNew video portals."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        if not url:
            return False
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
            return "sexvietnew" in host
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
        stream_url, title, thumbnail = self.resolve_sexvietnew_url(url, timeout=timeout)
        if not stream_url:
            raise VideoNotFoundError("Không tìm thấy luồng phát video cho liên kết SexVietNew này.")

        return ResolvedVideo(
            stream_url=stream_url,
            title=title or "SexVietNew Video",
            duration=None,
            thumbnail=thumbnail,
            is_live=False,
        )

    def resolve_sexvietnew_url(self, url: str, timeout: int = 10) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        try:
            parsed = urllib.parse.urlparse(url)
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
            title_m = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE)
            if title_m:
                raw_t = html.unescape(title_m.group(1))
                custom_title = re.sub(
                    r"\s*[-–|]\s*(Sex\s*Việt\s*Mới|sexvietnew).*$",
                    "",
                    raw_t,
                    flags=re.IGNORECASE,
                ).strip()

            custom_thumb = None
            thumb_m = re.search(
                r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                page_html,
                re.IGNORECASE,
            )
            if thumb_m:
                custom_thumb = thumb_m.group(1)

            # Check itemprop contentUrl or JSON-LD contentUrl
            cu_m = re.search(
                r'itemprop=["\']contentUrl["\']\s+content=["\']([^"\']+)["\']',
                page_html,
                re.IGNORECASE,
            )
            if not cu_m:
                cu_m = re.search(
                    r'content=["\']([^"\']+)["\']\s+itemprop=["\']contentUrl["\']',
                    page_html,
                    re.IGNORECASE,
                )
            if not cu_m:
                cu_m = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', page_html)

            if cu_m:
                media_url = html.unescape(cu_m.group(1)).replace(r"\/", "/")
                return media_url, custom_title, custom_thumb

            # Fallback: Check svn player iframe
            iframe_m = re.search(
                r'src=["\']([^"\']*svn_hls_player_frame[^"\']*)["\']',
                page_html,
                re.IGNORECASE,
            )
            if iframe_m:
                iframe_src = html.unescape(iframe_m.group(1))
                if iframe_src.startswith("/"):
                    iframe_src = f"{parsed.scheme}://{parsed.netloc}{iframe_src}"

                if_req = urllib.request.Request(
                    iframe_src,
                    headers={
                        "User-Agent": FAKE_USER_AGENT,
                        "Referer": url,
                    },
                )
                with urllib.request.urlopen(if_req, context=_SSL_CTX, timeout=timeout) as if_resp:
                    if_html = if_resp.read().decode("utf-8", errors="ignore")
                    data_m = re.search(r"window\.SVN_HLS_PLAYER_DATA\s*=\s*({.*?});", if_html, re.DOTALL)
                    if data_m:
                        player_data = json.loads(data_m.group(1))
                        sources = player_data.get("sources", [])
                        if sources and sources[0].get("src"):
                            return (
                                sources[0]["src"],
                                custom_title or player_data.get("title"),
                                custom_thumb or player_data.get("poster"),
                            )

            return None, custom_title, custom_thumb
        except Exception as exc:
            logger.warning("Error extracting SexVietNew video: %s", exc)
            return None, None, None
