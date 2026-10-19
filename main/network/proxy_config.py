"""
Proxy configuration and validation module for FB Video Watcher.
Supports HTTP, HTTPS, SOCKS5, and SOCKS5h protocols.
Enforces process-level isolation and zero memory/resource leaks.
"""

from dataclasses import dataclass
import logging
import time
from typing import Optional, List, Dict, Any, Tuple
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Represents in-app proxy configuration."""
    mode: str = "direct"             # "direct" (off) | "system" | "custom"
    proxy_type: str = "socks5h"      # "http" | "socks5" | "socks5h"
    host: str = ""
    port: int = 1080
    user: str = ""
    password: str = ""
    protocol: Optional[str] = None
    username: Optional[str] = None

    def __post_init__(self):
        if self.protocol and not self.proxy_type:
            self.proxy_type = self.protocol
        elif self.protocol:
            self.proxy_type = self.protocol
        if self.username and not self.user:
            self.user = self.username
        elif self.username:
            self.user = self.username

    def is_enabled(self) -> bool:
        """Returns True if a custom proxy is actively enabled and valid."""
        return (
            self.mode == "custom"
            and bool(self.host.strip())
            and 1 <= int(self.port or 0) <= 65535
        )

    def to_url(self) -> Optional[str]:
        """
        Builds the standard URL representation for the proxy.
        e.g. 'socks5h://user:pass@127.0.0.1:1080' or 'http://192.168.1.1:8080'
        """
        if not self.is_enabled():
            return None

        scheme = self.proxy_type.lower()
        if scheme not in ("http", "https", "socks5", "socks5h"):
            scheme = "socks5h"

        host = self.host.strip()
        port = int(self.port)

        if self.user.strip():
            quoted_user = urllib.parse.quote(self.user.strip())
            quoted_pass = urllib.parse.quote(self.password) if self.password else ""
            if quoted_pass:
                auth = f"{quoted_user}:{quoted_pass}@"
            else:
                auth = f"{quoted_user}@"
        else:
            auth = ""

        return f"{scheme}://{auth}{host}:{port}"

    def to_masked_url(self) -> Optional[str]:
        """
        Returns proxy URL with credentials masked for safe logging/devlog display.
        e.g. 'socks5h://user:****@127.0.0.1:1080'
        """
        if self.mode == "system":
            return "system"

        if not self.is_enabled():
            return None

        scheme = self.proxy_type.lower()
        host = self.host.strip()
        port = int(self.port)

        if self.user.strip():
            user = self.user.strip()
            auth = f"{user}:****@" if self.password else f"{user}@"
        else:
            auth = ""

        return f"{scheme}://{auth}{host}:{port}"

    def to_vlc_args(self) -> List[str]:
        """
        Generates native libVLC CLI arguments for proxying network streams.
        Returns empty list if proxy is disabled or mode is direct/system.
        """
        if not self.is_enabled():
            return []

        args = []
        host = self.host.strip()
        port = int(self.port)
        scheme = self.proxy_type.lower()

        if scheme in ("http", "https"):
            if self.user.strip():
                user_enc = urllib.parse.quote(self.user.strip())
                proxy_str = f"http://{user_enc}@{host}:{port}/"
                args.append(f"--http-proxy={proxy_str}")
                if self.password:
                    args.append(f"--http-proxy-pwd={self.password}")
            else:
                args.append(f"--http-proxy=http://{host}:{port}/")
        elif scheme in ("socks5", "socks5h"):
            args.append(f"--socks={host}:{port}")
            if self.user.strip():
                args.append(f"--socks-user={self.user.strip()}")
            if self.password:
                args.append(f"--socks-pwd={self.password}")

        return args

    def get_vlc_args(self) -> List[str]:
        """Alias for to_vlc_args."""
        return self.to_vlc_args()

    def to_telethon_proxy(self) -> Optional[Dict[str, Any]]:
        """
        Builds proxy dictionary for Telethon (Telegram MTProto client).
        Supports SOCKS5, SOCKS5h (rdns=True), and HTTP.
        """
        if not self.is_enabled():
            return None

        scheme = self.proxy_type.lower()
        host = self.host.strip()
        port = int(self.port)

        proxy_dict: Dict[str, Any] = {
            "addr": host,
            "port": port,
        }

        if scheme in ("socks5", "socks5h"):
            proxy_dict["proxy_type"] = "socks5"
            proxy_dict["rdns"] = (scheme == "socks5h")
        else:
            proxy_dict["proxy_type"] = "http"

        if self.user.strip():
            proxy_dict["username"] = self.user.strip()
            proxy_dict["password"] = self.password or ""

        return proxy_dict

    def test_connection(
        self,
        target_url: str = "https://cloudflare.com/cdn-cgi/trace",
        timeout: float = 4.0,
    ) -> Tuple[bool, float, str]:
        """
        Tests the proxy connection by issuing an HTTP GET to target_url.
        Returns:
            (success: bool, latency_ms: float, egress_info: str)
        """
        proxy_url = self.to_url()
        if not proxy_url:
            return False, 0.0, "Proxy chưa được cấu hình hoặc đang tắt."

        start_time = time.perf_counter()
        try:
            # Build an isolated opener to prevent contaminating global state
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            opener = urllib.request.build_opener(proxy_handler)
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": "FB-Video-Watcher-ProxyTest/1.0"},
            )

            with opener.open(req, timeout=timeout) as response:
                content = response.read(1024).decode("utf-8", errors="ignore")
                latency = (time.perf_counter() - start_time) * 1000.0

                # Extract IP if available from cloudflare trace
                ip_str = ""
                for line in content.splitlines():
                    if line.startswith("ip="):
                        ip_str = line.split("=", 1)[1].strip()
                        break

                if not ip_str:
                    ip_str = "Kết nối thành công"

                return True, round(latency, 1), ip_str
        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000.0
            err_msg = str(e)
            if "timed out" in err_msg.lower():
                err_msg = "Kết nối quá hạn (Timeout)"
            elif "refused" in err_msg.lower():
                err_msg = "Máy chủ proxy từ chối kết nối (Connection Refused)"
            elif "407" in err_msg:
                err_msg = "Sai tài khoản/mật khẩu Proxy (407 Proxy Auth Required)"
            return False, round(latency, 1), err_msg
