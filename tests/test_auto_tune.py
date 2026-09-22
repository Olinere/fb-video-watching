"""
Unit tests for main/auto_tune.py.
Verifies thread allocation, hardware acceleration selection, buffer size,
and strict priority: User Settings > Auto-detect > Default fallback.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.system_info import SystemInfo
from main.auto_tune import AutoTuner


def create_mock_sys_info(
    cores_logical=4,
    cores_physical=2,
    ram_total=8.0,
    ram_avail=4.0,
    gpu_vendor="intel",
    os_name="Windows",
    os_ver="10.0.22631",
    is_hybrid_cpu=False,
    cpu_p_cores=0,
    cpu_e_cores=0,
) -> SystemInfo:
    """Helper to generate mock SystemInfo."""
    return SystemInfo(
        cpu_name="Mock CPU",
        cpu_cores_physical=cores_physical,
        cpu_cores_logical=cores_logical,
        cpu_freq_mhz=3000.0,
        ram_total_gb=ram_total,
        ram_available_gb=ram_avail,
        gpu_name="Mock GPU",
        gpu_vram_mb=4096,
        gpu_vendor=gpu_vendor,
        os_name=os_name,
        os_version=os_ver,
        os_arch="64bit",
        python_version="3.12.0",
        python_arch="64bit",
        vlc_version="3.0.20",
        vlc_arch="64bit",
        is_hybrid_cpu=is_hybrid_cpu,
        cpu_p_cores=cpu_p_cores,
        cpu_e_cores=cpu_e_cores,
    )


class TestAutoTuner(unittest.TestCase):
    """Test AutoTuner dynamic hardware optimization."""

    def test_recommend_decode_threads(self):
        """Test CPU core boundaries for decode threads."""
        tuner_2c = AutoTuner(create_mock_sys_info(cores_logical=2))
        self.assertEqual(tuner_2c.recommend_decode_threads(), 1)

        tuner_4c = AutoTuner(create_mock_sys_info(cores_logical=4))
        self.assertEqual(tuner_4c.recommend_decode_threads(), 1)

        tuner_8c = AutoTuner(create_mock_sys_info(cores_logical=8))
        self.assertEqual(tuner_8c.recommend_decode_threads(), 2)

        tuner_14c = AutoTuner(create_mock_sys_info(cores_logical=14))
        self.assertEqual(tuner_14c.recommend_decode_threads(), 4)

        tuner_20c = AutoTuner(create_mock_sys_info(cores_logical=20))
        self.assertEqual(tuner_20c.recommend_decode_threads(), 6)

    def test_recommend_decode_threads_hybrid(self):
        """On hybrid CPUs (P/E cores), decoder threads must match physical P-cores to eliminate stragglers."""
        # 6 P-cores + 8 E-cores (e.g. i5-13500) -> 6 threads
        tuner_6p = AutoTuner(create_mock_sys_info(cores_logical=20, is_hybrid_cpu=True, cpu_p_cores=6, cpu_e_cores=8))
        self.assertEqual(tuner_6p.recommend_decode_threads(), 6)

        # 8 P-cores + 16 E-cores (e.g. i9-13900) -> 8 threads
        tuner_8p = AutoTuner(create_mock_sys_info(cores_logical=32, is_hybrid_cpu=True, cpu_p_cores=8, cpu_e_cores=16))
        self.assertEqual(tuner_8p.recommend_decode_threads(), 8)

        # 12 P-cores -> capped at 8
        tuner_12p = AutoTuner(create_mock_sys_info(cores_logical=36, is_hybrid_cpu=True, cpu_p_cores=12, cpu_e_cores=12))
        self.assertEqual(tuner_12p.recommend_decode_threads(), 8)

        # 4 P-cores (e.g. i3/laptop hybrid) -> 4 threads
        tuner_4p = AutoTuner(create_mock_sys_info(cores_logical=12, is_hybrid_cpu=True, cpu_p_cores=4, cpu_e_cores=4))
        self.assertEqual(tuner_4p.recommend_decode_threads(), 4)

    def test_recommend_thread_pool_size(self):
        """Worker count in background thread pool based on CPU topology."""
        # Standard <= 4 cores -> 1 worker
        tuner_4c = AutoTuner(create_mock_sys_info(cores_logical=4))
        self.assertEqual(tuner_4c.recommend_thread_pool_size(), 1)

        # Standard > 4 cores -> 2 workers
        tuner_8c = AutoTuner(create_mock_sys_info(cores_logical=8))
        self.assertEqual(tuner_8c.recommend_thread_pool_size(), 2)

        # Hybrid with >= 4 E-cores -> 4 workers (offload to E-cores)
        tuner_hybrid = AutoTuner(create_mock_sys_info(cores_logical=20, is_hybrid_cpu=True, cpu_p_cores=6, cpu_e_cores=8))
        self.assertEqual(tuner_hybrid.recommend_thread_pool_size(), 4)

        # Hybrid with < 4 E-cores -> 2 workers
        tuner_hybrid_few_e = AutoTuner(create_mock_sys_info(cores_logical=12, is_hybrid_cpu=True, cpu_p_cores=4, cpu_e_cores=2))
        self.assertEqual(tuner_hybrid_few_e.recommend_thread_pool_size(), 2)

    def test_get_recommendations_display_hybrid(self):
        """Verify display text highlights P-core decoding and E-core workers on hybrid CPUs."""
        sys_info = create_mock_sys_info(cores_logical=20, is_hybrid_cpu=True, cpu_p_cores=6, cpu_e_cores=8)
        tuner = AutoTuner(sys_info)
        disp = tuner.get_recommendations_display()
        self.assertIn("6 P-cores", disp["Decode threads"])
        self.assertIn("8 E-cores", disp["Thread pool"])

    def test_recommend_hw_accel(self):
        """Test GPU vendor and OS detection for hardware acceleration."""
        tuner_nvidia_win10 = AutoTuner(create_mock_sys_info(gpu_vendor="nvidia", os_ver="10.0"))
        self.assertEqual(tuner_nvidia_win10.recommend_hw_accel(), "d3d11va")

        tuner_amd_win11 = AutoTuner(create_mock_sys_info(gpu_vendor="amd", os_ver="11.0"))
        self.assertEqual(tuner_amd_win11.recommend_hw_accel(), "d3d11va")

        tuner_intel_win7 = AutoTuner(create_mock_sys_info(gpu_vendor="intel", os_ver="6.1"))
        self.assertEqual(tuner_intel_win7.recommend_hw_accel(), "dxva2")

        tuner_unknown = AutoTuner(create_mock_sys_info(gpu_vendor="unknown"))
        self.assertIsNone(tuner_unknown.recommend_hw_accel())

    def test_recommend_network_buffer(self):
        """Test network caching buffer recommendation based on RAM."""
        tuner_low_ram = AutoTuner(create_mock_sys_info(ram_total=4.0, ram_avail=2.0))
        self.assertEqual(tuner_low_ram.recommend_network_buffer(), 1500)

        tuner_mid_ram = AutoTuner(create_mock_sys_info(ram_total=8.0, ram_avail=4.5))
        self.assertEqual(tuner_mid_ram.recommend_network_buffer(), 3000)

        tuner_high_ram = AutoTuner(create_mock_sys_info(ram_total=32.0, ram_avail=16.0))
        self.assertEqual(tuner_high_ram.recommend_network_buffer(), 5000)

    def test_build_vlc_args_auto(self):
        """Test automatic VLC args generation without user overrides."""
        sys_info = create_mock_sys_info(
            cores_logical=20,
            ram_total=32.0,
            ram_avail=16.0,
            gpu_vendor="nvidia",
            os_ver="10.0.22631",
        )
        tuner = AutoTuner(sys_info, user_settings={})
        args = tuner.build_vlc_args()

        self.assertIn("--quiet", args)
        self.assertIn("--no-video-title-show", args)
        self.assertIn("--network-caching=5000", args)
        self.assertIn("--file-caching=2500", args)
        self.assertIn("--avcodec-hw=d3d11va", args)
        self.assertIn("--avcodec-threads=6", args)

    def test_user_override_priority(self):
        """User Settings must take absolute priority over auto-detect."""
        sys_info = create_mock_sys_info(cores_logical=20, ram_total=32.0, gpu_vendor="nvidia")
        custom_settings = {
            "streaming": {
                "network_caching": 2000,
                "hardware_decode": False,
                "decode_threads": 2,
            }
        }
        tuner = AutoTuner(sys_info, user_settings=custom_settings)
        args = tuner.build_vlc_args()

        # Overridden network caching
        self.assertIn("--network-caching=2000", args)
        # Hardware decode disabled by user
        self.assertFalse(any(a.startswith("--avcodec-hw") for a in args))
        # Overridden decode threads
        self.assertIn("--avcodec-threads=2", args)


if __name__ == "__main__":
    unittest.main()
