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


class PlaybackHealthMonitor:
    """Consume existing VLC/UI ticks instead of creating a background loop."""

    def __init__(self, degraded_after_ms: int = HEALTH_DEGRADED_AFTER_MS, critical_after_ms: int = HEALTH_CRITICAL_AFTER_MS):
        self.degraded_after_ms = max(1000, int(degraded_after_ms))
        self.critical_after_ms = max(self.degraded_after_ms, int(critical_after_ms))
        self._buffer_started: Optional[float] = None
        self._buffering_ms = 0
        self._buffering_events = 0
        self._error_count = 0
        self._state = "healthy"

    def tick(self, player_state: str, now: Optional[float] = None) -> HealthSnapshot:
        now = monotonic() if now is None else now
        if player_state == "buffering":
            if self._buffer_started is None:
                self._buffer_started = now
                self._buffering_events += 1
            self._buffering_ms = int((now - self._buffer_started) * 1000)
        elif self._buffer_started is not None:
            self._buffering_ms += int((now - self._buffer_started) * 1000)
            self._buffer_started = None
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
        return HealthSnapshot(self._state, self._buffering_ms, self._buffering_events, self._error_count)
