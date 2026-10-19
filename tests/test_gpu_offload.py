"""
Unit tests for Smart GPU Offloading (Hybrid Dual-GPU iGPU offload for gaming).
Tests:
- CPU iGPU capability detection (excluding F/KF series, Xeon, AMD non-G).
- GPU integrated vs discrete naming classification.
- AutoTuner GPU preference recommendations.
- VLC args generation with DirectX 11 adapter routing.
- Windows UserGpuPreferences registry configuration.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.system_info import SystemInfo, GPUInfo
from main.auto_tune import AutoTuner
from main.platform_utils import apply_windows_gpu_preference, get_windows_gpu_preference


class TestGPUOffload(unittest.TestCase):
    """Test Smart GPU Offload architecture and edge cases."""

    def test_cpu_igpu_capability_detection(self):
        """Verify CPU classification correctly excludes F/KF series without iGPU."""
        # Non-iGPU CPUs (Intel F/KF, AMD non-G AM4, Ryzen 7500F, Xeon)
        no_igpu_cases = [
            "12th Gen Intel(R) Core(TM) i5-12400F",
            "Intel(R) Core(TM) i7-13700KF @ 3.40GHz",
            "Intel(R) Core(TM) i9-14900F",
            "Intel(R) Core(TM) i3-10100F",
            "AMD Ryzen 5 7500F 6-Core Processor",
            "AMD Ryzen 5 3600 6-Core Processor",
            "AMD Ryzen 5 5600X 6-Core Processor",
            "AMD Ryzen 7 5800X 8-Core Processor",
            "Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz",
            "AMD Ryzen Threadripper 3960X",
        ]
        for name in no_igpu_cases:
            self.assertFalse(
                SystemInfo._detect_cpu_igpu_capability(name),
                f"Expected False for {name}"
            )

        # Has-iGPU CPUs (Intel standard/K, AMD G-series, AMD Ryzen 7000+ non-F)
        has_igpu_cases = [
            "13th Gen Intel(R) Core(TM) i5-13500",
            "Intel(R) Core(TM) i7-13700K",
            "Intel(R) Core(TM) i5-10400",
            "AMD Ryzen 7 5700G with Radeon Graphics",
            "AMD Ryzen 5 4600G with Radeon Graphics",
            "AMD Ryzen 7 7700X 8-Core Processor",
            "AMD Ryzen 9 7950X 16-Core Processor",
        ]
        for name in has_igpu_cases:
            self.assertTrue(
                SystemInfo._detect_cpu_igpu_capability(name),
                f"Expected True for {name}"
            )

    def test_gpu_integrated_classification(self):
        """Verify integrated vs discrete GPU classification."""
        # Integrated
        self.assertTrue(SystemInfo._is_integrated_gpu_name("Intel(R) UHD Graphics 770"))
        self.assertTrue(SystemInfo._is_integrated_gpu_name("Intel(R) Iris(R) Xe Graphics"))
        self.assertTrue(SystemInfo._is_integrated_gpu_name("Intel(R) HD Graphics 630"))
        self.assertTrue(SystemInfo._is_integrated_gpu_name("AMD Radeon(TM) Graphics"))
        self.assertTrue(SystemInfo._is_integrated_gpu_name("AMD Radeon Vega 8 Graphics"))

        # Discrete
        self.assertFalse(SystemInfo._is_integrated_gpu_name("NVIDIA GeForce RTX 4060"))
        self.assertFalse(SystemInfo._is_integrated_gpu_name("NVIDIA GeForce GTX 1660 Ti"))
        self.assertFalse(SystemInfo._is_integrated_gpu_name("AMD Radeon RX 6600"))
        self.assertFalse(SystemInfo._is_integrated_gpu_name("AMD Radeon RX 7900 XTX"))
        self.assertFalse(SystemInfo._is_integrated_gpu_name("Intel(R) Arc(TM) A770 Graphics"))

    def test_auto_tuner_gpu_preference_recommendations(self):
        """Verify AutoTuner routes to iGPU when hybrid dual-GPU is active, and dGPU otherwise."""
        # Case 1: Hybrid Dual-GPU with active iGPU and CPU with iGPU
        hybrid_sys = SystemInfo(
            cpu_name="13th Gen Intel(R) Core(TM) i5-13500",
            cpu_cores_physical=14,
            cpu_cores_logical=20,
            cpu_freq_mhz=2500.0,
            ram_total_gb=32.0,
            ram_available_gb=16.0,
            gpu_name="NVIDIA GeForce RTX 4060",
            gpu_vram_mb=8192,
            gpu_vendor="nvidia",
            os_name="Windows",
            os_version="10.0.22631",
            os_arch="64bit",
            python_version="3.10.11",
            python_arch="64bit",
            vlc_version="3.0.20",
            vlc_arch="64bit",
            gpu_topology="hybrid_dual_gpu",
            discrete_gpu_name="NVIDIA GeForce RTX 4060",
            integrated_gpu_name="Intel(R) UHD Graphics 770",
            igpu_adapter_index=1,
            cpu_has_igpu=True,
        )

        tuner_auto = AutoTuner(hybrid_sys, {"performance": {"gpu_preference": "auto"}})
        self.assertEqual(tuner_auto.recommend_gpu_preference(), "power_saving")

        # User explicit overrides
        tuner_force_dgpu = AutoTuner(hybrid_sys, {"performance": {"gpu_preference": "discrete"}})
        self.assertEqual(tuner_force_dgpu.recommend_gpu_preference(), "high_performance")

        tuner_force_igpu = AutoTuner(hybrid_sys, {"performance": {"gpu_preference": "integrated"}})
        self.assertEqual(tuner_force_igpu.recommend_gpu_preference(), "power_saving")

        tuner_sw = AutoTuner(hybrid_sys, {"performance": {"gpu_preference": "software"}})
        self.assertEqual(tuner_sw.recommend_gpu_preference(), "software")
        self.assertIsNone(tuner_sw.recommend_hw_accel())

        # Case 2: CPU has iGPU, but iGPU is disabled (Code 22 / BIOS) -> Single Discrete
        disabled_igpu_sys = SystemInfo(
            cpu_name="13th Gen Intel(R) Core(TM) i5-13500",
            cpu_cores_physical=14,
            cpu_cores_logical=20,
            cpu_freq_mhz=2500.0,
            ram_total_gb=32.0,
            ram_available_gb=16.0,
            gpu_name="NVIDIA GeForce RTX 4060",
            gpu_vram_mb=8192,
            gpu_vendor="nvidia",
            os_name="Windows",
            os_version="10.0.22631",
            os_arch="64bit",
            python_version="3.10.11",
            python_arch="64bit",
            vlc_version="3.0.20",
            vlc_arch="64bit",
            gpu_topology="single_discrete",
            discrete_gpu_name="NVIDIA GeForce RTX 4060",
            integrated_gpu_name="Intel(R) UHD Graphics 770 (Đã tắt trong Windows/BIOS)",
            igpu_adapter_index=None,
            cpu_has_igpu=True,
        )
        tuner_disabled = AutoTuner(disabled_igpu_sys, {"performance": {"gpu_preference": "auto"}})
        self.assertEqual(tuner_disabled.recommend_gpu_preference(), "high_performance")

        # Case 3: Intel F series CPU -> Single Discrete
        f_cpu_sys = SystemInfo(
            cpu_name="12th Gen Intel(R) Core(TM) i5-12400F",
            cpu_cores_physical=6,
            cpu_cores_logical=12,
            cpu_freq_mhz=2500.0,
            ram_total_gb=16.0,
            ram_available_gb=8.0,
            gpu_name="NVIDIA GeForce RTX 3060",
            gpu_vram_mb=12288,
            gpu_vendor="nvidia",
            os_name="Windows",
            os_version="10.0.22631",
            os_arch="64bit",
            python_version="3.10.11",
            python_arch="64bit",
            vlc_version="3.0.20",
            vlc_arch="64bit",
            gpu_topology="single_discrete",
            discrete_gpu_name="NVIDIA GeForce RTX 3060",
            integrated_gpu_name=None,
            igpu_adapter_index=None,
            cpu_has_igpu=False,
        )
        tuner_f_cpu = AutoTuner(f_cpu_sys, {"performance": {"gpu_preference": "auto"}})
        self.assertEqual(tuner_f_cpu.recommend_gpu_preference(), "high_performance")

    def test_vlc_args_hw_accel_validity(self):
        """Verify VLC arguments are valid and do not contain invalid CLI flags."""
        hybrid_sys = SystemInfo(
            cpu_name="13th Gen Intel(R) Core(TM) i5-13500",
            cpu_cores_physical=14,
            cpu_cores_logical=20,
            cpu_freq_mhz=2500.0,
            ram_total_gb=32.0,
            ram_available_gb=16.0,
            gpu_name="NVIDIA GeForce RTX 4060",
            gpu_vram_mb=8192,
            gpu_vendor="nvidia",
            os_name="Windows",
            os_version="10.0.22631",
            os_arch="64bit",
            python_version="3.10.11",
            python_arch="64bit",
            vlc_version="3.0.20",
            vlc_arch="64bit",
            gpu_topology="hybrid_dual_gpu",
            discrete_gpu_name="NVIDIA GeForce RTX 4060",
            integrated_gpu_name="Intel(R) UHD Graphics 770",
            igpu_adapter_index=1,
            cpu_has_igpu=True,
        )
        tuner = AutoTuner(hybrid_sys, {"performance": {"gpu_preference": "auto"}})
        args = tuner.build_vlc_args()
        self.assertIn("--avcodec-hw=d3d11va", args)
        for arg in args:
            self.assertFalse(arg.startswith("--direct3d11-adapter"))
            self.assertFalse(arg.startswith("--d3d11-adapter"))

    def test_windows_gpu_preference_registry(self):
        """Verify Windows UserGpuPreferences registry read/write roundtrip on Windows."""
        if sys.platform == "win32":
            res = apply_windows_gpu_preference(mode="power_saving")
            self.assertTrue(res)
            pref = get_windows_gpu_preference()
            self.assertEqual(pref, "power_saving")


if __name__ == "__main__":
    unittest.main()
