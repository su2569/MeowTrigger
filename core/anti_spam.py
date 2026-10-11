"""反重复触发：同用户同触发器短时间内连续触发会被忽略"""
import asyncio
import time
from typing import Dict, List, Tuple


class AntiSpam:
    MAX_RECORDS = 5000

    def __init__(self, window: int = 30, threshold: int = 3):
        self.window = window
        self.threshold = threshold
        self._records: Dict[str, List[float]] = {}
        self._total = 0
        self._lock = asyncio.Lock()

    async def check(self, user_id: str, trigger_name: str) -> Tuple[bool, str]:
        key = f"{user_id}_{trigger_name}"
        now = time.time()
        async with self._lock:
            lst = [t for t in self._records.get(key, []) if now - t < self.window]
            if len(lst) >= self.threshold:
                self._records[key] = lst
                return False, f"[阻止]同一触发器在半分钟内已连续触发{self.threshold}次，已忽略喵"
            lst.append(now)
            self._records[key] = lst
            self._total += 1
        if self._total % 500 == 0 or self._total > self.MAX_RECORDS:
            self._cleanup(now)
        return True, ""

    def _cleanup(self, now: float = None):
        if now is None:
            now = time.time()
        dead = []
        for k, ts in self._records.items():
            new = [t for t in ts if now - t < self.window]
            if new:
                self._records[k] = new
            else:
                dead.append(k)
        for k in dead:
            self._records.pop(k, None)
        self._total = sum(len(v) for v in self._records.values())
