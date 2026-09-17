"""会话归档查询：回溯任意一次历史会话的完整流水。

归档是只读留痕，不是三层记忆中的任何一层（ADR-0012）——短期记忆过期后，对话内容
从这里仍可查到。查询按会话标识或客户标识（`user_id`，即归档行的使用者标识）进行，
两个筛选项都可为空时返回最近的一批会话供浏览；具体某一次会话的完整流水走详情端点。

可见范围与工单、预警同一口径：客户经理只看得到自己名下客户的会话，其他内部角色
不受限（`app.customer_scope`）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent import archive
from app.auth.dependencies import current_employee
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok

router = APIRouter(prefix="/api/internal/conversations")


@router.get("")
def list_conversations(
    session_id: str | None = None,
    user_id: int | None = None,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    sessions = archive.list_sessions(
        db, viewer=employee, session_id=session_id, user_id=user_id
    )
    return ok(sessions)


@router.get("/{session_id}")
def get_conversation(
    session_id: str,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    return ok(archive.get_session(db, session_id, viewer=employee))
