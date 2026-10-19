"""Smart text parser for extracting video URLs and context descriptions from bulk text.

Supports:
- Unwrapping Facebook redirection shims (l.facebook.com / lm.facebook.com / l.php).
- Markdown link syntax: [Display](URL) and bare URLs.
- Cleaning tracking query parameters (fbclid, __tn__, _aem_, si, utm_*, etc.).
- Extracting preceding context text (e.g. "Phần 1-2", "A", "Tập 3", or arbitrary notes)
  without enforcing rigid regex keywords.
- Strict sequential order preservation and canonical de-duplication.
"""

from dataclasses import dataclass
import re
from typing import List, Optional, Set
from urllib.parse import parse_qsl, parse_qs, unquote, urlencode, urlparse, urlunparse

TRACKING_PARAM_EXACT = frozenset({
    # Facebook
    "fbclid", "__tn__", "h", "fref", "ref", "__cft__", "paipv",
    # YouTube
    "si", "feature", "pp",
    # Generic marketing / analytics
    "gclid", "dclid", "msclkid", "fb_action_ids", "fb_action_types",
})

TRACKING_PARAM_PREFIXES = ("utm_", "_aem_", "_hsenc", "_openstat")

SUPPORTED_DOMAINS = frozenset({
    "youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com",
    "facebook.com", "m.facebook.com", "fb.watch", "fb.com", "web.facebook.com",
    "tiktok.com", "vm.tiktok.com",
    "t.me", "telegram.me",
    "bilibili.com", "b23.tv",
    "vimeo.com", "dailymotion.com", "twitch.tv",
})

DIRECT_MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".m3u8", ".mpd", ".ts")


@dataclass(slots=True)
class ParsedVideoItem:
    """Represents a clean extracted video item with its context description."""
    url: str
    description: str = ""
    source_name: str = "Web"
    canonical_key: str = ""


class SmartTextParser:
    """Parses arbitrary text from posts/messages to cleanly extract video URLs in sequence."""

    # Combined regex to match Markdown links [display](url) OR standalone URLs
    TOKEN_REGEX = re.compile(
        r'\[(?P<md_text>[^\]\r\n]*)\]\((?P<md_url>https?://[^\s\)\<\>"]+)\)'
        r'|'
        r'(?P<bare_url>https?://[^\s\<\>"\)\]]+)'
    )

    @classmethod
    def unwrap_facebook_shim(cls, url: str) -> str:
        """Recursively decode l.facebook.com / lm.facebook.com redirection shims."""
        current_url = url.strip()
        for _ in range(5):  # avoid infinite loop on malformed redirects
            try:
                parsed = urlparse(current_url)
            except Exception:
                break

            netloc = parsed.netloc.lower()
            if any(dom in netloc for dom in ("facebook.com", "fb.com")) and parsed.path.startswith("/l.php"):
                qs = parse_qs(parsed.query)
                if "u" in qs and qs["u"]:
                    decoded = unquote(qs["u"][0]).strip()
                    if decoded.startswith("http://") or decoded.startswith("https://"):
                        current_url = decoded
                        continue
            break
        return current_url

    @classmethod
    def clean_tracking_params(cls, url: str) -> str:
        """Strip tracking query parameters while preserving video IDs and player parameters."""
        try:
            parsed = urlparse(url.strip())
        except Exception:
            return url.strip()

        if not parsed.query:
            return urlunparse(parsed)

        filtered_qsl = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=False):
            key_lower = key.lower()
            if key_lower in TRACKING_PARAM_EXACT:
                continue
            if any(key_lower.startswith(p) for p in TRACKING_PARAM_PREFIXES):
                continue
            filtered_qsl.append((key, value))

        clean_query = urlencode(filtered_qsl)
        return urlunparse(parsed._replace(query=clean_query))

    @classmethod
    def is_candidate_video_url(cls, url: str) -> bool:
        """Check if URL belongs to supported video platforms or direct media links."""
        try:
            parsed = urlparse(url.strip())
        except Exception:
            return False

        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Direct domain match or subdomain match
        if any(netloc == dom or netloc.endswith("." + dom) for dom in SUPPORTED_DOMAINS):
            return True

        # Direct video extension in path
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in DIRECT_MEDIA_EXTS):
            return True

        return False

    @classmethod
    def detect_source_name(cls, url: str) -> str:
        """Determine human-friendly source name for the URL."""
        netloc = urlparse(url).netloc.lower()
        if "youtube" in netloc or "youtu.be" in netloc:
            return "YouTube"
        if "facebook" in netloc or "fb.watch" in netloc:
            return "Facebook"
        if "tiktok" in netloc:
            return "TikTok"
        if "t.me" in netloc or "telegram" in netloc:
            return "Telegram"
        if "bilibili" in netloc:
            return "Bilibili"
        return "Web"

    @classmethod
    def get_canonical_key(cls, url: str) -> str:
        """Generate a canonical key for de-duplication while preserving order."""
        try:
            parsed = urlparse(url)
        except Exception:
            return url.lower().strip()

        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")

        # YouTube normalization
        if "youtu.be" in netloc:
            video_id = path.lstrip("/")
            if video_id:
                return f"yt:{video_id}"
        elif "youtube.com" in netloc:
            qs = dict(parse_qsl(parsed.query))
            if "v" in qs:
                return f"yt:{qs['v']}"
            if path.startswith("/shorts/"):
                return f"yt:{path.split('/shorts/')[-1]}"

        # Facebook Reel / Watch normalization
        if "facebook.com" in netloc or "fb.watch" in netloc:
            if "/reel/" in path:
                reel_id = path.split("/reel/")[-1].split("/")[0]
                if reel_id:
                    return f"fb:reel:{reel_id}"
            if "/videos/" in path:
                vid_id = path.split("/videos/")[-1].split("/")[0]
                if vid_id:
                    return f"fb:video:{vid_id}"

        # Default canonical representation: domain + path without trailing slash
        return f"{netloc}{path}"

    @classmethod
    def clean_context_text(cls, text: str) -> str:
        """Clean raw text snippet preceding a link to serve as a neat description."""
        if not text:
            return ""

        # Take only the last line if multiline
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        candidate = lines[-1]

        # Strip surrounding punctuation and brackets
        candidate = re.sub(r'^[\s\-_:=*#•\(\[\{]+', '', candidate)
        candidate = re.sub(r'[\s\-_:=*#•\)\]\}]+$', '', candidate)

        # Truncate if unreasonably long (e.g. max 120 chars)
        if len(candidate) > 120:
            candidate = candidate[-120:].lstrip()

        return candidate.strip()

    @classmethod
    def parse_text(cls, raw_text: str) -> List[ParsedVideoItem]:
        """Parse raw text, extract video URLs in 100% sequential order, and capture context."""
        if not raw_text or not raw_text.strip():
            return []

        items: List[ParsedVideoItem] = []
        seen_keys: Set[str] = set()

        last_pos = 0
        for match in cls.TOKEN_REGEX.finditer(raw_text):
            match_start = match.start()
            match_end = match.end()

            # Text preceding this match (from previous match end)
            preceding_raw = raw_text[last_pos:match_start]
            last_pos = match_end

            md_text = match.group("md_text")
            md_url = match.group("md_url")
            bare_url = match.group("bare_url")

            target_candidate = md_url if md_url else bare_url
            if not target_candidate:
                continue

            # Step 1: Unwrap Facebook shim if present
            unwrapped = cls.unwrap_facebook_shim(target_candidate)

            # Step 2: Clean tracking parameters
            clean_url = cls.clean_tracking_params(unwrapped)

            # Check if this is a video URL
            if not cls.is_candidate_video_url(clean_url):
                # If target was not video URL, but md_text might be a URL:
                if md_text and (md_text.startswith("http://") or md_text.startswith("https://")):
                    unwrapped_display = cls.unwrap_facebook_shim(md_text)
                    clean_display = cls.clean_tracking_params(unwrapped_display)
                    if cls.is_candidate_video_url(clean_display):
                        clean_url = clean_display
                    else:
                        continue
                else:
                    continue

            # Step 3: Determine context description
            # If preceding text exists, prioritize it
            context_desc = cls.clean_context_text(preceding_raw)

            # If preceding text was empty, but Markdown anchor text exists and isn't a URL, use it
            if not context_desc and md_text:
                if not (md_text.startswith("http://") or md_text.startswith("https://")):
                    context_desc = cls.clean_context_text(md_text)

            # Step 4: De-duplication and strict order preservation
            canonical_key = cls.get_canonical_key(clean_url)
            if canonical_key in seen_keys:
                continue

            seen_keys.add(canonical_key)
            source_name = cls.detect_source_name(clean_url)

            items.append(ParsedVideoItem(
                url=clean_url,
                description=context_desc,
                source_name=source_name,
                canonical_key=canonical_key,
            ))

        return items
