"""
Thread Pool Utilities for FB Video Watcher.
Provides DaemonThreadPoolExecutor so worker threads never block process termination on shutdown.
"""

import concurrent.futures
from concurrent.futures import thread
import threading
import weakref


class DaemonThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """
    ThreadPoolExecutor whose worker threads are strictly daemon threads.
    Does not register workers in concurrent.futures.thread._threads_queues,
    preventing Python's atexit hook (_python_exit) from calling t.join() and
    hanging application shutdown when network tasks (yt-dlp, urllib, AI queries)
    are in flight.
    """

    def _adjust_thread_count(self) -> None:
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = f"{self._thread_name_prefix or self}_{num_threads}"
            t = threading.Thread(
                name=thread_name,
                target=thread._worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)
