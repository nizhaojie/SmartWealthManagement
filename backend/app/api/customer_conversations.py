"""客户历史记录查询：客户查看本人过去的会话，只读回看。

数据来自 `conversation_archive`（审计级留痕），与内部端 `conversations.py` 共用同一张
表，但走客户身份域（`require_customer`）。列表排除当前会话——当前会话在对话页可见，
历史只收「已结束的登录会话」；详情只给 role / content / citations / 时间，不暴露
tool_calls 与 content_classification。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent import archive
from app.auth.dependencies import AuthContext, require_customer
from app.db.session import get_session
from app.http import ok

router = APIRouter(prefix="/api/customer/conversations")


@router.get("")
def list_conversations(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    sessions = archive.list_customer_sessions(
        db, user_id=auth.subject_id, exclude_session_id=auth.session_id
    )
    return ok(sessions)


@router.get("/{session_id}")
def get_conversation(
    session_id: str,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(archive.get_customer_session(db, session_id=session_id, user_id=auth.subject_id))
