"""
Network Manager Singleton for FB Video Watcher.
Coordinates Proxy routing and DoH DNS resolution across all subsystems.
Guarantees:
- Default is OFF / System configuration.
- User settings always take precedence.
- Zero leaks, full process-level isolation.
"""

import logging
import threading
from typing import Optional, Dict, Any, List, Tuple

from main.network.proxy_config import ProxyConfig
from main.network.doh_resolver import DoHResolver
from main.network.dns_interceptor import SocketDNSInterceptor

logger = logging.getLogger(__name__)


class NetworkManager:
    """Singleton managing application-level Proxy and DoH DNS."""

    _instance: Optional["NetworkManager"] = None
    _lock = threading.Lock()

    def __init__(self, initial_settings: Optional[Dict[str, Any]] = None):
        self._proxy_config = ProxyConfig()
        self._doh_resolver = DoHResolver()
        self._dns_interceptor = SocketDNSInterceptor(self._doh_resolver)
        self._route_vlc_via_stream_proxy = True

        if initial_settings:
            self.apply_settings(initial_settings)

    @classmethod
    def get_instance(cls, settings: Optional[Dict[str, Any]] = None) -> "NetworkManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(settings)
            elif settings:
                cls._instance.apply_settings(settings)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Utility for tests to reset state."""
        with cls._lock:
            if cls._instance:
                cls._instance._dns_interceptor.uninstall()
                cls._instance = None

    def apply_settings(self, settings_dict: Dict[str, Any]) -> None:
        """
        Updates Proxy and DoH configurations from settings dictionary.
        Respects user choice; if not enabled, ensures clean bypass/uninstallation.
        """
        net_cfg = settings_dict.get("network", {}) if isinstance(settings_dict, dict) else {}
        if not isinstance(net_cfg, dict):
            net_cfg = {}

        # 1. Update Proxy Config
        self._proxy_config = ProxyConfig(
            mode=net_cfg.get("proxy_mode", "direct"),
            proxy_type=net_cfg.get("proxy_protocol") or net_cfg.get("proxy_type", "socks5h"),
            host=str(net_cfg.get("proxy_host", "")).strip(),
            port=int(net_cfg.get("proxy_port", 1080) or 1080),
            user=str(net_cfg.get("proxy_user", "")).strip(),
            password=str(net_cfg.get("proxy_pass", "")),
        )

        # 2. Update DoH Settings
        doh_enabled = bool(net_cfg.get("doh_enabled", False))
        doh_provider = str(net_cfg.get("doh_provider", "cloudflare"))
        doh_custom_url = str(net_cfg.get("doh_custom_url", ""))
        self._route_vlc_via_stream_proxy = bool(net_cfg.get("route_vlc_via_stream_proxy", True))

        self._doh_resolver.set_provider(doh_provider, doh_custom_url)

        if doh_enabled:
            self._dns_interceptor.install(self._doh_resolver)
        else:
            self._dns_interceptor.uninstall()

    @property
    def proxy_config(self) -> ProxyConfig:
        return self._proxy_config

    @property
    def doh_resolver(self) -> DoHResolver:
        return self._doh_resolver

    @property
    def resolver(self) -> DoHResolver:
        """Alias for doh_resolver."""
        return self._doh_resolver

    @property
    def interceptor(self) -> SocketDNSInterceptor:
        """Access the socket DNS interceptor."""
        return self._dns_interceptor

    @property
    def is_proxy_enabled(self) -> bool:
        return self._proxy_config.is_enabled()

    @property
    def is_doh_enabled(self) -> bool:
        return self._dns_interceptor.is_installed

    @property
    def should_route_vlc_via_stream_proxy(self) -> bool:
        return self.is_doh_enabled and self._route_vlc_via_stream_proxy

    def get_ytdl_proxy(self) -> Optional[str]:
        """Returns proxy URL for yt-dlp."""
        return self.get_proxy_url()

    def get_proxy_url(self) -> Optional[str]:
        """Returns standard proxy URL string (e.g. for yt-dlp) or None if disabled."""
        return self._proxy_config.to_url()

    def get_masked_proxy_url(self) -> Optional[str]:
        """Returns proxy URL with masked password for safe logging."""
        return self._proxy_config.to_masked_url()

    def get_vlc_args(self) -> List[str]:
        """Returns native libVLC CLI arguments for proxying network streams."""
        return self._proxy_config.to_vlc_args()

    def get_telethon_proxy(self) -> Optional[Dict[str, Any]]:
        """Returns proxy dictionary for Telethon (Telegram MTProto client)."""
        return self._proxy_config.to_telethon_proxy()

    def test_proxy(self, config: Optional[ProxyConfig] = None) -> Tuple[bool, float, str]:
        """Test proxy connectivity and measure latency."""
        target = config or self._proxy_config
        return target.test_connection()

    def test_doh(self, provider: Optional[str] = None, custom_url: str = "") -> Tuple[bool, float, str]:
        """Test DoH resolution against a test domain."""
        return self._doh_resolver.test_provider(provider, custom_url)
