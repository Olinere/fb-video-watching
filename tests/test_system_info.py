"""
Unit tests for main/system_info.py.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.system_info import SystemInfo


class TestSystemInfo(unittest.TestCase):
    """Test SystemInfo detection and formatting."""

    def test_detection_succeeds_without_exception(self):
        info = SystemInfo.detect()
        self.assertIsInstance(info, SystemInfo)
        self.assertIsInstance(info.cpu_name, str)
        self.assertGreaterEqual(info.cpu_cores_logical, 1)
        self.assertGreaterEqual(info.cpu_cores_physical, 1)
        self.assertGreater(info.ram_total_gb, 0.0)
        self.assertIn(info.gpu_vendor, ("nvidia", "amd", "intel", "unknown"))
        self.assertIn(info.os_arch, ("64bit", "32bit"))

    def test_display_dict_keys(self):
        info = SystemInfo.detect()
        display = info.to_display_dict()
        expected_keys = {"CPU", "RAM", "GPU", "Hệ điều hành", "Python", "VLC"}
        self.assertTrue(expected_keys.issubset(display.keys()))
        for val in display.values():
            self.assertIsInstance(val, str)
            self.assertGreater(len(val), 0)

    def test_format_copy_text(self):
        info = SystemInfo.detect()
        text = info.format_copy_text()
        self.assertIn("FB Video Watcher - System Information", text)
        self.assertIn("CPU:", text)
        self.assertIn("RAM:", text)
        self.assertIn("GPU:", text)

    def test_caching_and_force_refresh(self):
        info1 = SystemInfo.detect()
        info2 = SystemInfo.detect()
        self.assertIs(info1, info2)

        info3 = SystemInfo.detect(force_refresh=True)
        self.assertIsNotNone(info3)
        self.assertIs(info3, SystemInfo._cached_info)

    def test_hybrid_cpu_detection_fields(self):
        info = SystemInfo.detect()
        self.assertIsInstance(info.is_hybrid_cpu, bool)
        self.assertIsInstance(info.cpu_p_cores, int)
        self.assertIsInstance(info.cpu_e_cores, int)
        self.assertIsInstance(info.p_core_logical_indices, list)
        self.assertIsInstance(info.e_core_logical_indices, list)

    def test_hybrid_cpu_formatting(self):
        # Mock hybrid CPU
        hybrid_info = SystemInfo(
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
            is_hybrid_cpu=True,
            cpu_p_cores=6,
            cpu_e_cores=8,
            p_core_logical_indices=list(range(12)),
            e_core_logical_indices=list(range(12, 20)),
        )
        display = hybrid_info.to_display_dict()
        self.assertIn("6P + 8E / 20T", display["CPU"])
        copy_text = hybrid_info.format_copy_text()
        self.assertIn("6P + 8E / 20T", copy_text)

        # Mock standard non-hybrid CPU
        std_info = SystemInfo(
            cpu_name="AMD Ryzen 7 5800X",
            cpu_cores_physical=8,
            cpu_cores_logical=16,
            cpu_freq_mhz=3800.0,
            ram_total_gb=16.0,
            ram_available_gb=8.0,
            gpu_name="AMD Radeon RX 6700 XT",
            gpu_vram_mb=12288,
            gpu_vendor="amd",
            os_name="Windows",
            os_version="10.0.22631",
            os_arch="64bit",
            python_version="3.10.11",
            python_arch="64bit",
            vlc_version="3.0.20",
            vlc_arch="64bit",
            is_hybrid_cpu=False,
            cpu_p_cores=8,
            cpu_e_cores=0,
        )
        std_display = std_info.to_display_dict()
        self.assertIn("8C/16T", std_display["CPU"])
        self.assertNotIn("+", std_display["CPU"])


if __name__ == "__main__":
    unittest.main()
