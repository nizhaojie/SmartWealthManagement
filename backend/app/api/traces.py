"""留痕清理的手工触发入口，以及两组从留痕里读出来的统计。

清理只作用于调试级留痕；审计级留痕永久保存、不在清理范围内（表结构上就是另一张表）。
时间基准在**最外层**取一次当前时间再传进清理函数（ADR-0011）——一次批处理内所有记录
用同一个基准，任务跑了几分钟也不会出现前后不一致；手工触发与将来的周期任务走的是
同一个服务函数，区别只在触发方式。

统计是**只读**的，与清理共用这张表：响应时间按月清理、降级频次按保留期统计，都是
当前留痕窗口内的事实，不是需要永久保存的合规证据。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import degradation
from app.agent import debug_trace
from app.auth.dependencies import AuthContext, require_internal
from app.db.session import get_session
from app.http import ok
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/internal/traces")


@router.post("/purge")
def purge_traces(
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deleted = debug_trace.purge(
        db, now=now, retention_days=settings.debug_trace_retention_days
    )
    return ok(
        {
            "deleted": deleted,
            "basis": now.isoformat(),
            "retention_days": settings.debug_trace_retention_days,
        }
    )


@router.get("/agent-response-times")
def agent_response_times(
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    """各 Agent 的响应时间统计：次数、平均、最快、最慢。"""
    return ok({"agents": debug_trace.response_time_summary(db)})


@router.get("/degradations")
def degradation_stats(
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    """降级频次统计：总数 + 按依赖分组 + 按原因分组。

    它回答「系统实际上有多少时间工作在降级状态下」——降级不产生错误，只看错误率
    是看不出来的。
    """
    return ok(degradation.summarize(db))
