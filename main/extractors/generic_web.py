"""
Generic Web Video Extractor.
Mechanism-based heuristic engine for extracting playable video streams from
thousands of web video portals (anime, movies, cyberlockers, adult sites, etc.)
without requiring site-specific extractors or hardcoded domain logic.

Adheres strictly to specs.md §16.4 ("Xài xong dọn"):
- Zero persistent storage of raw HTML or DOM trees
- Memory cleanup via explicit del and gc.collect()
- Bounded network timeouts with fail-safe fallback to GenericExtractor (yt-dlp)
"""

import gc
import html
import json
import logging
import re
from typing import Optional, Tuple, List, Dict, Any
import urllib.parse
import urllib.request

from main.constants import FAKE_USER_AGENT
from main.extractors.base import (
    BaseExtractor,
    ResolvedVideo,
    VideoNotFoundError,
    _SSL_CTX,
)

logger = logging.getLogger("FBVideoWatcher.Extractors.GenericWeb")

# Dean Edwards Packer regex pattern
PACKER_PATTERN = re.compile(
    r"eval\(function\(p,a,c,k,e,[rd]\)\{.*?return\s+p\}?\s*\(\s*(['\"].*?['\"])\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(['\"].*?['\"])\.split\(['\"]\s*\|\s*['\"]\)",
    re.DOTALL,
)

# Base-62 alphabet for Packer decoder
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _base_encode(num: int, radix: int) -> str:
    """Encode an integer into the given base-N radix string."""
    if num == 0:
        return "0"
    digits = []
    while num > 0:
        digits.append(_ALPHABET[num % radix])
        num //= radix
    return "".join(reversed(digits))


def unpack_packer(script: str) -> Optional[str]:
    """
    Unpack Dean Edwards JavaScript packer: eval(function(p,a,c,k,e,d)...).
    Pure in-memory base-62 dictionary substitution.
    """
    if not script or "eval(function(p,a,c,k" not in script:
        return None

    match = PACKER_PATTERN.search(script)
    if not match:
        return None

    try:
        raw_payload = match.group(1)
        radix = int(match.group(2))
        words_raw = match.group(4)

        # Strip outer quotes and normalize
        if (raw_payload.startswith("'") and raw_payload.endswith("'")) or (
            raw_payload.startswith('"') and raw_payload.endswith('"')
        ):
            payload = raw_payload[1:-1]
        else:
            payload = raw_payload

        # Unescape quotes
        payload = payload.replace(r"\'", "'").replace(r'\"', '"').replace(r"\\", "\\")

        # Extract words dictionary
        if (words_raw.startswith("'") and words_raw.endswith("'")) or (
            words_raw.startswith('"') and words_raw.endswith('"')
        ):
            words_str = words_raw[1:-1]
        else:
            words_str = words_raw
        words = words_str.split("|")

        # Build substitution table
        lookup = {}
        for i, word in enumerate(words):
            if word:
                lookup[_base_encode(i, radix)] = word

        def _sub(m: re.Match) -> str:
            token = m.group(0)
            return lookup.get(token, token)

        unpacked = re.sub(r"\b\w+\b", _sub, payload)

        # "Xài xong dọn" - clean up dictionary and local memory
        del lookup
        del words
        return unpacked
    except Exception as exc:
        logger.debug("Failed to unpack packer script: %s", exc)
        return None


class GenericWebExtractor(BaseExtractor):
    """
    Mechanism-based generic extractor capable of parsing video streams
    from any web page using common web video players, cyberlocker embeds,
    DOM data-attributes, and obfuscated JavaScript packers.
    """

    @classmethod
    def suitable(cls, url: str) -> bool:
        if not url or not isinstance(url, str):
            return False
        cleaned = url.strip()
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            return False

        # Layer 1: Local files handled by LocalFileExtractor
        try:
            from main.extractors.local import is_local_media_file
            if is_local_media_file(cleaned):
                return False
        except Exception:
            pass

        # Layer 2: Telegram handled by TelegramExtractor
        try:
            from main.extractors.telegram import TelegramExtractor
            if TelegramExtractor.suitable(cleaned):
                return False
        except Exception:
            pass

        # Layer 3: YouTube handled by YouTubeExtractor
        try:
            from main.extractors.youtube import YouTubeExtractor
            if YouTubeExtractor.suitable(cleaned):
                return False
        except Exception:
            pass

        try:
            parsed = urllib.parse.urlparse(cleaned.lower())
            host = parsed.netloc
            path = parsed.path
            query = parsed.query

            # Direct media playlists/manifests (e.g. .m3u8, .mpd) or plain media files
            # without web portal wrappers are handled directly by GenericExtractor
            if path.endswith((".m3u8", ".mpd", ".ts")):
                return False

            # Bypass Layer 4 for major platforms natively handled by yt-dlp
            ytdlp_primary_domains = (
                "facebook.com", "fb.watch", "fb.gg", "fb.com",
                "tiktok.com", "douyin.com",
                "twitter.com", "x.com",
                "instagram.com", "threads.net",
                "bilibili.com", "b23.tv",
                "twitch.tv", "vimeo.com", "dailymotion.com", "rumble.com",
                "reddit.com", "v.redd.it",
                "pornhub.com", "xvideos.com", "xnxx.com", "spankbang.com",
                "redtube.com", "youporn.com", "beeg.com", "xhamster.com",
            )
            if any(host == d or host.endswith("." + d) for d in ytdlp_primary_domains):
                return False

            # Check if this URL represents a potential web video page
            # 1. Video path keywords
            video_path_keywords = (
                "/video/", "/watch", "/reel/", "/reels/", "/shorts/",
                "/clip/", "/clips/", "/embed/", "/tv/", "/media/",
                "/play/", "/stream/", "/v/", "/hentai/", "/movie/",
                "/phim/", "/episode/", "/anime/", "/view/",
            )
            if any(kw in path for kw in video_path_keywords):
                return True

            # 2. Video query keywords
            if any(k in query for k in ("v=", "video_id=", "vid=", "mid=")):
                return True

            # 3. Video hosting / streaming / portal keywords in hostname
            host_video_keywords = (
                "vcast", "dood", "stream", "tape", "moon", "wish",
                "lulu", "drop", "voe", "vid", "play", "tv", "tube",
                "hentai", "sex", "phim", "anime", "vlxx", "xnhau",
            )
            if any(k in host for k in host_video_keywords):
                return True

            # Non-video websites (e.g. google.com, example.com homepage) without video paths
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
        stream_url, title, thumbnail = self.resolve_stream(url, timeout=timeout)
        if stream_url:
            return ResolvedVideo(
                stream_url=stream_url,
                title=title or "Web Video",
                duration=None,
                thumbnail=thumbnail,
                is_live=False,
            )

        # Fallback to GenericExtractor (yt-dlp) if generic heuristics did not resolve
        try:
            from main.extractors.generic import GenericExtractor
            generic_ext = GenericExtractor()
            logger.info("GenericWebExtractor heuristics returned no stream, falling back to yt-dlp...")
            return generic_ext.extract(
                url,
                cookie_file=cookie_file,
                max_height=max_height,
                timeout=timeout,
                retries=retries,
            )
        except Exception as exc:
            logger.debug("Fallback to GenericExtractor failed: %s", exc)
            raise VideoNotFoundError("Không tìm thấy luồng phát video cho liên kết web này.") from exc

    def resolve_stream(
        self, url: str, timeout: int = 10
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Main heuristic resolution pipeline:
        1. Fetch webpage HTML
        2. Extract title & thumbnail
        3. Hunt player config variables (videoData, __SRC, SVN, config, jwplayer, etc.)
        4. Hunt cyberlocker / host embeds (vcast, streamforester, dood, streamtape, etc.)
        5. Hunt CMS Ajax players (ajax.php endpoints)
        6. Decode any Dean Edwards packed scripts
        7. Extract HTML5 video / direct media links
        8. Route through StreamProxyServer if Referer or header de-obfuscation needed
        """
        page_html = None
        final_url = url
        custom_title = None
        custom_thumb = None

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
                    if isinstance(raw_geturl, str) and raw_geturl.startswith("http"):
                        final_url = raw_geturl
                except Exception:
                    final_url = url
                page_html = resp.read().decode("utf-8", errors="ignore")

            parsed_final = urllib.parse.urlparse(final_url)
            page_origin = f"{parsed_final.scheme}://{parsed_final.netloc}"

            # --- Extract Title & Thumbnail ---
            custom_title, custom_thumb = self._extract_metadata(page_html)

            # --- Engine A: Player Config Hunter ---
            stream_candidate, candidate_referer = self._hunt_player_configs(page_html, final_url, timeout=timeout)
            if stream_candidate:
                proxied = self._route_proxy_if_needed(stream_candidate, candidate_referer or page_origin)
                return proxied, custom_title, custom_thumb

            # --- Engine B: Cyberlocker & Host Embeds Resolver ---
            stream_candidate, candidate_referer = self._resolve_host_embeds(page_html, final_url, timeout=timeout)
            if stream_candidate:
                proxied = self._route_proxy_if_needed(stream_candidate, candidate_referer or page_origin)
                return proxied, custom_title, custom_thumb

            # --- Engine C: CMS Ajax Player Prober ---
            stream_candidate, candidate_referer = self._probe_ajax_player(page_html, final_url, timeout=timeout)
            if stream_candidate:
                proxied = self._route_proxy_if_needed(stream_candidate, candidate_referer or page_origin)
                return proxied, custom_title, custom_thumb

            # --- Engine D: Dean Edwards Packer Unpacker ---
            stream_candidate, candidate_referer = self._unpack_and_hunt(page_html, final_url)
            if stream_candidate:
                proxied = self._route_proxy_if_needed(stream_candidate, candidate_referer or page_origin)
                return proxied, custom_title, custom_thumb

            # --- Engine E: HTML5 / Direct Media Links ---
            stream_candidate, candidate_referer = self._extract_direct_media(page_html, final_url)
            if stream_candidate:
                proxied = self._route_proxy_if_needed(stream_candidate, candidate_referer or page_origin)
                return proxied, custom_title, custom_thumb

            return None, custom_title, custom_thumb
        except Exception as exc:
            logger.debug("Error in GenericWebExtractor.resolve_stream: %s", exc)
            return None, custom_title, custom_thumb
        finally:
            # "Xài xong dọn" (§16.4): Release raw page HTML string immediately
            if page_html is not None:
                del page_html
            gc.collect()

    # -------------------------------------------------------------------------
    # Internal Heuristic Engines
    # -------------------------------------------------------------------------

    def _extract_metadata(self, html_text: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract clean video title and thumbnail URL from HTML."""
        title = None
        thumb = None

        if not html_text:
            return None, None

        # 1. Title
        vt_m = re.search(r"video_title:\s*['\"]([^'\"]+)['\"]", html_text)
        if vt_m:
            title = html.unescape(vt_m.group(1)).strip()
        else:
            title_m = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE)
            if title_m:
                raw_title = html.unescape(title_m.group(1)).strip()
                # Clean common generic site branding suffixes dynamically
                cleaned = re.sub(
                    r"\s*[-–|]\s*(Hentai(Vietsub|Z)|VLXX|Sex\s*Việt\s*Mới|sexvietnew|xnhau|Phim.*|Watch.*|[a-zA-Z0-9.-]+\.(com|net|org|bot|tv|cab|vip|cc|phd|world|xyz)).*$",
                    "",
                    raw_title,
                    flags=re.IGNORECASE,
                ).strip()
                title = cleaned or raw_title

        # 2. Thumbnail
        vp_m = re.search(r"preview_url:\s*['\"]([^'\"]+)['\"]", html_text)
        if vp_m:
            thumb = html.unescape(vp_m.group(1)).strip()
        else:
            thumb_m = re.search(
                r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                html_text,
                re.IGNORECASE,
            )
            if not thumb_m:
                thumb_m = re.search(
                    r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                    html_text,
                    re.IGNORECASE,
                )
            if not thumb_m:
                thumb_m = re.search(
                    r'name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
                    html_text,
                    re.IGNORECASE,
                )
            if thumb_m:
                thumb = html.unescape(thumb_m.group(1)).strip()

        return title, thumb

    def _hunt_player_configs(
        self, html_text: str, base_url: str, timeout: int = 8
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Hunt for player config objects in JavaScript (videoData, __SRC, SVN, KVS flashvars, JSON-LD).
        """
        if not html_text:
            return None, None

        parsed_base = urllib.parse.urlparse(base_url)
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

        # 1. window.videoData = {...}
        vd_m = re.search(r'window\.videoData\s*=\s*(\{.*?\});', html_text, re.DOTALL)
        if vd_m:
            try:
                vd = json.loads(vd_m.group(1))
                if "sources" in vd and vd["sources"]:
                    f = vd["sources"][0].get("file") or vd["sources"][0].get("src")
                    if f:
                        return urllib.parse.urljoin(base_url, f), origin
                elif "id" in vd and "domain" in vd:
                    cfg_url = f"{origin}/videos/{vd['id']}/config?d={vd['domain']}"
                    cfg_req = urllib.request.Request(
                        cfg_url,
                        data=b"{}",
                        headers={
                            "User-Agent": FAKE_USER_AGENT,
                            "Referer": base_url,
                            "Origin": origin,
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(cfg_req, context=_SSL_CTX, timeout=timeout) as cfg_resp:
                        cfg_data = json.loads(cfg_resp.read().decode("utf-8"))
                        if "sources" in cfg_data and cfg_data["sources"]:
                            f = cfg_data["sources"][0].get("file") or cfg_data["sources"][0].get("src")
                            if f:
                                return urllib.parse.urljoin(base_url, f), origin
            except Exception:
                pass

        # 2. window.__SRC = [...]
        src_m = re.search(r'window\.__SRC\s*=\s*(\[.*?\]);', html_text, re.DOTALL)
        if src_m:
            try:
                src_list = json.loads(src_m.group(1))
                for item in src_list:
                    f = item.get("file") or item.get("src")
                    if f:
                        return urllib.parse.urljoin(base_url, f), origin
            except Exception:
                pass

        # 3. window.SVN_HLS_PLAYER_DATA = {...}
        svn_m = re.search(r'window\.SVN_HLS_PLAYER_DATA\s*=\s*(\{.*?\});', html_text, re.DOTALL)
        if svn_m:
            try:
                player_data = json.loads(svn_m.group(1))
                sources = player_data.get("sources", [])
                if sources and sources[0].get("src"):
                    return urllib.parse.urljoin(base_url, sources[0]["src"]), origin
            except Exception:
                pass

        # 4. Schema.org VideoObject / itemprop="contentUrl"
        cu_m = (
            re.search(r'itemprop=["\']contentUrl["\']\s+content=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
            or re.search(r'content=["\']([^"\']+)["\']\s+itemprop=["\']contentUrl["\']', html_text, re.IGNORECASE)
            or re.search(r'"contentUrl"\s*:\s*"([^"]+)"', html_text)
        )
        if cu_m:
            media_url = html.unescape(cu_m.group(1)).replace(r"\/", "/")
            return urllib.parse.urljoin(base_url, media_url), origin

        # 5. Flashvars / KVS player patterns (video_alt_url, video_url)
        for key in ["video_alt_url4", "video_alt_url3", "video_alt_url2", "video_alt_url", "video_url"]:
            m = re.search(rf"{key}:\s*['\"]([^'\"]+)['\"]", html_text)
            if m:
                val = m.group(1).replace(r"\/", "/")
                if (
                    val
                    and not any(bad in val.lower() for bad in ["login", "redirect", "signup"])
                    and any(good in val.lower() for good in ["/get_file/", ".mp4", ".m3u8", ".vl"])
                ):
                    return urllib.parse.urljoin(base_url, val), origin

        return None, None

    def _resolve_host_embeds(
        self, html_text: str, base_url: str, timeout: int = 8
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve cyberlocker and video player iframe / button embeds
        (vcast, streamforester, wogplayer, dood, streamtape, filemoon, etc.).
        """
        if not html_text:
            return None, None

        # 1. Check direct video ID / vcast.name embed
        vid_m = re.search(r'/videos/([a-f0-9]{24})', html_text)
        if vid_m:
            vid = vid_m.group(1)
            test_url = f"https://vcast.name/videos/{vid}/master.m3u8"
            try:
                t_req = urllib.request.Request(
                    test_url,
                    headers={"User-Agent": FAKE_USER_AGENT, "Referer": "https://vcast.name/"},
                )
                with urllib.request.urlopen(t_req, context=_SSL_CTX, timeout=5) as t_resp:
                    if t_resp.status == 200:
                        return test_url, "https://vcast.name/"
            except Exception:
                pass

        # 2. Extract embed candidates from data-source, data-src, or iframe
        raw_candidates = re.findall(
            r'(?:data-source|data-src|data-video)=["\']([^"\']+)["\']|<iframe[^>]+src=["\']([^"\']+)["\']',
            html_text,
            re.IGNORECASE,
        )
        sources: List[str] = []
        for c1, c2 in raw_candidates:
            c = (c1 or c2).strip()
            if c and not c.startswith("javascript:") and not c.startswith("about:"):
                full_src = urllib.parse.urljoin(base_url, html.unescape(c).replace(r"\/", "/"))
                if full_src not in sources:
                    sources.append(full_src)

        for src in sources[:5]:  # Bound search to first 5 embeds to prevent runaway network queries
            parsed_src = urllib.parse.urlparse(src)
            src_origin = f"{parsed_src.scheme}://{parsed_src.netloc}"

            # Check if source is direct master manifest or vcast
            if "vcast.name" in src and "/videos/" in src:
                vm = re.search(r'/videos/([a-f0-9]{24})', src)
                if vm:
                    test_url = f"https://vcast.name/videos/{vm.group(1)}/master.m3u8"
                    try:
                        t_req = urllib.request.Request(
                            test_url,
                            headers={"User-Agent": FAKE_USER_AGENT, "Referer": "https://vcast.name/"},
                        )
                        with urllib.request.urlopen(t_req, context=_SSL_CTX, timeout=5) as t_resp:
                            if t_resp.status == 200:
                                return test_url, "https://vcast.name/"
                    except Exception:
                        pass

            # Fetch embed page to search for player variables or nested players
            try:
                em_req = urllib.request.Request(
                    src,
                    headers={"User-Agent": FAKE_USER_AGENT, "Referer": base_url},
                )
                with urllib.request.urlopen(em_req, context=_SSL_CTX, timeout=timeout) as em_resp:
                    em_html = em_resp.read().decode("utf-8", errors="ignore")
                    em_final_url = em_resp.geturl()

                # Check player configs inside embed page
                found_url, found_ref = self._hunt_player_configs(em_html, em_final_url, timeout=timeout)
                if found_url:
                    del em_html
                    return found_url, found_ref or src_origin

                # Check packed scripts inside embed page
                found_url, found_ref = self._unpack_and_hunt(em_html, em_final_url)
                if found_url:
                    del em_html
                    return found_url, found_ref or src_origin

                del em_html
            except Exception:
                continue

        return None, None

    def _probe_ajax_player(
        self, html_text: str, base_url: str, timeout: int = 8
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Probe CMS ajax endpoint (e.g. ajax.php) to retrieve embed iframe and video stream.
        """
        if not html_text:
            return None, None

        parsed = urllib.parse.urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        m_vid = (
            re.search(r'data-id=["\'](\d+)["\']', html_text)
            or re.search(r'var\s+vid\s*=\s*(\d+)', html_text)
            or re.search(r"/(\d+)/?$", base_url)
        )
        if not m_vid:
            return None, None

        vid = m_vid.group(1)
        ajax_url = f"{origin}/ajax.php"

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
                        "Referer": base_url,
                        "X-Requested-With": "XMLHttpRequest",
                        "Origin": origin,
                    },
                )
                with urllib.request.urlopen(ajax_req, context=_SSL_CTX, timeout=timeout) as ajax_resp:
                    data = json.loads(ajax_resp.read().decode("utf-8", errors="ignore"))
                    player_html = data.get("player", "")
                    iframe_m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', player_html)
                    if iframe_m:
                        embed_url = iframe_m.group(1).replace(r"\/", "/")
                        em_origin = f"{urllib.parse.urlparse(embed_url).scheme}://{urllib.parse.urlparse(embed_url).netloc}/"
                        try:
                            em_req = urllib.request.Request(
                                embed_url,
                                headers={"User-Agent": FAKE_USER_AGENT, "Referer": base_url},
                            )
                            with urllib.request.urlopen(em_req, context=_SSL_CTX, timeout=timeout) as em_resp:
                                em_html = em_resp.read().decode("utf-8", errors="ignore")
                                em_final_url = em_resp.geturl()

                            found_url, found_ref = self._hunt_player_configs(em_html, em_final_url, timeout=timeout)
                            del em_html
                            if found_url:
                                return found_url, em_origin
                        except Exception:
                            pass

                        return embed_url, em_origin
            except Exception:
                continue

        return None, None

    def _unpack_and_hunt(self, html_text: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Search and unpack Dean Edwards packed scripts to reveal stream URLs."""
        if not html_text or "eval(function(p,a,c,k" not in html_text:
            return None, None

        parsed = urllib.parse.urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        for match in PACKER_PATTERN.finditer(html_text):
            unpacked = unpack_packer(match.group(0))
            if unpacked:
                found_url, found_ref = self._hunt_player_configs(unpacked, base_url)
                if found_url:
                    del unpacked
                    return found_url, found_ref or origin

                # Search direct m3u8 / mp4 in unpacked string
                direct_m = re.findall(r'https?://[^\s"\'<>]+\.(?:m3u8|mp4|vl)[^\s"\'<>]*', unpacked, re.IGNORECASE)
                for u in direct_m:
                    if not any(x in u.lower() for x in [".jpg", ".png", "preview", "timeline", "adv"]):
                        del unpacked
                        return u, origin

                del unpacked

        return None, None

    def _extract_direct_media(self, html_text: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract direct HTML5 <video> / <source> or direct media hyperlinks."""
        if not html_text:
            return None, None

        parsed = urllib.parse.urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # 1. HTML5 video or source tags
        srcs = re.findall(r'<(?:video|source)[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
        for s in srcs:
            clean = html.unescape(s).strip()
            if any(ext in clean.lower() for ext in [".m3u8", ".mp4", ".vl", "/get_file/"]):
                return urllib.parse.urljoin(base_url, clean), origin

        # 2. Direct regex scan for stream URLs
        direct_m = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8|vl)[^\s"\'<>]*', html_text, re.IGNORECASE)
        media_clean = [
            u for u in direct_m
            if not any(x in u.lower() for x in [".jpg", ".png", "preview", "timeline", "adv", "poster"])
        ]
        if media_clean:
            return media_clean[0], origin

        return None, None

    def _route_proxy_if_needed(self, stream_url: str, referer: Optional[str]) -> str:
        """
        Route stream through local StreamProxyServer if custom Referer,
        ByteDance image-chunk de-obfuscation, or multi-connection streaming is needed.
        """
        if not stream_url or stream_url.startswith("http://127.0.0.1:"):
            return stream_url

        url_lower = stream_url.lower()
        parsed_stream = urllib.parse.urlparse(stream_url)
        path_lower = parsed_stream.path.lower()
        host_lower = parsed_stream.netloc.lower()

        # Streams requiring StreamProxy:
        # 1. .vl files (ByteDance / image CDN TS chunks needing PNG header strip)
        # 2. .m3u8 manifests from anti-hotlink hosts (vcast, sdeli, streamforester, byteoversea, ibytedtos)
        # 3. Any .m3u8 stream with a known distinct referer
        requires_proxy = (
            path_lower.endswith(".vl")
            or ".vl?" in url_lower
            or any(h in host_lower for h in [
                "vcast.name", "sdeli.name", "streamforester", "mio9ecge", "byteoversea", "ibytedtos"
            ])
            or (referer and (".m3u8" in path_lower or ".m3u8?" in url_lower))
        )

        if requires_proxy:
            try:
                from main.stream_proxy import StreamProxyServer
                proxy = StreamProxyServer.get_instance()
                return proxy.get_proxy_playlist_url(stream_url, referer=referer)
            except Exception as exc:
                logger.warning("Failed to route stream through StreamProxyServer: %s", exc)

        # Rate-limited MP4 check
        if ".mp4" in url_lower and ("rate=" in url_lower or "phncdn.com" in url_lower):
            try:
                from main.stream_proxy import StreamProxyServer
                proxy = StreamProxyServer.get_instance()
                return proxy.get_proxy_mp4_url(stream_url, referer=referer)
            except Exception as exc:
                logger.warning("Failed to route rate-limited MP4 through StreamProxyServer: %s", exc)

        return stream_url
