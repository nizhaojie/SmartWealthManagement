from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_customer, require_internal
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params
from app.redis_client import get_redis
from app.risk_assessment.schemas import DraftAnswers, SubmitAnswers
from app.risk_assessment.service import (
    get_current_result,
    get_questionnaire,
    list_assessments,
    save_draft,
    submit_assessment,
)

router = APIRouter(prefix="/api/customer/risk-assessment")
internal_router = APIRouter(prefix="/api/internal/customers")


@router.get("/questionnaire")
def customer_questionnaire(auth: AuthContext = Depends(require_customer), cache=Depends(get_redis)):
    return ok(get_questionnaire(cache, customer_id=auth.subject_id))


@router.put("/draft")
def customer_save_draft(
    body: DraftAnswers,
    auth: AuthContext = Depends(require_customer),
    cache=Depends(get_redis),
):
    answers = save_draft(cache, customer_id=auth.subject_id, answers=body.answers)
    return ok({"answers": answers})


@router.post("")
def customer_submit_assessment(
    body: SubmitAnswers,
    auth: AuthContext = Depends(require_customer),
    cache=Depends(get_redis),
    db: Session = Depends(get_session),
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = submit_assessment(
        db,
        cache,
        customer_id=auth.subject_id,
        answers=body.answers,
        now=now,
    )
    return ok(result)


@router.get("")
def customer_current_assessment(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(get_current_result(db, customer_id=auth.subject_id))


@internal_router.get("/{customer_id}/risk-assessments")
def internal_list_assessments(
    customer_id: int,
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
    page: PageParams = Depends(page_params),
):
    return ok(list_assessments(db, customer_id=customer_id, page=page))
