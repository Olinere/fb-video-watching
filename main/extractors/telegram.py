"""
Telegram Video Extractor for FB Video Watcher.
Resolves private/public channel videos and streams them via local StreamProxyServer.
Supports multi-account fallback: tries active accounts in order.
"""

import logging
import urllib.parse
from typing import Optional

from main.extractors.base import (
    BaseExtractor,
    ResolvedVideo,
    Format,
    ResolverError,
    URLValidationError,
    VideoNotFoundError,
    AuthRequiredError,
    NetworkError,
)
from main.stream_proxy import StreamProxyServer
from main.telegram_manager import TelegramManager, TELEGRAM_URL_PATTERN

logger = logging.getLogger("FBVideoWatcher.Extractors.Telegram")


class TelegramExtractor(BaseExtractor):
    """Extractor for Telegram private and public channel videos."""

    @classmethod
    def suitable(cls, url: str) -> bool:
        if not url or not isinstance(url, str):
            return False
        u = url.strip()
        if "/k/d/" in u or "/a/d/" in u:
            return True
        return bool(TELEGRAM_URL_PATTERN.search(u))

    def extract(
        self,
        url: str,
        cookie_file: Optional[str] = None,
        max_height: int = 1080,
        timeout: int = 15,
        retries: int = 2,
    ) -> ResolvedVideo:
        u = url.strip()
        if "/k/d/" in u or "/a/d/" in u:
            raise URLValidationError(
                "Link '/k/d/...' là URL tạm thời do trình duyệt (Service Worker) quản lý nội bộ. "
                "Vui lòng chuột phải vào video trong Telegram và chọn 'Copy Link' (hoặc copy link dạng 'https://t.me/c/...')."
            )

        parsed = TelegramManager.parse_telegram_url(u)
        if not parsed:
            raise URLValidationError("Đường dẫn Telegram không hợp lệ hoặc không được hỗ trợ.")

        tg_mgr = TelegramManager.get_instance()
        if not tg_mgr.is_configured():
            raise AuthRequiredError(
                "Telegram API ID và API Hash chưa được cấu hình. "
                "Vui lòng vào Cài đặt -> Tab Telegram để nhập API ID, Hash và đăng nhập."
            )

        active_accounts = tg_mgr.get_active_accounts()
        if not active_accounts:
            raise AuthRequiredError(
                "Chưa có tài khoản Telegram nào được kích hoạt. "
                "Vui lòng vào Cài đặt -> Tab Telegram để thêm hoặc bật tài khoản."
            )

        peer = str(parsed["peer"])
        msg_id = parsed["msg_id"]

        try:
            # Multi-account fallback: tries active accounts in order
            info = tg_mgr.get_media_info_multi(peer, msg_id, selected_accounts=active_accounts)
        except (AuthRequiredError, VideoNotFoundError, URLValidationError):
            raise
        except NetworkError:
            raise
        except Exception as exc:
            err_str = str(exc).lower()
            if any(w in err_str for w in ("channel_private", "chat_admin_required", "user_banned_in_channel")):
                raise AuthRequiredError(
                    "Bạn chưa tham gia nhóm kín này hoặc không tài khoản nào có quyền truy cập."
                ) from exc
            elif any(w in err_str for w in ("connection", "timeout", "timed out", "network")):
                raise NetworkError(f"Lỗi kết nối tới Telegram: {exc}") from exc
            else:
                raise ResolverError(f"Lỗi khi trích xuất video từ Telegram: {exc}") from exc

        # Get the account that successfully fetched the info
        resolved_account = info.get("account")
        account_idx = None
        if resolved_account is not None:
            accounts = tg_mgr.get_accounts()
            for idx, acc in enumerate(accounts):
                if acc is resolved_account:
                    account_idx = idx
                    break

        # Prepare local streaming URL via StreamProxyServer
        proxy_server = StreamProxyServer.get_instance()
        port = proxy_server.ensure_started()
        query_params = {
            "channel": peer,
            "msg": str(msg_id),
        }
        if account_idx is not None:
            query_params["acc"] = str(account_idx)
        stream_url = f"http://127.0.0.1:{port}/telegram/stream?{urllib.parse.urlencode(query_params)}"

        title = info.get("title") or f"Telegram Video {msg_id}"
        duration = info.get("duration")
        file_size = info.get("file_size")

        formats = [
            Format(
                format_id="original",
                height=None,
                width=None,
                ext="mp4",
                vcodec="h264",
                acodec="aac",
                filesize=file_size,
            )
        ]

        logger.info(
            "Successfully resolved Telegram video: %s (size=%s bytes, account=%s)",
            title, file_size,
            resolved_account.label if resolved_account else "unknown",
        )

        return ResolvedVideo(
            stream_url=stream_url,
            title=title,
            duration=duration,
            thumbnail=None,
            is_live=False,
            formats=formats,
            audio_url=None,
            http_headers={},
        )
