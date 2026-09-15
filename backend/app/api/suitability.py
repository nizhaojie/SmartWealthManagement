from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_customer, require_internal
from app.db.session import get_session
from app.http import ok
from app.suitability.service import get_candidate_pool, list_suitability_decisions

router = APIRouter(prefix="/api/customer/candidate-pool")
internal_router = APIRouter(prefix="/api/internal/customers")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("")
def customer_candidate_pool(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(get_candidate_pool(db, customer_id=auth.subject_id, now=_now()))


@internal_router.get("/{customer_id}/candidate-pool")
def internal_candidate_pool(
    customer_id: int,
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
):
    return ok(get_candidate_pool(db, customer_id=customer_id, now=_now()))


@internal_router.get("/{customer_id}/suitability-decisions")
def internal_suitability_decisions(
    customer_id: int,
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
):
    return ok(list_suitability_decisions(db, customer_id=customer_id))
