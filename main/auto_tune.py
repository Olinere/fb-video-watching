"""
Auto-tuning module for dynamic hardware optimization.
Strictly adheres to Agent.md §3:
- Determines optimal configuration based on detected hardware.
- Follows the priority: User Settings > Auto-detect > Default fallback.
"""

from typing import Optional, List, Dict, Any
from main.system_info import SystemInfo


class AutoTuner:
    """Calculates hardware-tailored configurations and generates dynamic VLC arguments."""

    def __init__(self, sys_info: SystemInfo, user_settings: Optional[Dict[str, Any]] = None):
        """
        Initialize with detected system info and optional user settings.

        Args:
            sys_info: SystemInfo instance populated by SystemInfo.detect().
            user_settings: Dict matching DEFAULT_SETTINGS schema from settings.json.
        """
        self.sys_info = sys_info
        self.user_settings = user_settings or {}

    def recommend_decode_threads(self) -> int:
        """
        Recommend number of decoder threads based on CPU topology.
        - Hybrid CPUs (Intel P/E cores, AMD Zen/Zen-c): Bound to physical P-cores count
          (capped at 8) so video decoding never spills onto slower E-cores, which would
          cause frame-decoding stalls due to thread synchronization stragglers.
        - Standard multi-core:
          - <= 4 cores logical  -> 1 thread
          - 5-8 cores           -> 2 threads
          - 9-16 cores          -> 4 threads
          - > 16 cores          -> 6 threads
        """
        if self.sys_info.is_hybrid_cpu and self.sys_info.cpu_p_cores > 0:
            p_cores = self.sys_info.cpu_p_cores
            if p_cores <= 2:
                return 2
            elif p_cores <= 4:
                return 4
            elif p_cores <= 6:
                return 6
            else:
                return min(p_cores, 8)

        cores = self.sys_info.cpu_cores_logical
        if cores <= 4:
            return 1
        elif cores <= 8:
            return 2
        elif cores <= 16:
            return 4
        else:
            return 6

    def recommend_hw_accel(self) -> Optional[str]:
        """
        Choose hardware acceleration method tailored to the detected GPU and OS.
        - Windows 10+ with NVIDIA / AMD / Intel GPU -> 'd3d11va' (modern DirectX 11)
        - Older Windows with recognized GPU -> 'dxva2' (DirectX 9 fallback)
        - Unknown/Integrated fallback -> None (software decoding)
        """
        vendor = self.sys_info.gpu_vendor
        os_name = self.sys_info.os_name
        os_ver = self.sys_info.os_version

        if vendor in ("nvidia", "amd", "intel") and os_name == "Windows":
            # Extract major OS version (e.g. "10" from "10.0.22631")
            try:
                major = int(os_ver.split(".")[0])
            except (ValueError, IndexError):
                major = 10

            if major >= 10:
                return "d3d11va"
            return "dxva2"

        return None

    def recommend_network_buffer(self) -> int:
        """
        Recommend network caching buffer in milliseconds based on available or total RAM.
        - < 4 GB available and total < 8 GB  -> 1500 ms (conservative)
        - 4-8 GB available or 8-16 GB total   -> 3000 ms (standard)
        - > 8 GB available or >= 16 GB total  -> 5000 ms (comfortable while gaming)
        """
        ram_avail = self.sys_info.ram_available_gb
        ram_total = self.sys_info.ram_total_gb

        # If system has plenty of total RAM (>=16GB), allow generous buffer even if gaming consumes RAM
        if ram_avail > 8.0 or ram_total >= 16.0:
            return 5000
        elif ram_avail >= 4.0 or ram_total >= 8.0:
            return 3000
        else:
            return 1500

    def recommend_thread_pool_size(self) -> int:
        """
        Recommend worker count for ThreadPoolExecutor.
        - Hybrid CPUs: If >= 4 E-cores available, use 4 workers so background tasks
          (stream resolving, thumbnail downloads, devlog writing) can utilize E-cores
          effectively without competing with playback on P-cores.
        - Non-hybrid: <= 4 cores -> 1 worker, > 4 cores -> 2 workers.
        """
        if self.sys_info.is_hybrid_cpu and self.sys_info.cpu_e_cores >= 4:
            return 4
        cores = self.sys_info.cpu_cores_logical
        if cores <= 4:
            return 1
        return 2

    def build_vlc_args(self) -> List[str]:
        """
        Build optimized VLC arguments list dynamically based on Priority:
        1. User Settings (explicit override)
        2. Auto-detect (AutoTuner recommendation)
        3. Default fallback
        """
        args = [
            "--quiet",
            "--no-video-title-show",
            "--http-reconnect",
            "--drop-late-frames",
        ]

        # Platform-specific options
        if self.sys_info.os_name != "Windows":
            args.append("--no-xlib")

        streaming_cfg = self.user_settings.get("streaming", {})

        # 1. Network / File / Live Caching
        cache = streaming_cfg.get("network_caching")
        if not cache or not isinstance(cache, int) or cache <= 0:
            cache = self.recommend_network_buffer()

        args.append(f"--network-caching={cache}")
        args.append(f"--file-caching={max(cache // 2, 1000)}")
        args.append(f"--live-caching={cache}")

        # 2. Hardware Acceleration
        hw_enabled = streaming_cfg.get("hardware_decode", True)
        if hw_enabled:
            hw_method = streaming_cfg.get("hw_accel")
            if not hw_method or hw_method == "auto":
                hw_method = self.recommend_hw_accel()

            if hw_method and hw_method.lower() != "none":
                args.append(f"--avcodec-hw={hw_method}")

        # 3. Decode Threads
        threads = streaming_cfg.get("decode_threads", 0)
        if not threads or threads == 0:
            threads = self.recommend_decode_threads()

        args.append(f"--avcodec-threads={threads}")

        # 4. Subtitle / Freetype Styling
        sub_cfg = self.user_settings.get("subtitle")
        if sub_cfg:
            from main.subtitle import build_vlc_subtitle_args
            args.extend(build_vlc_subtitle_args(sub_cfg))

        return args

    def get_recommendations_display(self) -> Dict[str, str]:
        """Returns auto-tune recommendations formatted for Settings GUI tab."""
        hw = self.recommend_hw_accel()
        hw_str = (
            f"{hw} ({self.sys_info.gpu_vendor.upper()} detected)"
            if hw
            else "Software decode (No discrete GPU)"
        )
        threads = self.recommend_decode_threads()
        buffer_ms = self.recommend_network_buffer()
        pool_size = self.recommend_thread_pool_size()

        if self.sys_info.is_hybrid_cpu:
            thread_desc = f"{threads} (khớp {self.sys_info.cpu_p_cores} P-cores, tránh gián đoạn do E-core)"
            pool_desc = f"{pool_size} workers (phân bổ tác vụ nền vào {self.sys_info.cpu_e_cores} E-cores)"
        else:
            thread_desc = f"{threads} (dựa trên {self.sys_info.cpu_cores_logical} logical cores)"
            pool_desc = f"{pool_size} workers"

        return {
            "HW Decode": hw_str,
            "Decode threads": thread_desc,
            "Network buffer": f"{buffer_ms}ms (tự tối ưu RAM)",
            "Thread pool": pool_desc,
        }
