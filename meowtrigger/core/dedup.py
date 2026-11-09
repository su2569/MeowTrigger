"""消息去重：基于 message_id / 内容哈希"""
import asyncio
import time
from collections import deque
from typing import Optional


class MessageDeduplicator:
    def __init__(self, max_size: int = 2000, ttl: int = 300):
        self.ttl = ttl
        self._cache = deque(maxlen=max_size)
        self._set = set()
        self._lock = asyncio.Lock()
        self._stats = {"total": 0, "duplicate": 0, "unique": 0}

    def _cleanup(self):
        now = time.time()
        while self._cache and now - self._cache[0][1] > self.ttl:
            old, _ = self._cache.popleft()
            self._set.discard(old)

    async def check(self, msg_id: Optional[str] = None,
                    content_hash: Optional[str] = None) -> bool:
        async with self._lock:
            self._cleanup()
        key = msg_id or content_hash
        if not key:
            return True
        if key in self._set:
            self._stats["duplicate"] += 1
            return False
        self._cache.append((key, time.time()))
        self._set.add(key)
        self._stats["total"] += 1
        self._stats["unique"] += 1
        return True

    def mark(self, msg_id: Optional[str] = None, content_hash: Optional[str] = None):
        key = msg_id or content_hash
        if key and key not in self._set:
            self._cache.append((key, time.time()))
            self._set.add(key)

    def get_stats(self) -> dict:
        return {
            "total_checked": self._stats["total"] + self._stats["duplicate"],
            "unique": self._stats["unique"],
            "duplicate": self._stats["duplicate"],
            "cache_size": len(self._cache),
        }
