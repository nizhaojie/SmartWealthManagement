"""预警自身的处置判定：排除（误报）或升级（超出处置权限）。

```
未处理 ──排除──▶ 已排除
       └─升级──▶ 已升级
```

两条路径要求同一件事：**处置人与非空理由**。判定只能做出一次——结论一旦写下就
不再更改，所以「这条预警为什么被放过」永远有一个唯一的、署名的答案。也正因为只
发生一次，预警行上的处置人、理由与时间就是这条预警完整的处置留痕，不必再开一张
流水表。

升级不改编预警的等级与置信度：那是规则命中算出来的事实，由确定性代码推导
（`app.risk_monitoring.grading`），不由人改写。升级说的是「这件事超出了我的处置
权限，交上去」，是一个处置状态，不是一个新的风险判断。

预警这一行只收下这个判定结果。多步骤的处置过程（接单、核实、办结）由它派生的工单
承载（`app.work_order`），两套生命周期不合并。

这里没有任何自动路径：低置信、超时、订阅方报错都不会让预警离开「未处理」（见
`app.risk_monitoring.alert_status`）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Employee, RiskAlert
from app.exceptions import AppError
from app.risk_monitoring.alert_status import (
    ALERT_STATUS_ESCALATED,
    ALERT_STATUS_EXCLUDED,
    ALERT_STATUS_OPEN,
)

ALERT_NOT_FOUND_MESSAGE = "预警不存在"
REASON_REQUIRED_MESSAGE = "处置理由不能为空"
ALREADY_HANDLED_MESSAGE = "该预警已处置，不能重复处置"


def get_alert(db: Session, alert_id: int) -> RiskAlert:
    alert = db.get(RiskAlert, alert_id)
    if alert is None:
        raise AppError(404, ALERT_NOT_FOUND_MESSAGE)
    return alert


def exclude_alert(
    db: Session,
    *,
    alert_id: int,
    employee: Employee,
    reason: str | None,
    now: datetime,
) -> RiskAlert:
    """判定为已排除：误报，原因必须写清——它是这条预警被放过的唯一依据。"""
    return _decide(
        db,
        alert_id=alert_id,
        employee=employee,
        reason=reason,
        status=ALERT_STATUS_EXCLUDED,
        now=now,
    )


def escalate_alert(
    db: Session,
    *,
    alert_id: int,
    employee: Employee,
    reason: str | None,
    now: datetime,
) -> RiskAlert:
    """升级：超出处置权限，交上去。等级与置信度不动。"""
    return _decide(
        db,
        alert_id=alert_id,
        employee=employee,
        reason=reason,
        status=ALERT_STATUS_ESCALATED,
        now=now,
    )


def _decide(
    db: Session,
    *,
    alert_id: int,
    employee: Employee,
    reason: str | None,
    status: str,
    now: datetime,
) -> RiskAlert:
    checked_reason = _require_reason(reason)
    alert = get_alert(db, alert_id)
    # 已经处置过的预警不再接受第二个结论：留下的是第一个，也是唯一一个答案。
    if alert.status != ALERT_STATUS_OPEN:
        raise AppError(409, ALREADY_HANDLED_MESSAGE)

    alert.status = status
    alert.handler_id = employee.id
    alert.handle_result = checked_reason
    alert.update_time = now
    db.commit()
    db.refresh(alert)
    return alert


def _require_reason(reason: str | None) -> str:
    """空白字符不算理由：「随手敲个空格」与「没填」是一回事。"""
    if not reason or not reason.strip():
        raise AppError(400, REASON_REQUIRED_MESSAGE)
    return reason.strip()
