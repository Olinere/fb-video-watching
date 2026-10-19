import unittest
from unittest.mock import MagicMock, patch
from main.playback_health import PlaybackHealthMonitor, HealthSnapshot
from main.playback_profiles import resolve_profile, source_domain


class TestHealthAndAutoSuggestion(unittest.TestCase):
    def test_health_degraded_triggers_prompt_for_custom_profile(self):
        from main.app import Application
        
        # Mock settings, gui, root
        app = MagicMock(spec=Application)
        app.settings = MagicMock()
        app.settings.settings = {
            "source_profiles": {
                "global": {"mode": "custom", "max_height": 1080},
                "youtube.com": {"mode": "custom", "max_height": 720},
            }
        }
        app.gui = MagicMock()
        app._original_url = "https://www.youtube.com/watch?v=sample"
        app._last_health_suggestion_time = 0.0
        app._last_health_suggestion_url = ""
        
        health = HealthSnapshot(state="degraded", buffering_ms=6000, buffering_events=1, error_count=0)
        
        # Call the actual method
        Application._check_playback_health_degraded(app, health)
        
        # Verify show_network_suggestion_prompt was called on gui
        app.gui.show_network_suggestion_prompt.assert_called_once()
        args, kwargs = app.gui.show_network_suggestion_prompt.call_args
        self.assertIn("Auto", args[0])

    def test_health_degraded_cooldown_prevents_spam(self):
        from main.app import Application
        import time
        
        app = MagicMock(spec=Application)
        app.settings = MagicMock()
        app.settings.settings = {
            "source_profiles": {
                "global": {"mode": "custom"},
            }
        }
        app.gui = MagicMock()
        app._original_url = "https://www.facebook.com/watch?v=sample"
        # Set last suggestion to 10 seconds ago (cooldown is 60s)
        app._last_health_suggestion_time = time.monotonic() - 10.0
        app._last_health_suggestion_url = app._original_url
        
        health = HealthSnapshot(state="degraded", buffering_ms=6000, buffering_events=1, error_count=0)
        
        Application._check_playback_health_degraded(app, health)
        
        # Should NOT be called because of cooldown
        app.gui.show_network_suggestion_prompt.assert_not_called()
        app.gui.show_osd_message.assert_not_called()

    def test_health_degraded_shows_osd_for_auto_profile(self):
        from main.app import Application
        
        app = MagicMock(spec=Application)
        app.settings = MagicMock()
        app.settings.settings = {
            "source_profiles": {
                "global": {"mode": "auto"},
            }
        }
        app.gui = MagicMock()
        app._original_url = "https://www.facebook.com/watch?v=sample"
        app._last_health_suggestion_time = 0.0
        app._last_health_suggestion_url = ""
        
        health = HealthSnapshot(state="degraded", buffering_ms=6000, buffering_events=1, error_count=0)
        
        Application._check_playback_health_degraded(app, health)
        
        # Should show OSD message, not prompt
        app.gui.show_network_suggestion_prompt.assert_not_called()
        app.gui.show_osd_message.assert_called_once()

    def test_handle_switch_to_auto_profile(self):
        from main.app import Application
        
        saved_settings = {}
        def mock_set(section, val):
            saved_settings[section] = val
        def mock_get(section, default=None):
            return saved_settings.get(section, default)
            
        app = MagicMock(spec=Application)
        app.settings = MagicMock()
        saved_settings["source_profiles"] = {
            "global": {"mode": "custom"},
            "facebook.com": {"mode": "custom"},
        }
        app.settings.get.side_effect = mock_get
        app.settings.set.side_effect = mock_set
        app.gui = MagicMock()
        app._original_url = "https://www.facebook.com/watch?v=sample"
        
        Application.handle_switch_to_auto_profile(app)
        
        # Check source profiles updated
        profiles = saved_settings["source_profiles"]
        self.assertEqual(profiles["global"]["mode"], "auto")
        self.assertEqual(profiles["facebook.com"]["mode"], "auto")
        app.settings.save.assert_called_once()
        app.gui.hide_network_suggestion_prompt.assert_called_once()
        app.gui.show_osd_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
