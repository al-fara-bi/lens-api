"""Sliding-window rate limiter: in-memory state, persisted to a JSON file.

Why not Redis: the task explicitly allows file-based rate limiting, and a single
application instance has no shared state to coordinate. An ``asyncio.Lock`` is
sufficient here because asyncio runs coroutines on one thread — no request can
interleave between the read and the write below.

This does mean the counters live in one process. Running uvicorn with multiple
workers would give each worker its own view and silently multiply the effective
limit, which is why the service runs a single worker (see README).
"""

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path

logger = logging.getLogger(__name__)

SAVE_INTERVAL_SECONDS = 5.0


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int, state_path: Path) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.state_path = state_path
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_saved = 0.0

    # ---------- public API ----------

    async def check(self, key: str) -> tuple[bool, int]:
        """Record a hit for ``key``.

        Returns ``(allowed, retry_after_seconds)``. When the window is full the
        hit is *not* recorded, so a blocked caller cannot push their own reset
        further away by retrying.
        """
        now = time.time()
        async with self._lock:
            hits = self._hits[key]
            self._evict_expired(hits, now)

            if len(hits) >= self.max_requests:
                retry_after = int(hits[0] + self.window_seconds - now) + 1
                return False, max(retry_after, 1)

            hits.append(now)
            await self._maybe_persist(now)
            return True, 0

    async def remaining(self, key: str) -> int:
        now = time.time()
        async with self._lock:
            hits = self._hits[key]
            self._evict_expired(hits, now)
            return max(self.max_requests - len(hits), 0)

    # ---------- persistence ----------

    def load(self) -> None:
        """Restore counters so a restart cannot be used to reset the limit."""
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read rate-limit state, starting empty: %s", exc)
            return

        now = time.time()
        restored = 0
        for key, timestamps in raw.items():
            fresh = [t for t in timestamps if now - t < self.window_seconds]
            if fresh:
                self._hits[key] = deque(fresh)
                restored += 1
        logger.info("Restored rate-limit state for %d client(s)", restored)

    async def save(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write_state)

    async def _maybe_persist(self, now: float) -> None:
        # Called with the lock held. Debounced so a burst of requests does not
        # turn into a burst of disk writes.
        if now - self._last_saved < SAVE_INTERVAL_SECONDS:
            return
        self._last_saved = now
        await asyncio.to_thread(self._write_state)

    def _write_state(self) -> None:
        payload = {key: list(hits) for key, hits in self._hits.items() if hits}
        tmp = self.state_path.with_suffix(".tmp")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            # Atomic replace: a crash mid-write cannot leave a truncated file.
            tmp.replace(self.state_path)
        except OSError as exc:
            logger.warning("Could not persist rate-limit state: %s", exc)

    # ---------- internals ----------

    def _evict_expired(self, hits: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
