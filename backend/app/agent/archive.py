"""会话归档：会话结束后留下的只读留痕（不是三层记忆里的任何一层，见 ADR-0012）。

每一轮问答在结束时即刻落库，而**不是**等会话断开再批量写——进程中途退出也不会
丢掉已经发生过的对话。落库前脱敏：身份证号、手机号、银行卡号按形态识别，真实姓名
按当前客户的名字替换。工具调用记录、引用文档与内容分类一并留下。

归档只用于回溯与举证，不参与上下文组装：短期记忆过期后，这句话不会再回到上下文里，
但它仍然可以在归档中按会话标识或客户标识查到。

历史会话列表按会话分组后分页（ADR-0024），`total` 因此是「多少场会话」。会话详情
里的 `messages` 不分页：那是会话回看本身，一次会话的消息量与页长无关。
"""

import re
from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.citations import Citation
from app.customer_scope import is_under_management, restrict_to_own_customers
from app.db.models import ConversationArchive, Customer, Employee
from app.exceptions import AppError
from app.pagination import PageParams, count_matching, paginated_response

SESSION_NOT_FOUND_MESSAGE = "会话不存在"
NOT_YOUR_CUSTOMER_SESSION_MESSAGE = "该会话不在你名下客户的范围内，无权查看"

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
    params: PageParams,
    session_id: str | None = None,
    user_id: int | None = None,
) -> dict:
    """按会话标识或客户标识（归档列 `user_id`）列出历史会话的一页，按最后一次发言倒序。

    两个筛选项都可为空——那时给的是最近的会话，供界面逐页浏览（ADR-0024）。客户经理
    只看得到自己名下客户的会话，其他内部角色不受限（与工单、预警同一口径）。

    `total` 是**过滤后的会话数**而不是归档行数：这条查询按会话分组，`count_matching`
    数的是分组后的行数，也就是「有多少场会话」。口径写成「归档行数」时，页面上会说
    「共 400 条」而每一页只有 20 场会话，两个数字都像是真的。

    排序键是最后一次发言时间倒序 + 会话标识兜底：发言时间是秒精度，同一秒里结束的
    两场会话若不分先后，翻页时会在两页之间来回跳。
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

    total = count_matching(db, query)
    rows = db.execute(
        query.order_by(last_at.desc(), ConversationArchive.session_id.asc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    items = [_serialize_session(row) for row in rows]
    return paginated_response(items, total=total, params=params)


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


def _first_user_message_titles(db: Session, session_ids: list[str]) -> dict[str, str]:
    """每个会话的第一条客户提问（role 为 user 且 id 最小的行），用作历史列表的标题。

    批量取而非逐会话查，避免浏览一页历史时退化成每场会话一次查询。
    """
    if not session_ids:
        return {}
    first_ids = (
        select(
            ConversationArchive.session_id,
            func.min(ConversationArchive.id).label("first_id"),
        )
        .where(
            ConversationArchive.session_id.in_(session_ids),
            ConversationArchive.role == "user",
        )
        .group_by(ConversationArchive.session_id)
        .subquery()
    )
    rows = db.execute(
        select(first_ids.c.session_id, ConversationArchive.content).join(
            ConversationArchive,
            ConversationArchive.id == first_ids.c.first_id,
        )
    ).all()
    return {session_id: content for session_id, content in rows}


def list_customer_sessions(
    db: Session,
    *,
    user_id: int,
    params: PageParams,
    exclude_session_id: str | None = None,
) -> dict:
    """客户本人的历史会话一页：按最后发言倒序，标题取该会话第一条客户提问。

    与内部端 `list_sessions` 不同：这里不做客户经理可见范围收紧——调用方就是客户
    本人，可见范围天然是「自己」，直接把 user_id 定死、并排除当前会话（当前会话在
    智能对话页可见，历史只收「已结束的登录会话」）。

    排序键与内部端同口径：最后一次发言时间倒序 + 会话标识兜底。
    """
    last_at = func.max(ConversationArchive.create_time)
    conditions = [
        ConversationArchive.identity_domain == IDENTITY_CUSTOMER,
        ConversationArchive.user_id == user_id,
    ]
    if exclude_session_id is not None:
        conditions.append(ConversationArchive.session_id != exclude_session_id)

    query = (
        select(
            ConversationArchive.session_id,
            func.count(ConversationArchive.id).label("message_count"),
            func.min(ConversationArchive.create_time).label("started_at"),
            last_at.label("ended_at"),
        )
        .where(*conditions)
        .group_by(ConversationArchive.session_id)
    )
    total = count_matching(db, query)
    rows = db.execute(
        query.order_by(last_at.desc(), ConversationArchive.session_id.asc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    # 越界页没有行，但 `total` 仍然是真的「一共几场会话」——空 `items` 不等于没有历史。
    titles = _first_user_message_titles(db, [row.session_id for row in rows])
    items = [
        {
            "session_id": row.session_id,
            "title": titles.get(row.session_id, ""),
            "message_count": int(row.message_count),
            "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat(),
        }
        for row in rows
    ]
    return paginated_response(items, total=total, params=params)


def get_customer_session(db: Session, *, session_id: str, user_id: int) -> dict:
    """客户本人查看一次会话的完整流水（只读回看）。

    直接按 session_id + user_id 过滤：别人的会话即使知道 session_id 也查不到，
    与「不存在」同等待遇（404），不暴露存在性。详情只给 role / content / citations /
    时间——tool_calls 与 content_classification 是内部/合规字段，不进客户可见视图。
    """
    rows = list(
        db.scalars(
            select(ConversationArchive)
            .where(
                ConversationArchive.session_id == session_id,
                ConversationArchive.identity_domain == IDENTITY_CUSTOMER,
                ConversationArchive.user_id == user_id,
            )
            .order_by(ConversationArchive.id.asc())
        )
    )
    if not rows:
        raise AppError(404, SESSION_NOT_FOUND_MESSAGE)
    return {
        "session_id": session_id,
        "started_at": rows[0].create_time.isoformat(),
        "ended_at": rows[-1].create_time.isoformat(),
        "messages": [
            {
                "role": row.role,
                "content": row.content,
                "citations": row.citations or [],
                "created_at": row.create_time.isoformat(),
            }
            for row in rows
        ],
    }
