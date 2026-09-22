"""
Generic extractor using yt-dlp.
Handles Facebook, TikTok, Twitter/X, Bilibili, Pornhub, and any other supported video platforms.
"""

import gc
import logging
import os
import shutil
import urllib.parse
from typing import Optional, List, Dict, Any

from main.constants import FAKE_USER_AGENT
from main.extractors.base import (
    BaseExtractor,
    ResolvedVideo,
    Format,
    ResolverError,
    VideoNotFoundError,
    AuthRequiredError,
    NetworkError,
    get_js_runtimes,
    isolated_cookie_file,
)

logger = logging.getLogger("FBVideoWatcher.Extractors.Generic")


class GenericExtractor(BaseExtractor):
    """Fallback extractor utilizing yt-dlp for Facebook and all universal platforms."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        # Generic extractor accepts any valid HTTP/HTTPS URL
        return bool(url and (url.startswith("http://") or url.startswith("https://")))

    def extract(
        self,
        url: str,
        cookie_file: Optional[str] = None,
        max_height: int = 1080,
        timeout: int = 10,
        retries: int = 2,
    ) -> ResolvedVideo:
        try:
            import yt_dlp
        except ImportError as e:
            raise ResolverError(
                "Thư viện yt-dlp chưa được cài đặt. Vui lòng cài đặt qua requirements.txt."
            ) from e

        if max_height and max_height > 0:
            format_query = f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
        elif max_height == -1:
            format_query = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        else:
            format_query = "bestvideo+bestaudio/best"

        ydl_opts: Dict[str, Any] = {
            "format": format_query,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": timeout,
            "retries": retries,
            "http_headers": {
                "User-Agent": FAKE_USER_AGENT,
            },
        }

        js_runtimes = get_js_runtimes()
        if js_runtimes:
            ydl_opts["js_runtimes"] = js_runtimes

        ydl_opts["remote_components"] = ["ejs:github"]

        with isolated_cookie_file(cookie_file) as safe_cookie:
            if safe_cookie:
                ydl_opts["cookiefile"] = safe_cookie

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as exc:
                err_lower = str(exc).lower()
                if any(w in err_lower for w in ("login", "private", "permission", "cookies")):
                    raise AuthRequiredError(
                        "Video này ở chế độ riêng tư hoặc yêu cầu đăng nhập. "
                        "Vui lòng thiết lập file cookies trong Cài đặt."
                    ) from exc
                elif any(w in err_lower for w in ("not found", "deleted", "unavailable", "404")):
                    raise VideoNotFoundError("Video không tồn tại hoặc đã bị tác giả xóa.") from exc
                elif any(w in err_lower for w in ("unable to download webpage", "connection", "timeout", "timed out")):
                    raise NetworkError("Lỗi kết nối mạng khi phân giải video. Vui lòng thử lại.") from exc
                else:
                    raise ResolverError(f"Lỗi khi trích xuất video: {exc}") from exc
            except Exception as exc:
                raise ResolverError(f"Lỗi không xác định khi trích xuất video: {exc}") from exc

        if not info_dict:
            raise VideoNotFoundError("Không tìm thấy thông tin video từ liên kết được cung cấp.")

        # Handle playlist/multi-entry
        if "entries" in info_dict and info_dict["entries"]:
            entries = list(info_dict["entries"])
            selected_entry = next((e for e in entries if e and (e.get("url") or e.get("formats"))), None)
            if not selected_entry:
                raise VideoNotFoundError("Bài viết này không chứa video nào phát được.")
            info = selected_entry
        else:
            info = info_dict

        stream_url: Optional[str] = None
        audio_url: Optional[str] = None
        formats_raw = info.get("formats", [])

        # Priority 1: Progressive format (containing both video and audio, e.g. Facebook hd/sd)
        selected_v_fmt: Optional[Dict[str, Any]] = None
        selected_a_fmt: Optional[Dict[str, Any]] = None

        if formats_raw:
            progressive = [
                f for f in formats_raw
                if f.get("url") and (
                    f.get("format_id") in ("hd", "sd")
                    or (f.get("vcodec") != "none" and f.get("acodec") != "none" and f.get("acodec") is not None)
                )
            ]
            if progressive:
                if max_height == -1:
                    # Auto mode: choose balanced 720p for smooth playback on constrained networks
                    prog_matching = [
                        f for f in progressive
                        if f.get("height") and f.get("height") <= 720
                    ]
                    chosen = (prog_matching[-1] if prog_matching else progressive[-1])
                elif max_height and max_height > 0:
                    prog_matching = [
                        f for f in progressive
                        if f.get("height") and f.get("height") <= max_height
                    ]
                    chosen = (prog_matching[-1] if prog_matching else progressive[-1])
                else:
                    chosen = progressive[-1]
                stream_url = chosen["url"]
                selected_v_fmt = chosen
                audio_url = None

        # Priority 2: yt-dlp selected split requested_formats (DASH video + audio)
        if not stream_url:
            req_formats = info.get("requested_formats")
            if req_formats and isinstance(req_formats, list):
                v_fmt = next((f for f in req_formats if f.get("vcodec") != "none" and f.get("url")), None)
                a_fmt = next((f for f in req_formats if f.get("acodec") != "none" and f.get("url")), None)
                if v_fmt:
                    stream_url = v_fmt["url"]
                    selected_v_fmt = v_fmt
                if a_fmt:
                    audio_url = a_fmt["url"]
                    selected_a_fmt = a_fmt

        # Priority 3: Single direct URL
        if not stream_url:
            stream_url = info.get("url")

        # Priority 4: Fallback to separate format search
        if not stream_url and formats_raw:
            v_candidates = [f for f in formats_raw if f.get("url") and f.get("vcodec") != "none"]
            a_candidates = [f for f in formats_raw if f.get("url") and f.get("acodec") != "none"]
            if v_candidates:
                stream_url = v_candidates[-1]["url"]
                selected_v_fmt = v_candidates[-1]
            if a_candidates:
                audio_url = a_candidates[-1]["url"]
                selected_a_fmt = a_candidates[-1]

        if not stream_url:
            raise VideoNotFoundError("Không thể tìm thấy luồng phát trực tiếp cho video này.")

        if "#__youtubedl_smuggle" in stream_url:
            stream_url = stream_url.split("#__youtubedl_smuggle")[0]

        # Handle server-enforced stream availability delay if present
        max_available = max(
            [info.get("available_at") or 0] +
            [f.get("available_at") or 0 for f in info.get("requested_formats") or []],
            default=0,
        )
        if max_available > 0:
            wait_sec = max_available - time.time()
            if 0 < wait_sec <= 15:
                logger.info("Đồng bộ luồng phát: chờ mở khóa CDN (%.1fs)...", wait_sec)
                time.sleep(wait_sec + 0.5)
            elif wait_sec > 15:
                logger.warning("Video có thời gian bắt đầu khả dụng xa: %.1fs", wait_sec)

        # Collect required HTTP headers (Referer, User-Agent) for CDNs (Pornhub, Bilibili, etc.)
        http_headers: Dict[str, str] = dict(info.get("http_headers") or {})
        if selected_v_fmt and selected_v_fmt.get("http_headers"):
            http_headers.update(selected_v_fmt["http_headers"])
        if not http_headers.get("Referer"):
            try:
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme and parsed.netloc:
                    http_headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
            except Exception:
                pass

        # Check if stream is a rate-limited MP4 from CDNs that throttle single connections
        # (e.g. Pornhub with 'rate=' or 'phncdn.com')
        is_rate_limited = (
            stream_url.startswith("http")
            and not stream_url.startswith("http://127.0.0.1:")
            and (".mp4" in stream_url or "rate=" in stream_url)
            and ("rate=" in stream_url or "phncdn.com" in stream_url)
        )
        if is_rate_limited:
            from main.stream_proxy import StreamProxyServer
            referer_header = http_headers.get("Referer") if http_headers else None
            proxied_url = StreamProxyServer.get_instance().get_proxy_mp4_url(stream_url, referer=referer_header)
            logger.info("Kích hoạt Multi-Connection StreamProxy tăng tốc luồng MP4 bị bóp băng thông")
            stream_url = proxied_url

        title = info.get("title") or "Video"
        duration = info.get("duration")
        thumbnail = info.get("thumbnail")
        is_live = bool(info.get("is_live", False))

        formats_list: List[Format] = []
        for f in formats_raw:
            formats_list.append(
                Format(
                    format_id=str(f.get("format_id", "")),
                    height=f.get("height"),
                    width=f.get("width"),
                    ext=f.get("ext", "mp4"),
                    vcodec=f.get("vcodec"),
                    acodec=f.get("acodec"),
                    filesize=f.get("filesize") or f.get("filesize_approx"),
                )
            )

        # Giải phóng dữ liệu thô của yt-dlp (25-45MB) ngay sau khi đã trích xuất đủ thông tin.
        # Không ảnh hưởng đến formats_list (đã sao chép sang object Format tinh gọn).
        try:
            del formats_raw
            del info
            del info_dict
        except Exception:
            pass
        gc.collect()

        return ResolvedVideo(
            stream_url=stream_url,
            title=title,
            duration=duration,
            thumbnail=thumbnail,
            is_live=is_live,
            formats=formats_list,
            audio_url=audio_url,
            http_headers=http_headers,
        )
