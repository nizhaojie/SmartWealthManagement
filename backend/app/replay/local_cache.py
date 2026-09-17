"""回放模式用的进程内缓存：``redis.Redis`` 的一个极小子集。

回放模式不连 Redis（「开启后不发起任何外部调用」），但登录会话、短期记忆、
画像缓存、问卷草稿这些缓存消费者要照常工作，演示里的多轮对话才有上下文。
这个替身只实现仓库实际用到的那几个方法（``set/get/exists/delete/expire/
lrange/rpush/ltrim/publish``），数据存活在进程里、按 TTL 惰性过期——对
「单进程演示」这个场景，语义与 Redis 一致，而它连不上任何东西。

它从不抛 ``redis.RedisError``：降级路径为「缓存不可用」而设，回放模式里
缓存永远可用，各消费者因此走的是与正常开发完全相同的代码路径。
"""

import threading
import time
from typing import Any


class InMemoryCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # 一个键要么是字符串（键值用法）要么是字符串列表（列表用法），
        # 与 Redis 一样由使用方式决定，两类用法不会混在同一键上。
        self._values: dict[str, Any] = {}
        self._expires_at: dict[str, float] = {}

    def _live(self, key: str, now: float) -> bool:
        deadline = self._expires_at.get(key)
        if deadline is not None and deadline <= now:
            self._values.pop(key, None)
            self._expires_at.pop(key, None)
            return False
        return key in self._values

    def set(self, key: str, value: str, ex: Any = None) -> None:
        # redis-py 的 ex 接受秒数或 timedelta（登录会话传的就是 timedelta）。
        if hasattr(ex, "total_seconds"):
            ex = ex.total_seconds()
        with self._lock:
            self._values[key] = value
            if ex is None:
                self._expires_at.pop(key, None)
            else:
                self._expires_at[key] = time.monotonic() + float(ex)

    def get(self, key: str) -> str | None:
        with self._lock:
            if not self._live(key, time.monotonic()):
                return None
            value = self._values[key]
            return value if isinstance(value, str) else None

    def exists(self, key: str) -> int:
        with self._lock:
            return 1 if self._live(key, time.monotonic()) else 0

    def delete(self, key: str) -> int:
        with self._lock:
            removed = 1 if self._live(key, time.monotonic()) else 0
            self._values.pop(key, None)
            self._expires_at.pop(key, None)
            return removed

    def expire(self, key: str, seconds: Any) -> None:
        # redis-py 接受 int 或 timedelta；回放替身同样两者都收。
        if hasattr(seconds, "total_seconds"):
            seconds = seconds.total_seconds()
        with self._lock:
            if self._live(key, time.monotonic()):
                self._expires_at[key] = time.monotonic() + float(seconds)

    def rpush(self, key: str, value: str) -> None:
        with self._lock:
            items = self._values.get(key)
            if not isinstance(items, list):
                items = []
                self._values[key] = items
            items.append(value)

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        with self._lock:
            if not self._live(key, time.monotonic()):
                return []
            items = self._values.get(key)
            if not isinstance(items, list):
                return []
            items = list(items)
        # 与 redis 一致：stop=-1 表示到末尾（含）。
        if stop < 0:
            stop = len(items) + stop + 1
        return items[start:stop]

    def ltrim(self, key: str, start: int, stop: int) -> None:
        with self._lock:
            if not self._live(key, time.monotonic()):
                return
            items = self._values.get(key)
            if not isinstance(items, list):
                return
            if stop < 0:
                stop = len(items) + stop + 1
            self._values[key] = items[start:stop]

    def publish(self, channel: str, message: str) -> int:
        # 出站镜像在回放模式里没有进程外的读者；返回 0 个订阅者即是事实。
        return 0
