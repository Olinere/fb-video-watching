"""
VLC Player controller module.
Handles libVLC instantiation, media control, event subscriptions, and Tkinter embedding.
Strictly adheres to specs.md §4.2 and Agent.md.
"""

from pathlib import Path
from typing import Callable, Optional, List, Any
import sys
import tkinter as tk

from main.platform_utils import embed_vlc_in_frame
from main.timestamp import parse_timestamp


class VLCPlayerError(Exception):
    """Raised when VLC fails to initialize or execute a command."""
    pass


class VLCPlayer:
    """Controller for VLC Media Player embedded in a Tkinter Frame."""

    def __init__(self, parent_frame: tk.Widget, vlc_args: Optional[List[str]] = None):
        """
        Initialize VLC Instance and MediaPlayer, and embed into parent_frame.

        Args:
            parent_frame: Tkinter widget container for rendering video.
            vlc_args: List of command-line arguments for libVLC (built via AutoTuner).
        """
        self.parent_frame = parent_frame
        self._vlc_args = vlc_args or ["--quiet", "--no-video-title-show"]

        try:
            import vlc
            self._vlc_module = vlc
        except ImportError as exc:
            raise VLCPlayerError(
                "Không tìm thấy thư viện python-vlc. Vui lòng cài đặt qua requirements.txt."
            ) from exc

        try:
            self.instance = self._vlc_module.Instance(self._vlc_args)
            self.player = self.instance.media_player_new()
        except Exception as exc:
            raise VLCPlayerError(f"Không thể khởi tạo libVLC: {exc}") from exc

        # Attach hardware/native window handle
        self.parent_frame.update_idletasks()
        embed_vlc_in_frame(self.player, self.parent_frame)
        self._embedded_handle: Optional[int] = self.parent_frame.winfo_id()

        # Allow Tkinter to receive mouse clicks (e.g. right-click context menu / PiP)
        try:
            self.player.video_set_mouse_input(False)
            self.player.video_set_key_input(False)
        except Exception:
            pass

        # Internal state
        self._current_media = None
        self._is_muted = False
        self._last_volume = 80
        self._current_url: Optional[str] = None
        self._current_audio_url: Optional[str] = None
        self._current_subtitle_file: Optional[str] = None
        self._current_http_headers: Optional[dict] = None
        self._stats_obj = None

        # Callbacks
        self._time_changed_callback: Optional[Callable[[int], None]] = None
        self._end_reached_callback: Optional[Callable[[], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None

        # Attach libVLC event manager
        self._attach_events()

    def _attach_events(self) -> None:
        """Register listeners with libVLC EventManager."""
        vlc = self._vlc_module
        event_mgr = self.player.event_manager()

        event_mgr.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_end_reached)
        event_mgr.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error)

    # --- Event Handlers (VLC Thread) ---

    def _on_vlc_end_reached(self, event) -> None:
        try:
            if self._end_reached_callback:
                self._end_reached_callback()
        except Exception:
            pass

    def _on_vlc_error(self, event) -> None:
        try:
            if self._error_callback:
                self._error_callback("Lỗi phát video từ libVLC (stream có thể đã hết hạn).")
        except Exception:
            pass

    # --- Public Callback Registrations ---

    def on_time_changed(self, callback: Callable[[int], None]) -> None:
        """Register callback invoked when playback position changes (ms)."""
        self._time_changed_callback = callback

    def on_end_reached(self, callback: Callable[[], None]) -> None:
        """Register callback invoked when video playback reaches the end."""
        self._end_reached_callback = callback

    def on_error(self, callback: Callable[[str], None]) -> None:
        """Register callback invoked when VLC encounters a playback error."""
        self._error_callback = callback

    # --- Playback Controls ---

    def play(
        self,
        stream_url: Optional[str] = None,
        audio_url: Optional[str] = None,
        subtitle_file: Optional[str] = None,
        http_headers: Optional[dict] = None,
        network_caching_ms: Optional[int] = None,
    ) -> None:
        """
        Start playback. If stream_url is provided, load and play it.
        If audio_url is provided (e.g. Facebook DASH separate stream), attach it as audio slave track.
        If subtitle_file is provided, attach it as subtitle slave track.
        If http_headers is provided (e.g. Referer, User-Agent), configure media options.
        If network_caching_ms is provided, configure per-stream network cache.
        Otherwise resumes current media.
        """
        if subtitle_file is not None:
            self._current_subtitle_file = subtitle_file

        if stream_url:
            self._current_url = stream_url
            self._current_audio_url = audio_url
            if http_headers is not None:
                self._current_http_headers = http_headers

            # Stop existing playback before swapping media to cleanly reset decoders
            try:
                self.player.stop()
            except Exception:
                pass

            if self._current_media:
                try:
                    self._current_media.release()
                except Exception:
                    pass
                self._current_media = None

            self._current_media = self.instance.media_new(stream_url)

            if network_caching_ms is not None and int(network_caching_ms) > 0:
                self._current_media.add_option(f":network-caching={int(network_caching_ms)}")

            # Apply custom HTTP headers (Referer, User-Agent, Cookie) if required by CDN (e.g. Pornhub, Bilibili)
            active_headers = http_headers or self._current_http_headers
            if active_headers:
                referer = active_headers.get("Referer") or active_headers.get("referer")
                if referer:
                    self._current_media.add_option(f":http-referrer={referer}")
                ua = active_headers.get("User-Agent") or active_headers.get("user-agent")
                if ua:
                    self._current_media.add_option(f":http-user-agent={ua}")
                cookie = active_headers.get("Cookie") or active_headers.get("cookie")
                if cookie:
                    self._current_media.add_option(f":http-cookie={cookie}")

            self.player.set_media(self._current_media)

            # Synchronize separate audio track if present (§7.1)
            if audio_url:
                vlc = self._vlc_module
                self.player.add_slave(vlc.MediaSlaveType.audio, audio_url, True)

            # Attach external subtitle track if present
            if self._current_subtitle_file and Path(self._current_subtitle_file).is_file():
                vlc = self._vlc_module
                try:
                    resolved_sub = str(Path(self._current_subtitle_file).resolve())
                    self.player.add_slave(vlc.MediaSlaveType.subtitle, resolved_sub, True)
                except Exception:
                    pass

        # Refresh embedding handle if changed (e.g. undocking/docking PiP)
        handle = self.parent_frame.winfo_id()
        if self._embedded_handle != handle:
            self.parent_frame.update_idletasks()
            embed_vlc_in_frame(self.player, self.parent_frame)
            self._embedded_handle = handle

        vlc = self._vlc_module
        if not stream_url and self.player.get_state() == vlc.State.Ended:
            self.player.stop()

        self.player.play()

        # Re-apply subtitle after playback begins if attached
        if self._current_subtitle_file and Path(self._current_subtitle_file).is_file():
            try:
                resolved_sub = str(Path(self._current_subtitle_file).resolve())
                self.player.video_set_subtitle_file(resolved_sub)
            except Exception:
                pass

    def set_subtitle_file(self, subtitle_path: Optional[str]) -> bool:
        """
        Dynamically load or change the active subtitle file on the fly.
        Returns True if successfully set or cleared, False if file not found.
        """
        if not subtitle_path:
            self.clear_subtitle()
            return True

        sub_p = Path(subtitle_path).resolve()
        if not sub_p.is_file():
            return False

        self._current_subtitle_file = str(sub_p)
        vlc = self._vlc_module
        try:
            self.player.add_slave(vlc.MediaSlaveType.subtitle, self._current_subtitle_file, True)
        except Exception:
            pass
        try:
            self.player.video_set_subtitle_file(self._current_subtitle_file)
        except Exception:
            pass
        return True

    def clear_subtitle(self) -> None:
        """Clear the active subtitle track."""
        self._current_subtitle_file = None
        try:
            self.player.video_set_spu(-1)
        except Exception:
            pass

    def get_subtitle_file(self) -> Optional[str]:
        """Return the current active subtitle file path."""
        return self._current_subtitle_file

    def is_playing(self) -> bool:
        """Return True if media is actively playing."""
        return self.state == "playing"

    def get_time(self) -> int:
        """Return current playback position in milliseconds."""
        return self.get_position()

    def set_time(self, time_ms: int) -> None:
        """Seek to specified time in milliseconds."""
        self.seek_to(time_ms)

    def reinit_instance(self, vlc_args: List[str]) -> None:
        """
        Reinitialize VLC instance with new arguments (e.g. updated subtitle styling or network caching).
        If video is actively playing, resumes playback from current position with the new configuration.
        """
        was_playing = self.is_playing()
        cur_time = self.get_position() if was_playing else 0
        cur_url = self._current_url
        cur_audio = self._current_audio_url
        cur_sub = self._current_subtitle_file
        cur_headers = self._current_http_headers

        self.stop()
        try:
            self.player.release()
        except Exception:
            pass
        try:
            self.instance.release()
        except Exception:
            pass

        self._vlc_args = vlc_args
        self.instance = self._vlc_module.Instance(self._vlc_args)
        self.player = self.instance.media_player_new()

        self.parent_frame.update_idletasks()
        embed_vlc_in_frame(self.player, self.parent_frame)
        self._attach_events()

        try:
            self.player.video_set_mouse_input(False)
            self.player.video_set_key_input(False)
        except Exception:
            pass

        if was_playing and cur_url:
            self.play(cur_url, audio_url=cur_audio, subtitle_file=cur_sub, http_headers=cur_headers)
            if cur_time > 0:
                self.parent_frame.after(600, lambda: self.seek_to(cur_time))

    def pause(self) -> None:
        """Pause playback."""
        try:
            self.player.set_pause(1)
        except Exception:
            self.player.pause()

    def stop(self, clear_source: bool = False) -> None:
        """Stop playback and release media buffers.

        ``clear_source`` is used when switching queue items.  It deliberately
        remains false for the Ended->Replay control path, which needs the
        current source URL for ``play()`` without resolving it again.
        """
        try:
            self.player.stop()
            try:
                self.player.set_media(None)
            except Exception:
                pass
            if self._current_media:
                try:
                    self._current_media.release()
                except Exception:
                    pass
                self._current_media = None
            if clear_source:
                self._current_url = None
                self._current_audio_url = None
                self._current_http_headers = None
        except Exception:
            pass

    def toggle_play_pause(self) -> None:
        """Toggle between playing and paused states. Replays if video has ended."""
        vlc = self._vlc_module
        raw_state = self.player.get_state()
        if raw_state == vlc.State.Ended:
            self.player.stop()
            self.player.play()
        elif raw_state == vlc.State.Playing:
            self.pause()
        else:
            try:
                self.player.set_pause(0)
            except Exception:
                self.player.play()

    # --- Seeking & Timestamp Management ---

    def seek_to(self, time_ms: int) -> None:
        """
        Seek to an absolute timestamp in milliseconds.
        Uses player.set_time(ms) for accurate seeking.
        If video reached Ended state, cleanly resets playback and seeks to time_ms.
        """
        if time_ms < 0:
            time_ms = 0
        duration = self.get_duration()
        if duration > 0 and time_ms > duration:
            time_ms = max(0, duration - 1000)

        vlc = self._vlc_module
        if self.player.get_state() == vlc.State.Ended:
            self.player.stop()
            self.player.play()
            self.player.set_time(int(time_ms))
        else:
            self.player.set_time(int(time_ms))

    def seek_to_timestamp(self, timestamp: str) -> None:
        """
        Seek using a timestamp string (e.g., '1:30', '01:15:30', '90s', '1h20m').

        Raises:
            ValueError: If timestamp string is invalid.
        """
        time_ms = parse_timestamp(timestamp)
        self.seek_to(time_ms)

    def seek_relative(self, delta_seconds: int) -> None:
        """
        Seek relative to current position.
        e.g., seek_relative(-10) steps back 10 seconds.
        """
        vlc = self._vlc_module
        current_ms = self.get_position()
        if self.player.get_state() == vlc.State.Ended:
            dur = self.get_duration()
            if dur > 0:
                current_ms = dur
        target_ms = current_ms + (delta_seconds * 1000)
        self.seek_to(target_ms)

    def get_position(self) -> int:
        """Returns current playback position in milliseconds."""
        pos = self.player.get_time()
        return max(0, pos) if pos is not None else 0

    def get_duration(self) -> int:
        """Returns total media duration in milliseconds."""
        dur = self.player.get_length()
        return max(0, dur) if dur is not None else 0

    def get_media_stats(self) -> Optional[Any]:
        """
        Return current media playback statistics (displayed_pictures, lost_pictures, etc.)
        via libvlc_media_get_stats. Reuses cached MediaStats struct for zero-allocation performance.
        Returns None if stats are unavailable.
        """
        if not self._current_media or not self._vlc_module:
            return None
        try:
            if self._stats_obj is None:
                self._stats_obj = self._vlc_module.MediaStats()
            if self._current_media.get_stats(self._stats_obj):
                return self._stats_obj
        except Exception:
            pass
        return None

    def resync_video(self) -> bool:
        """
        Resynchronize video pipeline with audio clock when video frames are falling behind
        or dropping continuously. Flushes decoder queue and forces keyframe alignment.
        """
        if not self.player or not self.is_playing():
            return False
        try:
            cur_time = self.get_position()
            if cur_time > 0:
                self.player.set_time(int(cur_time))
                return True
        except Exception:
            pass
        return False

    # --- Volume Controls ---

    def set_volume(self, volume: int) -> None:
        """
        Set audio volume (0-150). Values >100 provide software amplification.
        """
        clamped = max(0, min(150, int(volume)))
        self._last_volume = clamped
        self._is_muted = (clamped == 0)
        self.player.audio_set_volume(clamped)

    def get_volume(self) -> int:
        """Returns current audio volume (0-150)."""
        vol = self.player.audio_get_volume()
        return vol if vol >= 0 else self._last_volume

    def toggle_mute(self) -> bool:
        """Toggle audio mute state. Returns True if now muted."""
        if self._is_muted:
            self.set_volume(self._last_volume if self._last_volume > 0 else 80)
            self._is_muted = False
        else:
            self._last_volume = self.get_volume()
            self.player.audio_set_volume(0)
            self._is_muted = True
        return self._is_muted

    def set_mute(self, muted: bool) -> None:
        """Explicitly set mute state."""
        if muted and not self._is_muted:
            self._last_volume = self.get_volume()
            self.player.audio_set_volume(0)
            self._is_muted = True
        elif not muted and self._is_muted:
            self.set_volume(self._last_volume if self._last_volume > 0 else 80)
            self._is_muted = False

    def is_muted(self) -> bool:
        """Returns True if audio is muted."""
        return self._is_muted

    # --- Playback Rate & Display ---

    def set_playback_rate(self, rate: float) -> None:
        """Set playback rate (e.g. 0.25, 0.5, 1.0, 1.5, 2.0)."""
        if rate > 0:
            self.player.set_rate(float(rate))

    def get_playback_rate(self) -> float:
        """Get current playback rate."""
        rate = self.player.get_rate()
        return rate if rate > 0 else 1.0

    def set_fullscreen(self, enabled: bool) -> None:
        """Set fullscreen mode on player."""
        self.player.set_fullscreen(enabled)

    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode on player."""
        curr = self.player.get_fullscreen()
        self.player.set_fullscreen(not curr)

    # --- Playback State ---

    @property
    def current_url(self) -> Optional[str]:
        """Returns the current media URL being played."""
        return self._current_url

    def is_proxy_active(self) -> bool:
        """Returns True if player is currently playing, paused, or buffering a local stream proxy."""
        if not self._current_url or not self._current_url.startswith("http://127.0.0.1:"):
            return False
        return self.state in ("playing", "paused", "buffering")

    @property
    def state(self) -> str:
        """
        Returns normalized state:
        'playing' | 'paused' | 'stopped' | 'buffering' | 'error'
        """
        vlc = self._vlc_module
        vlc_state = self.player.get_state()

        if vlc_state == vlc.State.Playing:
            return "playing"
        elif vlc_state == vlc.State.Paused:
            return "paused"
        elif vlc_state in (vlc.State.Opening, vlc.State.Buffering):
            return "buffering"
        elif vlc_state == vlc.State.Error:
            return "error"
        elif vlc_state in (vlc.State.Stopped, vlc.State.Ended, vlc.State.NothingSpecial):
            return "stopped"
        return "stopped"

    # --- Memory Leak Prevention & Lifecycle ---

    def release(self) -> None:
        """
        Completely release libVLC MediaPlayer and Instance.
        Crucial when switching streams or closing application to avoid memory leaks.
        """
        try:
            self.player.stop()
            try:
                self.player.set_media(None)
            except Exception:
                pass
            if self._current_media:
                self._current_media.release()
                self._current_media = None
            self.player.release()
            self.instance.release()
            self._current_url = None
            self._current_audio_url = None
            self._current_http_headers = None
        except Exception:
            pass
