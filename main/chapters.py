"""Small, validated chapter metadata models.

Chapters are intentionally kept separate from the resolver and GUI.  They are
metadata only; no media or thumbnail is loaded while normalising them.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Optional


@dataclass(frozen=True, slots=True)
class Chapter:
    """A seekable chapter expressed in milliseconds."""

    index: int
    title: str
    start_ms: int
    end_ms: Optional[int] = None


def normalize_chapters(
    raw_chapters: Optional[Iterable[dict[str, Any]]],
    duration_ms: Optional[int] = None,
) -> list[Chapter]:
    """Convert extractor chapter dictionaries into a small safe list.

    Invalid entries are ignored.  Duplicate/overlapping entries are removed
    conservatively so a malformed provider response cannot grow the UI model.
    """
    if not raw_chapters:
        return []

    candidates: list[tuple[str, int, Optional[int]]] = []
    for raw in raw_chapters:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        try:
            start_value = raw.get("start_time", raw.get("start_ms", 0))
            start_ms = max(0, int(float(start_value) * (1000 if "start_ms" not in raw else 1)))
        except (TypeError, ValueError):
            continue
        end_value = raw.get("end_time", raw.get("end_ms"))
        try:
            end_ms = None if end_value is None else max(0, int(float(end_value) * (1000 if "end_ms" not in raw else 1)))
        except (TypeError, ValueError):
            end_ms = None
        if duration_ms is not None:
            start_ms = min(start_ms, max(0, int(duration_ms)))
            if end_ms is not None:
                end_ms = min(end_ms, max(0, int(duration_ms)))
        if end_ms is not None and end_ms <= start_ms:
            end_ms = None
        candidates.append((title, start_ms, end_ms))

    candidates.sort(key=lambda item: (item[1], item[0]))
    result: list[Chapter] = []
    seen: set[tuple[str, int]] = set()
    for title, start_ms, end_ms in candidates:
        key = (title.casefold(), start_ms)
        if key in seen:
            continue
        # Providers occasionally return a chapter whose start is before the
        # previous chapter.  Keep the first entry and discard the bad one.
        if result and start_ms <= result[-1].start_ms:
            continue
        if result and result[-1].end_ms is not None and start_ms < result[-1].end_ms:
            prev = result[-1]
            result[-1] = Chapter(prev.index, prev.title, prev.start_ms, start_ms)
        seen.add(key)
        result.append(Chapter(len(result), title, start_ms, end_ms))
    return result
