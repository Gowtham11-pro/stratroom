"""Lightweight in-memory rate limiter using sliding window counters.

No external dependencies. Fails open (allows requests if limiter fails).
"""
import time
import threading
import logging

logger = logging.getLogger("stratroom.ratelimit")


class SlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter. Tracks requests per client key."""

    def __init__(self):
        self._lock = threading.Lock()
        self._windows: dict[str, list[float]] = {}

    def _cleanup(self, key: str, window_seconds: int):
        """Remove expired entries for a key."""
        now = time.time()
        cutoff = now - window_seconds
        entries = self._windows.get(key, [])
        self._windows[key] = [t for t in entries if t > cutoff]

    def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Check if request is allowed.

        Args:
            key: Client identifier (e.g., IP, user email, or combination).
            limit: Maximum requests allowed in the window.
            window_seconds: Sliding window duration in seconds.

        Returns:
            (allowed, retry_after_seconds) tuple.
        """
        try:
            with self._lock:
                self._cleanup(key, window_seconds)
                now = time.time()
                entries = self._windows.get(key, [])

                if len(entries) >= limit:
                    oldest = entries[0]
                    retry_after = int(oldest + window_seconds - now) + 1
                    return False, max(retry_after, 1)

                entries.append(now)
                self._windows[key] = entries
                return True, 0
        except Exception:
            logger.exception("Rate limiter error — failing open")
            return True, 0

    def get_remaining(self, key: str, limit: int, window_seconds: int = 60) -> int:
        """Get remaining requests in current window."""
        try:
            with self._lock:
                self._cleanup(key, window_seconds)
                entries = self._windows.get(key, [])
                return max(0, limit - len(entries))
        except Exception:
            return limit


limiter = SlidingWindowRateLimiter()
