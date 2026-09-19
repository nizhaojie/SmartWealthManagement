from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.advisory.access import ensure_can_view
from app.advisory.comments import add_comment, list_comments
from app.advisory.draft import get_draft, serialize_draft
from app.advisory.final import (
    get_final_by_draft_id,
    get_final_for_customer_by_id,
    get_latest_final_for_customer,
    list_finals_for_customer,
    serialize_final,
    serialize_final_for_customer,
)
from app.advisory.queue import list_my_history, list_queue
from app.advisory.review import (
    get_review_by_draft_id,
    reject_review,
    release_review,
    serialize_review,
)
from app.advisory.schemas import (
    AdvisoryCommentRequest,
    AdvisoryPlanRequest,
    AdvisoryRejectRequest,
    AdvisoryReleaseRequest,
)
from app.advisory.service import generate_advisory_plan
from app.auth.dependencies import AuthContext, require_customer, require_employee_role
from app.auth.roles import ACCOUNT_MANAGER, ADVISOR
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.redis_client import get_redis

router = APIRouter(prefix="/api/internal/advisory")
customer_router = APIRouter(prefix="/api/customer/advisory")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/customers/{customer_id}/plan")
def generate_plan(
    customer_id: int,
    body: AdvisoryPlanRequest,
    # 只有理财顾问能发起生成：投顾助手 Agent 面向理财顾问，客户经理没有资质。
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    draft = generate_advisory_plan(
        db,
        cache,
        customer_id=customer_id,
        advisor_id=employee.id,
        tilt=body.tilt,
        now=_now(),
        advisory_request_id=body.advisory_request_id,
    )
    return ok(draft)


@router.get("/queue")
def get_advisory_queue(
    _employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
):
    return ok(list_queue(db, _now()))


@router.get("/history")
def get_advisory_history(
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
):
    return ok({"history": list_my_history(db, employee.id)})


@router.get("/drafts/{draft_id}")
def get_advisory_draft(
    draft_id: int,
    # AI 原稿是投顾内容审核前的举证材料；理财顾问不受限，客户经理只能看
    # 自己名下客户的（见 app.advisory.access）。
    employee: Employee = Depends(require_employee_role(ADVISOR, ACCOUNT_MANAGER)),
    db: Session = Depends(get_session),
):
    draft = get_draft(db, draft_id)
    ensure_can_view(db, employee, draft.customer_id)
    return ok(serialize_draft(draft))


@router.get("/drafts/{draft_id}/review")
def get_draft_review(
    draft_id: int,
    employee: Employee = Depends(require_employee_role(ADVISOR, ACCOUNT_MANAGER)),
    db: Session = Depends(get_session),
):
    draft = get_draft(db, draft_id)
    ensure_can_view(db, employee, draft.customer_id)
    return ok(serialize_review(get_review_by_draft_id(db, draft_id)))


@router.get("/drafts/{draft_id}/final")
def get_draft_final(
    draft_id: int,
    employee: Employee = Depends(require_employee_role(ADVISOR, ACCOUNT_MANAGER)),
    db: Session = Depends(get_session),
):
    draft = get_draft(db, draft_id)
    ensure_can_view(db, employee, draft.customer_id)
    return ok(serialize_final(db, get_final_by_draft_id(db, draft_id)))


@router.get("/drafts/{draft_id}/comments")
def get_draft_comments(
    draft_id: int,
    employee: Employee = Depends(require_employee_role(ADVISOR, ACCOUNT_MANAGER)),
    db: Session = Depends(get_session),
):
    draft = get_draft(db, draft_id)
    ensure_can_view(db, employee, draft.customer_id)
    review = get_review_by_draft_id(db, draft_id)
    return ok({"comments": list_comments(db, review.id)})


@router.post("/drafts/{draft_id}/comments")
def post_draft_comment(
    draft_id: int,
    body: AdvisoryCommentRequest,
    employee: Employee = Depends(require_employee_role(ADVISOR, ACCOUNT_MANAGER)),
    db: Session = Depends(get_session),
):
    draft = get_draft(db, draft_id)
    ensure_can_view(db, employee, draft.customer_id)
    review = get_review_by_draft_id(db, draft_id)
    comment = add_comment(db, review.id, author=employee, body=body.body, now=_now())
    return ok(comment)


@router.post("/drafts/{draft_id}/release")
def release_advisory_draft(
    draft_id: int,
    body: AdvisoryReleaseRequest,
    # 放行资质在服务端收紧：只有理财顾问能放行，客户经理看得到但放不了行。
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    final = release_review(
        db,
        cache,
        draft_id=draft_id,
        advisor_id=employee.id,
        now=_now(),
        candidates=body.candidates,
        allocation_suggestion=body.allocation_suggestion,
        warnings=body.warnings,
    )
    return ok(final)


@router.post("/drafts/{draft_id}/reject")
def reject_advisory_draft(
    draft_id: int,
    body: AdvisoryRejectRequest,
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    result = reject_review(
        db,
        cache,
        draft_id=draft_id,
        advisor_id=employee.id,
        reason=body.reason,
        now=_now(),
    )
    return ok(result)


@customer_router.get("/plans")
def customer_list_advisory_plans(
    # 客户侧只读定稿：未经审核的原稿无论走哪个接口都读不到。
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    # 尚无已放行方案时是空列表，不是 404——「还没有方案」不是一种错误。
    return ok(
        {
            "plans": [
                serialize_final_for_customer(db, final)
                for final in list_finals_for_customer(db, customer_id=auth.subject_id)
            ]
        }
    )


@customer_router.get("/plans/{final_id}")
def customer_get_advisory_plan_by_id(
    final_id: int,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    # 范围由 id 与调用者共同圈定，不是由令牌单独兜住——越权检查显式写在
    # get_final_for_customer_by_id 里，别人的定稿在这里与不存在同义（404）。
    return ok(
        serialize_final_for_customer(
            db,
            get_final_for_customer_by_id(db, final_id=final_id, customer_id=auth.subject_id),
        )
    )


@customer_router.get("/plan")
def customer_get_advisory_plan(
    # 客户侧只读定稿：未经审核的原稿无论走哪个接口都读不到。
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(
        serialize_final_for_customer(
            db, get_latest_final_for_customer(db, customer_id=auth.subject_id)
        )
    )
