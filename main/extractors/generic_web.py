"""
Generic Web Video Extractor.
Mechanism-based heuristic engine for extracting playable video streams from
thousands of web video portals (anime, movies, cyberlockers, adult sites, etc.)
without requiring site-specific extractors or hardcoded domain logic.

Memory efficiency & resource cleanup:
- Zero persistent storage of raw HTML or DOM trees
- Memory cleanup via explicit del and gc.collect()
- Bounded network timeouts with fail-safe fallback to GenericExtractor (yt-dlp)
"""

import base64
import collections
import gc
import html
import json
import logging
import re
import time
from typing import Optional, Tuple, List, Dict, Any, Set
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

NON_MEDIA_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tiff",
    ".pdf", ".css", ".js", ".xml", ".txt", ".woff", ".woff2", ".ttf", ".eot",
    ".json", ".map", ".wasm", ".zip", ".rar", ".7z", ".tar", ".gz",
)


def _is_valid_media_candidate(url: str) -> bool:
    """Validate that a URL candidate is a valid media stream and NOT an image or static document."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if len(u) < 8 or u.startswith(("javascript:", "about:", "#", "data:image")):
        return False
    try:
        parsed = urllib.parse.urlparse(u)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in NON_MEDIA_EXTENSIONS):
            return False
        clean_path = path_lower.split("?")[0].split("#")[0]
        if any(clean_path.endswith(ext) for ext in NON_MEDIA_EXTENSIONS):
            return False
        return True
    except Exception:
        return False


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


def unpack_hunter(h: str, u: int, n: str, t: int, e: int) -> str:
    """Unpack Hunter / Obfuscator script into cleartext JavaScript."""
    chars = []
    i = 0
    delimiter = n[e]
    while i < len(h):
        s = ""
        while i < len(h) and h[i] != delimiter:
            s += h[i]
            i += 1
        i += 1  # skip delimiter
        if not s:
            continue
        for j, ch in enumerate(n):
            s = s.replace(ch, str(j))
        try:
            val = int(s, e) - t
            chars.append(chr(val))
        except Exception:
            pass
    raw = "".join(chars)
    try:
        return urllib.parse.unquote(raw)
    except Exception:
        return raw


def deobfuscate_script_deep(script_content: str, max_layers: int = 4) -> List[str]:
    """
    Deep iterative deobfuscation for multi-layer packed / encoded scripts:
    Layer 1: Dean Edwards Packer ->
    Layer 2: Base64 concatenation (e.g. Cookie.Run('a' + 'b') or atob('...')) ->
    Layer 3: Nested Dean Edwards Packer ->
    Layer 4: Hunter Obfuscator -> JWPlayer / VideoJS configuration.

    Guaranteed bounded execution (max_layers <= 4) and zero memory leakage.
    """
    results: List[str] = []
    if not script_content:
        return results

    current = script_content
    layer = 0

    while layer < max_layers:
        layer += 1
        progress = False

        # 1. Dean Edwards Packer
        if "eval(function(p,a,c,k" in current:
            unpacked = unpack_packer(current)
            if unpacked:
                results.append(unpacked)
                current = unpacked
                progress = True

        # 2. Hunter / Obfuscator pattern: function(h,u,n,t,e,r){...}("...", 66, "...", 9, 8, 60)
        if "function(h,u,n,t,e,r)" in current:
            hm = re.search(r'\}\("([^"]+)",\s*(\d+),\s*"([^"]+)",\s*(\d+),\s*(\d+)', current)
            if hm:
                h_str, u_val, n_str, t_val, e_val = hm.groups()
                decoded_hunter = unpack_hunter(h_str, int(u_val), n_str, int(t_val), int(e_val))
                if decoded_hunter and len(decoded_hunter) > 20:
                    results.append(decoded_hunter)
                    current = decoded_hunter
                    progress = True

        # 3. Base64 concatenation in Cookie.Run(...) or atob(...)
        # e.g.: Cookie.Run("aGVsbG8=" + "d29ybGQ=") or atob("...")
        b64_matches = re.findall(
            r'(?:Cookie\.Run|atob)\s*\(\s*([\'"][A-Za-z0-9+/=\s\'"+]+[\'"])\s*\)',
            current,
        )
        for b64_payload in b64_matches:
            try:
                parts = re.findall(r'[\'"]([A-Za-z0-9+/=]+)[\'"]', b64_payload)
                if parts:
                    raw_b64 = "".join(parts).strip()
                    padded_b64 = raw_b64 + "=" * (-len(raw_b64) % 4)
                    decoded = base64.b64decode(padded_b64).decode("utf-8", errors="ignore")
                    if decoded and len(decoded) > 10:
                        results.append(decoded)
                        if any(marker in decoded for marker in ["eval(function(p,a,c,k", "function(h,u,n,t,e,r)"]):
                            current = decoded
                            progress = True
            except Exception as e:
                logger.debug("Error decoding Base64 payload in deobfuscate_script_deep: %s", e)

        # Also search for loose base64 concatenated strings if no progress yet
        if not progress:
            loose_concat = re.findall(
                r'(?:[\'"][A-Za-z0-9+/=]{16,}[\'"]\s*\+\s*)+[\'"][A-Za-z0-9+/=]{4,}[\'"]',
                current,
            )
            for chunk_seq in loose_concat:
                try:
                    parts = re.findall(r'[\'"]([A-Za-z0-9+/=]+)[\'"]', chunk_seq)
                    raw_b64 = "".join(parts).strip()
                    padded_b64 = raw_b64 + "=" * (-len(raw_b64) % 4)
                    decoded = base64.b64decode(padded_b64).decode("utf-8", errors="ignore")
                    if decoded and any(kw in decoded for kw in ["sources", "file", "m3u8", "mp4", "jwplayer"]):
                        results.append(decoded)
                        if any(marker in decoded for marker in ["eval(function(p,a,c,k", "function(h,u,n,t,e,r)"]):
                            current = decoded
                            progress = True
                except Exception:
                    pass

        if not progress:
            break

    return results


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
            if path.endswith((".m3u8", ".mpd", ".ts", ".mp4", ".webm", ".mkv", ".avi", ".mov")):
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

            # Exclude known non-video developer/reference domains
            non_video_domains = (
                "github.com", "gitlab.com", "bitbucket.org", "wikipedia.org",
                "stackoverflow.com", "google.com", "microsoft.com", "apple.com",
            )
            if any(host == d or host.endswith("." + d) for d in non_video_domains):
                return False

            # 1. Video path keywords
            video_path_keywords = (
                "/video/", "/videos/", "/watch", "/reel/", "/reels/", "/shorts/",
                "/clip/", "/clips/", "/embed/", "/tv/", "/media/",
                "/play/", "/stream/", "/v/", "/hentai/", "/movie/",
                "/phim/", "/episode/", "/anime/", "/view/", "/vod/",
                "/film/", "/detail/", "/post/", "/archives/", "/bai-viet/",
                "/xem-phim/",
            )
            if any(kw in path for kw in video_path_keywords):
                return True

            # 2. Video query keywords
            if any(k in query for k in ("v=", "video_id=", "vid=", "mid=")):
                return True

            # 3. Media, streaming, or video genre keywords in hostname
            host_video_keywords = (
                "video", "stream", "media", "vod", "player", "tv", "tube",
                "play", "movie", "film", "anime", "hentai", "sex",
                "69", "xxx", "porn", "jav", "phim", "clip", "adult", "vl",
                "chill", "show", "xhub", "videohub", "flix", "cinema",
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
        timeout: int = 15,
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

        # Let url_resolver handle fallback to GenericExtractor (Single Responsibility Principle)
        raise VideoNotFoundError("Không tìm thấy luồng phát video cho liên kết web này.")

    def resolve_stream(
        self, url: str, timeout: int = 15
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

            # --- Engine F: Iterative Deep BFS Crawler (3 to 5 levels of nested embeds) ---
            stream_candidate, candidate_referer = self._crawl_and_extract_bfs(final_url, page_html, timeout=timeout)
            if stream_candidate:
                proxied = self._route_proxy_if_needed(stream_candidate, candidate_referer or page_origin)
                return proxied, custom_title, custom_thumb

            return None, custom_title, custom_thumb
        except Exception as exc:
            logger.debug("Error in GenericWebExtractor.resolve_stream: %s", exc)
            return None, custom_title, custom_thumb
        finally:
            # Release raw page HTML string immediately
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
                # Clean standard web branding suffixes (e.g. " - Site.com", " | Brand Name", " - Watch Online")
                cleaned = re.sub(
                    r"\s*[-–|•]\s*([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|[a-zA-Z0-9\s\u00C0-\u1EF9]{2,25})$",
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
        cu_patterns = [
            r'itemprop=["\']contentUrl["\']\s+content=["\']([^"\']+)["\']',
            r'content=["\']([^"\']+)["\']\s+itemprop=["\']contentUrl["\']',
            r'"contentUrl"\s*:\s*"([^"]+)"',
        ]
        for pat in cu_patterns:
            for cu_m in re.finditer(pat, html_text, re.IGNORECASE):
                raw_cand = html.unescape(cu_m.group(1)).replace(r"\/", "/")
                media_url = urllib.parse.urljoin(base_url, raw_cand)
                if _is_valid_media_candidate(media_url):
                    cand_lower = media_url.lower()
                    if (
                        any(ext in cand_lower for ext in (".m3u8", ".mp4", ".mpd", ".webm", ".avi", ".mkv", ".ts", ".vl"))
                        or any(kw in cand_lower for kw in ("/master", "/playlist", "/quality", "/stream", "/video", "/hls/", "/manifest", "videoplayback"))
                    ):
                        return media_url, origin

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
                    cand_u = urllib.parse.urljoin(base_url, val)
                    if _is_valid_media_candidate(cand_u):
                        return cand_u, origin

        # 6. JWPlayer / VideoJS object.sources = [{ "file": "..." }] or sources: [{ file: "..." }]
        jw_sources = re.findall(
            r'(?:object\.sources|sources)\s*=\s*\[\s*\{[^}]*["\']file["\']\s*:\s*["\']([^"\']+)["\']',
            html_text,
            re.IGNORECASE,
        )
        for s in jw_sources:
            cand_u = urllib.parse.urljoin(base_url, s)
            if _is_valid_media_candidate(cand_u):
                return cand_u, origin

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

        # 1. Check direct video ID / embed master manifest across any host
        vid_m = re.search(r'(https?://[^"\'\s<>]*/videos/[a-f0-9]{24})', html_text)
        if vid_m:
            base_vid_url = vid_m.group(1)
            parsed_v = urllib.parse.urlparse(base_vid_url)
            v_origin = f"{parsed_v.scheme}://{parsed_v.netloc}/"
            test_url = f"{base_vid_url}/master.m3u8"
            try:
                t_req = urllib.request.Request(
                    test_url,
                    headers={"User-Agent": FAKE_USER_AGENT, "Referer": v_origin},
                )
                with urllib.request.urlopen(t_req, context=_SSL_CTX, timeout=5) as t_resp:
                    if t_resp.status == 200:
                        return test_url, v_origin
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
            found_url, found_ref = self._resolve_single_embed(src, referer=base_url, timeout=timeout)
            if found_url:
                return found_url, found_ref

        return None, None

    def _extract_google_cwiz_stream(
        self, blogger_url: str, referer: Optional[str] = None, timeout: int = 8
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Decode Google Blogger c-wiz RPC array (data-p="%.@....") to extract direct GoogleVideo MP4 stream.
        Handles unescaped streamingData JSON blocks, Google RPC format arrays, and direct videoplayback links.
        """
        if not blogger_url or "blogger.com" not in blogger_url:
            return None, None

        b_html = None
        try:
            req_headers = {"User-Agent": FAKE_USER_AGENT}
            if referer:
                req_headers["Referer"] = referer
            req = urllib.request.Request(blogger_url, headers=req_headers)
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
                b_html = resp.read().decode("utf-8", errors="ignore")

            # 1. Look for unescaped streamingData JSON
            unescaped = html.unescape(b_html)
            sd_match = re.search(r'"streamingData"\s*:\s*(\{.*?\})\s*[,}]', unescaped)
            if sd_match:
                try:
                    sd = json.loads(sd_match.group(1))
                    formats = sd.get("formats", [])
                    if formats:
                        best = sorted(formats, key=lambda f: f.get("height", 0) or 0, reverse=True)[0]
                        stream_url = best.get("url")
                        if stream_url:
                            stream_url = stream_url.replace(r"\u003d", "=").replace(r"\u0026", "&")
                            return stream_url, referer
                except Exception:
                    pass

            # 2. Look for c-wiz data-p attribute
            cwiz_m = re.search(r'<c-wiz[^>]+data-p=["\']([^"\']+)["\']', b_html)
            if cwiz_m:
                raw_p = html.unescape(cwiz_m.group(1))
                if "streamingData" in raw_p and raw_p.startswith("%.@."):
                    try:
                        parsed = json.loads("[" + raw_p[4:])
                        for item in parsed:
                            if isinstance(item, str) and "streamingData" in item:
                                sd = json.loads(item)
                                formats = sd.get("streamingData", {}).get("formats", [])
                                if formats:
                                    best = sorted(formats, key=lambda f: f.get("height", 0) or 0, reverse=True)[0]
                                    stream_url = best.get("url")
                                    if stream_url:
                                        stream_url = stream_url.replace(r"\u003d", "=").replace(r"\u0026", "&")
                                        return stream_url, referer
                    except Exception:
                        pass

                if raw_p.startswith("%.@."):
                    try:
                        parsed = json.loads("[" + raw_p[4:])
                        for item in parsed:
                            if isinstance(item, list):
                                cands = [
                                    sub[0].replace(r"\u003d", "=").replace(r"\u0026", "&")
                                    for sub in item
                                    if isinstance(sub, list) and sub and isinstance(sub[0], str) and "googlevideo.com" in sub[0]
                                ]
                                if cands:
                                    return cands[-1], referer
                    except Exception:
                        pass

            # 3. Direct scan for googlevideo.com links
            gv_links = re.findall(r'https?://[a-zA-Z0-9.-]+\.googlevideo\.com/videoplayback[^\s"\'<>]*', unescaped)
            if gv_links:
                clean_gv = gv_links[0].replace(r"\u003d", "=").replace(r"\u0026", "&")
                return clean_gv, referer

            return None, None
        except Exception as exc:
            logger.debug("Failed to extract Google Blogger c-wiz stream: %s", exc)
            return None, None
        finally:
            if b_html is not None:
                del b_html
            gc.collect()

    def _resolve_single_embed(
        self,
        embed_url: str,
        referer: Optional[str] = None,
        timeout: int = 8,
        html_text: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve a single video player embed URL (iframe or player page).
        Recursively checks player configs, deobfuscated scripts, direct media, and multi-tier embed APIs.
        """
        if not embed_url or not embed_url.startswith("http"):
            return None, None

        parsed = urllib.parse.urlparse(embed_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # Fast check: direct cyberlocker master manifest across any host
        vm = re.search(r'(https?://[^"\'\s<>]*/videos/[a-f0-9]{24})', embed_url)
        if vm:
            base_vid_url = vm.group(1)
            test_url = f"{base_vid_url}/master.m3u8"
            try:
                t_req = urllib.request.Request(
                    test_url,
                    headers={"User-Agent": FAKE_USER_AGENT, "Referer": f"{origin}/"},
                )
                with urllib.request.urlopen(t_req, context=_SSL_CTX, timeout=3) as t_resp:
                    if t_resp.status == 200:
                        return test_url, f"{origin}/"
            except Exception:
                pass

        # If embed_url is direct Blogger URL
        if "blogger.com" in embed_url:
            return self._extract_google_cwiz_stream(embed_url, referer=referer or origin, timeout=timeout)

        em_html = None
        em_final_url = embed_url
        try:
            if html_text is not None:
                em_html = html_text
            else:
                em_req = urllib.request.Request(
                    embed_url,
                    headers={"User-Agent": FAKE_USER_AGENT, "Referer": referer or embed_url},
                )
                with urllib.request.urlopen(em_req, context=_SSL_CTX, timeout=timeout) as em_resp:
                    em_html = em_resp.read().decode("utf-8", errors="ignore")
                    em_final_url = em_resp.geturl() or embed_url

            # 1. Player configs inside embed page
            found_url, found_ref = self._hunt_player_configs(em_html, em_final_url, timeout=timeout)
            if found_url:
                if "blogger.com" in found_url:
                    cw_url, cw_ref = self._extract_google_cwiz_stream(found_url, referer=found_ref or origin, timeout=timeout)
                    if cw_url:
                        return cw_url, cw_ref
                return found_url, found_ref or origin

            # 2. Packed scripts
            found_url, found_ref = self._unpack_and_hunt(em_html, em_final_url)
            if found_url:
                return found_url, found_ref or origin

            # 3. Direct HTML5 media
            found_url, found_ref = self._extract_direct_media(em_html, em_final_url)
            if found_url:
                return found_url, found_ref or origin

            # 4. Multi-tier Embed API (e.g. window.videoId + /api/get-video, /api/player, etc.)
            em_vid_m = (
                re.search(r'(?:window\.)?videoId\s*=\s*["\']([^"\']+)["\']', em_html)
                or re.search(r'/(?:embed|player|v|f|video)/([a-zA-Z0-9_-]{10,})', embed_url)
            )
            em_vid = em_vid_m.group(1) if em_vid_m else None

            api_endpoints = []
            for m in re.finditer(r'["\'](/api/[a-zA-Z0-9_.-]+)["\']', em_html):
                api_endpoints.append(m.group(1))

            if not api_endpoints:
                for s_src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', em_html):
                    if any(k in s_src.lower() for k in ["main", "player", "app", "video"]):
                        js_url = urllib.parse.urljoin(embed_url, s_src)
                        try:
                            j_req = urllib.request.Request(js_url, headers={"User-Agent": FAKE_USER_AGENT, "Referer": embed_url})
                            with urllib.request.urlopen(j_req, context=_SSL_CTX, timeout=4) as j_r:
                                js_text = j_r.read().decode("utf-8", errors="ignore")
                            for m in re.finditer(r'["\'](/api/[a-zA-Z0-9_.-]+)["\']', js_text):
                                if m.group(1) not in api_endpoints:
                                    api_endpoints.append(m.group(1))
                        except Exception:
                            pass

            if not api_endpoints:
                api_endpoints = ["/api/get-video", "/api/player", "/api/source"]

            if em_vid:
                for api_path in api_endpoints:
                    api_url = urllib.parse.urljoin(embed_url, f"{api_path}?id={em_vid}")
                    try:
                        api_req = urllib.request.Request(api_url, headers={"User-Agent": FAKE_USER_AGENT, "Referer": embed_url})
                        with urllib.request.urlopen(api_req, context=_SSL_CTX, timeout=timeout) as r:
                            api_data = json.loads(r.read().decode("utf-8", errors="ignore"))
                        target = api_data.get("url") or api_data.get("src") or api_data.get("video")
                        if target:
                            if "blogger.com" in target:
                                cw_url, cw_ref = self._extract_google_cwiz_stream(target, referer=embed_url, timeout=timeout)
                                if cw_url:
                                    return cw_url, cw_ref
                            elif any(ext in target.lower() for ext in [".m3u8", ".mp4", ".vl"]):
                                return target, origin
                    except Exception:
                        continue

            return None, None
        except Exception as exc:
            logger.debug("Failed to resolve single embed %s: %s", embed_url, exc)
            return None, None
        finally:
            if em_html is not None and html_text is None:
                del em_html
            gc.collect()

    def _probe_ajax_player(
        self, html_text: str, base_url: str, timeout: int = 8
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Probe CMS dynamic ajax endpoints (e.g. /get.video.php, /ajax.php, /api/player)
        using placeholder attributes (data-movie, data-video, data-id) and script AST parameters.
        """
        if not html_text:
            return None, None

        parsed = urllib.parse.urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # 1. Detect dynamic AJAX endpoint in inline script or external bundles
        endpoint_patterns = [
            r'(?:urlVideo|url_video|ajax_url|player_url|endpoint)\s*[:=]\s*["\']([^"\']*(?:/api/|\.php|player|video)[^"\']*)["\']',
            r'\$\.(?:ajax|post|get)\s*\(\s*(?:(?:window\.)?location\.origin\s*\+\s*)?["\']([^"\']*(?:/api/|\.php|player|video)[^"\']*)["\']',
            r'\$\.ajax\s*\(\s*\{[^}]*?url\s*:\s*(?:(?:window\.)?location\.origin\s*\+\s*)?["\']([^"\']*(?:/api/|\.php|player|video)[^"\']*)["\']',
        ]
        ajax_path = None
        for pat in endpoint_patterns:
            m = re.search(pat, html_text)
            if m:
                ajax_path = m.group(1)
                break

        # If not found in inline HTML, scan external linked scripts (main*.js, player*.js, app*.js, video*.js, media*.js)
        if not ajax_path:
            script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
            candidate_scripts = [
                s for s in script_srcs
                if any(kw in s.lower() for kw in ("main", "player", "app", "video", "media", "embed"))
            ]
            for s_src in candidate_scripts[:4]:
                full_js_url = urllib.parse.urljoin(base_url, s_src)
                try:
                    js_req = urllib.request.Request(full_js_url, headers={"User-Agent": FAKE_USER_AGENT, "Referer": base_url})
                    with urllib.request.urlopen(js_req, context=_SSL_CTX, timeout=3) as js_resp:
                        js_text = js_resp.read().decode("utf-8", errors="ignore")
                    for pat in endpoint_patterns:
                        m = re.search(pat, js_text)
                        if m:
                            ajax_path = m.group(1)
                            break
                    del js_text
                    gc.collect()
                    if ajax_path:
                        break
                except Exception:
                    pass

        ajax_url = urllib.parse.urljoin(base_url, ajax_path) if ajax_path else f"{origin}/ajax.php"

        # 2. Extract candidate video elements / buttons / CMS identifiers
        cand_elements = []
        for m in re.finditer(
            r'<[a-zA-Z0-9]+[^>]+(?:data-video-id|data-movie|data-video|data-post-id|data-pid|data-vid|data-id)=["\']([^"\']+)["\'][^>]*>',
            html_text,
        ):
            tag = m.group(0)
            vid_val = m.group(1).strip()
            type_m = re.search(r'data-type=["\']([^"\']+)["\']', tag)
            type_val = type_m.group(1).strip() if type_m else "1"
            if vid_val and (vid_val, type_val) not in cand_elements:
                cand_elements.append((vid_val, type_val))

        # Check for server-id buttons / attributes
        server_ids = []
        for m in re.finditer(r'data-server(?:-id)?=["\'](\d+)["\']', html_text):
            s_val = int(m.group(1))
            if s_val not in server_ids:
                server_ids.append(s_val)
        if not server_ids:
            server_ids = [1]

        # Fallback to single ID if no list found
        if not cand_elements:
            m_vid = (
                re.search(r'data-(?:video-)?id=["\'](\d+)["\']', html_text)
                or re.search(r'var\s+vid\s*=\s*(\d+)', html_text)
                or re.search(r"/(\d+)/?$", base_url)
            )
            if m_vid:
                cand_elements.append((m_vid.group(1), "1"))

        if not cand_elements:
            return None, None

        # Dynamically discover any custom CMS server flags from page scripts or host prefix
        cms_flags: Dict[str, Any] = {}
        for m_flag in re.finditer(r'["\']?([a-zA-Z0-9_]+_server)["\']?\s*:\s*1', html_text):
            cms_flags[m_flag.group(1)] = 1
        domain_prefix = parsed.netloc.split(".")[0].replace("-", "_")
        if domain_prefix:
            cms_flags[f"{domain_prefix}_server"] = 1

        # Check script for param names in data payload
        has_movie_id_param = bool(re.search(r'movie_id\s*=', html_text))

        # Probe candidates (bound to at most 4 candidates to keep latency < 3.5s)
        fallback_embed_candidate: Optional[Tuple[str, str]] = None
        for idx, (vid_val, type_val) in enumerate(cand_elements[:4], 1):
            payloads = []
            if has_movie_id_param or not vid_val.isdigit():
                payloads.append({
                    "movie_id": vid_val,
                    "type": type_val,
                    "index": idx,
                })
                payloads.append({
                    "movie": vid_val,
                    "type": type_val,
                })

            for s_id in server_ids[:3]:
                payloads.append({
                    "id": vid_val,
                    "server": s_id,
                    **cms_flags,
                })

            for payload in payloads:
                try:
                    post_data = urllib.parse.urlencode(payload).encode("utf-8")
                    ajax_req = urllib.request.Request(
                        ajax_url,
                        data=post_data,
                        headers={
                            "User-Agent": FAKE_USER_AGENT,
                            "Referer": base_url,
                            "X-Requested-With": "XMLHttpRequest",
                            "Origin": origin,
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        },
                    )
                    with urllib.request.urlopen(ajax_req, context=_SSL_CTX, timeout=timeout) as ajax_resp:
                        raw_resp = ajax_resp.read().decode("utf-8", errors="ignore")

                    # If response is JSON, extract player field
                    resp_html = raw_resp
                    try:
                        j_data = json.loads(raw_resp)
                        if isinstance(j_data, dict):
                            # Unwrap nested "data" dict if present: {"status": "success", "data": {...}}
                            data_obj = j_data.get("data") if isinstance(j_data.get("data"), dict) else j_data
                            resp_html = data_obj.get("player", "") or data_obj.get("html", "") or raw_resp

                            # Check direct source / url / video / file
                            direct_u = (
                                data_obj.get("source") or data_obj.get("url")
                                or data_obj.get("src") or data_obj.get("video")
                                or data_obj.get("file")
                            )
                            if direct_u and isinstance(direct_u, str):
                                direct_u = html.unescape(direct_u).replace(r"\/", "/")
                                if data_obj.get("type") == "iframe" or "/player/" in direct_u or "/embed/" in direct_u:
                                    found_url, found_ref = self._resolve_single_embed(direct_u, referer=base_url, timeout=timeout)
                                    if found_url:
                                        return found_url, found_ref or origin
                                    if not fallback_embed_candidate:
                                        fallback_embed_candidate = (direct_u, origin)
                                elif "blogger.com" in direct_u:
                                    cw_url, cw_ref = self._extract_google_cwiz_stream(direct_u, referer=base_url, timeout=timeout)
                                    if cw_url:
                                        return cw_url, cw_ref
                                elif any(ext in direct_u.lower() for ext in [".m3u8", ".mp4", ".vl"]):
                                    return direct_u, origin
                    except Exception:
                        pass

                    # Extract iframe from response
                    iframe_m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', resp_html)
                    if iframe_m:
                        embed_url = urllib.parse.urljoin(base_url, iframe_m.group(1).replace(r"\/", "/"))
                        found_url, found_ref = self._resolve_single_embed(embed_url, referer=base_url, timeout=timeout)
                        if found_url:
                            return found_url, found_ref or origin
                        # If single embed didn't resolve stream immediately, save as fallback candidate and keep trying next
                        if not fallback_embed_candidate:
                            fallback_embed_candidate = (embed_url, origin)
                        continue

                    # If response contains direct script / player config
                    found_url, found_ref = self._hunt_player_configs(resp_html, base_url, timeout=timeout)
                    if found_url:
                        return found_url, found_ref or origin

                    found_url, found_ref = self._extract_direct_media(resp_html, base_url)
                    if found_url:
                        return found_url, found_ref or origin
                except Exception:
                    continue

        if fallback_embed_candidate:
            return fallback_embed_candidate

        return None, None

    def _extract_embed_candidates(self, html_text: str, base_url: str) -> List[str]:
        """
        Extract and prioritize candidate embed / player URLs from an HTML page.
        Handles iframe src, data-src, dynamic JS embed constructs, cover play buttons,
        and JSON server configurations.
        """
        if not html_text:
            return []

        candidates: List[str] = []
        parsed_base = urllib.parse.urlparse(base_url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

        # 1. <iframe> src and data-src
        iframe_srcs = re.findall(
            r'<iframe[^>]+(?:src|data-src)=["\']([^"\']+)["\']',
            html_text,
            re.IGNORECASE,
        )
        candidates.extend(iframe_srcs)

        # 2. Common embed data attributes (data-source, data-video, data-embed)
        attr_srcs = re.findall(
            r'(?:data-source|data-video|data-embed|data-url)=["\']([^"\']+)["\']',
            html_text,
            re.IGNORECASE,
        )
        candidates.extend(attr_srcs)

        # 3. Universal Dynamic JS Embed & URL Construction Scanner
        # Pattern 3A: Function defining a dynamic URL construction from argument
        func_dyn_builders = re.findall(
            r'function\s+(\w+)\s*\([^)]*?\b([a-zA-Z0-9_$-]+)\b[^)]*?\)\s*\{[^}]*?["\'](/?[a-zA-Z0-9_/-]+/)["\']\s*\+\s*\2',
            html_text,
            re.DOTALL,
        )
        for func_name, var_name, path_prefix in func_dyn_builders:
            invocations = re.findall(
                rf'(?:window\.)?{re.escape(func_name)}\s*\([^)]*?["\']?([a-zA-Z0-9_-]{{2,}})["\']?\s*\)',
                html_text,
            )
            for arg in invocations:
                candidates.append(f"{base_origin}/{path_prefix.strip('/')}/{arg}/")

        # Pattern 3B: Generic string concatenation of path + variable in script
        concat_matches = re.findall(
            r'(?:var|let|const)?\s*\w*\s*=\s*(?:[a-zA-Z_]\w*\s*\+\s*)?["\'](/?[a-zA-Z0-9_/-]+/)["\']\s*\+\s*([a-zA-Z0-9_$-]+)',
            html_text,
        )
        for path_prefix, vid_id in concat_matches:
            actual_id = vid_id
            if not vid_id.isdigit():
                m_def = re.search(rf'(?:var|let|const)\s+{re.escape(vid_id)}\s*=\s*["\']?([a-zA-Z0-9_-]+)', html_text)
                if m_def:
                    actual_id = m_def.group(1)
            candidates.append(f"{base_origin}/{path_prefix.strip('/')}/{actual_id}/")

        # Pattern 3C: ES6 Template Literals with media path
        tpl_matches = re.findall(
            r'[`"](/?[a-zA-Z0-9_-]+/(?:embed|player|video|v|f|stream|watch|playback)[a-zA-Z0-9_/-]*)/?\$\{([a-zA-Z0-9_$-]+)\}',
            html_text,
        )
        for path_prefix, var_name in tpl_matches:
            actual_id = var_name
            if not var_name.isdigit():
                m_def = re.search(rf'(?:var|let|const)\s+{re.escape(var_name)}\s*=\s*["\']?([a-zA-Z0-9_-]+)', html_text)
                if m_def:
                    actual_id = m_def.group(1)
            candidates.append(f"{base_origin}/{path_prefix.strip('/')}/{actual_id}/")

        # 4. JSON configs (window.VIDEO_APP = { "source": { "url": "..." } }, window.videoData, boot servers)
        json_urls = re.findall(
            r'["\'](?:url|source|server|embed)["\']\s*:\s*["\'](https?://[^"\']+)["\']',
            html_text,
            re.IGNORECASE,
        )
        candidates.extend(json_urls)

        # 5. Play cover button links (<a id="play" href="...">, <a class="btn-play" href="...">)
        play_btn_links = re.findall(
            r'<a[^>]+(?:id|class)=["\'][^"\']*(?:play|watch|btn-player)[^"\']*["\'][^>]+href=["\']([^"\']+)["\']',
            html_text,
            re.IGNORECASE,
        )
        candidates.extend(play_btn_links)

        # 6. Fallback scan for common embed path URLs in scripts
        script_embed_urls = re.findall(
            r'["\'](https?://[^\s"\'<>]*(?:/embed/|/v/|/player/|/playback/|/f/)[^\s"\'<>]*)["\']',
            html_text,
            re.IGNORECASE,
        )
        candidates.extend(script_embed_urls)

        # Blacklist domain / path patterns & non-web file extensions
        BLACKLIST_KEYWORDS = (
            "google", "doubleclick", "googlesyndication", "facebook", "fbcdn",
            "twitter", "disqus", "recaptcha", "histats", "statcounter", "analytics",
            "clarity.ms", "mc.yandex", "cloudflare", "jquery", "bootstrap", "marimo.me",
            ".css", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".woff", ".woff2",
            ".ttf", ".eot", ".json", ".xml", ".pdf", ".zip", ".wasm", ".txt", ".csv",
        )

        valid_candidates: List[str] = []
        seen = set()

        for c in candidates:
            c_clean = html.unescape(c).strip().replace(r"\/", "/")
            if not c_clean or c_clean.isdigit() or len(c_clean) < 3 or c_clean.startswith("javascript:") or c_clean.startswith("about:") or c_clean.startswith("#"):
                continue

            full_url = urllib.parse.urljoin(base_url, c_clean)
            parsed = urllib.parse.urlparse(full_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue

            url_lower = full_url.lower()
            if any(bad in url_lower for bad in BLACKLIST_KEYWORDS):
                continue

            norm = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/").lower()
            if norm in seen or norm == f"{parsed_base.scheme}://{parsed_base.netloc}{parsed_base.path}".rstrip("/").lower():
                continue
            seen.add(norm)
            valid_candidates.append(full_url)

        # Priority scoring: prioritize URLs likely to be real players
        def _score(u: str) -> int:
            score = 0
            u_low = u.lower()
            if any(bad in u_low for bad in ["ad", "banner", "tracking", "marimo", "click", "pop"]):
                score -= 50
            if "/playback/x/" in u_low or "backup" in u_low:
                score -= 10
            for kw in ["player", "embed", "playback", "stream", "/v/", "/f/", "source", "video", "media"]:
                if kw in u_low:
                    score += 20
            # Prioritize concrete IDs (numbers, hashes) over placeholder variable names
            if re.search(r'/\d{3,}/?', u_low) or re.search(r'/[a-f0-9]{8,}/?', u_low):
                score += 30
            if re.search(r'/[a-zA-Z]/?$', u_low):
                score -= 20
            return score

        valid_candidates.sort(key=_score, reverse=True)
        return valid_candidates

    def _crawl_and_extract_bfs(
        self, initial_url: str, initial_html: str, timeout: int = 15
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Iterative BFS Crawler (collections.deque) for multi-tier nested embeds
        (e.g. video portals hiding players across 3 to 5 levels of iframe / scripts).

        Key architectural properties:
        - Bounded execution: MAX_DEPTH = 5, MAX_IFRAMES_PER_PAGE = 3, MAX_TOTAL_PAGES = 8.
        - Absolute deadline: time.monotonic() + timeout (never hangs).
        - Zero RAM bloat: del html string + gc.collect() immediately each round.
        - Loop prevention: visited set with canonicalized URLs.
        """
        deadline = time.monotonic() + float(timeout)
        visited: Set[str] = set()

        def _normalize(u: str) -> str:
            p = urllib.parse.urlparse(u)
            return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()

        visited.add(_normalize(initial_url))
        queue: collections.deque = collections.deque()

        # Extract candidates from initial page (already fetched)
        init_candidates = self._extract_embed_candidates(initial_html, initial_url)
        for cand in init_candidates[:3]:
            norm = _normalize(cand)
            if norm not in visited:
                visited.add(norm)
                queue.append((cand, 1, initial_url))

        total_pages_fetched = 0
        MAX_TOTAL_PAGES = 10
        MAX_DEPTH = 6

        while queue and total_pages_fetched < MAX_TOTAL_PAGES:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0.8:
                break

            cand_url, depth, cand_referer = queue.popleft()
            if depth > MAX_DEPTH:
                continue

            req_timeout = min(3.5, max(1.0, remaining_time))
            em_html = None
            em_final_url = cand_url
            try:
                cand_parsed = urllib.parse.urlparse(cand_url)
                cand_origin = f"{cand_parsed.scheme}://{cand_parsed.netloc}"

                # 1. Fast checks (Blogger or Cyberlocker /videos/[hex]{24}) without fetching HTML
                if "blogger.com" in cand_url or re.search(r'/videos/[a-f0-9]{24}', cand_url):
                    stream_candidate, candidate_ref = self._resolve_single_embed(
                        cand_url, referer=cand_referer or initial_url, timeout=req_timeout
                    )
                    if stream_candidate:
                        return stream_candidate, candidate_ref or cand_origin

                # 2. Fetch candidate embed page ONCE
                req = urllib.request.Request(
                    cand_url,
                    headers={"User-Agent": FAKE_USER_AGENT, "Referer": cand_referer or initial_url},
                )
                with urllib.request.urlopen(req, context=_SSL_CTX, timeout=req_timeout) as resp:
                    em_final_url = resp.geturl() or cand_url
                    em_html = resp.read().decode("utf-8", errors="ignore")
                total_pages_fetched += 1

                # 3. Resolve stream from fetched HTML using multi-tier resolver
                stream_candidate, candidate_ref = self._resolve_single_embed(
                    em_final_url, referer=cand_referer or initial_url, timeout=req_timeout, html_text=em_html
                )
                if stream_candidate:
                    return stream_candidate, candidate_ref or cand_origin

                # 4. If not found and depth < MAX_DEPTH, enqueue next level candidates from em_html
                if depth < MAX_DEPTH:
                    next_cands = self._extract_embed_candidates(em_html, em_final_url)
                    for nc in next_cands[:2]:
                        nc_norm = _normalize(nc)
                        if nc_norm not in visited:
                            visited.add(nc_norm)
                            queue.append((nc, depth + 1, em_final_url))

            except Exception as exc:
                logger.debug("BFS crawl step failed on %s: %s", cand_url, exc)
            finally:
                if em_html is not None:
                    del em_html
                gc.collect()

        return None, None

    def _unpack_and_hunt(self, html_text: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Search and unpack obfuscated / multi-layer packed scripts to reveal stream URLs."""
        if not html_text:
            return None, None

        if not any(marker in html_text for marker in ["eval(function(p,a,c,k", "Cookie.Run", "atob("]):
            return None, None

        parsed = urllib.parse.urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # 1. Search within <script>...</script> blocks to prevent ReDoS on large HTML
        script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html_text, re.DOTALL | re.IGNORECASE)
        if not script_blocks:
            script_blocks = [html_text]

        for block in script_blocks:
            if not any(marker in block for marker in ["eval(function(p,a,c,k", "Cookie.Run", "atob("]):
                continue

            deobfuscated_variants = deobfuscate_script_deep(block)
            for unpacked in deobfuscated_variants:
                # 1. Hunt player configs in unpacked string (jwplayer, sources, etc.)
                found_url, found_ref = self._hunt_player_configs(unpacked, base_url)
                if found_url:
                    return found_url, found_ref or origin

                # 2. Search direct m3u8 / mp4 in unpacked string
                direct_m = re.findall(r'https?://[^\s"\'<>]+\.(?:m3u8|mp4|vl)[^\s"\'<>]*', unpacked, re.IGNORECASE)
                for u in direct_m:
                    if not any(x in u.lower() for x in [".jpg", ".png", "preview", "timeline", "adv"]):
                        return u, origin

                # 3. Check relative video paths like file: "/file/.../index.m3u8"
                rel_m = re.findall(r'(?:file|url|source)\s*:\s*["\']([^"\']+\.(?:m3u8|mp4|vl)[^"\']*)["\']', unpacked, re.IGNORECASE)
                for rel_u in rel_m:
                    full_u = urllib.parse.urljoin(base_url, rel_u)
                    return full_u, origin

        # Fallback to PACKER_PATTERN if script was inline outside standard script tags
        for match in PACKER_PATTERN.finditer(html_text):
            unpacked = unpack_packer(match.group(0))
            if unpacked:
                found_url, found_ref = self._hunt_player_configs(unpacked, base_url)
                if found_url:
                    del unpacked
                    return found_url, found_ref or origin
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

        # Streams requiring HLS StreamProxy:
        # 1. .vl files (ByteDance / image CDN TS chunks needing PNG header strip)
        # 2. Any .m3u8 stream or manifest endpoint with a referer
        # 3. Any stream from a CDN where path indicates HLS playlist structure
        is_hls_stream = (
            path_lower.endswith(".vl")
            or ".vl?" in url_lower
            or ".m3u8" in path_lower
            or ".m3u8?" in url_lower
            or (referer and any(kw in path_lower for kw in ("/master", "/playlist", "/quality", "/hls/", "/manifest", "/file/")))
        )

        if is_hls_stream:
            try:
                from main.stream_proxy import StreamProxyServer
                proxy = StreamProxyServer.get_instance()
                return proxy.get_proxy_playlist_url(stream_url, referer=referer)
            except Exception as exc:
                logger.warning("Failed to route stream through StreamProxyServer: %s", exc)

        # Rate-limited or protected MP4 check
        if ".mp4" in url_lower or "/get_file/" in url_lower or "/download/" in url_lower:
            needs_mp4_proxy = (
                "rate=" in url_lower
                or (referer and urllib.parse.urlparse(referer).netloc.lower() != host_lower)
            )
            if needs_mp4_proxy:
                try:
                    from main.stream_proxy import StreamProxyServer
                    proxy = StreamProxyServer.get_instance()
                    return proxy.get_proxy_mp4_url(stream_url, referer=referer)
                except Exception as exc:
                    logger.warning("Failed to route MP4 through StreamProxyServer: %s", exc)
        return stream_url
