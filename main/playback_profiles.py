"""Source playback profile resolution without mutating user settings."""

from dataclasses import dataclass, replace
import urllib.parse
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PlaybackProfile:
    mode: str = "auto"
    max_height: int = 1080
    network_caching_ms: int = 3000
    hardware_decode: bool = True


def source_domain(source_url: str) -> str:
    try:
        host = urllib.parse.urlparse(source_url).netloc.lower().split(":", 1)[0]
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return "global"


def _profile(raw: Mapping[str, Any], fallback: PlaybackProfile) -> PlaybackProfile:
    mode = raw.get("mode", fallback.mode)
    if mode not in {"auto", "custom"}:
        mode = fallback.mode
    try:
        max_height = int(raw.get("max_height", fallback.max_height))
    except (TypeError, ValueError):
        max_height = fallback.max_height
    try:
        cache = max(500, min(30_000, int(raw.get("network_caching_ms", fallback.network_caching_ms))))
    except (TypeError, ValueError):
        cache = fallback.network_caching_ms
    return replace(
        fallback,
        mode=mode,
        max_height=max_height if max_height in {0, 360, 480, 720, 1080} else fallback.max_height,
        network_caching_ms=cache,
        hardware_decode=bool(raw.get("hardware_decode", fallback.hardware_decode)),
    )


def resolve_profile(settings: Mapping[str, Any], source_url: str) -> PlaybackProfile:
    """Merge source profile over global profile over legacy settings."""
    video = settings.get("video", {}) if isinstance(settings, Mapping) else {}
    streaming = settings.get("streaming", {}) if isinstance(settings, Mapping) else {}
    domain = source_domain(source_url)
    default_cache = 6000 if domain in ("t.me", "telegram.org") else 3000
    fallback = PlaybackProfile(
        mode="auto",
        max_height=int(video.get("max_height", 1080)),
        network_caching_ms=int(streaming.get("network_caching", default_cache)),
        hardware_decode=bool(streaming.get("hardware_decode", True)),
    )
    profiles = settings.get("source_profiles", {}) if isinstance(settings, Mapping) else {}
    global_raw = profiles.get("global", {}) if isinstance(profiles, Mapping) else {}
    global_profile = _profile(global_raw, fallback)
    domain_raw = profiles.get(source_domain(source_url), {}) if isinstance(profiles, Mapping) else {}
    return _profile(domain_raw, global_profile) if isinstance(domain_raw, Mapping) else global_profile

