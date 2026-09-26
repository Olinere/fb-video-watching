"""
Extractor for YouTube (youtube.com, youtu.be).
Uses yt-dlp to extract metadata and resolves an unified HLS master manifest
so VLC plays synchronized audio/video natively and supports seamless instant seeking.
"""

import gc
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Optional, List, Dict, Any, Tuple
import urllib.parse
import urllib.request

from main.constants import FAKE_USER_AGENT, MAX_COLLECTION_ENTRIES
from main.chapters import normalize_chapters
from main.collection import CollectionEntry, ResolvedCollection
from main.extractors.base import (
    BaseExtractor,
    ResolvedVideo,
    Format,
    ResolverError,
    VideoNotFoundError,
    AuthRequiredError,
    NetworkError,
    _SSL_CTX,
    get_js_runtimes,
    isolated_cookie_file,
)
from main.ffmpeg_utils import YtDlpLogFilter

logger = logging.getLogger("FBVideoWatcher.Extractors.YouTube")


def _prepare_hls_master_manifest(master_url: str, max_height: int = 1080, timeout: int = 10) -> Optional[str]:
    """
    Fetch and filter an HLS master manifest (such as YouTube's hls_variant).
    Selects the optimal video variant matching max_height (preferring AVC1 for universal hardware decoding),
    binds the associated audio stream, and saves it to a local .m3u8 file for VLC.
    This avoids separate HTTP audio slave desync and enables seamless seeking and pausing in VLC.
    """
    try:
        req = urllib.request.Request(master_url, headers={"User-Agent": FAKE_USER_AGENT})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            manifest_text = resp.read().decode("utf-8", errors="replace")

        lines = manifest_text.splitlines()
        header_lines: List[str] = []
        variants: List[Tuple[int, int, int, str, str]] = []  # (height, is_avc, bandwidth, inf_line, url_line)
        curr_inf: Optional[str] = None

        for line in lines:
            line_s = line.strip()
            if not line_s:
                continue
            if line_s.startswith("#EXT-X-STREAM-INF:"):
                curr_inf = line_s
            elif curr_inf and not line_s.startswith("#"):
                m_res = re.search(r"RESOLUTION=\d+x(\d+)", curr_inf)
                height = int(m_res.group(1)) if m_res else 0
                m_bw = re.search(r"BANDWIDTH=(\d+)", curr_inf)
                bw = int(m_bw.group(1)) if m_bw else 0
                is_avc = 1 if "avc1" in curr_inf.lower() else 0
                variants.append((height, is_avc, bw, curr_inf, line_s))
                curr_inf = None
            elif not curr_inf:
                header_lines.append(line_s)

        if not variants:
            return None

        # Filter variants by max_height
        valid_variants = [v for v in variants if max_height <= 0 or v[0] <= max_height]
        if not valid_variants:
            valid_variants = variants

        # Sort to pick the best variant: highest height, then prefer avc1 (hardware acceleration), then bandwidth
        valid_variants.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        best_variant = valid_variants[0]

        out_lines = list(header_lines)
        out_lines.append(best_variant[3])  # inf
        out_lines.append(best_variant[4])  # url

        cache_dir = Path(tempfile.gettempdir()) / "fbw_hls"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Cleanup old m3u8 files (> 1 hour old)
        try:
            now = time.time()
            for old_f in cache_dir.glob("*.m3u8"):
                if now - old_f.stat().st_mtime > 3600:
                    old_f.unlink(missing_ok=True)
        except Exception:
            pass

        manifest_path = cache_dir / f"stream_{os.getpid()}_{int(time.time() * 1000) % 100000}.m3u8"
        manifest_path.write_text("\n".join(out_lines), encoding="utf-8")
        logger.info(
            "Built unified HLS master manifest (%dx%d, itag variant) at: %s",
            best_variant[0],
            best_variant[0],
            manifest_path,
        )
        return str(manifest_path.resolve())
    except Exception as exc:
        logger.warning("Error preparing HLS master manifest: %s", exc)
        return None


class YouTubeExtractor(BaseExtractor):
    """Dedicated extractor for YouTube videos."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        if not url:
            return False
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
            return any(d in host for d in ("youtube.com", "youtu.be"))
        except Exception:
            return False

    @classmethod
    def supports_collections(cls) -> bool:
        return True

    def extract_collection(
        self,
        url: str,
        cookie_file: Optional[str] = None,
        timeout: int = 10,
        max_entries: int = MAX_COLLECTION_ENTRIES,
    ) -> ResolvedCollection:
        """List playlist entries with yt-dlp's flat mode.

        Flat mode deliberately avoids format extraction, CDN URL generation,
        thumbnails and media downloads.  Only a bounded metadata page is
        retained in memory.
        """
        try:
            import yt_dlp
        except ImportError as exc:
            raise ResolverError("Thư viện yt-dlp chưa được cài đặt.") from exc

        page_size = max(1, min(int(max_entries), MAX_COLLECTION_ENTRIES))
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "playlistend": page_size + 1,
            "socket_timeout": timeout,
            "ignoreerrors": True,
            "logger": YtDlpLogFilter(),
        }
        js_runtimes = get_js_runtimes()
        if js_runtimes:
            opts["js_runtimes"] = js_runtimes
        opts["remote_components"] = ["ejs:github"]

        with isolated_cookie_file(cookie_file) as safe_cookie:
            if safe_cookie:
                opts["cookiefile"] = safe_cookie
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
            except Exception as exc:
                raise ResolverError(f"Không thể đọc playlist YouTube: {exc}") from exc

        if not info_dict or not isinstance(info_dict, dict):
            raise VideoNotFoundError("Playlist YouTube không có dữ liệu.")

        raw_entries = info_dict.get("entries") or []
        entries: list[CollectionEntry] = []
        has_more = False
        for raw in raw_entries:
            if len(entries) >= page_size:
                has_more = True
                break
            if not isinstance(raw, dict):
                continue
            content_id = str(raw.get("id") or "").strip() or None
            source_url = raw.get("webpage_url") or raw.get("original_url")
            if not source_url and content_id:
                source_url = f"https://www.youtube.com/watch?v={content_id}"
            if not source_url:
                continue
            duration = raw.get("duration")
            duration_ms = None
            try:
                duration_ms = max(0, int(float(duration) * 1000)) if duration is not None else None
            except (TypeError, ValueError):
                pass
            entries.append(CollectionEntry(
                source_url=str(source_url),
                content_id=content_id,
                title=str(raw.get("title") or content_id or "YouTube Video"),
                thumbnail_url=None,
                duration_ms=duration_ms,
                source_name="youtube",
            ))

        title = str(info_dict.get("title") or "YouTube Playlist")
        del raw_entries
        del info_dict
        gc.collect()
        return ResolvedCollection(
            source_url=url,
            title=title,
            entries=tuple(entries),
            is_partial=has_more,
            has_more=has_more,
        )

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
            "logger": YtDlpLogFilter(),
        }

        js_runtimes = get_js_runtimes()
        if js_runtimes:
            ydl_opts["js_runtimes"] = js_runtimes

        ydl_opts["remote_components"] = ["ejs:github"]

        # In-App Proxy integration
        try:
            from main.network import NetworkManager
            proxy_url = NetworkManager.get_instance().get_proxy_url()
            if proxy_url:
                ydl_opts["proxy"] = proxy_url
        except Exception:
            pass

        with isolated_cookie_file(cookie_file) as safe_cookie:
            if safe_cookie:
                ydl_opts["cookiefile"] = safe_cookie

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as exc:
                err_lower = str(exc).lower()
                if "confirm you're not a bot" in err_lower or "confirm you’re not a bot" in err_lower:
                    raise AuthRequiredError(
                        "YouTube yêu cầu xác minh bot (Sign in to confirm you're not a bot). "
                        "Vui lòng xuất file cookies mới từ trình duyệt và lưu vào Cài đặt."
                    ) from exc
                elif any(w in err_lower for w in ("login", "private", "permission", "cookies")):
                    raise AuthRequiredError(
                        "Video YouTube này yêu cầu đăng nhập hoặc xác thực cookies."
                    ) from exc
                elif any(w in err_lower for w in ("not found", "deleted", "unavailable", "404")):
                    raise VideoNotFoundError("Video YouTube không tồn tại hoặc đã bị tác giả gỡ.") from exc
                elif any(w in err_lower for w in ("connection", "timeout", "timed out")):
                    raise NetworkError("Lỗi kết nối mạng khi tải thông tin video YouTube.") from exc
                else:
                    raise ResolverError(f"Lỗi khi trích xuất video YouTube: {exc}") from exc
            except Exception as exc:
                raise ResolverError(f"Lỗi không xác định khi trích xuất video YouTube: {exc}") from exc

        if not info_dict:
            raise VideoNotFoundError("Không tìm thấy thông tin video từ liên kết YouTube được cung cấp.")

        # Handle playlist/multi-entry
        if "entries" in info_dict and info_dict["entries"]:
            entries = list(info_dict["entries"])
            selected_entry = next((e for e in entries if e and (e.get("url") or e.get("formats"))), None)
            if not selected_entry:
                raise VideoNotFoundError("Danh sách phát YouTube không chứa video nào phát được.")
            info = selected_entry
        else:
            info = info_dict

        stream_url: Optional[str] = None
        audio_url: Optional[str] = None
        selected_v_fmt: Optional[Dict[str, Any]] = None
        selected_a_fmt: Optional[Dict[str, Any]] = None
        formats_raw = info.get("formats", [])

        # Priority 1: HLS master manifest (resolves synchronous video + audio and instant seeking for live streams)
        manifest_candidates = [
            f.get("manifest_url") for f in formats_raw
            if f.get("manifest_url") and "m3u8" in f.get("protocol", "")
        ]
        if manifest_candidates:
            master_url = manifest_candidates[0]
            hls_file = _prepare_hls_master_manifest(master_url, max_height=max_height, timeout=timeout)
            if hls_file:
                stream_url = hls_file
                audio_url = None

        # Priority 2: Determine optimal stream between progressive format and requested_formats
        if not stream_url:
            progressive = [
                f for f in formats_raw
                if f.get("url") and (
                    f.get("vcodec") != "none" and f.get("acodec") != "none" and f.get("acodec") is not None
                )
            ]
            prog_best: Optional[Dict[str, Any]] = None
            if progressive:
                if max_height == -1:
                    matching = [f for f in progressive if f.get("height") and f.get("height") <= 720]
                    prog_best = matching[-1] if matching else progressive[-1]
                elif max_height and max_height > 0:
                    matching = [f for f in progressive if f.get("height") and f.get("height") <= max_height]
                    prog_best = matching[-1] if matching else progressive[-1]
                else:
                    prog_best = progressive[-1]

            req_formats = info.get("requested_formats")
            v_fmt: Optional[Dict[str, Any]] = None
            a_fmt: Optional[Dict[str, Any]] = None
            if req_formats and isinstance(req_formats, list):
                v_fmt = next((f for f in req_formats if f.get("vcodec") != "none" and f.get("url")), None)
                a_fmt = next((f for f in req_formats if f.get("acodec") != "none" and f.get("url")), None)

            v_height = (v_fmt.get("height") or 0) if v_fmt else 0
            p_height = (prog_best.get("height") or 0) if prog_best else 0

            # If yt-dlp requested an adaptive format higher than progressive (e.g. 1080p vs 360p progressive),
            # prefer requested_formats with separate audio slave track (VLC handles slave natively §7.1)
            if v_fmt and v_height > p_height:
                stream_url = v_fmt["url"]
                selected_v_fmt = v_fmt
                if a_fmt:
                    audio_url = a_fmt["url"]
                    selected_a_fmt = a_fmt
            elif prog_best:
                stream_url = prog_best["url"]
                selected_v_fmt = prog_best
                audio_url = None
            elif v_fmt:
                stream_url = v_fmt["url"]
                selected_v_fmt = v_fmt
                if a_fmt:
                    audio_url = a_fmt["url"]
                    selected_a_fmt = a_fmt

        if not stream_url:
            stream_url = info.get("url")

        if not stream_url:
            raise VideoNotFoundError("Không thể tìm thấy luồng phát trực tiếp cho video YouTube này.")

        # Priority 3: Server stream availability delay (YouTube web_embedded ad timing / rate lock)
        # Prevents VLC from receiving HTTP 403 Forbidden on newly extracted googlevideo URLs
        available_at_candidates = [
            info.get("available_at") or 0,
        ]
        if selected_v_fmt and selected_v_fmt.get("available_at"):
            available_at_candidates.append(selected_v_fmt["available_at"])
        if selected_a_fmt and selected_a_fmt.get("available_at"):
            available_at_candidates.append(selected_a_fmt["available_at"])

        max_available = max(available_at_candidates) if available_at_candidates else 0
        if max_available > 0:
            wait_sec = max_available - time.time()
            if 0 < wait_sec <= 15:
                logger.info(
                    "Đồng bộ luồng phát YouTube: chờ mở khóa CDN (%.1fs theo quy định máy chủ)...",
                    wait_sec,
                )
                time.sleep(wait_sec + 0.5)
            elif wait_sec > 15:
                logger.warning("Video có thời gian bắt đầu khả dụng xa: %.1fs", wait_sec)

        title = info.get("title") or "YouTube Video"
        duration = info.get("duration")
        thumbnail = info.get("thumbnail")
        is_live = bool(info.get("is_live", False))
        duration_ms = int(float(duration) * 1000) if duration is not None else None
        chapters = normalize_chapters(info.get("chapters"), duration_ms)
        content_id = str(info.get("id") or "").strip() or None
        canonical_url = info.get("webpage_url") or info.get("original_url") or url

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

        # Collect HTTP headers if present
        http_headers: Dict[str, str] = dict(info.get("http_headers") or {})
        if selected_v_fmt and selected_v_fmt.get("http_headers"):
            http_headers.update(selected_v_fmt["http_headers"])

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
            chapters=chapters,
            content_id=content_id,
            source_name="youtube",
            canonical_url=canonical_url,
        )


def cleanup_hls_cache() -> None:
    """
    Dọn dẹp toàn bộ thư mục manifest tạm %TEMP%/fbw_hls.
    Gọi khi đóng ứng dụng để không để lại file .m3u8 trên ổ cứng người dùng.
    """
    try:
        cache_dir = Path(tempfile.gettempdir()) / "fbw_hls"
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)
    except Exception:
        pass
