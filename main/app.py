"""
Application Orchestrator module.
Coordinates GUI, VLC Player, URL Resolver, ThreadPoolExecutor, History, and AutoTuner.
Strictly implements §7.6 (Re-resolve Strategy) and §9 (Threading & Anti-freeze).
Guarantees long-term stability: no freezes, no RAM leaks, no SQLite thread blocks, and auto stream recovery.
"""

import concurrent.futures
import gc
import logging
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, filedialog
from typing import Optional, Callable, Dict, Any, Tuple

from main.constants import (
    UI_UPDATE_INTERVAL_MS,
    UI_IDLE_INTERVAL_MS,
    CLIPBOARD_POLL_INTERVAL_MS,
    HEALTH_SUGGESTION_COOLDOWN_SECONDS,
    MAX_QUEUE_ITEMS,
)
from main.settings import SettingsManager
from main.theme import ThemeManager
from main.history import HistoryManager
from main.system_info import SystemInfo
from main.auto_tune import AutoTuner
from main.url_resolver import (
    resolve_facebook_url,
    resolve_collection,
    ResolverError,
    AuthRequiredError,
    is_potential_video_url,
    is_collection_url,
)
from main.vlc_player import VLCPlayer, VLCPlayerError
from main.gui import MainWindow
from main.timestamp import format_timestamp
from main.playback_queue import PlaybackQueue, QueueItem
from main.queue_controller import QueueController
from main.queue_persistence import QueuePersistence
from main.privacy_session import RuntimePersistencePolicy
from main.playback_profiles import resolve_profile, source_domain
from main.playback_health import PlaybackHealthMonitor

logger = logging.getLogger("FBVideoWatcher")


class Application:
    """Core application orchestrator connecting UI, threading, resolver, and VLC engine."""

    def __init__(
        self,
        root: tk.Tk,
        settings_mgr: Optional[SettingsManager] = None,
        history_mgr: Optional[HistoryManager] = None,
        privacy_enabled: bool = False,
    ):
        self.root = root
        self._is_shutting_down = False
        self._queue_transition = False
        self._pending_queue_item: Optional[QueueItem] = None
        self.persistence_policy = RuntimePersistencePolicy(bool(privacy_enabled))

        # 1. Initialize Settings, Theme, and History managers
        self.settings = settings_mgr or SettingsManager()
        initial_theme = self.settings.get("ui", "theme", default="system")
        self.theme = ThemeManager(self.root, initial_theme=initial_theme)
        self.history = history_mgr or HistoryManager()
        self.queue = PlaybackQueue(
            max_items=MAX_QUEUE_ITEMS,
            loop_enabled=self.settings.get("playback", "queue_loop_enabled", default=False),
        )
        self.queue_controller = QueueController(
            self.queue,
            skip_failed_items=self.settings.get("playback", "skip_failed_items", default=False),
        )
        self.queue_persistence = QueuePersistence(
            self.settings.config_dir / "queue.json",
            policy=self.persistence_policy,
        )
        if self.settings.get("playback", "queue_persist", default=True):
            loaded_count = self.queue_persistence.load(self.queue)
            if loaded_count > 0:
                logger.info(f"Đã khôi phục {loaded_count} mục trong hàng đợi phát.")
        self._active_queue_item: Optional[QueueItem] = None
        self.health_monitor = PlaybackHealthMonitor()
        self._last_health_suggestion_time = 0.0
        self._last_health_suggestion_url = ""

        # Auto-register fbvw:// protocol if enabled in settings
        if sys.platform == "win32" and self.settings.get("ui", "register_fbvw_protocol", default=True):
            try:
                from main.platform_utils import ensure_fbvw_protocol_registered
                ensure_fbvw_protocol_registered()
            except Exception as ex:
                logger.debug(f"Không thể tự động đăng ký protocol fbvw: {ex}")

        # 2. Network Manager (Proxy & In-App DoH DNS)
        from main.network import NetworkManager
        self.network_manager = NetworkManager.get_instance(self.settings.settings)

        # 3. Detect System Info & Auto-tune VLC arguments
        self.sys_info = SystemInfo.detect()
        self.tuner = AutoTuner(self.sys_info, self.settings.settings)
        self.vlc_args = self.tuner.build_vlc_args()

        if self.sys_info.is_hybrid_cpu:
            cpu_desc = f"{self.sys_info.cpu_name} ({self.sys_info.cpu_cores_physical}C: {self.sys_info.cpu_p_cores}P + {self.sys_info.cpu_e_cores}E / {self.sys_info.cpu_cores_logical}T)"
        else:
            cpu_desc = f"{self.sys_info.cpu_name} ({self.sys_info.cpu_cores_logical}T)"

        logger.info(
            f"Phần cứng: CPU={cpu_desc}, "
            f"RAM={self.sys_info.ram_total_gb:.1f}GB, GPU={self.sys_info.gpu_name}"
        )
        logger.info(f"Tham số VLC: {' '.join(self.vlc_args)}")
        self._apply_cpu_optimizations()

        # 3. Dedicated Background Worker Thread Pool (§9.2 D)
        pool_size = self.tuner.recommend_thread_pool_size()
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=pool_size,
            thread_name_prefix="fbw-worker",
        )

        # 4. State tracking for Stream Re-resolution & Stability (§7.6)
        self._original_url: Optional[str] = None
        self._current_stream_url: Optional[str] = None
        self._re_resolve_attempts = 0
        self._max_re_resolve_attempts = 3
        self._active_future: Optional[concurrent.futures.Future] = None
        self._consecutive_healthy_play_ticks = 0

        # Autosave throttling
        self._last_saved_position_ms = 0
        self._last_saved_time = 0.0

        # Loop & A-B repeat states
        self._is_loop_enabled: bool = self.settings.get("playback", "loop_enabled", default=False)
        self._ab_point_a: Optional[int] = None
        self._ab_point_b: Optional[int] = None
        self._resolved_duration_ms: int = 0

        # 5. Initialize GUI Window
        self.gui = MainWindow(
            root=self.root,
            settings_mgr=self.settings,
            theme_mgr=self.theme,
            on_play_request=self.handle_play_request,
            on_pause_toggle=self.handle_pause_toggle,
            on_seek_request=self.handle_seek_request,
            on_seek_relative=self.handle_seek_relative,
            on_volume_change=self.handle_volume_change,
            on_mute_toggle=self.handle_mute_toggle,
            on_rate_change=self.handle_rate_change,
            on_settings_saved=self.handle_settings_updated,
            on_history_request=self.handle_open_history,
            on_download_request=self.handle_download_request,
            on_loop_toggle=self.handle_loop_toggle,
            on_ab_repeat_toggle=self.handle_ab_repeat_toggle,
            on_subtitle_load=self.handle_load_subtitle,
            on_update_request=self._start_update_download,
            on_add_to_queue=self.handle_add_to_queue,
            on_play_queue_item=self.handle_play_queue_item,
            on_remove_queue_item=self.handle_remove_queue_item,
            on_move_queue_item=self.handle_move_queue_item,
            on_clear_queue=self.handle_clear_queue,
            on_clear_played_queue=self.handle_clear_played_queue,
            on_retry_queue_item=self.handle_retry_queue_item,
            on_next_track=self.handle_next_track,
            on_previous_track=self.handle_previous_track,
            on_chapter_seek=self.handle_seek_request,
            on_privacy_toggle=self.handle_privacy_toggle,
            on_bulk_import_queue=self.handle_bulk_add_to_queue,
            on_bulk_replace_and_play=self.handle_bulk_replace_and_play,
            on_queue_persist_toggle=self.handle_queue_persist_toggle,
        )
        self.gui.set_privacy_state(self.persistence_policy.is_enabled())
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self.gui.set_loop_state(self._is_loop_enabled)
        # Gán callback dọn bộ nhớ để gui.py dùng khi đóng SettingsDialog
        self.gui._trim_memory_if_possible = self._trim_memory_if_possible

        # 6. Initialize VLC Player embedded in video container
        try:
            self.player = VLCPlayer(self.gui.video_container, vlc_args=self.vlc_args)
            self.player.on_end_reached(self._on_playback_ended)
            self.player.on_error(self._on_playback_error)

            # Apply persistent audio volume and mute state
            init_vol = self.settings.get("audio", "default_volume", default=80)
            init_muted = self.settings.get("audio", "is_muted", default=False)
            self.player.set_volume(init_vol)
            if init_muted:
                self.player.set_mute(True)
            self.gui.volume_scale.set(init_vol)
            self.gui.set_mute_button_state(init_muted)

            # Register stream proxy in-use predicate to protect active/paused proxy streams
            try:
                from main.stream_proxy import StreamProxyServer
                StreamProxyServer.get_instance().set_in_use_predicate(
                    lambda: bool(self.player and self.player.is_proxy_active())
                )
            except Exception:
                pass
        except VLCPlayerError as exc:
            messagebox.showerror(
                "Lỗi VLC Media Player",
                f"Không thể khởi chạy VLC engine: {exc}\n"
                "Vui lòng đảm bảo đã cài đặt phần mềm VLC Media Player (64-bit).",
            )
            self.player = None

        # 7. Register Clean Shutdown protocol (§9.2 E)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 8. Start periodic UI refresh timer (§9.2 C)
        self._start_ui_timer()

        # 9. Start periodic maintenance (GC & WAL checkpoint)
        self._start_maintenance_timer()

        # 10. Restore last played URL into URL entry box (§Feature 1)
        last_url = self.settings.get("playback", "last_url", default="")
        if not last_url and self.persistence_policy.allow_content_state_write():
            recent = self.history.get_history(limit=1)
            if recent:
                last_url = recent[0].get("url", "")

        if last_url:
            self.gui.url_entry.delete(0, tk.END)
            self.gui.url_entry.insert(0, last_url)
            self.gui.overlay_label.configure(
                text="Nhấn 'Phát' để tiếp tục xem video gần nhất"
            )

        # 11. Clipboard auto-detection
        self._last_detected_clipboard = ""
        self._active_downloader = None
        self.root.bind("<FocusIn>", self._on_window_focus_in, add="+")
        self._start_clipboard_timer()

        # 12. Check if restarting from an update with saved playback state
        from main.updater import load_and_clear_resume_state
        self._update_resume_state = load_and_clear_resume_state()
        if self._update_resume_state and self._update_resume_state.get("url"):
            self.root.after(400, self._apply_post_update_resume)

        # 13. Background check for updates (non-blocking)
        self.root.after(4000, lambda: threading.Thread(target=self._background_check_update, daemon=True).start())

        # 14. Dọn sạch tàn dư file cũ từ lần cập nhật trước (background thread - không ảnh hưởng startup)
        threading.Thread(target=self._cleanup_on_startup, daemon=True).start()

        self._ui_timer_id = None
        self._maint_timer_id = None
        self._clip_timer_id = None
        self._seek_cleanup_timer_id = None

        def _on_root_destroyed(event=None):
            if event is not None and getattr(event, "widget", None) != self.root:
                return
            self._is_shutting_down = True
            for tid_name in ("_ui_timer_id", "_maint_timer_id", "_clip_timer_id", "_seek_cleanup_timer_id"):
                tid = getattr(self, tid_name, None)
                if tid is not None:
                    try:
                        self.root.after_cancel(tid)
                    except Exception:
                        pass
                    setattr(self, tid_name, None)
            if hasattr(self.gui, "destroy"):
                try:
                    self.gui.destroy()
                except Exception:
                    pass

        try:
            self.root.bind("<Destroy>", _on_root_destroyed, add="+")
        except Exception:
            pass

    # --- Periodic UI Refresh Timer (250ms interval) ---

    def _start_ui_timer(self) -> None:
        """Schedule UI updates via root.after() instead of while-loop."""
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        """Periodic tick running on main thread to synchronize UI with VLC engine."""
        if self._is_shutting_down:
            return
        if not hasattr(self.root, "winfo_exists"):
            return
        try:
            if not self.root.winfo_exists():
                self._is_shutting_down = True
                return
        except Exception:
            self._is_shutting_down = True
            return

        if self.player:
            raw_pos = self.player.get_position()
            raw_dur = self.player.get_duration()
            current_ms = int(raw_pos) if isinstance(raw_pos, (int, float)) else 0
            duration_ms = int(raw_dur) if isinstance(raw_dur, (int, float)) else 0
            if duration_ms <= 0 and getattr(self, "_resolved_duration_ms", 0) > 0:
                duration_ms = self._resolved_duration_ms
            try:
                self.gui.update_playback_time(current_ms, duration_ms)
                if hasattr(self.gui, "update_chapter_position"):
                    self.gui.update_chapter_position(current_ms)
            except Exception:
                pass

            state = self.player.state
            health = self.health_monitor.tick(state)
            self._check_playback_health_degraded(health)
            try:
                self.gui.set_play_pause_button_state(state == "playing")
            except Exception:
                pass

            if state == "playing":
                self._consecutive_healthy_play_ticks += 1
                # If played continuously for >= 30 seconds after reconnect, reset retry counter
                if self._consecutive_healthy_play_ticks >= int(30000 / UI_UPDATE_INTERVAL_MS):
                    self._re_resolve_attempts = 0

                # A-B Repeat loop check: loop back to Point A when Point B is reached
                if self._ab_point_a is not None and self._ab_point_b is not None:
                    if current_ms >= self._ab_point_b or current_ms < max(0, self._ab_point_a - 1500):
                        self.player.seek_to(self._ab_point_a)

                # Throttled async position autosave: at most once every 5 seconds
                now = time.monotonic()
                if (
                    self._original_url
                    and current_ms > 5000
                    and (now - self._last_saved_time >= 5.0)
                    and abs(current_ms - self._last_saved_position_ms) >= 3000
                ):
                    self._last_saved_time = now
                    self._last_saved_position_ms = current_ms
                    # Submit to background executor to completely prevent UI thread disk I/O stalls
                    if self.persistence_policy.allow_resume_write():
                        self.executor.submit(
                            self.history.update_position,
                            self._original_url,
                            current_ms,
                            duration_ms,
                        )
            else:
                self._consecutive_healthy_play_ticks = 0

        # VLC position needs smooth updates only while playing.  Polling at a
        # lower rate while idle avoids waking the main thread unnecessarily
        # when the user is gaming/editing in parallel.
        interval = UI_UPDATE_INTERVAL_MS if self.player and self.player.state == "playing" else UI_IDLE_INTERVAL_MS
        if not self._is_shutting_down:
            try:
                self._ui_timer_id = self.root.after(interval, self._update_ui_state)
            except Exception:
                pass

    # --- Periodic Maintenance (Memory leak & WAL prevention) ---

    def _start_maintenance_timer(self) -> None:
        """Schedule 60-second periodic maintenance for long-term video stability."""
        try:
            self._maint_timer_id = self.root.after(60000, self._periodic_maintenance)
        except Exception:
            pass

    def _periodic_maintenance(self) -> None:
        """Run GC and WAL checkpointing every 60s."""
        if self._is_shutting_down:
            return
        if not hasattr(self.root, "winfo_exists"):
            return
        try:
            if not self.root.winfo_exists():
                self._is_shutting_down = True
                return
        except Exception:
            self._is_shutting_down = True
            return

        # 1. Collect cyclic garbage across all generations in Python heap
        gc.collect()

        # 2. Checkpoint SQLite WAL & trim process working set in background
        self.executor.submit(self.history.checkpoint_wal)
        self.executor.submit(self._post_task_cleanup)

        # Re-arm timer
        if not self._is_shutting_down:
            try:
                self._maint_timer_id = self.root.after(60000, self._periodic_maintenance)
            except Exception:
                pass

    def _start_clipboard_timer(self) -> None:
        """Schedule periodic clipboard check (every 1000ms)."""
        try:
            self._clip_timer_id = self.root.after(CLIPBOARD_POLL_INTERVAL_MS, self._periodic_clipboard_check)
        except Exception:
            pass

    def _periodic_clipboard_check(self) -> None:
        """Periodic tick checking clipboard for copied video links."""
        if self._is_shutting_down:
            return
        if not hasattr(self.root, "winfo_exists"):
            return
        try:
            if not self.root.winfo_exists():
                self._is_shutting_down = True
                return
        except Exception:
            self._is_shutting_down = True
            return

        self._check_clipboard()
        if not self._is_shutting_down:
            try:
                self._clip_timer_id = self.root.after(CLIPBOARD_POLL_INTERVAL_MS, self._periodic_clipboard_check)
            except Exception:
                pass


    # --- Playback & Action Handlers ---

    def handle_play_request(self, url: str) -> None:
        """Handle URL play request from user (resolves via background thread)."""
        if not self.player:
            messagebox.showwarning("VLC chưa sẵn sàng", "VLC engine chưa khởi động được.")
            return

        # Playlist/album listing is a separate, bounded metadata job.  It
        # never enters the direct-stream resolver and therefore cannot create
        # a CDN URL per playlist item.
        if not self._queue_transition and is_collection_url(url):
            self.gui.set_loading("Đang đọc danh sách playlist...")
            self.gui.set_status("Đang tải metadata playlist (không tải video)...")
            cookie_file = self.settings.get("advanced", "cookie_file", default="")
            future = self.executor.submit(
                resolve_collection,
                url=url,
                cookie_file=cookie_file if cookie_file else None,
            )
            future.add_done_callback(
                lambda f: self.root.after(0, lambda: self._on_collection_completed(f, url))
            )
            return

        # Keep runtime queue intact: activate existing item if in queue,
        # or append if queue has items, or start fresh if queue was empty.
        if self._queue_transition and self._pending_queue_item is not None:
            queue_item = self._pending_queue_item
            self._pending_queue_item = None
        else:
            existing = next((it for it in self.queue.items if it.source_url == url), None)
            if existing is not None:
                queue_item = existing
            elif len(self.queue) > 0:
                try:
                    queue_item = self.queue_controller.add_url(
                        url,
                        title=url,
                        privacy_only=self.persistence_policy.is_enabled(),
                    )
                except (OverflowError, ValueError) as exc:
                    self.gui.show_error(str(exc))
                    return
            else:
                self.queue.clear()
                try:
                    queue_item = self.queue_controller.add_url(
                        url,
                        title=url,
                        privacy_only=self.persistence_policy.is_enabled(),
                    )
                except (OverflowError, ValueError) as exc:
                    self.gui.show_error(str(exc))
                    return
        self._active_queue_item = queue_item
        self.queue_controller.begin(queue_item)
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()

        # Save previous video position before loading new one (§7.2 case #17)
        if self._original_url and self.persistence_policy.allow_resume_write():
            self._save_current_position()

        self._original_url = url
        self._re_resolve_attempts = 0
        self._consecutive_healthy_play_ticks = 0
        self._ab_point_a = None
        self._ab_point_b = None
        if hasattr(self.gui, "set_ab_repeat_state"):
            self.gui.set_ab_repeat_state("OFF")
        if self.persistence_policy.allow_content_state_write():
            self.settings.set("playback", "last_url", url)
            self.settings.save()
        logger.info("Nhận yêu cầu phát nguồn: %s", self.persistence_policy.redact(url))

        # Update GUI to loading state
        self.gui.set_loading("Đang phân giải liên kết video...")
        self.gui.set_status("Đang lấy luồng video qua yt-dlp...")
        if hasattr(self.gui, "set_chapters"):
            self.gui.set_chapters([])
        # Do not retain the previous expiring CDN URL while a new item is
        # resolving.  VLC owns only the active media URL.
        self._current_stream_url = None

        # Cancel any previous in-flight resolve task (§7.2 case #16)
        if self._active_future and not self._active_future.done():
            self._active_future.cancel()

        cookie_file = self.settings.get("advanced", "cookie_file", default="")
        profile = resolve_profile(self.settings.settings, url)
        max_height = profile.max_height

        # Submit resolution task to background thread pool
        future = self.executor.submit(
            resolve_facebook_url,
            url=url,
            cookie_file=cookie_file if cookie_file else None,
            max_height=max_height,
        )
        self._active_future = future
        future.add_done_callback(
            lambda f: self.root.after(0, lambda: self._on_resolve_completed(f, url))
        )

    def _on_collection_completed(self, future: concurrent.futures.Future, source_url: str) -> None:
        """Add bounded collection metadata and lazily resolve only its first item."""
        if self._is_shutting_down:
            return
        try:
            collection = future.result()
        except Exception as exc:
            self.gui.show_error(f"Không thể đọc playlist: {exc}")
            return
        if not collection.entries:
            self.gui.show_error("Playlist không có video phát được.")
            return
        self.queue.clear()
        items = [
            QueueItem(
                source_url=entry.source_url,
                content_id=entry.content_id,
                source_name=entry.source_name,
                title=entry.title,
                thumbnail_url=entry.thumbnail_url,
                duration_ms=entry.duration_ms,
                privacy_only=self.persistence_policy.is_enabled(),
            )
            for entry in collection.entries
        ]
        try:
            self.queue.add_many(items)
        except (OverflowError, ValueError) as exc:
            self.gui.show_error(str(exc))
            return
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._pending_queue_item = items[0]
        self._queue_transition = True
        try:
            self.handle_play_request(items[0].source_url)
        finally:
            self._queue_transition = False

    def _save_queue_if_persisted(self) -> None:
        """Atomically persist queue snapshot if queue_persist is enabled and allowed by policy."""
        if self.settings.get("playback", "queue_persist", default=True):
            try:
                self.queue_persistence.save(self.queue)
            except Exception as exc:
                logger.debug("Không thể lưu queue persistence: %s", exc)

    def handle_queue_persist_toggle(self, enabled: bool) -> None:
        """Handle user toggling queue persistence directly in the Queue UI."""
        self.settings.set("playback", "queue_persist", enabled)
        self.settings.save()
        if enabled:
            self._save_queue_if_persisted()

    def handle_add_to_queue(self, url: str) -> None:
        """Add source metadata only; resolve lazily when it becomes active."""
        cleaned = (url or "").strip()
        if not cleaned:
            return
        if is_collection_url(cleaned):
            cookie_file = self.settings.get("advanced", "cookie_file", default="")
            future = self.executor.submit(
                resolve_collection,
                url=cleaned,
                cookie_file=cookie_file if cookie_file else None,
            )
            future.add_done_callback(
                lambda f: self.root.after(0, lambda: self._on_collection_add_completed(f))
            )
            self.gui.set_status("Đang thêm metadata playlist vào hàng đợi...")
            return
        try:
            item = self.queue_controller.add_url(
                cleaned,
                title=cleaned,
                privacy_only=self.persistence_policy.is_enabled(),
            )
        except (OverflowError, ValueError) as exc:
            self.gui.show_error(str(exc))
            return
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()
        self.gui.set_status(f"Đã thêm vào hàng đợi: {item.title}")

    def _on_collection_add_completed(self, future: concurrent.futures.Future) -> None:
        if self._is_shutting_down:
            return
        try:
            collection = future.result()
            items = [
                QueueItem(
                    source_url=entry.source_url,
                    content_id=entry.content_id,
                    source_name=entry.source_name,
                    title=entry.title,
                    duration_ms=entry.duration_ms,
                    privacy_only=self.persistence_policy.is_enabled(),
                )
                for entry in collection.entries
            ]
            self.queue.add_many(items)
            if hasattr(self.gui, "refresh_queue"):
                self.gui.refresh_queue(self.queue.snapshot())
            self._save_queue_if_persisted()
            self.gui.set_status(f"Đã thêm {len(items)} video metadata vào hàng đợi.")
        except Exception as exc:
            self.gui.show_error(f"Không thể thêm playlist: {exc}")

    def handle_bulk_add_to_queue(self, parsed_items: list) -> None:
        """Add multiple parsed video items to queue without clearing existing items."""
        if not parsed_items:
            return
        items = [
            QueueItem(
                source_url=p.url,
                source_name=p.source_name,
                title=p.description if p.description else p.url,
                description=p.description,
                privacy_only=self.persistence_policy.is_enabled(),
            )
            for p in parsed_items
        ]
        self.queue.add_many(items)
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()
        self.gui.set_status(f"Đã thêm {len(items)} video vào hàng đợi.")
        logger.info("Queue: Đã thêm %d video vào hàng đợi từ bộ bóc tách văn bản.", len(items))

    def handle_bulk_replace_and_play(self, parsed_items: list) -> None:
        """Clear queue, add parsed video items, and begin playing the first item immediately."""
        if not parsed_items:
            return
        self.queue.clear()
        items = [
            QueueItem(
                source_url=p.url,
                source_name=p.source_name,
                title=p.description if p.description else p.url,
                description=p.description,
                privacy_only=self.persistence_policy.is_enabled(),
            )
            for p in parsed_items
        ]
        self.queue.add_many(items)
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()
        first_item = items[0]
        self._pending_queue_item = first_item
        self._queue_transition = True
        try:
            self.handle_play_request(first_item.source_url)
        finally:
            self._queue_transition = False
        logger.info("Queue: Đã thay thế hàng đợi bằng %d video và phát tập 1.", len(items))

    def handle_play_queue_item(self, queue_id: str) -> None:
        """Play a specific item in the queue without clearing other playlist items."""
        item = self.queue.get(queue_id)
        if not item:
            return
        self._start_next_queue_item(item)

    def handle_remove_queue_item(self, queue_id: str) -> None:
        """Remove an item from the queue."""
        self.queue.remove(queue_id)
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()

    def handle_move_queue_item(self, queue_id: str, delta: int) -> None:
        """Reorder queue items up or down."""
        item = self.queue.get(queue_id)
        if not item:
            return
        new_idx = max(0, min(len(self.queue) - 1, item.position + delta))
        self.queue.move(queue_id, new_idx)
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()

    def handle_clear_queue(self) -> None:
        """Clear all items in queue except active playing item."""
        self.queue.clear(keep_current=True)
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()
        self.gui.show_osd_message("🗑️ Đã làm trống danh sách phát")

    def handle_clear_played_queue(self) -> None:
        """Remove played items from the queue."""
        removed = self.queue.clear_played()
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()
        self.gui.show_osd_message(f"🧹 Đã dọn {removed} video đã xem")

    def handle_retry_queue_item(self, queue_id: str) -> None:
        """Retry resolving and playing a failed item."""
        item = self.queue.get(queue_id)
        if not item:
            return
        self.queue.mark_status(queue_id, "pending")
        if hasattr(self.gui, "refresh_queue"):
            self.gui.refresh_queue(self.queue.snapshot())
        self._save_queue_if_persisted()
        self._start_next_queue_item(item)

    def handle_next_track(self) -> None:
        """Advance to next track in queue/playlist."""
        if not len(self.queue):
            return
        next_item = self.queue_controller.next_item()
        if next_item:
            self.gui.set_status("Đang chuyển sang video kế tiếp...")
            if hasattr(self.gui, "refresh_queue"):
                self.gui.refresh_queue(self.queue.snapshot())
            self._start_next_queue_item(next_item)
        else:
            self.gui.show_osd_message("⏭️ Đã đến cuối danh sách phát")

    def handle_previous_track(self) -> None:
        """Go back to previous track in queue/playlist."""
        if not len(self.queue):
            return
        prev_item = self.queue_controller.previous_item()
        if prev_item:
            self.gui.set_status("Đang chuyển sang video trước...")
            if hasattr(self.gui, "refresh_queue"):
                self.gui.refresh_queue(self.queue.snapshot())
            self._start_next_queue_item(prev_item)
        else:
            self.gui.show_osd_message("⏮️ Đã ở đầu danh sách phát")

    def handle_privacy_toggle(self) -> None:
        """Toggle runtime privacy; preference settings remain explicitly savable."""
        if not self.persistence_policy.is_enabled():
            if not messagebox.askyesno(
                "Bật Privacy Session",
                "Từ thời điểm này ứng dụng sẽ không ghi history, resume, last URL hoặc queue xuống đĩa. Tiếp tục?",
                parent=self.root,
            ):
                return
            self.persistence_policy.enabled = True
        else:
            self.persistence_policy.enabled = False
        self.gui.set_privacy_state(self.persistence_policy.is_enabled())
        self.gui.show_osd_message(
            "🔒 Đã bật Privacy Session" if self.persistence_policy.is_enabled() else "🔓 Đã tắt Privacy Session"
        )

    def _check_playback_health_degraded(self, health) -> None:
        """Check if playback health is degraded or critical and show suggestion according to profile mode."""
        if not health or health.state not in ("degraded", "critical"):
            return
        now = time.monotonic()
        if now - self._last_health_suggestion_time < HEALTH_SUGGESTION_COOLDOWN_SECONDS:
            return
        self._last_health_suggestion_time = now
        self._last_health_suggestion_url = self._original_url or ""

        url = self._original_url or ""
        profile = resolve_profile(self.settings.settings, url)
        if profile.mode == "custom":
            msg = (
                "Mạng có dấu hiệu không ổn định hoặc tốc độ tải không đủ cho cấu hình hiện tại.\n"
                "Gợi ý: chuyển sang Auto để ứng dụng tự tối ưu stream mượt hơn."
            )
            if hasattr(self.gui, "show_network_suggestion_prompt"):
                self.gui.show_network_suggestion_prompt(msg, self.handle_switch_to_auto_profile)
        else:
            self.gui.show_osd_message("📶 Mạng không ổn định - Đang tự động tối ưu...")

    def handle_switch_to_auto_profile(self) -> None:
        """Switch active domain or global source profile to 'auto' mode."""
        profiles = self.settings.get("source_profiles", default={})
        if not isinstance(profiles, dict):
            profiles = {}
        if self._original_url:
            domain = source_domain(self._original_url)
            if domain in profiles and isinstance(profiles[domain], dict):
                profiles[domain]["mode"] = "auto"
        if "global" in profiles and isinstance(profiles["global"], dict):
            profiles["global"]["mode"] = "auto"
        else:
            profiles["global"] = {"mode": "auto"}
        self.settings.set("source_profiles", profiles)
        self.settings.save()
        if hasattr(self.gui, "hide_network_suggestion_prompt"):
            self.gui.hide_network_suggestion_prompt()
        self.gui.show_osd_message("⚡ Đã chuyển sang cấu hình Auto tối ưu mạng")

    def _start_next_queue_item(self, item: QueueItem) -> None:
        """Start one queued item while retaining the rest of the queue."""
        self._pending_queue_item = item
        self._queue_transition = True
        try:
            self.handle_play_request(item.source_url)
        finally:
            self._queue_transition = False

    def _on_resolve_completed(self, future: concurrent.futures.Future, original_url: str) -> None:
        """Callback invoked on Main Thread when resolution completes."""
        if self._is_shutting_down:
            return

        try:
            resolved = future.result()
        except concurrent.futures.CancelledError:
            return
        except AuthRequiredError as err:
            if self._active_queue_item and self._active_queue_item.source_url == original_url:
                self.queue_controller.failed(self._active_queue_item, str(err))
                if hasattr(self.gui, "refresh_queue"):
                    self.gui.refresh_queue(self.queue.snapshot())
            logger.warning(f"Yêu cầu xác thực: {err}")
            self.gui.hide_overlay()
            if "telegram" in str(err).lower():
                from tkinter import messagebox
                if messagebox.askyesno("Yêu cầu đăng nhập Telegram", f"{err}\n\nBạn có muốn mở Cài đặt Telegram ngay bây giờ không?"):
                    self.gui.open_settings_dialog(initial_tab="telegram")
            else:
                self.gui.show_error(str(err))
            return
        except ResolverError as err:
            if self._active_queue_item and self._active_queue_item.source_url == original_url:
                self.queue_controller.failed(self._active_queue_item, str(err))
                if hasattr(self.gui, "refresh_queue"):
                    self.gui.refresh_queue(self.queue.snapshot())
            logger.warning(f"Lỗi phân giải URL: {err}")
            self.gui.show_error(str(err))
            return
        except Exception as exc:
            if self._active_queue_item and self._active_queue_item.source_url == original_url:
                self.queue_controller.failed(self._active_queue_item, str(exc))
                if hasattr(self.gui, "refresh_queue"):
                    self.gui.refresh_queue(self.queue.snapshot())
            logger.error(f"Lỗi không xác định khi phân giải: {exc}")
            self.gui.show_error(f"Lỗi không xác định: {exc}")
            return

        logger.info(
            f"Phân giải thành công: '{self.persistence_policy.redact(resolved.title)}' | "
            f"Thời lượng: {resolved.duration or 0:.0f}s | Live: {resolved.is_live}"
        )
        self.health_monitor.reset()
        self._last_health_suggestion_time = 0.0
        self._last_health_suggestion_url = original_url
        if hasattr(self.gui, "hide_network_suggestion_prompt"):
            self.gui.hide_network_suggestion_prompt()
        self._current_stream_url = resolved.stream_url
        if hasattr(self.gui, "set_chapters"):
            self.gui.set_chapters(getattr(resolved, "chapters", None))
        if self._active_queue_item and self._active_queue_item.source_url == original_url:
            self.queue_controller.resolved(
                self._active_queue_item,
                title=resolved.title,
                duration_ms=int((resolved.duration or 0) * 1000),
                chapters=getattr(resolved, "chapters", None),
                canonical_url=getattr(resolved, "canonical_url", None),
            )
            if hasattr(self.gui, "refresh_queue"):
                self.gui.refresh_queue(self.queue.snapshot())
        self.gui.hide_overlay()
        self.gui.set_status(f"Đang phát: {resolved.title}")

        # Auto-detect vertical video (9:16) for Reels, TikTok, Shorts only if auto-detection is enabled
        auto_pip = self.settings.get("ui", "pip_auto_aspect_ratio", default=False)
        if auto_pip:
            is_vertical = False
            url_lower = original_url.lower()
            if any(k in url_lower for k in ("/reel/", "/reels/", "/shorts/", "tiktok.com", "douyin.com")):
                is_vertical = True
            elif resolved.height and resolved.width and resolved.height > resolved.width:
                is_vertical = True
            elif resolved.formats:
                v_fmts = [f for f in resolved.formats if f.height and f.width]
                if v_fmts:
                    best_fmt = max(v_fmts, key=lambda f: (f.height or 0) * (f.width or 0))
                    if best_fmt.height and best_fmt.width and best_fmt.height > best_fmt.width:
                        is_vertical = True

            if is_vertical:
                self.gui.set_pip_aspect_ratio("9:16", persist=False)
            else:
                self.gui.set_pip_aspect_ratio("16:9", persist=False)

        resolved_dur_ms = int((resolved.duration or 0) * 1000)
        self._resolved_duration_ms = resolved_dur_ms

        # Record start of playback in history (increments watch count cleanly once)
        if self.persistence_policy.allow_history_write():
            self.history.record_playback_start(
                url=original_url,
                title=resolved.title,
                duration_ms=resolved_dur_ms,
                thumbnail_url=resolved.thumbnail,
            )

        # Stop the old VLC client before shutting down its local proxy.  A paused
        # Telegram stream can otherwise leave a proxy request handler blocked.
        # Proxy shutdown is asynchronous because server_close() may otherwise
        # block the Tkinter main thread while an old request is being unwound.
        if not resolved.stream_url.startswith("http://127.0.0.1:"):
            try:
                from main.stream_proxy import StreamProxyServer
                old_url = self.player.current_url if self.player else None
                if isinstance(old_url, str) and old_url.startswith("http://127.0.0.1:"):
                    self.player.stop(clear_source=True)
                StreamProxyServer.get_instance().stop_async()
            except Exception:
                pass

        # Start playback via VLC
        sub_file = self.settings.get("subtitle", "file", default="")
        profile = resolve_profile(self.settings.settings, original_url)
        self.player.play(
            resolved.stream_url,
            audio_url=resolved.audio_url,
            subtitle_file=sub_file if sub_file else None,
            http_headers=resolved.http_headers,
            network_caching_ms=profile.network_caching_ms,
        )

        # Apply default playback speed
        def_speed = self.settings.get("video", "default_speed", default=1.0)
        self.player.set_playback_rate(def_speed)
        self.gui.speed_var.set(f"{def_speed}x")

        # Check for saved history position to resume
        if (
            self.persistence_policy.allow_resume_write()
            and self.settings.get("playback", "resume_playback", default=True)
        ):
            saved_pos = self.history.get_last_position(original_url)
            if saved_pos and saved_pos > 5000:
                self.root.after(200, lambda: self._perform_resume_seek(original_url, saved_pos))

        # Kích hoạt dọn rác sau 2 giây (đảm bảo VLC đã buffer xong mới dọn)
        self.root.after(2000, lambda: self.executor.submit(self._post_task_cleanup))

    def _perform_resume_seek(self, url: str, target_ms: int, max_attempts: int = 25) -> None:
        """Reliably poll and seek to saved position once VLC stream begins playing."""
        if self._is_shutting_down or not self.player or not self._original_url:
            return

        if self._original_url != url:
            return

        state = self.player.state
        dur = self.player.get_duration()

        # Seek once VLC reports playing and duration, or when attempts exhausted
        if (state == "playing" and dur > 0) or max_attempts <= 0:
            self.player.seek_to(target_ms)
            time_str = format_timestamp(target_ms)
            self.gui.show_osd_message(f"⏱️ Tiếp tục từ {time_str}")
            logger.info(f"Đã tự động tiếp tục phát từ mốc: {time_str} ({target_ms}ms)")
            self._schedule_post_seek_cleanup()
        else:
            self.root.after(150, lambda: self._perform_resume_seek(url, target_ms, max_attempts - 1))

    def _apply_post_update_resume(self) -> None:
        """Seamlessly resume playback after application update."""
        if not getattr(self, "_update_resume_state", None) or self._is_shutting_down:
            return
        state = self._update_resume_state
        url = state.get("url")
        if url:
            self.gui.url_entry.delete(0, tk.END)
            self.gui.url_entry.insert(0, url)
            self.handle_play_request(url)

            # Restore audio volume and playback rate
            if "volume" in state and self.player:
                self.player.set_volume(state["volume"])
                self.gui.volume_scale.set(state["volume"])
            if "is_muted" in state and state["is_muted"] and self.player:
                self.player.set_mute(True)
                self.gui.set_mute_button_state(True)
            if "playback_rate" in state and self.player:
                rate = state["playback_rate"]
                self.player.set_playback_rate(rate)
                self.gui.speed_var.set(f"{rate}x")

            pos_ms = state.get("position_ms", 0)
            if pos_ms > 3000:
                self.root.after(300, lambda: self._perform_resume_seek(url, pos_ms))
            self.gui.show_osd_message("🚀 Đã cập nhật thành công & tiếp tục phát!")

    def get_current_playback_snapshot(self) -> Dict[str, Any]:
        """Capture complete playback snapshot for seamless resumption across updates."""
        pos = 0
        vol = 80
        muted = False
        rate = 1.0
        if self.player:
            try:
                pos = self.player.get_position()
                vol = self.player.get_volume()
                muted = self.player.is_muted()
                rate = self.player.get_playback_rate()
            except Exception:
                pass
        return {
            "url": self._original_url or self.gui.url_entry.get().strip(),
            "position_ms": pos,
            "volume": vol,
            "is_muted": muted,
            "playback_rate": rate,
            "loop_enabled": getattr(self, "_is_loop_enabled", False),
        }

    def _background_check_update(self) -> None:
        """Background thread checking GitHub releases."""
        if self._is_shutting_down:
            return
        from main.updater import check_for_updates
        info = check_for_updates()
        if info and not self._is_shutting_down:
            self.root.after(0, lambda: self._prompt_update_dialog(info))

    def _cleanup_on_startup(self) -> None:
        """Chạy trên background thread khi khởi động: dọn sạch file .old và cache update cũ."""
        try:
            from main.updater import cleanup_updater_leftovers
            cleanup_updater_leftovers()
        except Exception:
            pass

    def _schedule_post_seek_cleanup(self, delay_ms: int = 2500) -> None:
        """
        Debounce và lập lịch dọn RAM ngầm sau khi tua/seek video.
        Chờ 2.5s sau khi dừng tua để VLC ổn định luồng phát, sau đó mới
        chạy _post_task_cleanup trên background executor thread.
        """
        if self._is_shutting_down:
            return
        if self._seek_cleanup_timer_id is not None:
            try:
                self.root.after_cancel(self._seek_cleanup_timer_id)
            except Exception:
                pass
            self._seek_cleanup_timer_id = None
        if hasattr(self.root, "winfo_exists") and self.root.winfo_exists():
            try:
                self._seek_cleanup_timer_id = self.root.after(
                    delay_ms, self._trigger_post_seek_cleanup
                )
            except Exception:
                pass

    def _trigger_post_seek_cleanup(self) -> None:
        """Kích hoạt bởi debounce timer sau khi tua video."""
        self._seek_cleanup_timer_id = None
        if not self._is_shutting_down:
            self.executor.submit(self._post_task_cleanup)

    def _post_task_cleanup(self) -> None:
        """
        Dọn rác Python heap và ép Windows thu hồi RAM vật lý nhàn rỗi.
        Chỉ gọi sau khi tác vụ nặng hoàn thành (resolve, đóng dialog, dừng video, sau khi tua/seek).
        KHÔNG BAO GIỜ gọi trong vòng lặp UI timer 250ms.
        """
        gc.collect()
        try:
            from main.platform_utils import trim_process_memory
            trim_process_memory()
        except Exception:
            pass

    def _trim_memory_if_possible(self) -> None:
        """
        Bridge được gui.py gọi khi đóng SettingsDialog.
        Chạy _post_task_cleanup trên executor thread để không block main thread.
        """
        if not self._is_shutting_down:
            self.executor.submit(self._post_task_cleanup)

    def _prompt_update_dialog(self, info) -> None:
        """Prompt user with update dialog."""
        if self._is_shutting_down:
            return
        ans = messagebox.askyesno(
            "Có bản cập nhật mới!",
            f"Đã có phiên bản mới: v{info.version}!\n\n"
            f"Tiêu đề: {info.title}\n"
            f"Tệp cập nhật: {info.asset_name} ({info.asset_size // 1024 // 1024} MB)\n\n"
            f"Ghi chú:\n{info.release_notes[:250]}\n\n"
            "Bạn có muốn tải về và cập nhật ngay bây giờ không?\n"
            "(Video đang xem sẽ không bị gián đoạn trong khi tải)",
            parent=self.root,
        )
        if ans:
            self._start_update_download(info)

    def _start_update_download(self, info) -> None:
        """Start downloading update in background thread while video continues playing."""
        if self._is_shutting_down:
            return
        from main.updater import download_update, apply_update_and_restart
        self.gui.show_osd_message(f"⬇️ Đang tải bản cập nhật v{info.version} ngầm...")

        def _on_progress(percent: float, downloaded: int, total: int):
            mb_down = downloaded / (1024 * 1024)
            mb_tot = total / (1024 * 1024)
            msg = f"Đang tải cập nhật v{info.version}: {percent:.1f}% ({mb_down:.1f}MB / {mb_tot:.1f}MB)"
            self.root.after(0, lambda: self.gui.set_status(msg))

        def _worker():
            zip_path = download_update(info, progress_callback=_on_progress)
            if not zip_path:
                self.root.after(0, lambda: messagebox.showerror("Lỗi cập nhật", "Tải bản cập nhật thất bại hoặc bị hủy. Vui lòng thử lại sau.", parent=self.root))
                return

            def _on_ready():
                snapshot = self.get_current_playback_snapshot()
                self.gui.show_osd_message("🚀 Đang khởi động lại để áp dụng bản cập nhật...")
                if apply_update_and_restart(zip_path, snapshot):
                    self.on_closing()
                    import os
                    threading.Timer(1.0, lambda: os._exit(0)).start()

            self.root.after(0, _on_ready)

        threading.Thread(target=_worker, daemon=True).start()

    def handle_pause_toggle(self) -> None:
        if self.player:
            was_playing = (self.player.state == "playing")
            self.player.toggle_play_pause()
            self.gui.show_osd_action("pause" if was_playing else "play")
            self.gui.set_play_pause_button_state(not was_playing)

    def handle_seek_request(self, time_ms: int) -> None:
        if self.player:
            self.player.seek_to(time_ms)
            if self.player.state == "playing":
                self.gui.set_play_pause_button_state(True)
            self._schedule_post_seek_cleanup()

    def handle_seek_relative(self, delta_seconds: int) -> None:
        if self.player:
            self.player.seek_relative(delta_seconds)
            self.gui.show_osd_seek(delta_seconds)
            self._schedule_post_seek_cleanup()

    def handle_volume_change(self, volume: int) -> None:
        if self.player:
            self.player.set_volume(volume)
            is_muted = self.player.is_muted()
            self.gui.set_mute_button_state(is_muted)
            if type(volume) in (int, float):
                self.settings.set("audio", "default_volume", int(volume))
            if type(is_muted) is bool:
                self.settings.set("audio", "is_muted", is_muted)
            self.gui.show_osd_volume(volume, is_muted)

    def handle_mute_toggle(self) -> None:
        if self.player:
            is_muted = self.player.toggle_mute()
            self.gui.set_mute_button_state(is_muted)
            if type(is_muted) is bool:
                self.settings.set("audio", "is_muted", is_muted)
            vol = self.player.get_volume()
            self.gui.show_osd_volume(vol, is_muted)

    def handle_rate_change(self, rate: float) -> None:
        if self.player:
            self.player.set_playback_rate(rate)
            self.gui.show_osd_speed(rate)

    def _on_window_focus_in(self, event=None) -> None:
        """Check clipboard immediately when user focuses the application window."""
        if self._is_shutting_down:
            return
        if not hasattr(self.root, "winfo_exists"):
            return
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        self._check_clipboard()

    def _check_clipboard(self) -> None:
        """Check clipboard for playable video URLs and display toast prompt."""
        if self._is_shutting_down:
            return
        if not self.settings.get("ui", "clipboard_auto_detect", default=True):
            return
        if not hasattr(self.root, "winfo_exists"):
            return
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        try:
            clip = self.root.clipboard_get().strip()
        except Exception:
            return

        if not clip or clip == self._last_detected_clipboard:
            return

        try:
            if not hasattr(self.gui, "url_entry") or not self.gui.url_entry.winfo_exists():
                return
            current_url = self.gui.url_entry.get().strip()
        except Exception:
            return

        if clip == current_url or clip == self._original_url:
            return

        if is_potential_video_url(clip):
            self._last_detected_clipboard = clip
            try:
                self.gui.show_clipboard_prompt(clip)
            except Exception:
                pass


    def handle_open_history(self) -> None:
        """Open watch history modal. If already open, brings to front."""
        if not self.persistence_policy.allow_history_write():
            self.gui.show_osd_message("🔒 Privacy Session: lịch sử đã tắt")
            return
        if hasattr(self, "_history_dialog") and self._history_dialog is not None:
            try:
                if self._history_dialog.top.winfo_exists():
                    self._history_dialog.top.lift()
                    self._history_dialog.top.focus_force()
                    return
            except Exception:
                self._history_dialog = None

        from main.history_dialog import HistoryDialog
        self._history_dialog = HistoryDialog(
            parent=self.root,
            history_mgr=self.history,
            theme_mgr=self.theme,
            on_play_video=self._on_play_from_history,
        )

    def _on_play_from_history(self, url: str, resume_pos_ms: int) -> None:
        """Handle video selected from watch history."""
        self.gui.url_entry.delete(0, tk.END)
        self.gui.url_entry.insert(0, url)
        self.handle_play_request(url)
        if resume_pos_ms > 5000:
            self.root.after(200, lambda: self._perform_resume_seek(url, resume_pos_ms))

    def handle_download_request(self, audio_only: Optional[bool] = None) -> None:
        """Handle video download request via VideoDownloader or cancel active download."""
        if (
            hasattr(self, "_active_downloader")
            and self._active_downloader
            and self._active_downloader._thread
            and self._active_downloader._thread.is_alive()
        ):
            if messagebox.askyesno(
                "Hủy tải video",
                "Tiến trình tải video đang chạy.\nBạn có chắc chắn muốn hủy quá trình tải này không?",
                parent=self.root,
            ):
                self.gui.set_status("🛑 Đang hủy tiến trình tải...")
                self.gui.btn_download.configure(text="⏳ Đang hủy...", state=tk.DISABLED)
                self._active_downloader.cancel()
            return

        url = self.gui.url_entry.get().strip() or self._original_url
        if not url:
            messagebox.showinfo("Tải video", "Vui lòng dán hoặc nhập liên kết video trước khi tải về.")
            return

        # Determine download format (Video MP4 vs Audio MP3)
        if audio_only is None:
            fmt_setting = self.settings.get("download", "format", default="video")
            if fmt_setting == "audio":
                audio_only = True
            elif fmt_setting == "video":
                audio_only = False
            else:
                # "ask" mode: prompt user with a clean choice dialog
                choice = messagebox.askyesnocancel(
                    "Định dạng tải xuống",
                    "Bạn muốn tải video hay chỉ lấy âm thanh (MP3)?\n\n"
                    "• Chọn 'Yes' để tải Video đầy đủ (MP4)\n"
                    "• Chọn 'No' để chỉ tải file Âm thanh (MP3)\n"
                    "• Chọn 'Cancel' để hủy bỏ",
                    parent=self.root,
                )
                if choice is None:
                    return
                audio_only = (choice is False)

        from main.ffmpeg_utils import is_ffmpeg_available
        if not is_ffmpeg_available():
            logger.info("Tiện ích FFmpeg chưa cài đặt; tự động áp dụng chế độ tương thích (Progressive MP4).")

        from pathlib import Path
        from main.downloader import VideoDownloader, get_default_download_dir
        download_dir = None
        custom_dir = self.settings.get("download", "download_dir", default="")
        if custom_dir and Path(custom_dir).is_dir():
            download_dir = Path(custom_dir)
        else:
            download_dir = get_default_download_dir()

        # If user enabled "Always ask where to save before downloading"
        always_ask = self.settings.get("download", "always_ask", default=False)
        if always_ask:
            chosen = filedialog.askdirectory(
                parent=self.root,
                title="Chọn thư mục lưu file tải về",
                initialdir=str(download_dir),
            )
            if not chosen:
                return
            download_dir = Path(chosen)

        cookie_file = self.settings.get("advanced", "cookie_file", default="")
        max_height = self.settings.get("video", "max_height", default=1080)

        fmt_label = "âm thanh MP3" if audio_only else "video"
        self.gui.btn_download.configure(text="❌ Hủy (0%)", state=tk.NORMAL)
        self.gui.set_status(f"Bắt đầu tải {fmt_label} vào: {download_dir}...")

        def on_progress(info: dict):
            pct = info.get("percent", 0.0)
            spd = info.get("speed_str", "")
            sz = info.get("size_str", "")
            eta = info.get("eta_str", "")
            status_msg = f"Đang tải {pct:.1f}% ({sz} - {spd} - còn {eta})"
            self.root.after(0, lambda: self._on_download_progress(pct, status_msg))

        def on_complete(filepath: Path):
            self.root.after(0, lambda: self._on_download_completed(filepath))

        def on_error(err_msg: str):
            self.root.after(0, lambda: self._on_download_error(err_msg))

        self._active_downloader = VideoDownloader(
            url=url,
            output_dir=download_dir,
            cookie_file=cookie_file if cookie_file else None,
            max_height=max_height,
            audio_only=audio_only,
            audio_format="mp3",
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )
        self._active_downloader.start()

    def _on_download_progress(self, percent: float, status_msg: str) -> None:
        if not self._is_shutting_down:
            self.gui.btn_download.configure(text=f"❌ Hủy ({int(percent)}%)", state=tk.NORMAL)
            self.gui.set_status(status_msg)

    def _on_download_completed(self, filepath) -> None:
        if self._is_shutting_down:
            return
        self._active_downloader = None
        self.gui.btn_download.configure(text="⬇ Tải về", state=tk.NORMAL)
        self.gui.set_status(f"Tải thành công: {filepath.name}")

        # Trigger Windows Toast notification if enabled
        if self.settings.get("download", "show_toast", default=True):
            from main.platform_utils import show_windows_toast
            show_windows_toast(
                title="FB Video Watcher - Đã tải xong",
                message=f"Đã lưu thành công: {filepath.name}",
            )

        if messagebox.askyesno(
            "Tải thành công",
            f"Đã lưu file thành công vào:\n{filepath}\n\nBạn có muốn mở thư mục chứa file không?",
            parent=self.root,
        ):
            import subprocess
            try:
                subprocess.Popen(f'explorer /select,"{filepath}"')
            except Exception:
                pass

    def _on_download_error(self, err_msg: str) -> None:
        if self._is_shutting_down:
            return
        self._active_downloader = None
        self.gui.btn_download.configure(text="⬇ Tải về", state=tk.NORMAL)
        if "hủy" in err_msg.lower() or "cancel" in err_msg.lower():
            self.gui.set_status("🛑 Đã hủy tải video.")
            if hasattr(self.gui, "show_osd"):
                self.gui.show_osd("🛑 Đã hủy tải video")
            return
        self.gui.set_status(f"Lỗi tải video: {err_msg}")
        messagebox.showerror("Lỗi tải video", err_msg)

    def _apply_cpu_optimizations(self) -> None:
        """Apply Windows EcoQoS, multimedia timer, and CPU core affinity according to settings."""
        from main.platform_utils import (
            disable_process_power_throttling,
            enable_high_precision_timer,
            apply_cpu_affinity,
        )

        perf_cfg = self.settings.get("performance", default={})
        if not isinstance(perf_cfg, dict):
            perf_cfg = {}

        # 1. High precision multimedia timer (1ms resolution)
        if perf_cfg.get("high_precision_timer", True):
            enable_high_precision_timer()

        # 2. Disable Windows EcoQoS / Efficiency Mode / Power Throttling
        if perf_cfg.get("disable_eco_qos", True):
            disable_process_power_throttling()

        # 3. CPU Core Affinity
        mode = perf_cfg.get("cpu_affinity_mode", "auto")
        apply_cpu_affinity(mode, self.sys_info)

        # 4. Smart GPU Offloading (Windows UserGpuPreferences)
        from main.platform_utils import apply_windows_gpu_preference
        gpu_pref_mode = self.tuner.recommend_gpu_preference()
        if gpu_pref_mode in ("power_saving", "high_performance", "default"):
            apply_windows_gpu_preference(mode=gpu_pref_mode)
            if gpu_pref_mode == "power_saving":
                logger.info(
                    "Smart GPU: Tự động phân bổ giải mã video sang iGPU (%s) để nhường card rời (%s) cho Game/3D.",
                    getattr(self.sys_info, "integrated_gpu_name", "iGPU"),
                    getattr(self.sys_info, "discrete_gpu_name", "dGPU"),
                )

    def handle_settings_updated(self) -> None:
        """Callback when user saves new settings."""
        # Update in-app isolated NetworkManager (Proxy & DoH DNS)
        if hasattr(self, "network_manager") and self.network_manager:
            try:
                self.network_manager.apply_settings(self.settings.settings)
            except Exception as e:
                logger.warning("Lỗi cập nhật cấu hình mạng: %s", e)

        # Rebuild AutoTuner and VLC args for subsequent playbacks
        self.tuner = AutoTuner(self.sys_info, self.settings.settings)
        self.vlc_args = self.tuner.build_vlc_args()

        # Re-apply CPU performance optimizations (Affinity, EcoQoS, Timer)
        self._apply_cpu_optimizations()

        # Dynamically reinitialize VLC player instance with new args (subtitle styling, font size, etc.)
        if self.player:
            self.player.reinit_instance(self.vlc_args)

        # Apply updated subtitle file to player if active
        sub_file = self.settings.get("subtitle", "file", default="")
        if self.player:
            self.player.set_subtitle_file(sub_file if sub_file else None)

        if hasattr(self.gui, "update_seek_buttons"):
            self.gui.update_seek_buttons()
        if hasattr(self.gui, "rebind_shortcuts"):
            self.gui.rebind_shortcuts()
        if hasattr(self.gui, "apply_theme"):
            self.gui.apply_theme()

    def handle_load_subtitle(self, subtitle_path: str) -> None:
        """Attach external subtitle file dynamically to player."""
        if self.player:
            self.player.set_subtitle_file(subtitle_path)

    # --- Error & Re-resolution Strategy (§7.6) ---

    def _on_playback_error(self, message: str) -> None:
        """Marshal VLC error callback to main thread."""
        if not self._is_shutting_down:
            self.root.after(0, lambda: self._handle_playback_error_safe(message))

    def _handle_playback_error_safe(self, message: str) -> None:
        """Auto re-resolve Facebook/CDN stream URL if token expired mid-playback."""
        self.health_monitor.record_error()
        if self._is_shutting_down or not self.player or not self._original_url:
            self.gui.show_error(message)
            return

        current_pos = self.player.get_position()

        # If played > 5s and within retry limit -> Auto re-resolve
        if current_pos > 5000 and self._re_resolve_attempts < self._max_re_resolve_attempts:
            self._re_resolve_attempts += 1
            self.gui.set_loading(f"Stream gián đoạn. Đang tự động kết nối lại ({self._re_resolve_attempts}/3)...")

            cookie_file = self.settings.get("advanced", "cookie_file", default="")
            max_height = self.settings.get("video", "max_height", default=1080)

            future = self.executor.submit(
                resolve_facebook_url,
                url=self._original_url,
                cookie_file=cookie_file if cookie_file else None,
                max_height=max_height,
            )
            future.add_done_callback(
                lambda f: self.root.after(0, lambda: self._on_re_resolve_completed(f, current_pos))
            )
        else:
            self.gui.show_error(message)

    def _on_re_resolve_completed(self, future: concurrent.futures.Future, resume_pos: int) -> None:
        if self._is_shutting_down:
            return
        try:
            resolved = future.result()
            self._current_stream_url = resolved.stream_url
            self.gui.hide_overlay()
            self.player.play(
                resolved.stream_url,
                audio_url=resolved.audio_url,
                http_headers=resolved.http_headers,
            )
            # Delay 600ms before seek to let VLC media stream initialize
            self.root.after(600, lambda: self.player.seek_to(resume_pos))
        except Exception as exc:
            self.gui.show_error(f"Không thể kết nối lại video: {exc}")

    def _on_playback_ended(self) -> None:
        """Invoked when video finishes playing (VLC C-thread -> main thread)."""
        if not self._is_shutting_down:
            self.root.after(0, self._handle_playback_ended_safe)

    def _handle_playback_ended_safe(self) -> None:
        """Detect whether stream completed naturally or terminated prematurely (token expired)."""
        if self._is_shutting_down or not self.player or not self._original_url:
            return

        current_pos = self.player.get_position()
        duration_ms = self.player.get_duration()

        # If video ended prematurely (e.g. duration > 30s and ended > 15s early)
        if duration_ms > 30000 and current_pos < (duration_ms - 15000):
            logger.warning(
                f"Phát hiện stream bị ngắt sớm tại {current_pos // 1000}s / {duration_ms // 1000}s "
                "(có thể token Facebook/CDN đã hết hạn). Đang tự động kết nối lại..."
            )
            self._handle_playback_error_safe("Stream bị ngắt kết nối giữa chừng.")
            return

        # Check A-B repeat first
        if self._ab_point_a is not None and self.player:
            self.player.seek_to(self._ab_point_a)
            self.player.play()
            return

        # Check full video loop
        if self._is_loop_enabled and self._current_stream_url and self.player:
            logger.info("Phát hiện video kết thúc, tự động phát lặp lại (Loop Playback)")
            self.gui.show_osd_message("🔁 Tự động phát lặp lại")
            self.player.play(self._current_stream_url)
            return

        # Natural end of video
        next_item = self.queue_controller.on_natural_end(
            self._active_queue_item,
            loop_video=False,
            ab_repeat=False,
        )
        if next_item is not None:
            self.gui.set_status("Đang chuyển sang video kế tiếp...")
            if hasattr(self.gui, "refresh_queue"):
                self.gui.refresh_queue(self.queue.snapshot())
            self._save_queue_if_persisted()
            self._start_next_queue_item(next_item)
            return
        self._save_queue_if_persisted()
        self.gui.set_status("Đã phát xong video.")
        self.gui.set_play_pause_button_state(False)

    def handle_loop_toggle(self) -> None:
        """Toggle full video repeat on/off."""
        self._is_loop_enabled = not self._is_loop_enabled
        self.settings.set("playback", "loop_enabled", self._is_loop_enabled)
        self.settings.save()
        self.gui.set_loop_state(self._is_loop_enabled)
        self.gui.show_osd_message("🔁 Bật lặp lại video" if self._is_loop_enabled else "➡️ Tắt lặp lại video")

    def handle_ab_repeat_toggle(self) -> None:
        """Cycle A-B repeat state: Set A -> Set B -> Turn Off."""
        if not self.player:
            return

        current_pos = self.player.get_position()
        if self._ab_point_a is None:
            self._ab_point_a = current_pos
            self._ab_point_b = None
            time_a = format_timestamp(current_pos)
            self.gui.set_ab_repeat_state("A", time_a_ms=current_pos)
            self.gui.show_osd_message(f"🔁 Điểm A: {time_a}")
        elif self._ab_point_b is None:
            if current_pos <= self._ab_point_a:
                self.gui.show_osd_message("⚠️ Điểm B phải lớn hơn điểm A")
                return
            self._ab_point_b = current_pos
            time_a = format_timestamp(self._ab_point_a)
            time_b = format_timestamp(self._ab_point_b)
            self.gui.set_ab_repeat_state("AB", time_a_ms=self._ab_point_a, time_b_ms=self._ab_point_b)
            self.gui.show_osd_message(f"🔁 Lặp A-B: [{time_a} ⇄ {time_b}]")
        else:
            self._ab_point_a = None
            self._ab_point_b = None
            self.gui.set_ab_repeat_state("OFF")
            self.gui.show_osd_message("🔁 Tắt lặp đoạn A-B")

    # --- Shutdown & Position Persistence (§9.2 E) ---

    def _save_current_position(self) -> None:
        """Persist current video playback position into SQLite."""
        if self.persistence_policy.allow_resume_write() and self.player and self._original_url:
            pos = self.player.get_position()
            dur = self.player.get_duration()
            if pos > 3000:
                self.history.save_position(
                    url=self._original_url,
                    position_ms=pos,
                    duration_ms=dur,
                )

    def on_closing(self) -> None:
        """Handle window closing event cleanly without freezing (§9.2 E)."""
        self._is_shutting_down = True
        for tid_name in ("_ui_timer_id", "_maint_timer_id", "_clip_timer_id", "_seek_cleanup_timer_id"):
            tid = getattr(self, tid_name, None)
            if tid is not None:
                try:
                    self.root.after_cancel(tid)
                except Exception:
                    pass
                setattr(self, tid_name, None)
        self._save_current_position()

        # Save last PiP dimensions if closed during PiP mode
        if getattr(self.gui, "_is_pip", False):
            w = getattr(self.gui, "_last_resized_pip_w", None) or self.gui.root.winfo_width()
            h = getattr(self.gui, "_last_resized_pip_h", None) or self.gui.root.winfo_height()
            self.gui._save_current_pip_size(w, h)

        # Save last URL from entry or active URL (§Feature 1)
        current_url = self.gui.url_entry.get().strip() or self._original_url
        if current_url and self.persistence_policy.allow_content_state_write():
            self.settings.set("playback", "last_url", current_url)

        # Save persistent audio volume and mute state
        if self.player:
            try:
                vol = self.player.get_volume()
                if type(vol) in (int, float):
                    self.settings.set("audio", "default_volume", int(vol))
                muted = self.player.is_muted()
                if type(muted) is bool:
                    self.settings.set("audio", "is_muted", muted)
            except Exception:
                pass

        self.settings.save()

        # Save queue persistence if enabled
        if self.settings.get("playback", "queue_persist", default=False):
            try:
                self.queue_persistence.save(self.queue)
            except Exception:
                pass

        if self.player:
            self.player.release()

        # Cancel active background downloader if running
        if hasattr(self, "_active_downloader") and self._active_downloader:
            try:
                self._active_downloader.cancel()
            except Exception:
                pass

        # Shutdown worker threads
        self.executor.shutdown(wait=False, cancel_futures=True)

        # Shut down local stream proxy off the Tkinter thread.  Active proxy
        # sockets are closed by StreamProxyServer.stop(), which lets paused
        # Telegram handlers exit without freezing application shutdown.
        try:
            from main.stream_proxy import StreamProxyServer
            StreamProxyServer.get_instance().stop_async()
        except Exception:
            pass

        # Restore Windows multimedia timer resolution
        try:
            from main.platform_utils import disable_high_precision_timer
            disable_high_precision_timer()
        except Exception:
            pass

        # Dọn sạch file manifest HLS tạm trong %TEMP%/fbw_hls
        try:
            from main.extractors.youtube import cleanup_hls_cache
            cleanup_hls_cache()
        except Exception:
            pass

        # Destroy GUI
        if hasattr(self.gui, "destroy"):
            try:
                self.gui.destroy()
            except Exception:
                pass
        self.root.destroy()
