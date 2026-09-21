"""操作建议的内部入口：客户经理发起与查看进度，理财顾问审核，双方都能留言。

`CONTEXT.md`「客户经理」：可以为名下客户发起操作建议——它只发起，放行是理财顾问的
事。因此发起路由只对客户经理开放（归属校验在 `app.operation_advice.service`），
放行与驳回只对理财顾问开放。生成本身在业务操作 Agent 里、审核在审核流水线上，
这里只做参数拼装。

读取这一侧与方案同一条口径（`app.api.advisory`）：**理财顾问不受限，客户经理只能看
自己名下客户的**（`app.advisory.access.ensure_can_view`），两类角色都能看能留言，
放行与驳回只有理财顾问拿得到。审核页与进度表读同一份载荷与同一份审核状态
（`app.operation_advice.console`），因此「顾问看到的」与「客户经理看到的」不会漂移。
"""

from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.advisory.access import ensure_can_view
from app.advisory.comments import add_comment, list_comments
from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review import get_review_by_content
from app.auth.dependencies import require_employee_role
from app.auth.roles import ACCOUNT_MANAGER, ADVISOR
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.operation_advice.console import list_for_customer, serialize_review_status
from app.operation_advice.draft import get_draft, serialize_draft
from app.operation_advice.review import reject_advice, release_advice
from app.operation_advice.schemas import (
    OperationAdviceCommentRequest,
    OperationAdviceRejectRequest,
    OperationAdviceRequest,
)
from app.operation_advice.service import generate_operation_advice
from app.redis_client import get_redis

router = APIRouter(prefix="/api/internal/customers")
review_router = APIRouter(prefix="/api/internal/operation-advice")

# 审核内容的查看者：理财顾问审核，客户经理只读与留言。放行与驳回在这一对之外另收紧。
_VIEWERS = (ADVISOR, ACCOUNT_MANAGER)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _viewed_advice(db: Session, employee: Employee, advice_id: int):
    """按建议 id 取原稿并判定可见范围；不可见的与不存在的同义（404/403）。

    可见范围与方案那一侧共用 `ensure_can_view`：客户经理只能看自己名下客户的，
    理财顾问不受限。
    """
    draft = get_draft(db, advice_id)
    ensure_can_view(db, employee, draft.customer_id)
    return draft


def _review_of(db: Session, advice_id: int):
    """这条建议的审核记录。读取几处都按「内容类型 + 内容引用」寻址，写一遍就够。"""
    return get_review_by_content(
        db, content_type=CONTENT_TYPE_OPERATION_ADVICE, content_ref=advice_id
    )


@router.post("/{customer_id}/operation-advice")
def create_operation_advice(
    customer_id: int,
    body: OperationAdviceRequest,
    employee: Employee = Depends(require_employee_role(ACCOUNT_MANAGER)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    return ok(
        generate_operation_advice(
            db,
            cache,
            customer_id=customer_id,
            manager=employee,
            direction=body.direction,
            now=_now(),
        )
    )


@router.get("/{customer_id}/operation-advice")
def list_customer_operation_advice(
    customer_id: int,
    employee: Employee = Depends(require_employee_role(*_VIEWERS)),
    db: Session = Depends(get_session),
):
    # 客户经理看的是「这位客户的建议走到哪一步了」——按客户归属判定，与审核队列、
    # 预警列表的可见范围同一个口径（不是按发起人：客户转手后新经理要看得见全部）。
    ensure_can_view(db, employee, customer_id)
    return ok(list_for_customer(db, customer_id=customer_id, now=_now()))


@review_router.get("/{advice_id}")
def get_operation_advice(
    advice_id: int,
    employee: Employee = Depends(require_employee_role(*_VIEWERS)),
    db: Session = Depends(get_session),
):
    return ok(serialize_draft(db, _viewed_advice(db, employee, advice_id)))


@review_router.get("/{advice_id}/review")
def get_operation_advice_review(
    advice_id: int,
    employee: Employee = Depends(require_employee_role(*_VIEWERS)),
    db: Session = Depends(get_session),
):
    _viewed_advice(db, employee, advice_id)
    return ok(serialize_review_status(_review_of(db, advice_id)))


@review_router.get("/{advice_id}/comments")
def get_operation_advice_comments(
    advice_id: int,
    employee: Employee = Depends(require_employee_role(*_VIEWERS)),
    db: Session = Depends(get_session),
):
    _viewed_advice(db, employee, advice_id)
    return ok({"comments": list_comments(db, _review_of(db, advice_id).id)})


@review_router.post("/{advice_id}/comments")
def post_operation_advice_comment(
    advice_id: int,
    body: OperationAdviceCommentRequest,
    employee: Employee = Depends(require_employee_role(*_VIEWERS)),
    db: Session = Depends(get_session),
):
    _viewed_advice(db, employee, advice_id)
    review = _review_of(db, advice_id)
    comment = add_comment(db, review.id, author=employee, body=body.body, now=_now())
    return ok(comment)


@review_router.post("/{advice_id}/release")
def release_operation_advice(
    advice_id: int,
    # 放行资质在服务端收紧：客户经理看得到这条建议，但放不了行（发起与放行是两件事）。
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    return ok(
        release_advice(db, cache, advice_id=advice_id, advisor_id=employee.id, now=_now())
    )


@review_router.post("/{advice_id}/reject")
def reject_operation_advice(
    advice_id: int,
    body: OperationAdviceRejectRequest,
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    return ok(
        reject_advice(
            db,
            cache,
            advice_id=advice_id,
            advisor_id=employee.id,
            reason=body.reason,
            now=_now(),
        )
    )
