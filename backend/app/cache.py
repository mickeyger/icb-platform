"""Process-local TTL cache for small read-mostly lookup tables.

Backs the calculator hot path: BOMSection / Formula / GlobalVariable are read
on every /api/calculate but written rarely (admin edits only). Each Passenger
worker keeps its own copy; admin write endpoints call invalidate() so the
worker handling the write sees fresh data immediately, and other workers
catch up within TTL seconds.

Design notes:
 - First check is lockless (dict.get is GIL-atomic in CPython); the lock is
   only taken on miss or expiry, so steady-state cost is one dict lookup and
   one monotonic() call (~200 ns).
 - Loader runs OUTSIDE the lock to avoid serialising DB calls across threads.
 - We don't memoise loader exceptions — a transient DB error shouldn't poison
   the cache for TTL seconds.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_store: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def get(key: str, loader: Callable[[], Any], ttl: float = 30.0) -> Any:
    """Return cached value for `key`, or call `loader()` and cache for `ttl`s."""
    now = time.monotonic()
    entry = _store.get(key)
    if entry is not None and entry[0] > now:
        return entry[1]
    # Miss / expired: load outside the lock, then publish under it.
    value = loader()
    with _lock:
        _store[key] = (now + ttl, value)
    return value


def invalidate(key: str) -> None:
    """Drop a single key. Cheap no-op if absent."""
    with _lock:
        _store.pop(key, None)


def invalidate_all() -> None:
    """Drop everything. Use sparingly — admin reset only."""
    with _lock:
        _store.clear()
