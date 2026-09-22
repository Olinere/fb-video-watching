"""
Base extractor module for video resolution architecture.
Defines common data structures, exceptions, and the BaseExtractor interface.
"""

from abc import ABC, abstractmethod
import contextlib
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import ssl
import sys
import tempfile
from typing import Optional, List, Dict, Any, Tuple
import urllib.parse
import urllib.request

from main.constants import FAKE_USER_AGENT
from main.chapters import Chapter
from main.collection import ResolvedCollection

logger = logging.getLogger("FBVideoWatcher.Extractors")

# Reusable SSL context for media hosts with self-signed / expired certificates
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


@contextlib.contextmanager
def isolated_cookie_file(cookie_file: Optional[str]):
    """
    Context manager yielding an isolated temporary copy of the cookie file.
    Prevents yt-dlp from mutating, overwriting, or stripping session cookies
    (such as LOGIN_INFO, SID, SSID) from the user's original cookie file.
    """
    if not cookie_file or not os.path.isfile(cookie_file):
        yield None
        return

    temp_path = None
    safe_path = cookie_file
    try:
        fd, temp_path = tempfile.mkstemp(prefix="fbw_cookie_", suffix=".txt")
        os.close(fd)
        shutil.copyfile(cookie_file, temp_path)
        safe_path = temp_path
    except Exception as exc:
        logger.warning("Không thể tạo bản sao an toàn cho cookie file: %s", exc)

    try:
        yield safe_path
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass



def get_js_runtimes() -> Dict[str, Dict[str, Any]]:
    """
    Detect available JavaScript runtimes for yt-dlp challenge solving (e.g. YouTube n-challenge).
    Prioritizes bundled QuickJS-ng binary (qjs.exe), then system runtimes (Node, Deno, Bun).
    Also imports yt-dlp-ejs if available to register challenge solvers.
    """
    try:
        import yt_dlp_ejs  # noqa: F401
    except ImportError:
        pass

    runtimes: Dict[str, Dict[str, Any]] = {}

    # Look for bundled or local QuickJS-ng binary
    qjs_candidates: List[Path] = []
    if hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        qjs_candidates.extend([
            meipass / "main" / "bin" / "qjs.exe",
            meipass / "bin" / "qjs.exe",
            meipass / "qjs.exe",
        ])

    base_dir = Path(__file__).resolve().parent.parent  # main/
    qjs_candidates.extend([
        base_dir / "bin" / "qjs.exe",
        base_dir.parent / "main" / "bin" / "qjs.exe",
        Path(sys.prefix) / "Scripts" / "qjs.exe",
    ])

    which_qjs = shutil.which("qjs") or shutil.which("qjs.exe")
    if which_qjs:
        qjs_candidates.append(Path(which_qjs))

    for cand in qjs_candidates:
        try:
            if cand.is_file():
                runtimes["quickjs"] = {"path": str(cand.resolve())}
                break
        except Exception:
            continue

    # Also register system runtimes as fallbacks
    for rt in ("node", "deno", "bun"):
        if shutil.which(rt):
            runtimes[rt] = {}

    return runtimes



@dataclass
class Format:
    """Represents an available stream format."""
    format_id: str
    height: Optional[int]
    width: Optional[int]
    ext: str
    vcodec: Optional[str]
    acodec: Optional[str]
    filesize: Optional[int]


@dataclass
class ResolvedVideo:
    """Holds direct stream and metadata for VLC playback."""
    stream_url: str
    title: str
    duration: Optional[float]
    thumbnail: Optional[str]
    is_live: bool
    formats: List[Format] = field(default_factory=list)
    audio_url: Optional[str] = None  # Separate audio stream URL for DASH split streams
    width: Optional[int] = None
    height: Optional[int] = None
    http_headers: Optional[Dict[str, str]] = None
    chapters: List[Chapter] = field(default_factory=list)
    content_id: Optional[str] = None
    source_name: Optional[str] = None
    canonical_url: Optional[str] = None


# --- Custom Domain Exceptions ---

class ResolverError(Exception):
    """Base exception for URL resolution errors."""
    pass


class URLValidationError(ResolverError):
    """Raised when URL is invalid or malformed."""
    pass


class VideoNotFoundError(ResolverError):
    """Raised when video does not exist, was deleted, or post has no video."""
    pass


class AuthRequiredError(ResolverError):
    """Raised when video is private and requires cookies/login."""
    pass


class NetworkError(ResolverError):
    """Raised when network connection fails during resolution."""
    pass


class NotSupportedError(ResolverError):
    """Raised when an extractor does not implement a requested collection."""
    pass


class BaseExtractor(ABC):
    """Abstract base class for platform-specific video extractors."""

    @classmethod
    @abstractmethod
    def suitable(cls, url: str) -> bool:
        """
        Determine if this extractor can handle the given URL.
        
        Args:
            url: Cleaned input URL.
            
        Returns:
            bool: True if this extractor should be selected.
        """
        return False

    @abstractmethod
    def extract(
        self,
        url: str,
        cookie_file: Optional[str] = None,
        max_height: int = 1080,
        timeout: int = 10,
        retries: int = 2,
    ) -> ResolvedVideo:
        """
        Extract direct playable media URL and metadata.
        
        Args:
            url: Target URL to resolve.
            cookie_file: Path to cookies.txt if required.
            max_height: Maximum requested video height (0 = best).
            timeout: Network timeout in seconds.
            retries: Number of retries on transient network errors.
            
        Returns:
            ResolvedVideo: Container with direct playable stream and metadata.
        """
        raise NotImplementedError

    @classmethod
    def supports_collections(cls) -> bool:
        """Whether this extractor can list collection metadata without streams."""
        return False

    def extract_collection(
        self,
        url: str,
        cookie_file: Optional[str] = None,
        timeout: int = 10,
        max_entries: int = 100,
    ) -> ResolvedCollection:
        """Return a lightweight collection listing, if the source supports it."""
        raise NotSupportedError("Nguồn này không hỗ trợ playlist/collection.")

    def _http_request(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
        data: Optional[bytes] = None,
    ) -> Tuple[str, str]:
        """
        Helper method to fetch HTTP content and return (decoded_html, final_url).
        """
        req_headers = {
            "User-Agent": FAKE_USER_AGENT,
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, data=data, headers=req_headers)
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            try:
                raw_final = resp.geturl()
                final_url = raw_final if isinstance(raw_final, str) and raw_final.startswith("http") else url
            except Exception:
                final_url = url
            content = resp.read().decode("utf-8", errors="ignore")
            return content, final_url
