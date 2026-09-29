"""客户历史记录查询：客户查看本人过去的会话，只读回看。

数据来自 `conversation_archive`（审计级留痕），与内部端 `conversations.py` 共用同一张
表，但走客户身份域（`require_customer`）。列表分页（ADR-0024），排除当前会话——当前
会话在对话页可见，历史只收「已结束的登录会话」；详情只给 role / content / citations /
时间 / `data`，不暴露 tool_calls 与 content_classification，`messages` 不分页。

`/current` 补的是「当前会话在对话页可见」这半句：刷新页面只丢前端内存态，凭证与
session_id 都还在，所以这一场会话的归档仍然属于「当前会话」。它按凭证里的 session_id
取，客户侧因此不需要自己知道（也不该知道）会话标识。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent import archive
from app.auth.dependencies import AuthContext, require_customer
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params

router = APIRouter(prefix="/api/customer/conversations")


@router.get("")
def list_conversations(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    page: PageParams = Depends(page_params),
):
    return ok(
        archive.list_customer_sessions(
            db, user_id=auth.subject_id, params=page, exclude_session_id=auth.session_id
        )
    )


# 必须声明在 `/{session_id}` 之前：否则 "current" 会被当成一个会话标识吃进去。
@router.get("/current")
def get_current_conversation(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(
        archive.get_current_customer_session(
            db, session_id=auth.session_id, user_id=auth.subject_id
        )
    )


@router.get("/{session_id}")
def get_conversation(
    session_id: str,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(archive.get_customer_session(db, session_id=session_id, user_id=auth.subject_id))
