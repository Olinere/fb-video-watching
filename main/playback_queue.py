"""Runtime playback queue independent of Tkinter, VLC and network code."""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Iterable, Optional
from uuid import uuid4

from main.chapters import Chapter
from main.constants import MAX_QUEUE_ITEMS

QUEUE_STATUSES = frozenset({
    "pending", "resolving", "ready", "playing", "played", "skipped", "error",
})


@dataclass(slots=True)
class QueueItem:
    """Queue metadata only.  Direct stream URLs must never be added here."""

    source_url: str
    queue_id: str = field(default_factory=lambda: uuid4().hex)
    canonical_url: Optional[str] = None
    source_name: Optional[str] = None
    content_id: Optional[str] = None
    title: str = "Video"
    thumbnail_url: Optional[str] = None
    duration_ms: Optional[int] = None
    chapters: tuple[Chapter, ...] = field(default_factory=tuple)
    status: str = "pending"
    position: int = 0
    error_message: Optional[str] = None
    privacy_only: bool = False
    description: Optional[str] = None

    def __post_init__(self) -> None:
        self.source_url = str(self.source_url).strip()
        if not self.source_url:
            raise ValueError("Queue item source_url cannot be empty")
        if self.status not in QUEUE_STATUSES:
            raise ValueError(f"Unknown queue status: {self.status}")
        self.title = (self.title or self.source_url).strip()
        self.chapters = tuple(self.chapters or ())

    def snapshot(self) -> dict[str, Any]:
        """Return persistence-safe metadata; no stream/auth/format fields."""
        return {
            "queue_id": self.queue_id,
            "source_url": self.source_url,
            "canonical_url": self.canonical_url,
            "source_name": self.source_name,
            "content_id": self.content_id,
            "title": self.title,
            "thumbnail_url": self.thumbnail_url,
            "duration_ms": self.duration_ms,
            "chapters": [
                {"index": c.index, "title": c.title, "start_ms": c.start_ms, "end_ms": c.end_ms}
                for c in self.chapters
            ],
            "status": self.status,
            "position": self.position,
            "error_message": self.error_message,
            "privacy_only": self.privacy_only,
            "description": self.description,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "QueueItem":
        chapters = tuple(
            Chapter(
                int(ch.get("index", index)),
                str(ch.get("title", "")),
                max(0, int(ch.get("start_ms", 0))),
                ch.get("end_ms"),
            )
            for index, ch in enumerate(data.get("chapters") or ())
            if isinstance(ch, dict) and str(ch.get("title", "")).strip()
        )
        return cls(
            source_url=str(data.get("source_url", "")),
            queue_id=str(data.get("queue_id") or uuid4().hex),
            canonical_url=data.get("canonical_url"),
            source_name=data.get("source_name"),
            content_id=data.get("content_id"),
            title=str(data.get("title") or "Video"),
            thumbnail_url=data.get("thumbnail_url"),
            duration_ms=data.get("duration_ms"),
            chapters=chapters,
            status=str(data.get("status") or "pending"),
            position=int(data.get("position", 0)),
            error_message=data.get("error_message"),
            privacy_only=bool(data.get("privacy_only", False)),
            description=data.get("description"),
        )


class PlaybackQueue:
    """Thread-safe in-memory queue with a strict bounded item count."""

    def __init__(self, max_items: int = MAX_QUEUE_ITEMS, loop_enabled: bool = False):
        self.max_items = max(1, int(max_items))
        self.loop_enabled = bool(loop_enabled)
        self._items: list[QueueItem] = []
        self._current_id: Optional[str] = None
        self._lock = RLock()

    @property
    def current_id(self) -> Optional[str]:
        with self._lock:
            return self._current_id

    @property
    def items(self) -> list[QueueItem]:
        with self._lock:
            return list(self._items)

    def get(self, queue_id: str) -> Optional[QueueItem]:
        with self._lock:
            return next((item for item in self._items if item.queue_id == queue_id), None)

    def clear_played(self) -> int:
        with self._lock:
            initial = len(self._items)
            self._items = [it for it in self._items if it.status != "played"]
            if self._current_id and not any(it.queue_id == self._current_id for it in self._items):
                self._current_id = None
            self._renumber()
            return initial - len(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def add(self, item: QueueItem) -> QueueItem:
        with self._lock:
            if len(self._items) >= self.max_items:
                raise OverflowError(f"Queue giới hạn {self.max_items} item để bảo vệ RAM.")
            if any(existing.queue_id == item.queue_id for existing in self._items):
                raise ValueError(f"Duplicate queue id: {item.queue_id}")
            item.position = len(self._items)
            self._items.append(item)
            return item

    def add_many(self, items: Iterable[QueueItem]) -> int:
        added = 0
        for item in items:
            self.add(item)
            added += 1
        return added

    def remove(self, queue_id: str) -> Optional[QueueItem]:
        with self._lock:
            index = next((i for i, item in enumerate(self._items) if item.queue_id == queue_id), None)
            if index is None:
                return None
            removed = self._items.pop(index)
            if self._current_id == queue_id:
                self._current_id = None
            self._renumber()
            return removed

    def move(self, queue_id: str, new_index: int) -> bool:
        with self._lock:
            old_index = next((i for i, item in enumerate(self._items) if item.queue_id == queue_id), None)
            if old_index is None:
                return False
            item = self._items.pop(old_index)
            self._items.insert(max(0, min(int(new_index), len(self._items))), item)
            self._renumber()
            return True

    def clear(self, keep_current: bool = False) -> None:
        with self._lock:
            if keep_current and self._current_id:
                current = self.current_item()
                self._items = [current] if current else []
            else:
                self._items.clear()
                self._current_id = None
            self._renumber()

    def current_item(self) -> Optional[QueueItem]:
        with self._lock:
            return next((item for item in self._items if item.queue_id == self._current_id), None)

    def next_item(self) -> Optional[QueueItem]:
        with self._lock:
            if not self._items:
                return None
            current_index = next((i for i, item in enumerate(self._items) if item.queue_id == self._current_id), -1)
            start = current_index + 1
            for item in self._items[start:]:
                if item.status not in {"skipped", "error"}:
                    self._current_id = item.queue_id
                    return item
            if self.loop_enabled:
                for item in self._items[:start or len(self._items)]:
                    if item.status not in {"skipped", "error"}:
                        self._current_id = item.queue_id
                        return item
            return None

    def previous_item(self) -> Optional[QueueItem]:
        with self._lock:
            current_index = next((i for i, item in enumerate(self._items) if item.queue_id == self._current_id), len(self._items))
            for item in reversed(self._items[:current_index]):
                if item.status not in {"skipped", "error"}:
                    self._current_id = item.queue_id
                    return item
            return None

    def mark_status(self, queue_id: str, status: str, error: Optional[str] = None) -> bool:
        if status not in QUEUE_STATUSES:
            raise ValueError(f"Unknown queue status: {status}")
        with self._lock:
            item = next((entry for entry in self._items if entry.queue_id == queue_id), None)
            if item is None:
                return False
            item.status = status
            item.error_message = error if status == "error" else None
            if status in ("playing", "resolving"):
                self._current_id = queue_id
            return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [item.snapshot() for item in self._items]

    def restore(self, snapshot: Iterable[dict[str, Any]]) -> int:
        restored: list[QueueItem] = []
        for data in snapshot:
            if len(restored) >= self.max_items:
                break
            if not isinstance(data, dict):
                continue
            try:
                restored.append(QueueItem.from_snapshot(data))
            except (TypeError, ValueError, KeyError):
                continue
        with self._lock:
            self._items = restored
            self._current_id = None
            self._renumber()
        return len(restored)

    def _renumber(self) -> None:
        for index, item in enumerate(self._items):
            item.position = index
