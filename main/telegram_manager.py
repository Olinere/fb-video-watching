"""
Telegram Manager module for FB Video Watcher.
Manages MTProto client connection (Telethon), QR code login flow,
channel message resolution, and multi-chunk streaming with Range support.
Supports multiple accounts with per-account session files.
"""

import asyncio
import logging
import os
from pathlib import Path
import queue
import re
import threading
import time
from typing import Optional, Dict, Any, Generator, Callable, List

from main.constants import CONFIG_DIR, SETTINGS_FILE
from main.extractors.base import (
    ResolverError,
    VideoNotFoundError,
    AuthRequiredError,
    NetworkError,
)

logger = logging.getLogger("FBVideoWatcher.TelegramManager")

TELEGRAM_URL_PATTERN = re.compile(
    r"""(?x)
    https?://
    (?:
        t\.me/
        (?:
            c/(?P<private_channel>\d+)/(?P<private_msg>\d+)
            |
            (?P<public_channel>[a-zA-Z0-9_]+)/(?P<public_msg>\d+)
        )
        |
        web\.telegram\.org/
        (?:k|a)/\#
        (?:
            -(?P<web_channel>\d+)(?:_(?P<web_msg>\d+))?
            |
            @(?P<web_user>[a-zA-Z0-9_]+)(?:/(?P<web_user_msg>\d+))?
        )
    )
    """,
    re.IGNORECASE,
)


class TelegramAccount:
    """Represents a single Telegram account with its own TelegramClient session."""

    def __init__(self, session_file: str, label: str, active: bool = True):
        self.session_file = session_file   # e.g. "telegram_account_0.session"
        self.label = label                 # Display name, e.g. "Tài khoản 1"
        self.active = active               # Whether this account is selected to be used
        self._client = None
        self._client_lock = threading.Lock()

    def get_session_path(self) -> str:
        """Absolute path string for the session file."""
        return str(CONFIG_DIR / self.session_file)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_file": self.session_file,
            "label": self.label,
            "active": self.active,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TelegramAccount":
        return TelegramAccount(
            session_file=d.get("session_file", ""),
            label=d.get("label", "Tài khoản"),
            active=bool(d.get("active", True)),
        )


class TelegramManager:
    """Singleton manager for Telegram MTProto clients, authentication, and streaming."""

    _instance: Optional["TelegramManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

        self._api_id: Optional[int] = None
        self._api_hash: Optional[str] = None

        # List of TelegramAccount objects
        self._accounts: List[TelegramAccount] = []
        self._accounts_lock = threading.Lock()

        # Cache for resolved messages {cache_key: {"info": dict, "cached_at": float}}
        self._msg_cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()

        self._ensure_loop_started()
        self._load_settings()

    @classmethod
    def get_instance(cls) -> "TelegramManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = TelegramManager()
            return cls._instance

    def _ensure_loop_started(self):
        """Start a persistent background thread with an asyncio event loop."""
        if self._loop is not None and self._loop.is_running():
            return

        loop_ready = threading.Event()

        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            loop_ready.set()
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=_run_loop, daemon=True, name="TelegramManagerLoop")
        self._loop_thread.start()
        loop_ready.wait()

    def _run_coro(self, coro, timeout: Optional[float] = 30):
        """Execute a coroutine in the background asyncio event loop and return result."""
        self._ensure_loop_started()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def _load_settings(self):
        """Load API credentials and accounts list from settings.json."""
        try:
            import json
            if SETTINGS_FILE.is_file():
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tg_cfg = data.get("telegram", {})
                raw_id = str(tg_cfg.get("api_id", "")).strip()
                raw_hash = str(tg_cfg.get("api_hash", "")).strip()
                self._api_id = int(raw_id) if raw_id.isdigit() else None
                self._api_hash = raw_hash if raw_hash else None

                with self._accounts_lock:
                    self._accounts = [
                        TelegramAccount.from_dict(a)
                        for a in tg_cfg.get("accounts", [])
                        if isinstance(a, dict) and a.get("session_file")
                    ]

                # Backward compat: if old single session file exists and no accounts registered yet
                if not self._accounts:
                    old_session = CONFIG_DIR / "telegram.session"
                    if old_session.is_file():
                        acc = TelegramAccount(
                            session_file="telegram_account_0.session",
                            label="Tài khoản 1",
                            active=True,
                        )
                        import shutil
                        try:
                            shutil.copy2(str(old_session), acc.get_session_path())
                        except Exception:
                            pass
                        self._accounts.append(acc)
                        logger.info("Migrated legacy telegram.session -> telegram_account_0.session")
        except Exception as exc:
            logger.debug("Error loading Telegram settings: %s", exc)

    # -------------------------------------------------------------------------
    # Credentials
    # -------------------------------------------------------------------------

    def set_credentials(self, api_id: int, api_hash: str) -> None:
        """Update API credentials. Disconnect all clients if credentials actually changed."""
        new_id = int(api_id)
        new_hash = str(api_hash).strip()
        if self._api_id == new_id and self._api_hash == new_hash:
            return
        self._api_id = new_id
        self._api_hash = new_hash
        # Disconnect all existing clients so they reconnect with new credentials
        with self._accounts_lock:
            for acc in self._accounts:
                with acc._client_lock:
                    if acc._client is not None:
                        try:
                            self._run_coro(acc._client.disconnect(), timeout=5)
                        except Exception:
                            pass
                        acc._client = None

    def is_configured(self) -> bool:
        """Return True if both api_id and api_hash are configured."""
        return bool(self._api_id and self._api_hash)

    # -------------------------------------------------------------------------
    # Account management
    # -------------------------------------------------------------------------

    def get_accounts(self) -> List[TelegramAccount]:
        """Return a snapshot of all accounts."""
        with self._accounts_lock:
            return list(self._accounts)

    def get_active_accounts(self) -> List[TelegramAccount]:
        """Return only accounts marked as active."""
        with self._accounts_lock:
            return [a for a in self._accounts if a.active]

    def _next_session_filename(self) -> str:
        """Generate next available session filename: telegram_account_N.session."""
        with self._accounts_lock:
            existing = {a.session_file for a in self._accounts}
        for i in range(100):
            name = f"telegram_account_{i}.session"
            if name not in existing:
                return name
        return f"telegram_account_{int(time.time())}.session"

    def add_account(self, label: str = "") -> TelegramAccount:
        """Create a new TelegramAccount slot and append to accounts list."""
        session_file = self._next_session_filename()
        idx = len(self._accounts)
        display_label = label.strip() if label.strip() else f"Tài khoản {idx + 1}"
        acc = TelegramAccount(session_file=session_file, label=display_label, active=True)
        with self._accounts_lock:
            self._accounts.append(acc)
        return acc

    def remove_account(self, account: TelegramAccount) -> None:
        """Log out, delete session file, and remove from accounts list."""
        with account._client_lock:
            if account._client is not None:
                try:
                    self._run_coro(account._client.log_out(), timeout=10)
                except Exception:
                    try:
                        self._run_coro(account._client.disconnect(), timeout=5)
                    except Exception:
                        pass
                account._client = None

        # Delete session files
        for p in CONFIG_DIR.glob(f"{Path(account.session_file).stem}*"):
            try:
                p.unlink()
            except Exception:
                pass

        with self._accounts_lock:
            try:
                self._accounts.remove(account)
            except ValueError:
                pass

    def set_account_active(self, account: TelegramAccount, active: bool) -> None:
        """Set active state of an account."""
        account.active = active

    def rename_account(self, account: TelegramAccount, new_label: str) -> None:
        """Rename an account."""
        account.label = new_label.strip() or account.label

    def get_accounts_as_dicts(self) -> List[Dict[str, Any]]:
        """Return accounts list as serializable dicts."""
        with self._accounts_lock:
            return [a.to_dict() for a in self._accounts]

    # -------------------------------------------------------------------------
    # Per-account client management
    # -------------------------------------------------------------------------

    def _get_or_create_client(self, account: TelegramAccount):
        """Create or return TelegramClient for a specific account."""
        with account._client_lock:
            if not self.is_configured():
                raise AuthRequiredError(
                    "Telegram API ID và API Hash chưa được cấu hình. "
                    "Vui lòng vào Cài đặt -> Tab Telegram để nhập thông tin."
                )
            if account._client is None:
                from telethon import TelegramClient
                proxy_dict = None
                try:
                    from main.network import NetworkManager
                    proxy_dict = NetworkManager.get_instance().get_telethon_proxy()
                except Exception:
                    pass

                account._client = TelegramClient(
                    account.get_session_path(),
                    self._api_id,
                    self._api_hash,
                    loop=self._loop,
                    proxy=proxy_dict,
                )
            return account._client

    def is_authorized(self, account: Optional[TelegramAccount] = None) -> bool:
        """
        Check if a specific account (or any active account) is authorized.
        If account is None, returns True if ANY active account is authorized.
        """
        accounts_to_check = [account] if account is not None else self.get_active_accounts()
        if not self.is_configured() or not accounts_to_check:
            return False
        for acc in accounts_to_check:
            try:
                client = self._get_or_create_client(acc)

                async def _check(c=client):
                    if not c.is_connected():
                        await c.connect()
                    return await c.is_user_authorized()

                if self._run_coro(_check(), timeout=10):
                    return True
            except Exception as exc:
                logger.debug("Error checking Telegram authorization for %s: %s", acc.label, exc)
        return False

    def is_account_authorized(self, account: TelegramAccount) -> bool:
        """Check if a specific account is authorized."""
        if not self.is_configured():
            return False
        try:
            client = self._get_or_create_client(account)

            async def _check():
                if not client.is_connected():
                    await client.connect()
                return await client.is_user_authorized()

            return bool(self._run_coro(_check(), timeout=10))
        except Exception as exc:
            logger.debug("Error checking auth for %s: %s", account.label, exc)
            return False

    def get_user_info(self, account: Optional[TelegramAccount] = None) -> Optional[Dict[str, Any]]:
        """
        Return authenticated user info dict for the first authorized active account,
        or for a specific account if provided.
        """
        accounts_to_check = [account] if account is not None else self.get_active_accounts()
        for acc in accounts_to_check:
            try:
                client = self._get_or_create_client(acc)

                async def _get_me(c=client):
                    if not c.is_connected():
                        await c.connect()
                    me = await c.get_me()
                    if not me:
                        return None
                    return {
                        "id": me.id,
                        "first_name": me.first_name or "",
                        "last_name": me.last_name or "",
                        "username": me.username or "",
                        "phone": me.phone or "",
                    }

                info = self._run_coro(_get_me(), timeout=10)
                if info:
                    return info
            except Exception as exc:
                logger.debug("Error getting user info for %s: %s", acc.label, exc)
        return None

    def get_account_user_info(self, account: TelegramAccount) -> Optional[Dict[str, Any]]:
        """Return user info for a specific account."""
        if not self.is_configured():
            return None
        try:
            client = self._get_or_create_client(account)

            async def _get_me():
                if not client.is_connected():
                    await client.connect()
                if not await client.is_user_authorized():
                    return None
                me = await client.get_me()
                if not me:
                    return None
                return {
                    "id": me.id,
                    "first_name": me.first_name or "",
                    "last_name": me.last_name or "",
                    "username": me.username or "",
                    "phone": me.phone or "",
                }

            return self._run_coro(_get_me(), timeout=10)
        except Exception as exc:
            logger.debug("Error getting account user info for %s: %s", account.label, exc)
            return None

    def start_qr_login(
        self,
        account: TelegramAccount,
        on_qr_ready: Callable[[Any], None],
        on_success: Callable[[Dict[str, Any]], None],
        on_fail: Callable[[str], None],
        on_2fa_required: Callable[[], None],
        cancel_event: threading.Event,
    ) -> None:
        """
        Start QR code login flow for a specific account in background.
        on_qr_ready: callback(pil_image)
        on_success: callback(user_info_dict)
        on_fail: callback(error_str)
        on_2fa_required: callback()
        cancel_event: threading.Event to abort
        """
        import qrcode
        import telethon.errors

        client = self._get_or_create_client(account)

        async def _qr_flow():
            try:
                if not client.is_connected():
                    await client.connect()

                if await client.is_user_authorized():
                    me = await client.get_me()
                    on_success({
                        "id": me.id,
                        "first_name": me.first_name or "",
                        "last_name": me.last_name or "",
                        "username": me.username or "",
                        "phone": me.phone or "",
                    })
                    return

                qr = await client.qr_login()
                qr_img = qrcode.make(qr.url)
                on_qr_ready(qr_img)

                while not cancel_event.is_set():
                    try:
                        user = await qr.wait(timeout=25)
                        on_success({
                            "id": user.id,
                            "first_name": user.first_name or "",
                            "last_name": user.last_name or "",
                            "username": user.username or "",
                            "phone": user.phone or "",
                        })
                        return
                    except asyncio.TimeoutError:
                        if cancel_event.is_set():
                            return
                        try:
                            await qr.recreate()
                            qr_img = qrcode.make(qr.url)
                            on_qr_ready(qr_img)
                        except Exception as rec_err:
                            on_fail(f"Lỗi làm mới mã QR: {rec_err}")
                            return
                    except telethon.errors.SessionPasswordNeededError:
                        on_2fa_required()
                        return
                    except Exception as err:
                        on_fail(str(err))
                        return
            except Exception as e:
                on_fail(str(e))

        asyncio.run_coroutine_threadsafe(_qr_flow(), self._loop)

    def submit_2fa_password(self, account: TelegramAccount, password: str) -> Dict[str, Any]:
        """Submit 2FA cloud password to complete login for an account."""
        client = self._get_or_create_client(account)

        async def _sign_in_2fa():
            if not client.is_connected():
                await client.connect()
            user = await client.sign_in(password=password)
            return {
                "id": user.id,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "username": user.username or "",
                "phone": user.phone or "",
            }

        return self._run_coro(_sign_in_2fa(), timeout=15)

    def logout(self, account: Optional[TelegramAccount] = None) -> None:
        """
        Log out a specific account, or all accounts if account is None.
        Deletes session files.
        """
        if account is not None:
            accounts_to_logout = [account]
        else:
            with self._accounts_lock:
                accounts_to_logout = list(self._accounts)

        for acc in accounts_to_logout:
            with acc._client_lock:
                if acc._client is not None:
                    try:
                        self._run_coro(acc._client.log_out(), timeout=10)
                    except Exception:
                        try:
                            self._run_coro(acc._client.disconnect(), timeout=5)
                        except Exception:
                            pass
                    acc._client = None

            # Remove session files
            for p in CONFIG_DIR.glob(f"{Path(acc.session_file).stem}*"):
                try:
                    p.unlink()
                except Exception:
                    pass

        if account is None:
            # Also clean up legacy session file
            for p in CONFIG_DIR.glob("telegram.session*"):
                try:
                    p.unlink()
                except Exception:
                    pass
            with self._accounts_lock:
                self._accounts.clear()

    # -------------------------------------------------------------------------
    # URL parsing (static, unchanged)
    # -------------------------------------------------------------------------

    @staticmethod
    def parse_telegram_url(url: str) -> Optional[Dict[str, Any]]:
        """Parse supported Telegram URLs into channel/peer and message ID."""
        m = TELEGRAM_URL_PATTERN.search(url.strip())
        if not m:
            return None

        gd = m.groupdict()
        if gd.get("private_channel") and gd.get("private_msg"):
            return {
                "peer": f"-100{gd['private_channel']}",
                "msg_id": int(gd["private_msg"]),
                "is_private": True,
            }
        elif gd.get("public_channel") and gd.get("public_msg"):
            return {
                "peer": gd["public_channel"],
                "msg_id": int(gd["public_msg"]),
                "is_private": False,
            }
        elif gd.get("web_channel") and gd.get("web_msg"):
            return {
                "peer": f"-100{gd['web_channel']}",
                "msg_id": int(gd["web_msg"]),
                "is_private": True,
            }
        elif gd.get("web_user") and gd.get("web_user_msg"):
            return {
                "peer": gd["web_user"],
                "msg_id": int(gd["web_user_msg"]),
                "is_private": False,
            }
        return None

    # -------------------------------------------------------------------------
    # Media info: multi-account fallback
    # -------------------------------------------------------------------------

    def _fetch_media_info_for_account(self, account: TelegramAccount, peer_str: str, msg_id: int) -> Dict[str, Any]:
        """Fetch media info using a specific account. Raises on error."""
        client = self._get_or_create_client(account)

        async def _fetch():
            if not client.is_connected():
                await client.connect()
            if not await client.is_user_authorized():
                raise AuthRequiredError(
                    f"Tài khoản '{account.label}' chưa đăng nhập hoặc phiên đã hết hạn."
                )

            if peer_str.lstrip("-").isdigit():
                peer_val = int(peer_str)
            else:
                peer_val = peer_str

            try:
                entity = await client.get_entity(peer_val)
            except Exception:
                # Refresh dialogs if peer is not yet cached
                await client.get_dialogs(limit=50)
                entity = await client.get_entity(peer_val)

            msg = await client.get_messages(entity, ids=msg_id)
            if not msg:
                raise VideoNotFoundError(f"Không tìm thấy tin nhắn {msg_id} trên Telegram.")

            is_video = bool(
                msg.video
                or (msg.document and any(
                    attr.__class__.__name__ == "DocumentAttributeVideo"
                    for attr in (msg.document.attributes or [])
                ))
                or (msg.file and msg.file.mime_type and msg.file.mime_type.startswith("video/"))
            )

            if not is_video or not msg.file:
                raise VideoNotFoundError("Tin nhắn này không chứa video nào phát được.")

            file_size = msg.file.size
            duration = getattr(msg.video, "duration", None) if msg.video else None
            if not duration and msg.document and getattr(msg.document, "attributes", None):
                for attr in msg.document.attributes:
                    if attr.__class__.__name__ == "DocumentAttributeVideo":
                        duration = getattr(attr, "duration", None)
                        break
            mime_type = msg.file.mime_type or "video/mp4"

            caption = (msg.message or "").strip().split("\n")[0]
            title = caption if caption else (msg.file.name or f"Telegram Video {msg_id}")

            return {
                "file_size": file_size,
                "duration": duration,
                "mime_type": mime_type,
                "title": title,
                "file_name": getattr(msg.file, "name", None),
                "media": msg.media,
                "message": msg,
                "account": account,  # track which account succeeded
            }

        return self._run_coro(_fetch(), timeout=20)

    def get_media_info(self, peer_str: str, msg_id: int, account: Optional[TelegramAccount] = None) -> Dict[str, Any]:
        """
        Fetch media info. If account is provided, use that account only.
        Otherwise, uses multi-account fallback (get_media_info_multi).
        """
        if account is not None:
            cache_key = f"{account.session_file}_{peer_str}_{msg_id}"
            with self._cache_lock:
                cached = self._msg_cache.get(cache_key)
                if cached and (time.time() - cached["cached_at"]) < 300:
                    return cached["info"]
            info = self._fetch_media_info_for_account(account, peer_str, msg_id)
            with self._cache_lock:
                self._msg_cache[cache_key] = {"info": info, "cached_at": time.time()}
            return info
        else:
            return self.get_media_info_multi(peer_str, msg_id)

    def get_media_info_multi(
        self,
        peer_str: str,
        msg_id: int,
        selected_accounts: Optional[List[TelegramAccount]] = None,
    ) -> Dict[str, Any]:
        """
        Try active accounts in order until one succeeds.
        If selected_accounts is provided, only those are tried (respects user selection).
        Returns info dict with extra key 'account' indicating which account succeeded.
        """
        if not self.is_configured():
            raise AuthRequiredError(
                "Telegram API ID và API Hash chưa được cấu hình. "
                "Vui lòng vào Cài đặt -> Tab Telegram để nhập thông tin."
            )

        accounts_to_try = selected_accounts if selected_accounts is not None else self.get_active_accounts()

        if not accounts_to_try:
            raise AuthRequiredError(
                "Chưa có tài khoản Telegram nào được kích hoạt. "
                "Vui lòng vào Cài đặt -> Tab Telegram để thêm hoặc bật tài khoản."
            )

        cache_key = f"multi_{peer_str}_{msg_id}"
        with self._cache_lock:
            cached = self._msg_cache.get(cache_key)
            if cached and (time.time() - cached["cached_at"]) < 300:
                return cached["info"]

        access_errors: List[str] = []  # accounts that got channel_private / no access errors
        tried_labels: List[str] = []

        for acc in accounts_to_try:
            tried_labels.append(acc.label)
            try:
                info = self._fetch_media_info_for_account(acc, peer_str, msg_id)
                # Success! Cache and return
                with self._cache_lock:
                    self._msg_cache[cache_key] = {"info": info, "cached_at": time.time()}
                return info
            except VideoNotFoundError:
                raise  # Don't retry on "message not found"
            except AuthRequiredError:
                access_errors.append(acc.label)
                continue
            except Exception as exc:
                err_str = str(exc).lower()
                if any(w in err_str for w in ("channel_private", "chat_admin_required", "user_banned_in_channel", "forbidden")):
                    access_errors.append(acc.label)
                    continue  # Try next account
                elif any(w in err_str for w in ("connection", "timeout", "timed out", "network")):
                    raise NetworkError(f"Lỗi kết nối tới Telegram: {exc}") from exc
                else:
                    raise ResolverError(f"Lỗi khi trích xuất video từ Telegram: {exc}") from exc

        # All tried accounts failed with access errors
        tried_str = ", ".join(tried_labels) if tried_labels else "(không có)"
        if access_errors:
            raise AuthRequiredError(
                f"Không tài khoản Telegram nào được chọn có quyền truy cập nội dung này.\n"
                f"Đã thử: {tried_str}.\n"
                f"Bạn có thể thêm tài khoản khác hoặc bật tài khoản có quyền trong Cài đặt -> Telegram."
            )
        raise AuthRequiredError(
            f"Không thể lấy thông tin video từ bất kỳ tài khoản nào đã chọn.\n"
            f"Đã thử: {tried_str}."
        )

    # -------------------------------------------------------------------------
    # Streaming
    # -------------------------------------------------------------------------

    def stream_media_range(
        self,
        peer_str: str,
        msg_id: int,
        start_byte: int,
        end_byte: int,
        chunk_size: int = 512 * 1024,
        account: Optional[TelegramAccount] = None,
    ) -> Generator[bytes, None, None]:
        """
        Synchronous generator yielding downloaded chunks of bytes for HTTP response.
        If account is None, uses multi-account fallback to find which account can access the media.
        """
        info = self.get_media_info(peer_str, msg_id, account=account)
        media = info["media"]
        total_len = info["file_size"]
        req_len = end_byte - start_byte + 1
        # Use the account that succeeded
        resolved_account = info.get("account", account)

        if req_len <= 0 or start_byte >= total_len:
            return

        if resolved_account is None:
            # Fallback: use first authorized active account
            active = self.get_active_accounts()
            resolved_account = active[0] if active else None

        if resolved_account is None:
            raise AuthRequiredError("Không tìm thấy tài khoản Telegram nào để stream video.")

        client = self._get_or_create_client(resolved_account)
        chunk_queue: queue.Queue = queue.Queue(maxsize=16)  # Max 16 * 512KB = 8MB buffer in memory
        stop_event = asyncio.Event()

        async def _producer():
            try:
                if not client.is_connected():
                    await client.connect()

                # Optimization: Lookahead prefetch for documents if range is larger than 2 chunks
                doc = getattr(media, "document", None) if hasattr(media, "document") else None
                if doc is None and hasattr(media, "size") and hasattr(media, "dc_id"):
                    doc = media

                if doc is not None and getattr(doc, "size", 0) > 0 and req_len > chunk_size * 2:
                    from telethon import utils
                    from telethon.network import MTProtoSender
                    from telethon.tl.alltlobjects import LAYER
                    from telethon.tl.functions import InvokeWithLayerRequest
                    from telethon.tl.functions.auth import ExportAuthorizationRequest, ImportAuthorizationRequest
                    from telethon.tl.functions.upload import GetFileRequest

                    dc_id, location = utils.get_input_location(doc)
                    dc = await client._get_dc(dc_id)
                    auth_key = None if dc_id and client.session.dc_id != dc_id else client.session.auth_key

                    num_senders = 3
                    senders = []
                    try:
                        for _ in range(num_senders):
                            if stop_event.is_set():
                                break
                            s = MTProtoSender(auth_key, loggers=client._log)
                            await s.connect(client._connection(
                                dc.ip_address, dc.port, dc.id,
                                loggers=client._log, proxy=client._proxy
                            ))
                            if not auth_key:
                                auth = await client(ExportAuthorizationRequest(dc_id))
                                client._init_request.query = ImportAuthorizationRequest(id=auth.id, bytes=auth.bytes)
                                req = InvokeWithLayerRequest(LAYER, client._init_request)
                                await s.send(req)
                                auth_key = s.auth_key
                            else:
                                req = InvokeWithLayerRequest(LAYER, client._init_request)
                                await s.send(req)
                            senders.append(s)

                        ALIGNMENT = 4096  # MTProto requires offset divisible by 1KB / 4KB
                        aligned_start = (start_byte // ALIGNMENT) * ALIGNMENT
                        lead_skip = start_byte - aligned_start
                        total_to_fetch = end_byte - aligned_start + 1
                        num_chunks = (total_to_fetch + chunk_size - 1) // chunk_size

                        in_flight = {}
                        for idx in range(min(len(senders), num_chunks)):
                            chunk_offset = aligned_start + idx * chunk_size
                            if total_len > 0 and chunk_offset >= total_len:
                                break
                            in_flight[idx] = client.loop.create_task(
                                client._call(senders[idx % len(senders)], GetFileRequest(
                                    location, offset=chunk_offset, limit=chunk_size
                                ))
                            )

                        bytes_delivered = 0
                        for next_consume in range(num_chunks):
                            if stop_event.is_set():
                                break
                            if next_consume not in in_flight:
                                break
                            res = await in_flight.pop(next_consume)
                            chunk = res.bytes if res else b""
                            if not chunk:
                                break

                            # Trim unrequested leading bytes if start_byte was unaligned
                            if lead_skip > 0:
                                if len(chunk) <= lead_skip:
                                    lead_skip -= len(chunk)
                                    next_to_fetch = next_consume + len(senders)
                                    if next_to_fetch < num_chunks and not stop_event.is_set():
                                        fetch_offset = aligned_start + next_to_fetch * chunk_size
                                        if total_len <= 0 or fetch_offset < total_len:
                                            s_idx = next_to_fetch % len(senders)
                                            in_flight[next_to_fetch] = client.loop.create_task(
                                                client._call(senders[s_idx], GetFileRequest(
                                                    location, offset=fetch_offset, limit=chunk_size
                                                ))
                                            )
                                    continue
                                chunk = chunk[lead_skip:]
                                lead_skip = 0

                            # Trim trailing bytes if chunk exceeds requested range
                            remaining_needed = req_len - bytes_delivered
                            if remaining_needed <= 0:
                                break
                            if len(chunk) > remaining_needed:
                                chunk = chunk[:remaining_needed]

                            while not stop_event.is_set():
                                try:
                                    chunk_queue.put(chunk, timeout=0.05)
                                    break
                                except queue.Full:
                                    await asyncio.sleep(0.02)

                            bytes_delivered += len(chunk)
                            if bytes_delivered >= req_len:
                                break

                            next_to_fetch = next_consume + len(senders)
                            if next_to_fetch < num_chunks and not stop_event.is_set():
                                fetch_offset = aligned_start + next_to_fetch * chunk_size
                                if total_len <= 0 or fetch_offset < total_len:
                                    s_idx = next_to_fetch % len(senders)
                                    in_flight[next_to_fetch] = client.loop.create_task(
                                        client._call(senders[s_idx], GetFileRequest(
                                            location, offset=fetch_offset, limit=chunk_size
                                        ))
                                    )
                    finally:
                        for t in in_flight.values():
                            if not t.done():
                                t.cancel()
                            else:
                                try:
                                    t.exception()
                                except Exception:
                                    pass
                        if in_flight:
                            await asyncio.gather(*in_flight.values(), return_exceptions=True)
                        await asyncio.gather(*[s.disconnect() for s in senders], return_exceptions=True)
                else:
                    ALIGNMENT = 4096
                    aligned_start = (start_byte // ALIGNMENT) * ALIGNMENT
                    lead_skip = start_byte - aligned_start
                    total_to_fetch = end_byte - aligned_start + 1
                    chunks_limit = (total_to_fetch + chunk_size - 1) // chunk_size

                    bytes_delivered = 0
                    async for chunk in client.iter_download(
                        media,
                        offset=aligned_start,
                        limit=chunks_limit,
                        request_size=chunk_size,
                    ):
                        if stop_event.is_set():
                            break

                        if lead_skip > 0:
                            if len(chunk) <= lead_skip:
                                lead_skip -= len(chunk)
                                continue
                            chunk = chunk[lead_skip:]
                            lead_skip = 0

                        remaining_needed = req_len - bytes_delivered
                        if remaining_needed <= 0:
                            break
                        if len(chunk) > remaining_needed:
                            chunk = chunk[:remaining_needed]

                        # Thread-safe put into queue with backpressure
                        while not stop_event.is_set():
                            try:
                                chunk_queue.put(chunk, timeout=0.05)
                                break
                            except queue.Full:
                                await asyncio.sleep(0.02)

                        bytes_delivered += len(chunk)
                        if bytes_delivered >= req_len:
                            break
            except Exception as exc:
                chunk_queue.put(exc)
            finally:
                chunk_queue.put(None)  # Sentinel to signify completion

        producer_fut = asyncio.run_coroutine_threadsafe(_producer(), self._loop)

        try:
            while True:
                try:
                    item = chunk_queue.get(timeout=1.0)
                except queue.Empty:
                    # Abort if stop requested or producer finished
                    if stop_event.is_set() or producer_fut.done():
                        break
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            # Stop producer task immediately when consumer finishes or disconnects
            self._loop.call_soon_threadsafe(stop_event.set)
            producer_fut.cancel()
            # Drain remaining items so producer's finally block can put sentinel
            deadline = time.time() + 2.0
            while time.time() < deadline:
                try:
                    chunk_queue.get_nowait()
                except queue.Empty:
                    break

    def download_media_file(
        self,
        peer_str: str,
        msg_id: int,
        destination_file: Path,
        account: Optional[TelegramAccount] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """
        Download Telegram media directly to destination_file with progress reporting.
        Uses multi-account fallback to identify which account has access to the channel/peer.
        Utilizes FastTelethonDownloader with 6 parallel worker senders for up to 10x-50x download speeds.
        """
        if account:
            selected_accounts = [account]
        else:
            selected_accounts = self.get_active_accounts()

        if not selected_accounts:
            raise AuthRequiredError("Chưa có tài khoản Telegram nào được kích hoạt để tải file.")

        info = self.get_media_info_multi(peer_str, msg_id, selected_accounts=selected_accounts)
        msg_obj = info.get("message") or info.get("media")
        resolved_account = info.get("account")
        if resolved_account is None:
            resolved_account = selected_accounts[0]

        client = self._get_or_create_client(resolved_account)

        # Check if we can use FastTelethonDownloader
        doc = getattr(msg_obj, "document", None)
        if doc is None and hasattr(msg_obj, "media"):
            doc = getattr(msg_obj.media, "document", None)

        if doc is not None and getattr(doc, "size", 0) > 0:
            downloader = FastTelethonDownloader(client, max_workers=6)

            async def _download_fast():
                if cancel_check and cancel_check():
                    raise RuntimeError("Người dùng đã hủy quá trình tải.")
                return await downloader.download(
                    doc,
                    destination_file=destination_file,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )

            return self._run_coro(_download_fast(), timeout=None)

        # Standard Telethon download fallback (for photos or other non-document media)
        async def _download():
            if cancel_check and cancel_check():
                raise RuntimeError("Người dùng đã hủy quá trình tải.")
            if not client.is_connected():
                await client.connect()

            def _progress(current: int, total: int):
                if cancel_check and cancel_check():
                    raise RuntimeError("Người dùng đã hủy quá trình tải.")
                if progress_callback:
                    progress_callback(current, total)

            # Ensure destination directory exists
            destination_file.parent.mkdir(parents=True, exist_ok=True)

            res = await client.download_media(
                msg_obj,
                file=str(destination_file),
                progress_callback=_progress,
            )
            return Path(res) if res else destination_file

        return self._run_coro(_download(), timeout=None)


class FastTelethonDownloader:
    """
    Downloads Telegram media files using multiple parallel MTProto connections.
    Connects N worker senders to the target DC, sharing the exported authorization key.
    Writes chunks directly to the seekable destination file.
    """

    def __init__(self, client, max_workers: int = 6):
        self.client = client
        self.max_workers = max_workers
        self.senders: List[Any] = []

    async def download(
        self,
        document,
        destination_file: Path,
        part_size: int = 512 * 1024,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Path:
        from telethon import utils
        from telethon.network import MTProtoSender
        from telethon.tl.alltlobjects import LAYER
        from telethon.tl.functions import InvokeWithLayerRequest
        from telethon.tl.functions.auth import ExportAuthorizationRequest, ImportAuthorizationRequest
        from telethon.tl.functions.upload import GetFileRequest

        if not self.client.is_connected():
            await self.client.connect()

        dc_id, location = utils.get_input_location(document)
        file_size = getattr(document, "size", 0)
        part_count = (file_size + part_size - 1) // part_size if file_size > 0 else 1
        num_workers = min(self.max_workers, max(1, part_count))

        destination_file.parent.mkdir(parents=True, exist_ok=True)
        f = open(destination_file, "wb")
        if file_size > 0:
            f.truncate(file_size)
        file_lock = asyncio.Lock()

        dc = await self.client._get_dc(dc_id)
        auth_key = None if dc_id and self.client.session.dc_id != dc_id else self.client.session.auth_key

        try:
            for _ in range(num_workers):
                if cancel_check and cancel_check():
                    raise RuntimeError("Người dùng đã hủy quá trình tải.")
                s = MTProtoSender(auth_key, loggers=self.client._log)
                await s.connect(self.client._connection(
                    dc.ip_address, dc.port, dc.id,
                    loggers=self.client._log, proxy=self.client._proxy
                ))
                if not auth_key:
                    auth = await self.client(ExportAuthorizationRequest(dc_id))
                    self.client._init_request.query = ImportAuthorizationRequest(
                        id=auth.id, bytes=auth.bytes
                    )
                    req = InvokeWithLayerRequest(LAYER, self.client._init_request)
                    await s.send(req)
                    auth_key = s.auth_key
                else:
                    req = InvokeWithLayerRequest(LAYER, self.client._init_request)
                    await s.send(req)
                self.senders.append(s)

            queue: asyncio.Queue = asyncio.Queue()
            for i in range(part_count):
                queue.put_nowait(i)

            downloaded_total = 0

            async def worker(sender):
                nonlocal downloaded_total
                while not queue.empty():
                    if cancel_check and cancel_check():
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        raise RuntimeError("Người dùng đã hủy quá trình tải.")
                    try:
                        part_idx = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    offset = part_idx * part_size
                    # Always use part_size (must be divisible by 1KB/4KB). Telegram returns remaining bytes on last chunk.
                    limit = part_size

                    chunk_data = None
                    for attempt in range(3):
                        if cancel_check and cancel_check():
                            while not queue.empty():
                                try:
                                    queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    break
                            raise RuntimeError("Người dùng đã hủy quá trình tải.")
                        try:
                            res = await self.client._call(
                                sender,
                                GetFileRequest(location, offset=offset, limit=limit)
                            )
                            chunk_data = res.bytes
                            break
                        except Exception:
                            if attempt == 2:
                                while not queue.empty():
                                    try:
                                        queue.get_nowait()
                                    except asyncio.QueueEmpty:
                                        break
                                raise
                            await asyncio.sleep(0.5)

                    if chunk_data:
                        async with file_lock:
                            f.seek(offset)
                            f.write(chunk_data)

                        downloaded_total += len(chunk_data)
                        if progress_callback:
                            progress_callback(downloaded_total, file_size)

                    queue.task_done()

            await asyncio.gather(*[worker(s) for s in self.senders])
            return destination_file
        finally:
            f.close()
            await asyncio.gather(*[s.disconnect() for s in self.senders], return_exceptions=True)
            self.senders.clear()

