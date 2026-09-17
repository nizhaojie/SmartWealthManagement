"""进程内的周期校准调度。

调度器本身很薄：把「周期校准」这件工作接到 asyncio 循环上。这里测的是它的循环语义
（按间隔跑、失败不拖垮进程）与工作入口的接线（时间基准在最外层取一次、会话一定关闭），
而不是校准算得对不对——那是 `test_profile_rerank_and_calibration.py` 的事。
"""

import asyncio
from datetime import datetime

import pytest

from app import scheduler
from app.settings import get_settings


def test_interval_is_never_shorter_than_a_minute():
    settings = get_settings().model_copy(update={"calibration_interval_minutes": 0})
    assert scheduler.interval_seconds(settings) == 60.0
    assert (
        scheduler.interval_seconds(
            get_settings().model_copy(update={"calibration_interval_minutes": 5})
        )
        == 300.0
    )


def test_periodic_loop_runs_the_job_once_per_interval_and_stops_cleanly():
    calls: list[int] = []

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            scheduler._run_periodically(
                lambda: calls.append(1), interval_seconds=0.03, stop_event=stop
            )
        )
        await asyncio.sleep(0.12)
        stop.set()
        await task

    asyncio.run(scenario())

    # 第一个周期之前不跑；跑过之后至少两次（0.12s / 0.03s）。
    assert len(calls) >= 2


def test_a_failing_job_does_not_kill_the_loop():
    attempts: list[int] = []

    async def scenario() -> None:
        stop = asyncio.Event()

        def job() -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("第一次失败")

        task = asyncio.create_task(
            scheduler._run_periodically(job, interval_seconds=0.03, stop_event=stop)
        )
        await asyncio.sleep(0.15)
        stop.set()
        await task

    asyncio.run(scenario())

    assert len(attempts) >= 2


def test_scheduled_job_takes_one_basis_and_always_closes_its_session(monkeypatch):
    captured: dict = {}

    class FakeSession:
        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(scheduler, "open_session", lambda: FakeSession())
    monkeypatch.setattr(scheduler, "redis_client", lambda: "cache")

    def fake_recalibrate(session, *, now, expiry_threshold, cache=None):
        captured.update(
            session=session, now=now, expiry_threshold=expiry_threshold, cache=cache
        )
        return {"ok": True}

    monkeypatch.setattr(scheduler, "recalibrate", fake_recalibrate)
    settings = get_settings().model_copy(update={"profile_tag_expiry_threshold": 0.42})

    result = scheduler.run_calibration_once(settings=settings)

    assert result == {"ok": True}
    assert captured["expiry_threshold"] == 0.42
    assert captured["cache"] == "cache"
    assert captured["closed"] is True
    # 时间基准是朴素时间（与数据库列一致），且由调度入口取一次后向下传。
    assert isinstance(captured["now"], datetime)
    assert captured["now"].tzinfo is None


def test_start_and_shutdown_are_idempotent():
    async def scenario() -> None:
        scheduler.start(get_settings())
        scheduler.start(get_settings())
        await scheduler.shutdown()
        await scheduler.shutdown()

    asyncio.run(scenario())
