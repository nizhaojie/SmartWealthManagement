"""业务操作 Agent 的生成入口：把一次生成运行推进到审核中断点。

产出以 AI 原稿的形式落库（`app.operation_advice.draft`），随后图用运行时的
`interrupt()` 暂停等待理财顾问审核（`app.operation_advice.graph`）——本函数只发起
运行、拿到暂停前落库的原稿并返回，不关心恢复；恢复是 `app.advisory.review` 的职责，
它按内容类型查表拿到这张图（ADR-0020）。

发起人只能是客户经理，且只能对自己名下的客户（Q7）：**角色与归属是两道独立的门**。
角色在入口的依赖里声明（`require_employee_role`），归属在这里判定——混在一起写的话，
将来给别的角色开一个口子时，就会顺手把归属那一道也放开。归属的判定本身只有一份
（`app.customer_scope`），这里只决定「不属于你」对外说成什么。

**产品与金额 / 份额由发起人给，图之前先受理校验**（ADR-0021）：校验读的是可选项端点
的同一份计算（`app.operation_advice.options`），因此「下拉里有的」与「提交得过」不会
漂移。校验不进 `submit_transaction_event`（ADR-0018 不变）：那仍然是既成事实的入海口。
"""

import time
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import redis
from sqlalchemy.orm import Session

from app.agent import debug_trace
from app.agent.config import OPERATION_ADVICE_CONFIG
from app.customer_scope import is_under_management
from app.db.models import Customer, Employee
from app.exceptions import AppError
from app.operation_advice.draft import get_draft, serialize_draft
from app.operation_advice.graph import OperationAdviceState, build_graph
from app.operation_advice.options import (
    ALLOWED_DIRECTIONS,
    UNKNOWN_DIRECTION_MESSAGE,
    resolve_advice_choice,
)
from app.order_acceptance.service import PURCHASE

CUSTOMER_NOT_FOUND_MESSAGE = "客户不存在"
NOT_YOUR_CUSTOMER_MESSAGE = "该客户不在你的名下，无权发起建议"


def _ensure_own_customer(db: Session, *, manager: Employee, customer_id: int) -> None:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise AppError(404, CUSTOMER_NOT_FOUND_MESSAGE)
    if not is_under_management(customer, manager):
        raise AppError(403, NOT_YOUR_CUSTOMER_MESSAGE)


def generate_operation_advice(
    db: Session,
    cache: redis.Redis,
    *,
    customer_id: int,
    manager: Employee,
    direction: str,
    product_code: str,
    amount: Decimal | None = None,
    shares: Decimal | None = None,
    now: datetime,
) -> dict:
    # 三道门按「谁在问、问的是谁、问得对不对」的顺序过：角色在入口的依赖里，方向与
    # 归属在这里，发起人给的三个输入最后——被拒绝的是输入，不是这次请求本身。
    if direction not in ALLOWED_DIRECTIONS:
        raise AppError(400, UNKNOWN_DIRECTION_MESSAGE)
    _ensure_own_customer(db, manager=manager, customer_id=customer_id)
    # 受理校验读的是可选项端点的**同一份计算**（ADR-0021）：产品必须在方向的可选项里，
    # 金额 / 份额必须落在后端给出的区间内。不通过就到此为止——图根本不编译，因此图里
    # 不会出现「Agent 又选了一次」的余地。
    option, chosen = resolve_advice_choice(
        db,
        customer_id=customer_id,
        direction=direction,
        product_code=product_code,
        amount=amount,
        shares=shares,
        now=now,
    )

    graph = build_graph(db, cache)
    thread_id = uuid4().hex
    started = time.monotonic()
    inputs: OperationAdviceState = {
        "customer_id": customer_id,
        "manager_id": manager.id,
        "direction": direction,
        "product_code": option["product_code"],
        "now": now,
        "thread_id": thread_id,
    }
    # 两个方向各只有一个数：申购是金额、赎回是份额（`chosen` 由方向决定是哪一个）。
    if direction == PURCHASE:
        inputs["amount"] = chosen
    else:
        inputs["shares"] = chosen
    final_state = graph.invoke(inputs, {"configurable": {"thread_id": thread_id}})

    # 生成耗时进响应时间统计（与其余四个 Agent 同一张表）。
    debug_trace.record_response_time(
        db,
        agent_type=OPERATION_ADVICE_CONFIG.name,
        duration_ms=int((time.monotonic() - started) * 1000),
        user_id=manager.id,
    )

    return serialize_draft(db, get_draft(db, final_state["draft_id"]))
