"""
Network package for FB Video Watcher.
Provides In-App Isolated Proxy and DoH DNS capabilities.
"""

from main.network.proxy_config import ProxyConfig
from main.network.doh_resolver import DoHResolver
from main.network.dns_interceptor import SocketDNSInterceptor
from main.network.manager import NetworkManager

__all__ = [
    "ProxyConfig",
    "DoHResolver",
    "SocketDNSInterceptor",
    "NetworkManager",
]
