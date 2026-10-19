"""Policy layer for queue transitions; contains no Tkinter or VLC code."""

from typing import Optional

from main.playback_queue import PlaybackQueue, QueueItem


class QueueController:
    """Keep queue transition rules separate from the application orchestrator."""

    def __init__(self, queue: PlaybackQueue, skip_failed_items: bool = False):
        self.queue = queue
        self.skip_failed_items = bool(skip_failed_items)

    def add_url(self, source_url: str, **metadata) -> QueueItem:
        return self.queue.add(QueueItem(source_url=source_url, **metadata))

    def begin(self, item: QueueItem) -> None:
        self.queue.mark_status(item.queue_id, "resolving")

    def resolved(self, item: QueueItem, *, title: Optional[str] = None,
                 duration_ms: Optional[int] = None, chapters=None,
                 canonical_url: Optional[str] = None) -> None:
        """Store compact metadata only; the direct stream stays in VLC scope."""
        if title:
            item.title = title
        if duration_ms is not None:
            item.duration_ms = duration_ms
        if chapters is not None:
            item.chapters = tuple(chapters)
        if canonical_url:
            item.canonical_url = canonical_url
        self.queue.mark_status(item.queue_id, "playing")

    def failed(self, item: QueueItem, error: str) -> Optional[QueueItem]:
        self.queue.mark_status(item.queue_id, "error", error)
        if self.skip_failed_items:
            return self.queue.next_item()
        return None

    def on_natural_end(self, item: Optional[QueueItem], *, loop_video: bool = False,
                       ab_repeat: bool = False) -> Optional[QueueItem]:
        """Advance only after a genuine natural end.

        A-B repeat and per-video loop have priority over the queue.  Errors and
        pauses never call this method from the application layer.
        """
        if item is None or ab_repeat or loop_video:
            return None
        self.queue.mark_status(item.queue_id, "played")
        return self.queue.next_item()

    def next_item(self) -> Optional[QueueItem]:
        """Manually advance to next playable item."""
        return self.queue.next_item()

    def previous_item(self) -> Optional[QueueItem]:
        """Manually navigate to previous playable item."""
        return self.queue.previous_item()

