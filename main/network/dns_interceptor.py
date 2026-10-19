"""
Process-level socket.getaddrinfo interceptor for FB Video Watcher.
Hooks DNS resolution inside the Python process to route hostnames through DoH.
Does NOT modify Windows OS network adapters or any other process.
"""

import logging
import re
import socket
import threading
from typing import Optional, List, Tuple, Any

from main.network.doh_resolver import DoHResolver

logger = logging.getLogger(__name__)

# Preserve native C getaddrinfo reference
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


class SocketDNSInterceptor:
    """
    Manages process-isolated interception of socket.getaddrinfo.
    Thread-safe and fail-safe.
    """

    def __init__(self, resolver: Optional[DoHResolver] = None):
        self.resolver = resolver
        self._is_installed = False
        self._lock = threading.RLock()

    @property
    def is_installed(self) -> bool:
        with self._lock:
            return self._is_installed

    def install(self, resolver: Optional[DoHResolver] = None) -> None:
        """Installs the getaddrinfo hook."""
        with self._lock:
            if resolver:
                self.resolver = resolver
            if self._is_installed:
                return

            def _hooked_getaddrinfo(
                host: Any,
                port: Any,
                family: int = 0,
                type: int = 0,
                proto: int = 0,
                flags: int = 0,
            ) -> List[Tuple[Any, ...]]:
                # If host is not a string, or is loopback/IP literal, bypass hook
                if not host or not isinstance(host, str):
                    return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

                host_str = host.strip()
                if host_str in ("localhost", "127.0.0.1", "::1"):
                    return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

                # Numeric IPv4 literal check
                if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host_str):
                    return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

                # Attempt resolution via DoH
                if self.resolver:
                    try:
                        resolved_ips = self.resolver.resolve_a(host_str)
                        if resolved_ips:
                            # Use the first resolved clean IP with native getaddrinfo to produce standard sockaddr
                            clean_ip = resolved_ips[0]
                            return _ORIGINAL_GETADDRINFO(
                                clean_ip, port, family, type, proto, flags
                            )
                    except Exception as e:
                        logger.debug("DNS Hook DoH lookup failed for %s, falling back to system DNS: %s", host_str, e)

                # Fail-safe: Always fallback to system resolution
                return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

            socket.getaddrinfo = _hooked_getaddrinfo
            self._is_installed = True
            logger.info("In-App DoH Socket DNS Interceptor installed successfully.")

    def uninstall(self) -> None:
        """Restores the original native socket.getaddrinfo function."""
        with self._lock:
            if not self._is_installed:
                return

            socket.getaddrinfo = _ORIGINAL_GETADDRINFO
            self._is_installed = False
            logger.info("In-App DoH Socket DNS Interceptor uninstalled. System DNS restored.")
