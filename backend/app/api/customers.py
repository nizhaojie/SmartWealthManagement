"""开户入口。

客户与员工分属两个身份域（ADR-0004），客户账号不能自助注册：由客户经理为其
名下客户开立。开户建立账户与初始画像（`app.customer_onboarding`），此后客户
本人才能登录、完成风险评测，进入客户可见视图内的各项服务。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_employee_role
from app.auth.roles import ACCOUNT_MANAGER
from app.customer_onboarding import open_account, serialize_account
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.redis_client import get_redis

router = APIRouter(prefix="/api/internal/customers")


class OpenAccountRequest(BaseModel):
    username: str
    password: str
    real_name: str
    id_number: str
    phone: str
    customer_level: str
    annual_income_range: str
    total_assets: str
    investment_experience: str
    target_allocation: dict | None = None
    product_preference: dict | None = None


@router.post("")
def open_customer_account(
    body: OpenAccountRequest,
    db: Session = Depends(get_session),
    cache=Depends(get_redis),
    employee: Employee = Depends(require_employee_role(ACCOUNT_MANAGER)),
):
    customer = open_account(
        db,
        cache,
        username=body.username.strip(),
        password=body.password,
        real_name=body.real_name,
        id_number=body.id_number,
        phone=body.phone,
        customer_level=body.customer_level,
        manager=employee,
        annual_income_range=body.annual_income_range,
        total_assets=body.total_assets,
        investment_experience=body.investment_experience,
        target_allocation=body.target_allocation,
        product_preference=body.product_preference,
        now=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    return ok(serialize_account(customer))
