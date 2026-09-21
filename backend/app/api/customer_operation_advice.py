"""客户侧的「我的建议」：已送达的操作建议与客户决定。

两条约束在这里合流：**未放行的建议读不到**（读取入口按「已放行」过滤，见
`app.operation_advice.decision`），以及**最终决定权在客户手里**——接受与拒绝都只有
本人能做，客户标识由凭证推导，请求体里塞进来的不作数。接受当场成交，走的是与直接
交易同一个受理服务；这里的路由只做参数拼装。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_customer
from app.db.session import get_session
from app.event_bus import EventPublisher, get_event_publisher
from app.http import ok
from app.operation_advice.decision import decide, get_my_advice, list_my_advice
from app.operation_advice.schemas import CustomerDecisionRequest

router = APIRouter(prefix="/api/customer/operation-advice")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("")
def list_my_operation_advice(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    # 还没有建议时是空列表，不是 404——「还没有」不是一种错误。
    return ok(list_my_advice(db, customer_id=auth.subject_id, now=_now()))


@router.get("/{advice_id}")
def get_my_operation_advice(
    advice_id: int,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    # 未放行的、别人名下的与不存在的在这里同义（404）：客户侧读不到就是读不到。
    return ok(
        get_my_advice(
            db, advice_id=advice_id, customer_id=auth.subject_id, now=_now()
        )
    )


@router.post("/{advice_id}/decision")
def decide_my_operation_advice(
    advice_id: int,
    body: CustomerDecisionRequest,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    return ok(
        decide(
            db,
            publisher,
            advice_id=advice_id,
            customer_id=auth.subject_id,
            decision=body.decision,
            now=_now(),
        )
    )
