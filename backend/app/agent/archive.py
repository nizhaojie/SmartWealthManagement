"""会话归档：会话结束后留下的只读留痕（不是三层记忆里的任何一层，见 ADR-0012）。

每一轮问答在结束时即刻落库，而**不是**等会话断开再批量写——进程中途退出也不会
丢掉已经发生过的对话。落库前脱敏：身份证号、手机号、银行卡号按形态识别，真实姓名
按当前客户的名字替换。工具调用记录、引用文档与内容分类一并留下。

归档只用于回溯与举证，不参与上下文组装：短期记忆过期后，这句话不会再回到上下文里，
但它仍然可以在归档中按会话标识或客户标识查到。
"""

import re
from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.citations import Citation
from app.customer_scope import is_under_management, restrict_to_own_customers
from app.db.models import ConversationArchive, Customer, Employee
from app.exceptions import AppError

SESSION_NOT_FOUND_MESSAGE = "会话不存在"
NOT_YOUR_CUSTOMER_SESSION_MESSAGE = "该会话不在你名下客户的范围内，无权查看"

# 一次查询最多返回的会话条数：归档是只增表，浏览历史需要上限，避免一次拉全表。
LIST_LIMIT = 100

# 归档里的身份域：本 slice 落库的是客户侧对话，客户经理的可见范围按客户归属收紧。
IDENTITY_CUSTOMER = "customer"

_ID_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_BANK_CARD_PATTERN = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)(1\d{10})(?!\d)")


def _mask(value: str, *, keep_prefix: int, keep_suffix: int) -> str:
    stars = "*" * (len(value) - keep_prefix - keep_suffix)
    return f"{value[:keep_prefix]}{stars}{value[len(value) - keep_suffix:]}"


def _mask_id_number(match: re.Match[str]) -> str:
    # 18 位数字身份证号与 18 位银行卡号在字符形态上无法区分，此处按身份证号处理
    # （保留地区码），因此一个恰好 18 位的银行卡号会比 16/19 位银行卡号多暴露
    # 中间的地区码位——脱敏文本没有字段语义可供消歧，这是可接受的折衷。
    return _mask(match.group(1), keep_prefix=6, keep_suffix=4)


def _mask_bank_card(match: re.Match[str]) -> str:
    return _mask(match.group(1), keep_prefix=0, keep_suffix=4)


def _mask_phone(match: re.Match[str]) -> str:
    return _mask(match.group(1), keep_prefix=3, keep_suffix=4)


def _mask_name(name: str) -> str:
    if len(name) <= 1:
        return "*"
    return f"{name[0]}{'*' * (len(name) - 1)}"


def mask_pii(text: str, *, real_name: str | None = None) -> str:
    masked = text
    if real_name:
        masked = masked.replace(real_name, _mask_name(real_name))
    masked = _ID_NUMBER_PATTERN.sub(_mask_id_number, masked)
    masked = _BANK_CARD_PATTERN.sub(_mask_bank_card, masked)
    masked = _PHONE_PATTERN.sub(_mask_phone, masked)
    return masked


def record_turn(
    db: Session,
    *,
    session_id: str,
    user_id: int,
    agent_type: str,
    question: str,
    answer: str,
    citations: list[Citation],
    tool_calls: list[dict],
    content_classification: str,
) -> None:
    customer = db.get(Customer, user_id)
    real_name = customer.real_name if customer else None

    db.add(
        ConversationArchive(
            session_id=session_id,
            identity_domain=IDENTITY_CUSTOMER,
            user_id=user_id,
            agent_type=agent_type,
            role="user",
            content=mask_pii(question, real_name=real_name),
        )
    )
    db.add(
        ConversationArchive(
            session_id=session_id,
            identity_domain=IDENTITY_CUSTOMER,
            user_id=user_id,
            agent_type=agent_type,
            role="assistant",
            content=mask_pii(answer, real_name=real_name),
            tool_calls=tool_calls or None,
            citations=[asdict(citation) for citation in citations] or None,
            content_classification=content_classification,
        )
    )
    db.commit()


def _serialize_message(row: ConversationArchive) -> dict:
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "tool_calls": row.tool_calls or [],
        "citations": row.citations or [],
        "content_classification": row.content_classification,
        "created_at": row.create_time.isoformat(),
    }


def _serialize_session(row) -> dict:
    (
        session_id,
        identity_domain,
        user_id,
        agent_type,
        message_count,
        started_at,
        ended_at,
    ) = row
    return {
        "session_id": session_id,
        "identity_domain": identity_domain,
        "user_id": user_id,
        # 一个会话只有一份 Agent 配置，取最大值只是为了满足分组查询的聚合语法。
        "agent_type": agent_type,
        "message_count": int(message_count),
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
    }


def list_sessions(
    db: Session,
    *,
    viewer: Employee,
    session_id: str | None = None,
    user_id: int | None = None,
) -> list[dict]:
    """按会话标识或客户标识（归档列 `user_id`）列出历史会话，按最后一次发言倒序。

    两个筛选项都可为空——那时返回最近的一批会话，供界面浏览。客户经理只看得到
    自己名下客户的会话，其他内部角色不受限（与工单、预警同一口径）。
    """
    last_at = func.max(ConversationArchive.create_time)
    query = select(
        ConversationArchive.session_id,
        ConversationArchive.identity_domain,
        ConversationArchive.user_id,
        func.max(ConversationArchive.agent_type),
        func.count(ConversationArchive.id),
        func.min(ConversationArchive.create_time),
        last_at,
    ).group_by(
        ConversationArchive.session_id,
        ConversationArchive.identity_domain,
        ConversationArchive.user_id,
    )
    if session_id is not None:
        query = query.where(ConversationArchive.session_id == session_id)
    if user_id is not None:
        query = query.where(ConversationArchive.user_id == user_id)
    if restrict_to_own_customers(viewer):
        query = query.join(Customer, Customer.id == ConversationArchive.user_id).where(
            Customer.manager_id == viewer.id
        )

    rows = db.execute(query.order_by(last_at.desc()).limit(LIST_LIMIT)).all()
    return [_serialize_session(row) for row in rows]


def get_session(db: Session, session_id: str, *, viewer: Employee) -> dict:
    """一次会话的完整流水：消息按发生顺序排列，工具调用与引用随消息给出。"""
    rows = list(
        db.scalars(
            select(ConversationArchive)
            .where(ConversationArchive.session_id == session_id)
            .order_by(ConversationArchive.id.asc())
        )
    )
    if not rows:
        raise AppError(404, SESSION_NOT_FOUND_MESSAGE)
    _ensure_can_view(db, rows[0], viewer)
    return {
        "session_id": session_id,
        "identity_domain": rows[0].identity_domain,
        "user_id": rows[0].user_id,
        "agent_type": rows[0].agent_type,
        "message_count": len(rows),
        "started_at": rows[0].create_time.isoformat(),
        "ended_at": rows[-1].create_time.isoformat(),
        "messages": [_serialize_message(row) for row in rows],
    }


def _ensure_can_view(db: Session, row: ConversationArchive, viewer: Employee) -> None:
    if not restrict_to_own_customers(viewer):
        return
    customer = (
        db.get(Customer, row.user_id) if row.identity_domain == IDENTITY_CUSTOMER else None
    )
    if not is_under_management(customer, viewer):
        raise AppError(403, NOT_YOUR_CUSTOMER_SESSION_MESSAGE)
