from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.advisory_request.schemas import AdvisoryRequestCreate
from app.advisory_request.service import (
    list_requests,
    list_requests_for_queue,
    submit_request,
)
from app.auth.dependencies import AuthContext, require_customer, require_internal
from app.db.session import get_session
from app.http import ok

router = APIRouter(prefix="/api/customer/advisory-requests")
internal_router = APIRouter(prefix="/api/internal/advisory-requests")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("")
def customer_submit_advisory_request(
    body: AdvisoryRequestCreate,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(
        submit_request(
            db,
            customer_id=auth.subject_id,
            filters=body.model_dump(),
            now=_now(),
        )
    )


@router.get("")
def customer_list_advisory_requests(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok({"requests": list_requests(db, customer_id=auth.subject_id)})


@internal_router.get("")
def internal_list_advisory_requests(
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
    status: str | None = None,
):
    return ok({"requests": list_requests_for_queue(db, status=status)})
