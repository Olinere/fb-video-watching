import unittest

from main.chapters import normalize_chapters
from main.collection import CollectionEntry, ResolvedCollection
from main.playback_queue import PlaybackQueue, QueueItem


class TestPlaybackQueue(unittest.TestCase):
    def test_queue_is_bounded_and_never_contains_stream_fields(self):
        queue = PlaybackQueue(max_items=2)
        queue.add(QueueItem("https://example.test/a", title="A"))
        queue.add(QueueItem("https://example.test/b", title="B"))
        with self.assertRaises(OverflowError):
            queue.add(QueueItem("https://example.test/c"))
        self.assertFalse(any("stream_url" in item for item in queue.snapshot()))
        self.assertFalse(any("http_headers" in item for item in queue.snapshot()))

    def test_next_skips_failed_only_when_selecting_next(self):
        queue = PlaybackQueue()
        first = queue.add(QueueItem("https://example.test/1"))
        failed = queue.add(QueueItem("https://example.test/2"))
        third = queue.add(QueueItem("https://example.test/3"))
        queue.mark_status(first.queue_id, "playing")
        queue.mark_status(failed.queue_id, "error", "unavailable")
        self.assertIs(queue.next_item(), third)
        self.assertEqual(third.status, "pending")

    def test_restore_is_bounded_and_preserves_metadata_only(self):
        queue = PlaybackQueue(max_items=1)
        source = QueueItem("https://example.test/a", title="A")
        source.status = "error"
        source.error_message = "broken"
        restored = queue.restore([source.snapshot(), QueueItem("https://example.test/b").snapshot()])
        self.assertEqual(restored, 1)
        item = queue.current_item()
        self.assertIsNone(item)
        self.assertEqual(queue.snapshot()[0]["error_message"], "broken")

    def test_move_and_loop(self):
        queue = PlaybackQueue(loop_enabled=True)
        first = queue.add(QueueItem("https://example.test/1"))
        second = queue.add(QueueItem("https://example.test/2"))
        queue.mark_status(first.queue_id, "playing")
        queue.mark_status(second.queue_id, "skipped")
        self.assertIs(queue.next_item(), first)
        self.assertTrue(queue.move(first.queue_id, 1))
        self.assertEqual(queue.snapshot()[1]["source_url"], first.source_url)


class TestChapterAndCollectionModels(unittest.TestCase):
    def test_chapters_are_normalized(self):
        chapters = normalize_chapters([
            {"title": "Late", "start_time": 80, "end_time": 100},
            {"title": "Intro", "start_time": 0, "end_time": 10},
            {"title": "Intro", "start_time": 0, "end_time": 10},
            {"title": "", "start_time": 20},
        ], duration_ms=90_000)
        self.assertEqual([chapter.title for chapter in chapters], ["Intro", "Late"])
        self.assertEqual(chapters[1].start_ms, 80_000)
        self.assertEqual(chapters[1].end_ms, 90_000)

    def test_collection_is_compact_metadata(self):
        collection = ResolvedCollection(
            "https://example.test/list",
            "List",
            (CollectionEntry("https://example.test/a", title="A"),),
        )
        self.assertEqual(len(collection.entries), 1)
        self.assertIsNone(collection.entries[0].thumbnail_url)


if __name__ == "__main__":
    unittest.main()
