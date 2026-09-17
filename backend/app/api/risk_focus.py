"""风险关注的读取入口：风控专员在这里看到其他 Agent 提醒过什么。

只读，没有写操作，也没有处置动作：记录由订阅方在事件到达时写下，是一次观察的
留痕，不是需要被推进的状态机。要处置就走工单（`app.work_order`），不把两套
东西合并。

可见范围与预警、工单同一口径：客户经理只看得到自己名下客户的提示。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import risk_focus
from app.auth.dependencies import current_employee
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok

router = APIRouter(prefix="/api/internal/risk-focus")


@router.get("")
def list_risk_focus(
    focus_type: str | None = None,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    return ok(risk_focus.list_recent(db, employee=employee, focus_type=focus_type))
