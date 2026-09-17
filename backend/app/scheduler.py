"""进程内的周期任务调度。

答辩系统只有一个后端进程，周期任务用**进程内调度**即可，不引入分布式任务队列
（spec「Out of Scope」）。当前只有一件周期任务：画像置信度校准。

调度器本身不承载业务：真正的工作在 `calibration.recalibrate` 里，时间基准也由它在
最外层取一次（ADR-0011），于是「校准做了什么」可以直接测，不必睡线程等调度。

第一次执行发生在**一个周期之后**，而不是启动瞬间：这样每次拉起应用（包括测试里
反复进入 lifespan）都不会顺带改一次库。
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from app.customer_profile.calibration import recalibrate
from app.db.session import open_session
from app.redis_client import redis_client
from app.settings import Settings, get_settings

logger = logging.getLogger("app")

_running: asyncio.Task | None = None
_stop: asyncio.Event | None = None


def interval_seconds(settings: Settings) -> float:
    # 至少一分钟：一个 0 会把周期任务变成忙循环。
    return max(settings.calibration_interval_minutes, 1) * 60.0


def run_calibration_once(*, settings: Settings | None = None) -> dict:
    """跑一次全量置信度校准，返回本次规模。时间基准在这里取一次并向下传。"""
    resolved = settings or get_settings()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = open_session()
    try:
        return recalibrate(
            session,
            cache=redis_client(),
            now=now,
            expiry_threshold=resolved.profile_tag_expiry_threshold,
        )
    finally:
        session.close()


async def _run_periodically(
    job: Callable[[], object],
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    # 周期任务在 worker 线程里跑：校准是同步的数据库工作，不能阻塞事件循环。
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.to_thread(job)
        except Exception:
            # 周期任务失败只在日志里留痕，不拖垮进程；下一个周期再试。
            logger.exception("周期校准失败")


def start(settings: Settings) -> None:
    global _running, _stop
    if _running is not None and not _running.done():
        return
    _stop = asyncio.Event()
    _running = asyncio.create_task(
        _run_periodically(
            lambda: run_calibration_once(settings=settings),
            interval_seconds=interval_seconds(settings),
            stop_event=_stop,
        )
    )


async def shutdown() -> None:
    global _running, _stop
    if _stop is not None:
        _stop.set()
    if _running is not None:
        _running.cancel()
        try:
            await _running
        except asyncio.CancelledError:
            pass
    _running = None
    _stop = None
