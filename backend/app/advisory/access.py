"""审核内容的查看权限：理财顾问不受限，客户经理只能看自己名下的客户。

放行/驳回的资质校验已经在 `require_employee_role(ADVISOR)` 里做了（见
app.api.advisory），这里只管「谁能看」——客户经理能看能评论，但看得到的
范围要收紧到自己负责的客户，否则「名下客户」这个概念就是摆设。
"""

from sqlalchemy.orm import Session

from app.auth.roles import ACCOUNT_MANAGER
from app.db.models import Customer, Employee
from app.exceptions import AppError

NOT_YOUR_CUSTOMER_MESSAGE = "该客户不在你的名下，无权查看"
CUSTOMER_NOT_FOUND_MESSAGE = "客户不存在"


def ensure_can_view(db: Session, employee: Employee, customer_id: int) -> None:
    if employee.employee_role != ACCOUNT_MANAGER:
        return

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise AppError(404, CUSTOMER_NOT_FOUND_MESSAGE)
    if customer.manager_id != employee.id:
        raise AppError(403, NOT_YOUR_CUSTOMER_MESSAGE)
