"""
History Manager module.
Handles watch history and resume playback using SQLite with WAL mode.
Strictly adheres to specs.md §4.4 and Edge Cases §7.5 (WAL mode, corruption recovery).
Guarantees zero connection and handle leaks via explicit context management.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sqlite3
from typing import Optional, List, Dict, Any, Generator

from main.constants import CONFIG_DIR, HISTORY_DB, get_config_dir


@dataclass
class HistoryEntry:
    """Represents a saved video history item."""
    id: int
    url: str
    title: str
    duration_ms: int
    last_position: int
    watch_count: int
    first_watched: str
    last_watched: str
    thumbnail_url: Optional[str]
    is_bookmarked: bool = False


class HistoryManager:
    """Manages watch history in SQLite with WAL mode for concurrent instance safety and leak prevention."""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize HistoryManager.

        Args:
            db_path: Path to SQLite database file. Defaults to get_config_dir() / "history.db".
        """
        self.db_path = db_path or (get_config_dir() / "history.db")
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self) -> None:
        """Ensure parent directory exists."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @contextmanager
    def _db_cursor(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager that yields an open SQLite connection and guarantees
        both commit/rollback AND explicit connection closure to eliminate handle leaks.
        """
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema, handling corruption recovery (§7.5 case #36)."""
        create_sql = """
            CREATE TABLE IF NOT EXISTS watch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                duration_ms INTEGER DEFAULT 0,
                last_position INTEGER DEFAULT 0,
                watch_count INTEGER DEFAULT 1,
                first_watched TEXT DEFAULT (datetime('now', 'localtime')),
                last_watched TEXT DEFAULT (datetime('now', 'localtime')),
                thumbnail_url TEXT,
                is_bookmarked INTEGER DEFAULT 0
            );
        """
        def _setup(conn):
            conn.execute(create_sql)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_watch_history_url ON watch_history(url);")
            try:
                conn.execute("ALTER TABLE watch_history ADD COLUMN is_bookmarked INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass

        try:
            with self._db_cursor() as conn:
                _setup(conn)
        except sqlite3.DatabaseError:
            # Handle corrupted database: delete and recreate safely
            try:
                if self.db_path.exists():
                    self.db_path.unlink()
            except OSError:
                pass
            with self._db_cursor() as conn:
                _setup(conn)

    def record_playback_start(
        self,
        url: str,
        title: Optional[str] = None,
        duration_ms: Optional[int] = None,
        thumbnail_url: Optional[str] = None,
    ) -> None:
        """Record the start of video playback. Increments watch_count by 1."""
        if not url:
            return
        try:
            with self._db_cursor() as conn:
                conn.execute("""
                    INSERT INTO watch_history (url, title, duration_ms, last_position, thumbnail_url, watch_count, first_watched, last_watched)
                    VALUES (:url, :title, :duration_ms, 0, :thumbnail_url, 1, datetime('now', 'localtime'), datetime('now', 'localtime'))
                    ON CONFLICT(url) DO UPDATE SET
                        watch_count = watch_count + 1,
                        last_watched = datetime('now', 'localtime'),
                        title = COALESCE(:title, title),
                        duration_ms = COALESCE(:duration_ms, duration_ms),
                        thumbnail_url = COALESCE(:thumbnail_url, thumbnail_url);
                """, {
                    "url": url,
                    "title": title,
                    "duration_ms": duration_ms or 0,
                    "thumbnail_url": thumbnail_url,
                })
        except (sqlite3.Error, OSError):
            pass

    def update_position(self, url: str, position_ms: int, duration_ms: Optional[int] = None) -> None:
        """
        Update playback position without inflating watch_count.
        Lightweight update designed for periodic autosave.
        """
        if not url:
            return
        try:
            with self._db_cursor() as conn:
                conn.execute("""
                    UPDATE watch_history
                    SET last_position = :last_position,
                        last_watched = datetime('now', 'localtime'),
                        duration_ms = CASE WHEN :duration_ms > 0 THEN :duration_ms ELSE duration_ms END
                    WHERE url = :url;
                """, {
                    "url": url,
                    "last_position": max(0, int(position_ms)),
                    "duration_ms": duration_ms or 0,
                })
        except (sqlite3.Error, OSError):
            pass

    def save_position(
        self,
        url: str,
        position_ms: int,
        title: Optional[str] = None,
        duration_ms: Optional[int] = None,
        thumbnail_url: Optional[str] = None,
    ) -> None:
        """
        Record or update playback position for a URL.
        Preserves watch_count on updates instead of incrementing every tick.
        """
        if not url:
            return

        try:
            with self._db_cursor() as conn:
                conn.execute("""
                    INSERT INTO watch_history (url, title, duration_ms, last_position, thumbnail_url, watch_count, first_watched, last_watched)
                    VALUES (:url, :title, :duration_ms, :last_position, :thumbnail_url, 1, datetime('now', 'localtime'), datetime('now', 'localtime'))
                    ON CONFLICT(url) DO UPDATE SET
                        last_position = :last_position,
                        last_watched = datetime('now', 'localtime'),
                        title = COALESCE(:title, title),
                        duration_ms = COALESCE(:duration_ms, duration_ms),
                        thumbnail_url = COALESCE(:thumbnail_url, thumbnail_url);
                """, {
                    "url": url,
                    "title": title,
                    "duration_ms": duration_ms or 0,
                    "last_position": max(0, int(position_ms)),
                    "thumbnail_url": thumbnail_url,
                })
        except (sqlite3.Error, OSError):
            pass

    def get_last_position(self, url: str) -> Optional[int]:
        """
        Retrieve saved playback position for a URL.

        Returns:
            int position in milliseconds if found (> 5000 ms), else None.
        """
        if not url:
            return None

        try:
            with self._db_cursor() as conn:
                cursor = conn.execute(
                    "SELECT last_position, duration_ms FROM watch_history WHERE url = ?;",
                    (url,),
                )
                row = cursor.fetchone()
                if row:
                    pos = row["last_position"]
                    dur = row["duration_ms"]
                    # Only return if viewed for > 5 seconds and not at the very end
                    if pos > 5000 and (dur == 0 or pos < (dur - 5000)):
                        return pos
        except (sqlite3.Error, OSError):
            pass
        return None

    def get_history(self, limit: int = 50, bookmarked_only: bool = False) -> List[Dict[str, Any]]:
        """Retrieve recent watch history ordered by bookmarked and last watched."""
        try:
            with self._db_cursor() as conn:
                if bookmarked_only:
                    cursor = conn.execute(
                        "SELECT * FROM watch_history WHERE is_bookmarked = 1 ORDER BY last_watched DESC LIMIT ?;",
                        (limit,),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM watch_history ORDER BY is_bookmarked DESC, last_watched DESC LIMIT ?;",
                        (limit,),
                    )
                return [dict(row) for row in cursor.fetchall()]
        except (sqlite3.Error, OSError):
            return []

    def toggle_bookmark(self, entry_id: int) -> bool:
        """Toggle bookmark (favorite) status for an entry. Returns new boolean state."""
        try:
            with self._db_cursor() as conn:
                cursor = conn.execute("SELECT is_bookmarked FROM watch_history WHERE id = ?;", (entry_id,))
                row = cursor.fetchone()
                if row:
                    new_state = 0 if row["is_bookmarked"] else 1
                    conn.execute("UPDATE watch_history SET is_bookmarked = ? WHERE id = ?;", (new_state, entry_id))
                    return bool(new_state)
        except (sqlite3.Error, OSError):
            pass
        return False

    def clear_history(self) -> None:
        """Clear all records from watch history."""
        try:
            with self._db_cursor() as conn:
                conn.execute("DELETE FROM watch_history;")
        except (sqlite3.Error, OSError):
            pass

    def delete_entry(self, url: str) -> bool:
        """Delete a single history record by URL."""
        if not url:
            return False
        try:
            with self._db_cursor() as conn:
                cursor = conn.execute("DELETE FROM watch_history WHERE url = ?;", (url,))
                return cursor.rowcount > 0
        except (sqlite3.Error, OSError):
            return False

    def delete_entry_by_id(self, entry_id: int) -> bool:
        """Delete a single history record by its primary key ID."""
        try:
            with self._db_cursor() as conn:
                cursor = conn.execute("DELETE FROM watch_history WHERE id = ?;", (entry_id,))
                return cursor.rowcount > 0
        except (sqlite3.Error, OSError):
            return False

    def search_history(self, keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search history records by title or URL matching keyword."""
        term = f"%{keyword.strip()}%"
        try:
            with self._db_cursor() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM watch_history
                    WHERE title LIKE ? OR url LIKE ?
                    ORDER BY last_watched DESC
                    LIMIT ?;
                    """,
                    (term, term, limit),
                )
                return [dict(row) for row in cursor.fetchall()]
        except (sqlite3.Error, OSError):
            return []

    def checkpoint_wal(self) -> None:
        """Truncate SQLite WAL file to reclaim disk space and prevent unbounded growth."""
        try:
            with self._db_cursor() as conn:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        except (sqlite3.Error, OSError):
            pass

