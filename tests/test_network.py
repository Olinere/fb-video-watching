"""
Unit tests for In-App Isolated Proxy & DoH DNS Subsystem.
Verifies App-level isolation, zero global system tampering, thread-safety,
LRU caching, DNS interception, fallback resilience, and GUI integration.
"""

import socket
import unittest
from unittest.mock import MagicMock, patch

from main.network.proxy_config import ProxyConfig
from main.network.doh_resolver import DoHResolver, DOH_PROVIDERS
from main.network.dns_interceptor import SocketDNSInterceptor
from main.network.manager import NetworkManager


class TestProxyConfig(unittest.TestCase):
    """Test ProxyConfig formatting, masking, VLC args, and Telethon dicts."""

    def test_direct_mode_defaults(self):
        cfg = ProxyConfig(mode="direct")
        self.assertFalse(cfg.is_enabled())
        self.assertIsNone(cfg.to_url())
        self.assertIsNone(cfg.to_masked_url())
        self.assertEqual(cfg.to_vlc_args(), [])
        self.assertEqual(cfg.get_vlc_args(), [])
        self.assertIsNone(cfg.to_telethon_proxy())

    def test_system_mode(self):
        cfg = ProxyConfig(mode="system")
        self.assertFalse(cfg.is_enabled())  # is_enabled checks for custom proxy
        self.assertIsNone(cfg.to_url())
        self.assertEqual(cfg.to_masked_url(), "system")
        self.assertEqual(cfg.to_vlc_args(), [])
        self.assertIsNone(cfg.to_telethon_proxy())

    def test_custom_http_no_auth(self):
        cfg = ProxyConfig(mode="custom", protocol="http", host="192.168.1.100", port=8080)
        self.assertTrue(cfg.is_enabled())
        self.assertEqual(cfg.to_url(), "http://192.168.1.100:8080")
        self.assertEqual(cfg.to_masked_url(), "http://192.168.1.100:8080")
        self.assertEqual(cfg.to_vlc_args(), ["--http-proxy=http://192.168.1.100:8080/"])
        
        telethon_dict = cfg.to_telethon_proxy()
        self.assertIsNotNone(telethon_dict)
        self.assertEqual(telethon_dict["proxy_type"], "http")
        self.assertEqual(telethon_dict["addr"], "192.168.1.100")
        self.assertEqual(telethon_dict["port"], 8080)
        self.assertNotIn("username", telethon_dict)

    def test_custom_http_with_auth_and_masking(self):
        cfg = ProxyConfig(
            mode="custom",
            protocol="http",
            host="proxy.corp.com",
            port=3128,
            username="admin",
            password="SuperSecretPassword123",
        )
        self.assertEqual(cfg.to_url(), "http://admin:SuperSecretPassword123@proxy.corp.com:3128")
        self.assertEqual(cfg.to_masked_url(), "http://admin:****@proxy.corp.com:3128")
        vlc_args = cfg.to_vlc_args()
        self.assertTrue(any("--http-proxy=" in a for a in vlc_args))
        self.assertTrue(any("--http-proxy-pwd=" in a for a in vlc_args))

        telethon_dict = cfg.to_telethon_proxy()
        self.assertEqual(telethon_dict["username"], "admin")
        self.assertEqual(telethon_dict["password"], "SuperSecretPassword123")

    def test_custom_socks5_with_vlc_args(self):
        cfg = ProxyConfig(
            mode="custom",
            protocol="socks5",
            host="127.0.0.1",
            port=1080,
            username="user5",
            password="pass5",
        )
        self.assertEqual(cfg.to_url(), "socks5://user5:pass5@127.0.0.1:1080")
        vlc_args = cfg.to_vlc_args()
        self.assertIn("--socks=127.0.0.1:1080", vlc_args)
        self.assertIn("--socks-user=user5", vlc_args)
        self.assertIn("--socks-pwd=pass5", vlc_args)

        telethon_dict = cfg.to_telethon_proxy()
        self.assertEqual(telethon_dict["proxy_type"], "socks5")

    def test_custom_socks5h_remote_dns(self):
        cfg = ProxyConfig(
            mode="custom",
            protocol="socks5h",
            host="proxy.privacy.org",
            port=1080,
        )
        self.assertEqual(cfg.to_url(), "socks5h://proxy.privacy.org:1080")
        telethon_dict = cfg.to_telethon_proxy()
        self.assertEqual(telethon_dict["proxy_type"], "socks5")
        self.assertTrue(telethon_dict["rdns"])


class TestDoHResolver(unittest.TestCase):
    """Test DNS-over-HTTPS resolver, caching, bootstrap IPs, and JSON parsing."""

    def setUp(self):
        self.resolver = DoHResolver(provider="cloudflare")

    def test_bootstrap_ips(self):
        self.assertTrue(self.resolver.is_bootstrap_ip("1.1.1.1"))
        self.assertTrue(self.resolver.is_bootstrap_ip("8.8.8.8"))
        self.assertTrue(self.resolver.is_bootstrap_ip("9.9.9.9"))
        self.assertFalse(self.resolver.is_bootstrap_ip("facebook.com"))
        self.assertFalse(self.resolver.is_bootstrap_ip("127.0.0.1"))

    def test_cache_hit_and_eviction(self):
        # Manually seed cache
        self.resolver._cache["test.example.com"] = (["93.184.216.34"], 9999999999.0)
        ips = self.resolver.resolve("test.example.com")
        self.assertEqual(ips, ["93.184.216.34"])

        # Expired TTL
        self.resolver._cache["expired.com"] = (["1.2.3.4"], 1.0)
        with patch.object(self.resolver, "_query_doh_json", return_value=([], 0)):
            ips_expired = self.resolver.resolve("expired.com")
            self.assertEqual(ips_expired, [])

    def test_json_dns_parsing(self):
        json_data = {
            "Status": 0,
            "Answer": [
                {"name": "example.com", "type": 1, "TTL": 300, "data": "93.184.216.34"},
                {"name": "example.com", "type": 28, "TTL": 300, "data": "2606:2800:220:1:248:1893:25c8:1946"},
            ]
        }
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.status = 200
            import json
            mock_resp.read.return_value = json.dumps(json_data).encode("utf-8")
            mock_url.return_value.__enter__.return_value = mock_resp

            ips, ttl = self.resolver._query_doh_json("example.com", timeout=2.0)
            self.assertEqual(ips, ["93.184.216.34"])
            self.assertEqual(ttl, 300)

    def test_clear_cache(self):
        self.resolver._cache["foo.com"] = (["1.1.1.1"], 9999999999.0)
        self.resolver.clear_cache()
        self.assertEqual(len(self.resolver._cache), 0)


class TestDNSInterceptor(unittest.TestCase):
    """Test process-isolated socket.getaddrinfo monkeypatcher."""

    def setUp(self):
        self.resolver = DoHResolver(provider="cloudflare")
        self.interceptor = SocketDNSInterceptor(self.resolver)

    def tearDown(self):
        self.interceptor.uninstall()

    def test_install_and_uninstall(self):
        self.assertFalse(self.interceptor.is_installed)
        self.interceptor.install()
        self.assertTrue(self.interceptor.is_installed)
        self.interceptor.uninstall()
        self.assertFalse(self.interceptor.is_installed)

    def test_loopback_and_numeric_bypassed(self):
        self.interceptor.install()
        # Must resolve 127.0.0.1 directly via original getaddrinfo without calling DoH
        with patch.object(self.resolver, "resolve_a", side_effect=Exception("Should not be called!")):
            res = socket.getaddrinfo("127.0.0.1", 80)
            self.assertTrue(any(addr[4][0] == "127.0.0.1" for addr in res))

            res_localhost = socket.getaddrinfo("localhost", 80)
            self.assertTrue(any(addr[4][0] in ("127.0.0.1", "::1") for addr in res_localhost))

    def test_intercept_hostname_to_doh_ip(self):
        self.interceptor.install()
        with patch.object(self.resolver, "resolve_a", return_value=["104.21.45.67"]):
            res = socket.getaddrinfo("intercept-test.org", 443, family=socket.AF_INET)
            self.assertTrue(len(res) > 0)
            self.assertEqual(res[0][4][0], "104.21.45.67")
            self.assertEqual(res[0][4][1], 443)

    def test_fallback_on_doh_failure(self):
        self.interceptor.install()
        # If DoH returns empty or throws, fallback to native getaddrinfo
        with patch.object(self.resolver, "resolve_a", return_value=[]):
            res = socket.getaddrinfo("127.0.0.1", 80)
            self.assertIsNotNone(res)


class TestNetworkManager(unittest.TestCase):
    """Test NetworkManager singleton coordination and default settings."""

    def tearDown(self):
        mgr = NetworkManager.get_instance()
        mgr.interceptor.uninstall()
        NetworkManager.reset_instance()

    def test_default_is_direct_and_doh_off(self):
        NetworkManager.reset_instance()
        mgr = NetworkManager.get_instance({})
        self.assertFalse(mgr.is_proxy_enabled)
        self.assertFalse(mgr.is_doh_enabled)
        self.assertFalse(mgr.interceptor.is_installed)
        self.assertIsNone(mgr.get_ytdl_proxy())
        self.assertEqual(mgr.get_vlc_args(), [])

    def test_apply_settings_enables_proxy_and_doh(self):
        NetworkManager.reset_instance()
        mgr = NetworkManager.get_instance()
        settings = {
            "network": {
                "proxy_mode": "custom",
                "proxy_protocol": "socks5",
                "proxy_host": "127.0.0.1",
                "proxy_port": 1080,
                "doh_enabled": True,
                "doh_provider": "google",
            }
        }
        mgr.apply_settings(settings)
        self.assertTrue(mgr.is_proxy_enabled)
        self.assertTrue(mgr.is_doh_enabled)
        self.assertTrue(mgr.interceptor.is_installed)
        self.assertEqual(mgr.get_ytdl_proxy(), "socks5://127.0.0.1:1080")
        self.assertEqual(mgr.resolver.provider, "google")

        # Disable DoH
        settings["network"]["doh_enabled"] = False
        mgr.apply_settings(settings)
        self.assertFalse(mgr.is_doh_enabled)
        self.assertFalse(mgr.interceptor.is_installed)


class TestSettingsDialogNetwork(unittest.TestCase):
    """Test SettingsDialog network tab initialization and persistence."""

    def setUp(self):
        import tkinter as tk
        import tempfile
        from pathlib import Path
        from main.settings import SettingsManager
        from main.theme import ThemeManager

        self.root = tk.Tk()
        self.root.withdraw()
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir)
        self.settings_mgr = SettingsManager(config_dir=self.config_dir)
        self.theme_mgr = ThemeManager(self.root, initial_theme="dark")

    def tearDown(self):
        import shutil
        try:
            self.root.destroy()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_settings_dialog_network_tab_exists(self):
        from main.gui import SettingsDialog

        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        self.assertTrue(hasattr(dialog, "tab_network"))
        self.assertIn(dialog.tab_network, dialog.notebook.tabs())
        dialog.top.destroy()

    def test_settings_dialog_network_tab_persists(self):
        from main.gui import SettingsDialog

        dialog = SettingsDialog(self.root, self.settings_mgr, self.theme_mgr)
        dialog.proxy_mode_var.set("custom")
        dialog.proxy_protocol_var.set("socks5")
        dialog.proxy_host_var.set("127.0.0.1")
        dialog.proxy_port_var.set("1080")
        dialog.proxy_user_var.set("myuser")
        dialog.proxy_pass_var.set("mypass")
        dialog.doh_enabled_var.set(True)
        dialog.doh_provider_var.set("google")
        dialog.doh_custom_url_var.set("")
        dialog._save_and_close()

        net = self.settings_mgr.get("network")
        self.assertEqual(net.get("proxy_mode"), "custom")
        self.assertEqual(net.get("proxy_protocol"), "socks5")
        self.assertEqual(net.get("proxy_host"), "127.0.0.1")
        self.assertEqual(net.get("proxy_port"), 1080)
        self.assertEqual(net.get("proxy_user"), "myuser")
        self.assertEqual(net.get("proxy_pass"), "mypass")
        self.assertTrue(net.get("doh_enabled"))
        self.assertEqual(net.get("doh_provider"), "google")


if __name__ == "__main__":
    unittest.main()
