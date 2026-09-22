"""
Settings Manager module.
Handles loading, saving, validating, and updating persistent JSON settings in ~/.fb-video-watcher/settings.json.
Strictly adheres to specs.md §4.3 and handles Edge Cases §7.5 case #35 (corrupt JSON).
"""

import copy
import json
import os
from pathlib import Path
from typing import Any, Optional, Dict

from main.constants import CONFIG_DIR, SETTINGS_FILE, DEFAULT_SETTINGS, get_config_dir


class SettingsManager:
    """Manages application persistent configuration with deep-merge and corruption recovery."""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize SettingsManager.

        Args:
            config_dir: Base directory for storing configuration files. Defaults to get_config_dir().
        """
        self.config_dir = config_dir or get_config_dir()
        self.settings_file = self.config_dir / "settings.json"
        self._ensure_dir()
        self.settings: Dict[str, Any] = self._load()

    def _ensure_dir(self) -> None:
        """Create config directory if it does not exist."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _deep_merge(self, default_dict: Dict[str, Any], user_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge saved user settings onto default schema."""
        result = copy.deepcopy(default_dict)
        for key, val in user_dict.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    def _load(self) -> Dict[str, Any]:
        """Load settings from disk. If missing or corrupted, resets to DEFAULT_SETTINGS."""
        if self.settings_file.is_file():
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    merged = self._deep_merge(DEFAULT_SETTINGS, saved)
                    self._migrate_playback_profiles(merged, saved)
                    return merged
            except (json.JSONDecodeError, OSError):
                # Edge case #35: Corrupt settings file -> restore from defaults
                pass

        # Return default copy and save
        defaults = copy.deepcopy(DEFAULT_SETTINGS)
        try:
            self._save_data(defaults)
        except Exception:
            pass
        return defaults

    def _migrate_playback_profiles(self, merged: Dict[str, Any], saved: Dict[str, Any]) -> None:
        """Preserve non-default legacy playback overrides as Custom global."""
        if "source_profiles" in saved:
            return
        old_video = saved.get("video") if isinstance(saved.get("video"), dict) else {}
        old_stream = saved.get("streaming") if isinstance(saved.get("streaming"), dict) else {}
        changed = any((
            old_video.get("max_height", DEFAULT_SETTINGS["video"]["max_height"]) != DEFAULT_SETTINGS["video"]["max_height"],
            old_stream.get("network_caching", DEFAULT_SETTINGS["streaming"]["network_caching"]) != DEFAULT_SETTINGS["streaming"]["network_caching"],
            old_stream.get("hardware_decode", DEFAULT_SETTINGS["streaming"]["hardware_decode"]) != DEFAULT_SETTINGS["streaming"]["hardware_decode"],
        ))
        if changed:
            global_profile = merged.setdefault("source_profiles", {}).setdefault("global", {})
            global_profile.update({
                "mode": "custom",
                "max_height": old_video.get("max_height", merged["video"]["max_height"]),
                "network_caching_ms": old_stream.get("network_caching", merged["streaming"]["network_caching"]),
                "hardware_decode": old_stream.get("hardware_decode", merged["streaming"]["hardware_decode"]),
            })

    def _save_data(self, data: Dict[str, Any]) -> None:
        """Helper to write dictionary to JSON file."""
        self._ensure_dir()
        with open(self.settings_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def save(self) -> None:
        """Write current in-memory settings to JSON file on disk."""
        try:
            self._save_data(self.settings)
        except OSError:
            # Edge case #38: Disk full / permission error
            pass

    def get(self, *keys, default: Any = None) -> Any:
        """
        Access nested settings by key path.
        e.g., get('video', 'max_height') -> 1080
        """
        current = self.settings
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, *keys_and_value) -> None:
        """
        Assign nested setting value and automatically commit to disk.
        e.g., set('video', 'max_height', 720)
        """
        if len(keys_and_value) < 2:
            raise ValueError("set() requires at least one key and a value.")

        *keys, value = keys_and_value
        d = self.settings
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]

        d[keys[-1]] = value
        self.save()

    def reset_to_defaults(self) -> None:
        """Reset all settings back to default."""
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.save()
