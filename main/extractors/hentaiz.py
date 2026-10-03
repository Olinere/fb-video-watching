"""
Extractor for HentaiVietSub and HentaiZ video portals (hentaivietsub.com, hentaiz.bot, etc.).
Extracts video sources from embedded players (vcast, streamforester, wogplayer)
and routes HLS .m3u8 manifests through local StreamProxyServer with proper Referer.
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

logger = logging.getLogger("FBVideoWatcher.Extractors.HentaiZ")


class HentaiZExtractor(BaseExtractor):
    """Extractor for HentaiVietSub and HentaiZ anime video portals."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        if not url or not isinstance(url, str):
            return False
        try:
            parsed = urllib.parse.urlparse(url.strip())
            host = parsed.netloc.lower()
            # Match any domain with 'hentaivietsub' or 'hentaiz' regardless of TLD (.com, .bot, .net, etc.)
            if "hentaivietsub" in host or "hentaiz" in host:
                return True
            # Also match any domain having 'hentai' in host and '/hentai/' in path
            if "hentai" in host and ("/hentai/" in parsed.path or parsed.path.startswith("/hentai")):
                return True
            return False
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
        stream_url, title, thumbnail = self.resolve_hentai_url(url, timeout=timeout)
        if not stream_url:
            raise VideoNotFoundError("Không tìm thấy luồng phát video cho liên kết Hentai này.")

        return ResolvedVideo(
            stream_url=stream_url,
            title=title or "Hentai Video",
            duration=None,
            thumbnail=thumbnail,
            is_live=False,
        )

    def resolve_hentai_url(self, url: str, timeout: int = 10) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Query Hentai webpage, parse player CDN source candidates,
        resolve master .m3u8, and route through local StreamProxyServer.
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

            # 1. Parse Title
            custom_title = None
            title_m = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE)
            if title_m:
                raw_title = html.unescape(title_m.group(1)).strip()
                custom_title = re.sub(
                    r"\s*-\s*Hentai(Vietsub|Z).*$", "", raw_title, flags=re.IGNORECASE
                ).strip()

            # 2. Parse Thumbnail
            custom_thumb = None
            thumb_m = re.search(
                r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                page_html,
                re.IGNORECASE,
            )
            if thumb_m:
                custom_thumb = thumb_m.group(1).strip()

            # 3. Extract candidate data-source URLs & video IDs
            raw_sources = re.findall(r'data-source=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
            sources = [html.unescape(s).strip() for s in raw_sources]

            vid = None
            vid_m = re.search(r'/videos/([a-f0-9]{24})', page_html)
            if vid_m:
                vid = vid_m.group(1)

            m3u8_url = None
            referer = None

            # Priority 1: Check vcast.name source if available
            for src in sources:
                src_vid_m = re.search(r'/videos/([a-f0-9]{24})', src)
                v = src_vid_m.group(1) if src_vid_m else vid
                if "vcast.name" in src and v:
                    test_url = f"https://vcast.name/videos/{v}/master.m3u8"
                    try:
                        t_req = urllib.request.Request(
                            test_url,
                            headers={"User-Agent": FAKE_USER_AGENT, "Referer": "https://vcast.name/"},
                        )
                        with urllib.request.urlopen(t_req, context=_SSL_CTX, timeout=5) as t_resp:
                            if t_resp.status == 200:
                                m3u8_url = test_url
                                referer = "https://vcast.name/"
                                break
                    except Exception:
                        pass

            # Priority 2: Direct video ID on vcast.name
            if not m3u8_url and vid:
                test_url = f"https://vcast.name/videos/{vid}/master.m3u8"
                try:
                    t_req = urllib.request.Request(
                        test_url,
                        headers={"User-Agent": FAKE_USER_AGENT, "Referer": "https://vcast.name/"},
                    )
                    with urllib.request.urlopen(t_req, context=_SSL_CTX, timeout=5) as t_resp:
                        if t_resp.status == 200:
                            m3u8_url = test_url
                            referer = "https://vcast.name/"
                except Exception:
                    pass

            # Priority 3: Fetch embed page (e.streamforester.name / wogplayer.top)
            if not m3u8_url:
                for src in sources:
                    try:
                        em_req = urllib.request.Request(
                            src,
                            headers={"User-Agent": FAKE_USER_AGENT, "Referer": final_url},
                        )
                        with urllib.request.urlopen(em_req, context=_SSL_CTX, timeout=timeout) as em_resp:
                            em_html = em_resp.read().decode("utf-8", errors="ignore")
                            final_em_url = em_resp.geturl()

                        parsed_em = urllib.parse.urlparse(final_em_url)
                        em_origin = f"{parsed_em.scheme}://{parsed_em.netloc}"

                        vd_m = re.search(r'window\.videoData\s*=\s*(\{.*?\});', em_html, re.DOTALL)
                        if vd_m:
                            vd = json.loads(vd_m.group(1))
                            if "sources" in vd and vd["sources"]:
                                f = vd["sources"][0].get("file")
                                if f:
                                    m3u8_url = urllib.parse.urljoin(final_em_url, f)
                                    referer = f"{em_origin}/"
                                    break
                            elif "id" in vd and "domain" in vd:
                                cfg_url = f"{em_origin}/videos/{vd['id']}/config?d={vd['domain']}"
                                cfg_req = urllib.request.Request(
                                    cfg_url,
                                    data=b"{}",
                                    headers={
                                        "User-Agent": FAKE_USER_AGENT,
                                        "Referer": final_em_url,
                                        "Origin": em_origin,
                                        "Content-Type": "application/json",
                                    },
                                    method="POST",
                                )
                                with urllib.request.urlopen(cfg_req, context=_SSL_CTX, timeout=timeout) as cfg_resp:
                                    cfg_data = json.loads(cfg_resp.read().decode("utf-8"))
                                    if "sources" in cfg_data and cfg_data["sources"]:
                                        f = cfg_data["sources"][0].get("file")
                                        if f:
                                            m3u8_url = urllib.parse.urljoin(final_em_url, f)
                                            referer = f"{em_origin}/"
                                            break
                    except Exception:
                        continue

            if m3u8_url:
                from main.stream_proxy import StreamProxyServer
                proxy = StreamProxyServer.get_instance()
                proxy_url = proxy.get_proxy_playlist_url(m3u8_url, referer=referer)
                return proxy_url, custom_title, custom_thumb

            return None, custom_title, custom_thumb
        except Exception as exc:
            logger.warning("Error extracting Hentai video: %s", exc)
            return None, None, None
