"""
Extractor for VLXX video portals (vlxx.phd, vlxx.sex, vlxx.com, etc.).
Extracts iframe embeds and passes .vl / .m3u8 manifests through local StreamProxyServer
to strip fake PNG headers from ByteDance / CDN segments.
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

logger = logging.getLogger("FBVideoWatcher.Extractors.VLXX")


class VLXXExtractor(BaseExtractor):
    """Extractor for VLXX adult portal."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        if not url:
            return False
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
            return "vlxx" in host
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
        stream_url, title, thumbnail = self.resolve_vlxx_url(url, timeout=timeout)
        if not stream_url:
            raise VideoNotFoundError("Không tìm thấy luồng phát video cho liên kết VLXX này.")

        return ResolvedVideo(
            stream_url=stream_url,
            title=title or "VLXX Video",
            duration=None,
            thumbnail=thumbnail,
            is_live=False,
        )

    def resolve_vlxx_url(self, url: str, timeout: int = 10) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Query VLXX webpage, trigger ajax.php, parse embed iframe, and route .vl file
        through local StreamProxyServer.
        """
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": FAKE_USER_AGENT,
                    "Referer": url,
                },
            )
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
                try:
                    raw_geturl = resp.geturl()
                    final_url = raw_geturl if isinstance(raw_geturl, str) and raw_geturl.startswith("http") else url
                except Exception:
                    final_url = url
                page_html = resp.read().decode("utf-8", errors="ignore")

            parsed_final = urllib.parse.urlparse(final_url)
            custom_title = None
            title_m = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE)
            if title_m:
                custom_title = re.sub(
                    r"\s*-\s*VLXX.*$", "", html.unescape(title_m.group(1)), flags=re.IGNORECASE
                ).strip()

            custom_thumb = None
            thumb_m = re.search(
                r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                page_html,
                re.IGNORECASE,
            )
            if thumb_m:
                custom_thumb = thumb_m.group(1)

            m_vid = (
                re.search(r'data-id=["\'](\d+)["\']', page_html)
                or re.search(r'var\s+vid\s*=\s*(\d+)', page_html)
                or re.search(r"/(\d+)/?$", final_url)
                or re.search(r"/(\d+)/?$", url)
            )

            if m_vid:
                vid = m_vid.group(1)
                ajax_url = f"{parsed_final.scheme}://{parsed_final.netloc}/ajax.php"
                for srv in (1, 2):
                    try:
                        post_data = urllib.parse.urlencode({
                            "vlxx_server": 1,
                            "id": vid,
                            "server": srv,
                        }).encode("utf-8")
                        ajax_req = urllib.request.Request(
                            ajax_url,
                            data=post_data,
                            headers={
                                "User-Agent": FAKE_USER_AGENT,
                                "Referer": final_url,
                                "X-Requested-With": "XMLHttpRequest",
                                "Origin": f"{parsed_final.scheme}://{parsed_final.netloc}",
                            },
                        )
                        with urllib.request.urlopen(ajax_req, context=_SSL_CTX, timeout=timeout) as ajax_resp:
                            data = json.loads(ajax_resp.read().decode("utf-8", errors="ignore"))
                            player_html = data.get("player", "")
                            iframe_m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', player_html)
                            if iframe_m:
                                embed_url = iframe_m.group(1).replace(r"\/", "/")
                                # Fetch embed page to extract direct .vl playlist
                                try:
                                    em_req = urllib.request.Request(
                                        embed_url,
                                        headers={
                                            "User-Agent": FAKE_USER_AGENT,
                                            "Referer": final_url,
                                        },
                                    )
                                    with urllib.request.urlopen(em_req, context=_SSL_CTX, timeout=timeout) as em_resp:
                                        em_html = em_resp.read().decode("utf-8", errors="ignore")

                                    src_m = re.search(r'window\.__SRC\s*=\s*(\[.*?\]);', em_html, re.DOTALL)
                                    if src_m:
                                        src_list = json.loads(src_m.group(1))
                                        for src_item in src_list:
                                            vl_file = src_item.get("file")
                                            if vl_file:
                                                from main.stream_proxy import StreamProxyServer
                                                proxy = StreamProxyServer.get_instance()
                                                proxy_url = proxy.get_proxy_playlist_url(
                                                    vl_file,
                                                    referer=f"{urllib.parse.urlparse(embed_url).scheme}://{urllib.parse.urlparse(embed_url).netloc}/",
                                                )
                                                return proxy_url, custom_title, custom_thumb
                                except Exception:
                                    pass

                                return embed_url, custom_title, custom_thumb
                    except Exception:
                        continue

            return None, custom_title, custom_thumb
        except Exception as exc:
            logger.warning("Error extracting VLXX video: %s", exc)
            return None, None, None
