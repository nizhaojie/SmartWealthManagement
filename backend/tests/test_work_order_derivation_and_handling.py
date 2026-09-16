"""工单派生与处置流程。

三件事在这里被固定下来：

- **一条预警最多派生一张工单**。重复派生被拒绝，数据库上的唯一约束是最后一道；
- **每次状态流转都记下处置人与非空理由**，空理由的请求被拒绝，工单状态不动；
- 工单走完整个生命周期也不动预警的状态——**系统不自动关闭任何预警**，关闭只能
  由人做出并留下理由。

工单也能来自预警之外的源头（客户投诉、转人工），这类工单不带来源预警，也不受
「一条预警一张工单」的约束。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    Customer,
    Employee,
    Product,
    RiskAlert,
    Transaction,
    WorkOrder,
    WorkOrderTransition,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER_USERNAME = "risk1"
ADVISOR_USERNAME = "advisor1"
MANAGER_USERNAME = "manager1"
MANAGER2_USERNAME = "manager2"

SUBMIT_PATH = "/api/internal/transaction-events"
ALERTS_PATH = "/api/internal/risk-alerts"
WORK_ORDERS_PATH = "/api/internal/work-orders"

# 测试自己造的交易都落在 2026 年之后；种子数据最晚一笔在 2023 年，两者不会混。
TEST_EPOCH = datetime(2026, 1, 1)
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)

CUSTOMER_LIGHT = "wangc1"  # 归属 manager1
CUSTOMER_OTHER = "zhaoc4"  # 归属 manager2
PRODUCT_R1 = "F000001"

DERIVE_REASON = "客户短期内大额申购，需要核实资金来源"
ACCEPT_REASON = "已接单，联系客户核实"
COMPLETE_REASON = "客户已提供资金来源证明，核实完毕"
CONCLUSION = "确认为正常交易，非可疑"


def _engine():
    return create_engine(get_settings().test_database_url)


def _purge(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(WorkOrderTransition))
        session.execute(delete(WorkOrder))
        session.execute(delete(RiskAlert))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))
        session.commit()


@pytest.fixture(autouse=True)
def _clean_work_order_state(auth_client: TestClient) -> Iterator[None]:
    engine = _engine()
    _purge(engine)
    try:
        yield
    finally:
        _purge(engine)
        engine.dispose()


def _headers(client: TestClient, username: str = RISK_OFFICER_USERNAME) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == username))
    assert value is not None
    return int(value)


def _product_id(engine, product_code: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Product.id).where(Product.product_code == product_code))
    assert value is not None
    return int(value)


def _employee_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Employee.id).where(Employee.username == username))
    assert value is not None
    return int(value)


def _an_alert(client: TestClient, engine, headers: dict[str, str], *, amount: str = "50000.00") -> int:
    """走一遍真实链路造一条预警：提交交易事件，命中的规则产生预警。"""
    response = client.post(
        SUBMIT_PATH,
        headers=headers,
        json={
            "customer_id": _customer_id(engine, CUSTOMER_LIGHT),
            "product_id": _product_id(engine, PRODUCT_R1),
            "transaction_type": "申购",
            "amount": amount,
            "occurred_at": TRADE_AT.isoformat(),
        },
    )
    assert response.status_code == 200
    alerts = response.json()["data"]["alerts"]
    assert len(alerts) == 1
    return int(alerts[0]["id"])


def _derive(client: TestClient, headers: dict[str, str], alert_id: int, reason: str = DERIVE_REASON):
    return client.post(
        f"{ALERTS_PATH}/{alert_id}/work-orders", headers=headers, json={"reason": reason}
    )


def _transitions(engine, work_order_id: int) -> list[WorkOrderTransition]:
    with OrmSession(engine) as session:
        return list(
            session.scalars(
                select(WorkOrderTransition)
                .where(WorkOrderTransition.work_order_id == work_order_id)
                .order_by(WorkOrderTransition.id.asc())
            ).all()
        )


def _stored_alert(engine, alert_id: int) -> RiskAlert:
    with OrmSession(engine) as session:
        alert = session.get(RiskAlert, alert_id)
    assert alert is not None
    return alert


def test_deriving_a_work_order_from_an_alert_records_the_owner_and_the_reason(
    auth_client: TestClient,
):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    response = _derive(auth_client, headers, alert_id)

    assert response.status_code == 200
    order = response.json()["data"]
    assert order["work_order_no"]
    assert order["order_type"] == "预警处置"
    assert order["alert_id"] == alert_id
    assert order["status"] == "待处理"
    # 轻度预警派生的工单是普通优先级——等级决定优先级，不需要人再选一次。
    assert order["priority"] == "普通"
    # 派生人即受理人：工单从产生那一刻就有责任人。
    assert order["handler_id"] == _employee_id(engine, RISK_OFFICER_USERNAME)
    assert order["handle_reason"] == DERIVE_REASON
    assert order["customer_id"] == _customer_id(engine, CUSTOMER_LIGHT)
    assert order["handle_result"] is None

    with OrmSession(engine) as session:
        stored = session.scalar(select(WorkOrder).where(WorkOrder.id == order["id"]))
    assert stored is not None
    assert stored.source_alert_id == alert_id
    assert stored.submitter_id == _employee_id(engine, RISK_OFFICER_USERNAME)

    # 建单也留痕：工单的第一个状态同样有出处，不是凭空出现的。
    records = _transitions(engine, order["id"])
    assert len(records) == 1
    assert records[0].from_status is None
    assert records[0].to_status == "待处理"
    assert records[0].handler_id == _employee_id(engine, RISK_OFFICER_USERNAME)
    assert records[0].reason == DERIVE_REASON


def test_the_same_alert_cannot_derive_a_second_work_order(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    assert _derive(auth_client, headers, alert_id).status_code == 200

    duplicate = _derive(auth_client, headers, alert_id, reason="再派一张")
    assert duplicate.status_code == 409
    assert "工单" in duplicate.json()["message"]

    with OrmSession(engine) as session:
        assert len(list(session.scalars(select(WorkOrder)).all())) == 1


def test_deriving_requires_a_reason(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    response = _derive(auth_client, headers, alert_id, reason="   ")

    assert response.status_code == 400
    assert "理由" in response.json()["message"]
    with OrmSession(engine) as session:
        assert list(session.scalars(select(WorkOrder)).all()) == []


def test_an_alert_that_was_already_judged_does_not_derive_a_work_order(auth_client: TestClient):
    """已排除或已升级的预警不再派生工单：处置结论已经由人做出了。"""
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    excluded = auth_client.post(
        f"{ALERTS_PATH}/{alert_id}/exclude",
        headers=headers,
        json={"reason": "客户资金来源为工资卡，误报"},
    )
    assert excluded.status_code == 200

    response = _derive(auth_client, headers, alert_id)
    assert response.status_code == 409
    assert _stored_alert(engine, alert_id).status == "已排除"


def test_deriving_from_an_unknown_alert_is_reported_as_missing(auth_client: TestClient):
    headers = _headers(auth_client)
    assert _derive(auth_client, headers, 999999).status_code == 404


def test_a_work_order_can_come_from_a_source_other_than_an_alert(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    customer_id = _customer_id(engine, CUSTOMER_LIGHT)

    complaint = auth_client.post(
        WORK_ORDERS_PATH,
        headers=headers,
        json={
            "order_type": "客户投诉",
            "customer_id": customer_id,
            "reason": "客户投诉收益到账延迟",
        },
    )
    assert complaint.status_code == 200
    order = complaint.json()["data"]
    assert order["order_type"] == "客户投诉"
    assert order["alert_id"] is None
    assert order["status"] == "待处理"
    assert order["priority"] == "普通"
    assert order["customer_id"] == customer_id
    assert order["handle_reason"] == "客户投诉收益到账延迟"

    # 没有来源预警的工单不受「一条预警一张工单」约束，可以有多张。
    transfer = auth_client.post(
        WORK_ORDERS_PATH,
        headers=headers,
        json={"order_type": "转人工", "reason": "客户要求人工说明持仓调整"},
    )
    assert transfer.status_code == 200
    assert transfer.json()["data"]["alert_id"] is None

    with OrmSession(engine) as session:
        assert len(list(session.scalars(select(WorkOrder)).all())) == 2


def test_a_source_the_work_order_does_not_support_is_rejected(auth_client: TestClient):
    """「预警处置」只能由预警派生：直接从建单入口进来会绕开「一条预警一张工单」。"""
    headers = _headers(auth_client)

    for order_type in ("预警处置", "随便写"):
        response = auth_client.post(
            WORK_ORDERS_PATH,
            headers=headers,
            json={"order_type": order_type, "reason": "试试"},
        )
        assert response.status_code == 400, order_type
        assert "来源" in response.json()["message"]


def test_an_unknown_customer_on_an_external_work_order_is_reported_as_missing(
    auth_client: TestClient,
):
    headers = _headers(auth_client)
    response = auth_client.post(
        WORK_ORDERS_PATH,
        headers=headers,
        json={"order_type": "客户投诉", "customer_id": 999999, "reason": "投诉"},
    )
    assert response.status_code == 404
    assert "客户" in response.json()["message"]


def test_the_lifecycle_runs_from_pending_through_in_progress_to_completed(
    auth_client: TestClient,
):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    order_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]

    accepted = auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=headers, json={"reason": ACCEPT_REASON}
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["status"] == "处理中"
    assert accepted.json()["data"]["current_node"] == "处理中"

    completed = auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/complete",
        headers=headers,
        json={"reason": COMPLETE_REASON, "conclusion": CONCLUSION},
    )
    assert completed.status_code == 200
    order = completed.json()["data"]
    assert order["status"] == "已完成"
    assert order["handle_result"] == CONCLUSION
    assert order["handle_reason"] == COMPLETE_REASON

    records = _transitions(engine, order_id)
    assert [(row.from_status, row.to_status) for row in records] == [
        (None, "待处理"),
        ("待处理", "处理中"),
        ("处理中", "已完成"),
    ]
    assert [row.reason for row in records] == [DERIVE_REASON, ACCEPT_REASON, COMPLETE_REASON]
    assert {row.handler_id for row in records} == {_employee_id(engine, RISK_OFFICER_USERNAME)}


def test_a_work_order_can_be_closed_from_in_progress_without_a_conclusion(
    auth_client: TestClient,
):
    """「已关闭」是不了了之的终止：理由必须说清为什么关，但不要求一份处置结论。"""
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    order_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]
    auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=headers, json={"reason": ACCEPT_REASON}
    )

    closed = auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/close",
        headers=headers,
        json={"reason": "客户已销户，工单终止"},
    )

    assert closed.status_code == 200
    assert closed.json()["data"]["status"] == "已关闭"
    assert closed.json()["data"]["handle_result"] is None


def test_a_transition_without_a_reason_is_rejected(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    order_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]

    blank = auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=headers, json={"reason": "   "}
    )
    assert blank.status_code == 400
    assert "理由" in blank.json()["message"]

    with OrmSession(engine) as session:
        stored = session.get(WorkOrder, order_id)
    assert stored is not None and stored.status == "待处理"
    # 被拒绝的请求不留痕：留痕意味着那次流转真的发生了。
    assert len(_transitions(engine, order_id)) == 1


def test_completing_without_a_conclusion_is_rejected(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    order_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]
    auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=headers, json={"reason": ACCEPT_REASON}
    )

    response = auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/complete",
        headers=headers,
        json={"reason": COMPLETE_REASON, "conclusion": "  "},
    )

    assert response.status_code == 400
    assert "结论" in response.json()["message"]
    with OrmSession(engine) as session:
        stored = session.get(WorkOrder, order_id)
    assert stored is not None and stored.status == "处理中"


def test_the_lifecycle_is_a_one_way_chain(auth_client: TestClient):
    """待处理不能直接完成，已完成与已关闭不能再流转。"""
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    order_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]

    skipping_ahead = auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/complete",
        headers=headers,
        json={"reason": COMPLETE_REASON, "conclusion": CONCLUSION},
    )
    assert skipping_ahead.status_code == 409

    auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=headers, json={"reason": ACCEPT_REASON}
    )
    auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/complete",
        headers=headers,
        json={"reason": COMPLETE_REASON, "conclusion": CONCLUSION},
    )

    for path in ("accept", "complete", "close"):
        again = auth_client.post(
            f"{WORK_ORDERS_PATH}/{order_id}/{path}",
            headers=headers,
            json={"reason": "再推一次", "conclusion": CONCLUSION},
        )
        assert again.status_code == 409, path


def test_an_unknown_work_order_is_reported_as_missing(auth_client: TestClient):
    headers = _headers(auth_client)
    assert auth_client.get(f"{WORK_ORDERS_PATH}/999999", headers=headers).status_code == 404
    assert (
        auth_client.post(
            f"{WORK_ORDERS_PATH}/999999/accept", headers=headers, json={"reason": "接单"}
        ).status_code
        == 404
    )


def test_finishing_a_work_order_does_not_close_the_alert(auth_client: TestClient):
    """系统不自动关闭任何预警：工单走完，预警还停在「未处理」。

    预警的关闭只能由人做出并留下理由（排除）。把「工单完成了」当成「预警关闭了」
    会让预警被处置流程悄悄消化掉——这正是 CONTEXT 里要把两者分开的原因。
    """
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    order_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]
    auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=headers, json={"reason": ACCEPT_REASON}
    )
    auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/complete",
        headers=headers,
        json={"reason": COMPLETE_REASON, "conclusion": CONCLUSION},
    )

    alert = _stored_alert(engine, alert_id)
    assert alert.status == "未处理"
    assert alert.handler_id is None
    assert alert.handle_result is None


def test_the_list_can_be_filtered_by_status_and_by_alert(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    derived_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]
    external = auth_client.post(
        WORK_ORDERS_PATH,
        headers=headers,
        json={"order_type": "客户投诉", "reason": "客户投诉收益到账延迟"},
    ).json()["data"]["id"]

    pending = auth_client.get(f"{WORK_ORDERS_PATH}?status=待处理", headers=headers).json()["data"]
    assert {order["id"] for order in pending} == {derived_id, external}

    auth_client.post(
        f"{WORK_ORDERS_PATH}/{derived_id}/accept", headers=headers, json={"reason": ACCEPT_REASON}
    )
    in_progress = auth_client.get(
        f"{WORK_ORDERS_PATH}?status=处理中", headers=headers
    ).json()["data"]
    assert [order["id"] for order in in_progress] == [derived_id]

    by_alert = auth_client.get(
        f"{WORK_ORDERS_PATH}?alert_id={alert_id}", headers=headers
    ).json()["data"]
    assert [order["id"] for order in by_alert] == [derived_id]


def test_the_work_order_detail_carries_the_transition_history(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)
    order_id = _derive(auth_client, headers, alert_id).json()["data"]["id"]
    auth_client.post(
        f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=headers, json={"reason": ACCEPT_REASON}
    )

    detail = auth_client.get(f"{WORK_ORDERS_PATH}/{order_id}", headers=headers)

    assert detail.status_code == 200
    order = detail.json()["data"]
    assert order["status"] == "处理中"
    assert order["handler_name"] == "周风控"
    assert [record["to_status"] for record in order["transitions"]] == ["待处理", "处理中"]
    assert order["transitions"][0]["from_status"] is None
    assert order["transitions"][0]["reason"] == DERIVE_REASON
    assert order["transitions"][0]["handler_name"] == "周风控"
    assert order["transitions"][0]["handled_at"]


def test_only_risk_officers_can_write_work_orders(auth_client: TestClient):
    engine = _engine()
    officer = _headers(auth_client, RISK_OFFICER_USERNAME)
    advisor = _headers(auth_client, ADVISOR_USERNAME)
    manager = _headers(auth_client, MANAGER_USERNAME)
    alert_id = _an_alert(auth_client, engine, officer)
    order_id = _derive(auth_client, officer, alert_id).json()["data"]["id"]

    assert _derive(auth_client, advisor, alert_id, reason="我也派一张").status_code == 403
    assert (
        auth_client.post(
            WORK_ORDERS_PATH,
            headers=advisor,
            json={"order_type": "客户投诉", "reason": "投诉"},
        ).status_code
        == 403
    )
    assert (
        auth_client.post(
            f"{WORK_ORDERS_PATH}/{order_id}/accept", headers=manager, json={"reason": "接单"}
        ).status_code
        == 403
    )

    # 读不受限：理财顾问与客户经理要看得到自己客户名下的工单状态。
    assert auth_client.get(WORK_ORDERS_PATH, headers=advisor).status_code == 200
    assert auth_client.get(f"{WORK_ORDERS_PATH}/{order_id}", headers=manager).status_code == 200


def test_an_account_manager_only_sees_his_own_customers_work_orders(auth_client: TestClient):
    """「看得见自己名下客户的工单」不是「看得见所有人的工单」。

    与审核流的查看权限同一口径（`app.advisory.access`）：客户经理的范围收到自己名下
    的客户，理财顾问不受限。
    """
    engine = _engine()
    officer = _headers(auth_client, RISK_OFFICER_USERNAME)
    first_manager = _headers(auth_client, MANAGER_USERNAME)
    second_manager = _headers(auth_client, MANAGER2_USERNAME)
    advisor = _headers(auth_client, ADVISOR_USERNAME)

    alert_id = _an_alert(auth_client, engine, officer)
    own_order = _derive(auth_client, officer, alert_id).json()["data"]["id"]
    other_customer = _customer_id(engine, CUSTOMER_OTHER)
    other_order = auth_client.post(
        WORK_ORDERS_PATH,
        headers=officer,
        json={
            "order_type": "客户投诉",
            "customer_id": other_customer,
            "reason": "客户投诉收益到账延迟",
        },
    ).json()["data"]["id"]

    first_list = auth_client.get(WORK_ORDERS_PATH, headers=first_manager).json()["data"]
    assert [order["id"] for order in first_list] == [own_order]

    second_list = auth_client.get(WORK_ORDERS_PATH, headers=second_manager).json()["data"]
    assert [order["id"] for order in second_list] == [other_order]

    forbidden = auth_client.get(f"{WORK_ORDERS_PATH}/{other_order}", headers=first_manager)
    assert forbidden.status_code == 403
    assert "名下" in forbidden.json()["message"]

    assert auth_client.get(f"{WORK_ORDERS_PATH}/{other_order}", headers=second_manager).status_code == 200
    # 理财顾问与风控专员不受这条限制。
    assert len(auth_client.get(WORK_ORDERS_PATH, headers=advisor).json()["data"]) == 2
    assert len(auth_client.get(WORK_ORDERS_PATH, headers=officer).json()["data"]) == 2


def test_work_order_endpoints_reject_unauthenticated_calls(auth_client: TestClient):
    assert auth_client.get(WORK_ORDERS_PATH).status_code == 401
    assert auth_client.post(WORK_ORDERS_PATH, json={"order_type": "客户投诉"}).status_code == 401
    assert (
        auth_client.post(
            f"{WORK_ORDERS_PATH}/1/accept", json={"reason": "接单"}
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            f"{ALERTS_PATH}/1/work-orders", json={"reason": "派生"}
        ).status_code
        == 401
    )
