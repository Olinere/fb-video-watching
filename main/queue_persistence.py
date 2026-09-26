"""Opt-in, metadata-only queue persistence."""

import json
import os
from pathlib import Path
from typing import Optional

from main.playback_queue import PlaybackQueue
from main.privacy_session import RuntimePersistencePolicy


class QueuePersistence:
    """Persist queue snapshots atomically only when explicitly enabled."""

    def __init__(self, path: Path, policy: Optional[RuntimePersistencePolicy] = None):
        self.path = Path(path)
        self.policy = policy or RuntimePersistencePolicy(False)

    def save(self, queue: PlaybackQueue) -> bool:
        if not self.policy.allow_queue_persist():
            return False
        items = [item for item in queue.snapshot() if not item.get("privacy_only")]
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            os.replace(temp_path, self.path)
            return True
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def load(self, queue: PlaybackQueue) -> int:
        if not self.policy.allow_queue_persist() or not self.path.is_file():
            return 0
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return queue.restore(data if isinstance(data, list) else ())
        except (OSError, ValueError, TypeError):
            return 0

