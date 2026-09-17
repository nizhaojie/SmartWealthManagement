"""客户经理的可见范围：只看得到自己名下客户的业务。

其他内部角色不受限——理财顾问在本系统里不绑定客户归属（与 `app.advisory.access`
同一口径）。审核内容、工单与预警三处都按这条规则收紧可见范围，规则只写在这里一份：
各写一遍的话，改口径时总有一处会被漏掉，而漏掉的那一处就是一次越权读。

这里只有判定，没有错误码：三处调用方各自决定「看不到」对外说成什么（客户、工单、
预警各自的措辞与状态码不同），而「谁看得到谁」是同一件事。
"""

from __future__ import annotations

from app.auth.roles import ACCOUNT_MANAGER
from app.db.models import Customer, Employee


def restrict_to_own_customers(employee: Employee) -> bool:
    """这位员工是否只看得到自己名下的客户。"""
    return employee.employee_role == ACCOUNT_MANAGER


def is_under_management(customer: Customer | None, employee: Employee) -> bool:
    """这位客户是否在这位员工名下；不受限的角色一律为真。

    `customer` 为空表示查不到这位客户（例如没有关联客户的工单），对受限角色不可见。
    这是个纯函数：只比较两侧已有的事实，不查库。
    """
    if not restrict_to_own_customers(employee):
        return True
    return customer is not None and customer.manager_id == employee.id
