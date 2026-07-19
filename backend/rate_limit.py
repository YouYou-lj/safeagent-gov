"""Thread-safe per-identity API sliding-window limiter."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from safeagent_gov.auth import AuthClaims


class RateLimitExceeded(RuntimeError):
    pass


class SlidingWindowLimiter:
    def __init__(
        self,
        *,
        limit: int = 120,
        window_seconds: float = 60.0,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0 or max_keys < 1:
            raise ValueError("invalid rate limiter configuration")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> dict[str, float | int]:
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            if key not in self._events and len(self._events) >= self.max_keys:
                stale = [name for name, events in self._events.items() if not events or events[-1] <= cutoff]
                for name in stale:
                    self._events.pop(name, None)
                if len(self._events) >= self.max_keys:
                    raise RateLimitExceeded("限流器身份基数达到上限")
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(0.0, self.window_seconds - (now - events[0]))
                raise RateLimitExceeded(f"请求过于频繁，请在 {retry_after:.3f} 秒后重试")
            events.append(now)
            return {"limit": self.limit, "remaining": self.limit - len(events), "window_seconds": self.window_seconds}


def _default_limiter() -> SlidingWindowLimiter:
    try:
        limit = int(os.getenv("SAFEAGENT_API_RATE_LIMIT", "120"))
        window = float(os.getenv("SAFEAGENT_API_RATE_WINDOW_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("API 限流配置必须是数值") from exc
    return SlidingWindowLimiter(limit=limit, window_seconds=window)


DEFAULT_API_LIMITER = _default_limiter()


def rate_limit_identity(principal: AuthClaims) -> None:
    DEFAULT_API_LIMITER.check(f"{principal.tenant_id}:{principal.sub}")
