"""
Subtitle cue parsing and serialization module.
Supports WebVTT and SubRip (SRT) format cue extraction, normalization,
and serialization for AI translation and format transformation.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional, Union

# Matches WebVTT & SRT timestamp formats:
# 00:00:01.000 --> 00:00:04.000 or 00:01,000 --> 00:04,000
VTT_TIMING_REGEX = re.compile(
    r"((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})(?:[ \t]+([^\r\n]*))?"
)


@dataclass
class SubtitleCue:
    """Represents a single timed caption / subtitle cue."""
    index: int
    start: str
    end: str
    text: str
    settings: str = ""

    def __post_init__(self):
        # Normalize comma separator to period for WebVTT compliance
        self.start = self.start.replace(",", ".")
        self.end = self.end.replace(",", ".")
        # Ensure hh:mm:ss.mmm format (add 00: prefix if only mm:ss.mmm)
        if self.start.count(":") == 1:
            self.start = f"00:{self.start}"
        if self.end.count(":") == 1:
            self.end = f"00:{self.end}"


class CueParser:
    """Parser and serializer for subtitle cue streams."""

    @staticmethod
    def parse_vtt(content: str) -> List[SubtitleCue]:
        """Parse WebVTT content into a list of SubtitleCue objects."""
        cues: List[SubtitleCue] = []
        if not content:
            return cues

        # Normalize line endings
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")

        idx = 1
        i = 0
        n = len(lines)

        # Skip header ("WEBVTT", etc.)
        while i < n and not VTT_TIMING_REGEX.search(lines[i]):
            i += 1

        while i < n:
            line = lines[i].strip()
            timing_match = VTT_TIMING_REGEX.search(line)

            if timing_match:
                start = timing_match.group(1).strip()
                end = timing_match.group(2).strip()
                settings = (timing_match.group(3) or "").strip()

                text_lines: List[str] = []
                i += 1
                while i < n and lines[i].strip():
                    # Clean up cue inline tags like <c>, <v>, <b>, etc. if needed, but preserve text
                    clean_line = lines[i].strip()
                    # Strip voice tag like <v Roger>
                    clean_line = re.sub(r"</?[a-zA-Z0-9_\-\.]+.*?>", "", clean_line).strip()
                    if clean_line:
                        text_lines.append(clean_line)
                    i += 1

                cue_text = "\n".join(text_lines).strip()
                if cue_text:
                    cues.append(SubtitleCue(
                        index=idx,
                        start=start,
                        end=end,
                        text=cue_text,
                        settings=settings,
                    ))
                    idx += 1
            else:
                i += 1

        return cues

    @staticmethod
    def serialize_vtt(cues: List[SubtitleCue]) -> str:
        """Serialize a list of SubtitleCue objects to WebVTT string format."""
        out = ["WEBVTT\n"]
        for cue in cues:
            settings_part = f" {cue.settings}" if cue.settings else ""
            out.append(f"{cue.index}\n{cue.start} --> {cue.end}{settings_part}\n{cue.text}\n")
        return "\n".join(out)

    @staticmethod
    def parse_srt(content: str) -> List[SubtitleCue]:
        """Parse SRT content into a list of SubtitleCue objects."""
        cues: List[SubtitleCue] = []
        if not content:
            return cues

        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r"\n\s*\n", normalized.strip())

        idx = 1
        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue

            timing_line_idx = -1
            for l_idx, l in enumerate(lines):
                if VTT_TIMING_REGEX.search(l):
                    timing_line_idx = l_idx
                    break

            if timing_line_idx == -1:
                continue

            match = VTT_TIMING_REGEX.search(lines[timing_line_idx])
            if match:
                start = match.group(1).strip()
                end = match.group(2).strip()
                text_lines = lines[timing_line_idx + 1 :]
                clean_text = "\n".join(text_lines).strip()
                if clean_text:
                    cues.append(SubtitleCue(
                        index=idx,
                        start=start,
                        end=end,
                        text=clean_text,
                    ))
                    idx += 1

        return cues

    @classmethod
    def parse_file(cls, file_path: Union[str, Path]) -> List[SubtitleCue]:
        """Auto-detect format and parse subtitle file into cues."""
        path = Path(file_path)
        if not path.is_file():
            return []

        encodings = ["utf-8-sig", "utf-8", "utf-16", "cp1258", "cp1252", "latin-1"]
        content = ""
        for enc in encodings:
            try:
                content = path.read_text(encoding=enc)
                break
            except Exception:
                continue

        ext = path.suffix.lower()
        if ext == ".vtt":
            return cls.parse_vtt(content)
        elif ext == ".srt":
            return cls.parse_srt(content)
        else:
            # Fallback: try vtt then srt
            cues = cls.parse_vtt(content)
            if not cues:
                cues = cls.parse_srt(content)
            return cues
