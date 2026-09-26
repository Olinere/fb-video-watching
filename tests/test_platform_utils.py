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

    def test_apply_window_icon(self):
        """Test apply_window_icon sets icons without raising exceptions."""
        import tkinter as tk
        from main.platform_utils import apply_window_icon
        from main.constants import ICON_FILE

        root = tk.Tk()
        try:
            root.withdraw()
            apply_window_icon(root, ICON_FILE)
            root.deiconify()
            apply_window_icon(root, ICON_FILE)
        finally:
            root.destroy()

    def test_trim_process_memory(self):
        """Test Win32 process working set trimming."""
        from main.platform_utils import trim_process_memory
        # Must execute cleanly without exceptions
        trim_process_memory()

    def test_get_app_launch_command(self):
        """Test get_app_launch_command returns a valid formatted command string."""
        from main.platform_utils import get_app_launch_command
        cmd = get_app_launch_command()
        self.assertIsInstance(cmd, str)
        self.assertTrue(cmd.endswith('"%1"'))
        self.assertTrue(cmd.startswith('"'))

    def test_fbvw_protocol_registration_lifecycle(self):
        """Test register, check status, and unregister fbvw protocol."""
        from main.platform_utils import (
            register_fbvw_protocol,
            unregister_fbvw_protocol,
            is_fbvw_protocol_registered,
        )
        if sys.platform != "win32":
            self.assertFalse(register_fbvw_protocol())
            self.assertFalse(is_fbvw_protocol_registered())
            return

        initial_state = is_fbvw_protocol_registered()
        try:
            # Register
            reg_ok = register_fbvw_protocol()
            self.assertTrue(reg_ok)
            self.assertTrue(is_fbvw_protocol_registered())

            # Unregister
            unreg_ok = unregister_fbvw_protocol()
            self.assertTrue(unreg_ok)
            self.assertFalse(is_fbvw_protocol_registered())
        finally:
            # Restore initial state if it was originally registered
            if initial_state:
                register_fbvw_protocol()
            else:
                unregister_fbvw_protocol()


if __name__ == "__main__":
    unittest.main()

