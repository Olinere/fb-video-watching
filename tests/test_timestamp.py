"""
Unit tests for main/timestamp.py.
Covers all formats specified in specs.md §10 and various edge cases.
"""

import unittest
import sys
from pathlib import Path

# Add project root to sys.path so tests can import main.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main.timestamp import parse_timestamp, format_timestamp


class TestTimestampParser(unittest.TestCase):
    """Test parse_timestamp function."""

    def test_specs_table_cases(self):
        """Test exact cases from specs.md §10."""
        self.assertEqual(parse_timestamp("90"), 90_000)
        self.assertEqual(parse_timestamp("1:30"), 90_000)
        self.assertEqual(parse_timestamp("1:01:30"), 3_690_000)
        self.assertEqual(parse_timestamp("1h30m"), 5_400_000)
        self.assertEqual(parse_timestamp("1h30m45s"), 5_445_000)
        self.assertEqual(parse_timestamp("30s"), 30_000)
        self.assertEqual(parse_timestamp("5m"), 300_000)

    def test_clock_formats(self):
        """Test various digital clock formats."""
        self.assertEqual(parse_timestamp("0"), 0)
        self.assertEqual(parse_timestamp("00"), 0)
        self.assertEqual(parse_timestamp("0:00"), 0)
        self.assertEqual(parse_timestamp("00:00:00"), 0)
        self.assertEqual(parse_timestamp("05:00"), 300_000)
        self.assertEqual(parse_timestamp("00:01:30"), 90_000)
        self.assertEqual(parse_timestamp("2:15:30"), 8_130_000)

    def test_human_unit_formats(self):
        """Test human readable unit combinations and casing."""
        self.assertEqual(parse_timestamp("2h"), 7_200_000)
        self.assertEqual(parse_timestamp("1H30M"), 5_400_000)
        self.assertEqual(parse_timestamp("1h 30m"), 5_400_000)
        self.assertEqual(parse_timestamp("1h 45s"), 3_645_000)
        self.assertEqual(parse_timestamp("10M 20S"), 620_000)

    def test_whitespace_handling(self):
        """Test leading and trailing whitespaces."""
        self.assertEqual(parse_timestamp("  90  "), 90_000)
        self.assertEqual(parse_timestamp("  1:30  "), 90_000)
        self.assertEqual(parse_timestamp("   1h30m45s   "), 5_445_000)

    def test_invalid_formats(self):
        """Test invalid inputs that should raise ValueError."""
        invalid_inputs = [
            "",
            "   ",
            "abc",
            "-10",
            "-1:30",
            "::",
            "1:2:3:4",
            "1h30x",
            "1x",
            "m5s",
            "1h-30m",
            None,
            123,  # non-string type
        ]
        for item in invalid_inputs:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    parse_timestamp(item)  # type: ignore


class TestTimestampFormatter(unittest.TestCase):
    """Test format_timestamp function."""

    def test_format_under_one_hour(self):
        self.assertEqual(format_timestamp(0), "00:00")
        self.assertEqual(format_timestamp(5_000), "00:05")
        self.assertEqual(format_timestamp(90_000), "01:30")
        self.assertEqual(format_timestamp(300_000), "05:00")
        self.assertEqual(format_timestamp(3_599_000), "59:59")

    def test_format_over_one_hour(self):
        self.assertEqual(format_timestamp(3_600_000), "01:00:00")
        self.assertEqual(format_timestamp(3_690_000), "01:01:30")
        self.assertEqual(format_timestamp(5_445_000), "01:30:45")
        self.assertEqual(format_timestamp(86_400_000), "24:00:00")

    def test_format_negative_clamped(self):
        self.assertEqual(format_timestamp(-5000), "00:00")


if __name__ == "__main__":
    unittest.main()
