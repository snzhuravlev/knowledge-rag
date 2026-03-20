import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException


class RateLimiter:
    def __init__(self) -> None:
        self._bucket: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, limit_per_minute: int) -> None:
        now = time.time()
        threshold = now - 60
        queue = self._bucket[key]
        while queue and queue[0] < threshold:
            queue.popleft()
        if len(queue) >= limit_per_minute:
            raise HTTPException(status_code=429, detail="Too many requests. Please retry later.")
        queue.append(now)
