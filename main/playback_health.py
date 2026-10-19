"""Low-cost playback health state machine; no network polling."""

from dataclasses import dataclass
from time import monotonic
from typing import Optional
from main.constants import HEALTH_DEGRADED_AFTER_MS, HEALTH_CRITICAL_AFTER_MS


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    state: str = "healthy"
    buffering_ms: int = 0
    buffering_events: int = 0
    error_count: int = 0
    video_frozen: bool = False


class PlaybackHealthMonitor:
    """Consume existing VLC/UI ticks instead of creating a background loop."""

    def __init__(self, degraded_after_ms: int = HEALTH_DEGRADED_AFTER_MS, critical_after_ms: int = HEALTH_CRITICAL_AFTER_MS):
        self.degraded_after_ms = max(1000, int(degraded_after_ms))
        self.critical_after_ms = max(self.degraded_after_ms, int(critical_after_ms))
        self._buffer_started: Optional[float] = None
        self._healthy_play_started: Optional[float] = None
        self._buffering_ms = 0
        self._buffering_events = 0
        self._error_count = 0
        self._state = "healthy"
        self._video_frozen = False

        # Video presentation / A-V sync tracking
        self._last_displayed_pictures: Optional[int] = None
        self._last_lost_pictures: Optional[int] = None
        self._last_video_advance_time: Optional[float] = None
        self._last_audio_pos_ms: Optional[int] = None
        self._audio_advancing_since: Optional[float] = None

    def reset(self) -> None:
        """Reset health state for a newly loaded video."""
        self._buffer_started = None
        self._healthy_play_started = None
        self._buffering_ms = 0
        self._buffering_events = 0
        self._error_count = 0
        self._state = "healthy"
        self._video_frozen = False
        self._last_displayed_pictures = None
        self._last_lost_pictures = None
        self._last_video_advance_time = None
        self._last_audio_pos_ms = None
        self._audio_advancing_since = None

    def reset_video_sync(self, now: Optional[float] = None) -> None:
        """Clear video frozen state and give the newly synced stream time to present frames."""
        now = monotonic() if now is None else now
        self._video_frozen = False
        self._last_video_advance_time = now
        self._audio_advancing_since = None

    def tick(
        self,
        player_state: str,
        now: Optional[float] = None,
        current_time_ms: int = 0,
        displayed_pictures: Optional[int] = None,
        lost_pictures: Optional[int] = None,
    ) -> HealthSnapshot:
        now = monotonic() if now is None else now
        if player_state == "buffering":
            self._healthy_play_started = None
            if self._buffer_started is None:
                self._buffer_started = now
                self._buffering_events += 1
            self._buffering_ms = int((now - self._buffer_started) * 1000)
            self._video_frozen = False
            self._audio_advancing_since = None
        else:
            if self._buffer_started is not None:
                self._buffering_ms = int((now - self._buffer_started) * 1000)
                self._buffer_started = None
            if player_state == "playing":
                if self._healthy_play_started is None:
                    self._healthy_play_started = now
                else:
                    smooth_sec = now - self._healthy_play_started
                    if smooth_sec >= 20.0:
                        self._buffering_ms = 0
                    elif smooth_sec >= 10.0:
                        self._buffering_ms = min(self._buffering_ms, self.degraded_after_ms)

                # A/V Sync & Video presentation check
                is_num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
                if is_num(displayed_pictures) and is_num(current_time_ms) and current_time_ms > 0:
                    valid_lost = lost_pictures if is_num(lost_pictures) else 0
                    # Check audio forward progress
                    if self._last_audio_pos_ms is None:
                        self._audio_advancing_since = now
                    elif current_time_ms > self._last_audio_pos_ms + 100:
                        if self._audio_advancing_since is None:
                            self._audio_advancing_since = now
                    elif current_time_ms <= self._last_audio_pos_ms:
                        self._audio_advancing_since = None
                    self._last_audio_pos_ms = current_time_ms

                    # Check video displayed frames
                    if self._last_displayed_pictures is None:
                        self._last_displayed_pictures = displayed_pictures
                        self._last_lost_pictures = valid_lost
                        self._last_video_advance_time = now
                        self._video_frozen = False
                    elif displayed_pictures > self._last_displayed_pictures:
                        self._last_displayed_pictures = displayed_pictures
                        self._last_lost_pictures = valid_lost
                        self._last_video_advance_time = now
                        self._video_frozen = False
                    else:
                        # displayed_pictures has NOT increased while playing
                        lost_delta = (valid_lost - (self._last_lost_pictures or 0))
                        stuck_sec = (now - self._last_video_advance_time) if self._last_video_advance_time is not None else 0.0
                        audio_sec = (now - self._audio_advancing_since) if self._audio_advancing_since is not None else 0.0

                        # Video is frozen if audio has advanced for >= 2.5s while 0 video frames were displayed
                        # (or if lost frames jumped by >= 25 frames due to drop-late-frames)
                        if audio_sec >= 2.5 and (stuck_sec >= 2.5 or lost_delta >= 25):
                            self._video_frozen = True
            else:
                self._healthy_play_started = None
                self._video_frozen = False
                self._audio_advancing_since = None

        if self._buffering_ms >= self.critical_after_ms:
            self._state = "critical"
        elif self._buffering_ms >= self.degraded_after_ms:
            self._state = "degraded"
        else:
            self._state = "healthy"
        return self.snapshot()

    def record_error(self) -> HealthSnapshot:
        self._error_count += 1
        return self.snapshot()

    def snapshot(self) -> HealthSnapshot:
        return HealthSnapshot(
            self._state,
            self._buffering_ms,
            self._buffering_events,
            self._error_count,
            self._video_frozen,
        )

