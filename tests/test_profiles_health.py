import unittest

from main.playback_health import PlaybackHealthMonitor
from main.playback_profiles import resolve_profile, source_domain


class TestProfilesAndHealth(unittest.TestCase):
    def test_source_profile_overrides_global_without_affecting_other_domain(self):
        settings = {
            "video": {"max_height": 1080},
            "streaming": {"network_caching": 3000, "hardware_decode": True},
            "source_profiles": {
                "global": {"mode": "auto", "max_height": 1080},
                "youtube.com": {"mode": "custom", "max_height": 720, "network_caching_ms": 1500},
            },
        }
        self.assertEqual(source_domain("https://www.youtube.com/watch?v=1"), "youtube.com")
        youtube = resolve_profile(settings, "https://www.youtube.com/watch?v=1")
        facebook = resolve_profile(settings, "https://www.facebook.com/watch?v=1")
        self.assertEqual((youtube.mode, youtube.max_height, youtube.network_caching_ms), ("custom", 720, 1500))
        self.assertEqual(facebook.mode, "auto")

    def test_health_needs_sustained_buffering(self):
        monitor = PlaybackHealthMonitor(degraded_after_ms=5000, critical_after_ms=15000)
        self.assertEqual(monitor.tick("buffering", now=0).state, "healthy")
        self.assertEqual(monitor.tick("buffering", now=6).state, "degraded")
        self.assertEqual(monitor.tick("buffering", now=16).state, "critical")
        self.assertEqual(monitor.tick("playing", now=17).state, "critical")
        # Health recovery after sustained playing
        self.assertEqual(monitor.tick("playing", now=28).state, "degraded")
        self.assertEqual(monitor.tick("playing", now=38).state, "healthy")

    def test_health_reset(self):
        monitor = PlaybackHealthMonitor(degraded_after_ms=5000, critical_after_ms=15000)
        monitor.tick("buffering", now=0)
        monitor.tick("buffering", now=16)
        self.assertEqual(monitor.snapshot().state, "critical")
        monitor.reset()
        self.assertEqual(monitor.snapshot().state, "healthy")
        self.assertEqual(monitor.snapshot().buffering_ms, 0)


if __name__ == "__main__":
    unittest.main()
