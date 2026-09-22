"""
Timestamp parser and formatter utility.
Parses user input timestamps into milliseconds and formats milliseconds into human-readable strings.
"""

import re

# Regex for human-readable units: e.g. "1h30m45s", "1h", "5m", "30s", "1h 30m"
# Must contain at least one of h, m, s
_HUMAN_TIMESTAMP_PATTERN = re.compile(
    r"^(?=.*[hmsHMS])\s*(?:(\d+)\s*[hH])?\s*(?:(\d+)\s*[mM])?\s*(?:(\d+)\s*[sS])?\s*$"
)

# Regex for digital clock formats: e.g. "90", "1:30", "01:01:30"
_CLOCK_TIMESTAMP_PATTERN = re.compile(
    r"^(?:(?:(\d+):)?(\d+):)?(\d+)$"
)


def parse_timestamp(text: str) -> int:
    """
    Parse timestamp string into milliseconds.

    Supported formats:
    - Pure seconds: "90", "45"
    - Clock formats: "1:30" (mm:ss), "1:01:30" (hh:mm:ss)
    - Unit formats: "1h30m", "1h30m45s", "30s", "5m", "2h", "1h 45s"

    Args:
        text: Raw user input string.

    Returns:
        int: Duration / timestamp in milliseconds.

    Raises:
        ValueError: If input is empty, negative, or does not match any valid format.
    """
    if not isinstance(text, str):
        raise ValueError("Timestamp input must be a string")

    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Timestamp cannot be empty")

    # Prevent negative values
    if cleaned.startswith("-"):
        raise ValueError("Timestamp cannot be negative")

    # 1. Try human unit format: 1h30m45s, 5m, 30s, etc.
    human_match = _HUMAN_TIMESTAMP_PATTERN.match(cleaned)
    if human_match:
        hours = int(human_match.group(1)) if human_match.group(1) else 0
        minutes = int(human_match.group(2)) if human_match.group(2) else 0
        seconds = int(human_match.group(3)) if human_match.group(3) else 0
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds * 1000

    # 2. Try clock / numeric format: "90", "1:30", "1:01:30"
    clock_match = _CLOCK_TIMESTAMP_PATTERN.match(cleaned)
    if clock_match:
        part1, part2, part3 = clock_match.groups()
        if part1 is not None and part2 is not None:
            # hh:mm:ss
            hours = int(part1)
            minutes = int(part2)
            seconds = int(part3)
        elif part2 is not None:
            # mm:ss (part1 is None, part2 has minutes, part3 has seconds)
            hours = 0
            minutes = int(part2)
            seconds = int(part3)
        else:
            # ss only (part1 and part2 are None, part3 has seconds)
            hours = 0
            minutes = 0
            seconds = int(part3)

        total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds * 1000

    raise ValueError(f"Invalid timestamp format: '{text}'")


def format_timestamp(time_ms: int) -> str:
    """
    Format milliseconds into a display string (mm:ss or hh:mm:ss).

    Args:
        time_ms: Timestamp in milliseconds.

    Returns:
        str: Formatted string like "02:34" or "01:15:30".
    """
    if time_ms < 0:
        time_ms = 0

    total_seconds = int(time_ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
