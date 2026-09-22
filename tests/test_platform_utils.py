"""
Unit tests for main/platform_utils.py CPU and OS optimizations.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.system_info import SystemInfo
from main.platform_utils import (
    disable_process_power_throttling,
    enable_high_precision_timer,
    disable_high_precision_timer,
    apply_cpu_affinity,
)


class TestPlatformUtils(unittest.TestCase):
    """Test OS integrations and CPU optimizations."""

    def test_multimedia_timer(self):
        """Test enabling and disabling 1ms Windows multimedia timer."""
        if sys.platform == "win32":
            res_enable = enable_high_precision_timer()
            self.assertTrue(res_enable)
            res_disable = disable_high_precision_timer()
            self.assertTrue(res_disable)
        else:
            self.assertFalse(enable_high_precision_timer())
            self.assertFalse(disable_high_precision_timer())

    def test_process_power_throttling(self):
        """Test disabling Windows EcoQoS / Power Throttling."""
        res = disable_process_power_throttling()
        if sys.platform == "win32":
            # On Windows 10/11, SetProcessInformation should succeed
            self.assertTrue(res)
        else:
            self.assertFalse(res)

    def test_apply_cpu_affinity(self):
        """Test CPU Core Affinity application for 'auto', 'all', and 'p_cores'."""
        info = SystemInfo.detect()

        # Mode: auto
        res_auto = apply_cpu_affinity("auto", info)
        self.assertTrue(res_auto)

        # Mode: all
        res_all = apply_cpu_affinity("all", info)
        self.assertTrue(res_all)

        # Mode: p_cores
        res_p = apply_cpu_affinity("p_cores", info)
        self.assertTrue(res_p)

    def test_get_monitor_bounds_and_apply_fullscreen(self):
        """Test get_monitor_bounds_for_window and apply_fullscreen_on_monitor."""
        import tkinter as tk
        from main.platform_utils import get_monitor_bounds_for_window, apply_fullscreen_on_monitor

        root = tk.Tk()
        try:
            # Keep the native fullscreen positioning test from taking over the
            # user's desktop when the suite is run interactively.
            root.withdraw()
            root.geometry("400x300+100+100")
            root.update()

            bounds = get_monitor_bounds_for_window(root)
            self.assertIsNotNone(bounds)
            self.assertEqual(len(bounds), 4)
            mx, my, mw, mh = bounds
            self.assertGreater(mw, 0)
            self.assertGreater(mh, 0)

            # Test apply_fullscreen_on_monitor doesn't raise exception
            apply_fullscreen_on_monitor(root, bounds)
            apply_fullscreen_on_monitor(root, None)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
