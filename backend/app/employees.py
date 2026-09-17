"""把员工 id 换成人名。

工单受理人、预警处置人、规则调整人都要在界面上显示成人名，而不是工号。查询形状完全
一样，各写一遍就会出现「同一批 id，有的地方查了、有的地方忘了」的差别，而这种差别
在界面上表现为一个空的姓名列——不会报错，只会看起来像没填。

一次查完再查表，而不是逐条查：调用点拿到的通常是一整页记录上的若干个 id。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Employee


def names_by_id(db: Session, employee_ids: Iterable[int | None]) -> dict[int, str]:
    """这些员工 id 对应的姓名；查不到的 id 不出现在结果里。"""
    ids = {employee_id for employee_id in employee_ids if employee_id is not None}
    if not ids:
        return {}
    return {
        employee.id: employee.real_name
        for employee in db.scalars(select(Employee).where(Employee.id.in_(ids))).all()
    }
