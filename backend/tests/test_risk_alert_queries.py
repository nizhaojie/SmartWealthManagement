"""Seam 1：预警列表与详情的读取接口（ticket 04）。

覆盖两件风控专员靠它工作的事：按等级、状态、时间筛出先看哪一条；点进详情一次拿全
命中依据、关联交易、客户信息与这位客户的历史预警。

命中依据要落到**字段与值**的粒度（「交易金额 520000 ≥ 阈值 50000」），而不只是
规则名——所以这里断言的是 `rule_hits` 里的字段标签、实测值、阈值与算子符号，不是
一句「命中大额交易规则」。依据是命中那一刻的快照，阈值后来被调过也不该改写它。

可见范围与工单、审核内容同口径：客户经理只看得到自己名下客户的预警，其他内部角色
不受限。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    Customer,
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
MANAGER_ONE_USERNAME = "manager1"
MANAGER_TWO_USERNAME = "manager2"

SUBMIT_PATH = "/api/internal/transaction-events"
ALERTS_PATH = "/api/internal/risk-alerts"

TEST_EPOCH = datetime(2026, 1, 1)
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)

# wangc1 与 lisic2 归 manager1，zhaoc4 归 manager2（见 db/seed.py）。
CUSTOMER_LIGHT = "wangc1"
CUSTOMER_MODERATE = "lisic2"
CUSTOMER_OTHER_MANAGER = "zhaoc4"

PRODUCT_LOW_RISK = "F000001"
PRODUCT_BOND = "F000002"

# 5 万：只命中 R001（单笔大额交易），单条 == 轻度。
LIGHT_AMOUNT = "50000.00"
# 52 万：落到 R001/R003/R004/R005/R018 上，多条交叉且无历史 == 中度。
MODERATE_AMOUNT = "520000.00"


def _engine():
    return create_engine(get_settings().test_database_url)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _purge(engine) -> None:
    """清掉本文件造出来的预警、工单与交易。

    工单先删：`biz_work_order.source_alert_id` 指着预警，反过来删会撞外键。
    """
    with OrmSession(engine) as session:
        alert_ids = select(RiskAlert.id)
        order_ids = select(WorkOrder.id).where(WorkOrder.source_alert_id.in_(alert_ids))
        session.execute(
            delete(WorkOrderTransition).where(WorkOrderTransition.work_order_id.in_(order_ids))
        )
        session.execute(delete(WorkOrder).where(WorkOrder.source_alert_id.in_(alert_ids)))
        session.execute(delete(RiskAlert))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))
        session.commit()


@pytest.fixture(autouse=True)
def _clean_alert_state(auth_client: TestClient) -> Iterator[None]:
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


def _ids(engine, *, customer_username: str, product_code: str) -> tuple[int, int]:
    with OrmSession(engine) as session:
        customer_id = session.scalar(
            select(Customer.id).where(Customer.username == customer_username)
        )
        product_id = session.scalar(select(Product.id).where(Product.product_code == product_code))
    assert customer_id is not None and product_id is not None
    return int(customer_id), int(product_id)


def _submit_alert(
    client: TestClient,
    engine,
    headers: dict[str, str],
    *,
    customer_username: str = CUSTOMER_LIGHT,
    product_code: str = PRODUCT_LOW_RISK,
    amount: str = LIGHT_AMOUNT,
    occurred_at: datetime = TRADE_AT,
) -> dict:
    """走真实链路造一条预警：提交交易 → 落库 → 过规则引擎。"""
    customer_id, product_id = _ids(
        engine, customer_username=customer_username, product_code=product_code
    )
    response = client.post(
        SUBMIT_PATH,
        headers=headers,
        json={
            "customer_id": customer_id,
            "product_id": product_id,
            "transaction_type": "申购",
            "amount": amount,
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert response.status_code == 200
    alerts = response.json()["data"]["alerts"]
    assert alerts, "这笔交易本该命中规则"
    return alerts[0]


def _list(client: TestClient, headers: dict[str, str], **params) -> list[dict]:
    response = client.get(ALERTS_PATH, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def _detail(client: TestClient, headers: dict[str, str], alert_id: int) -> dict:
    response = client.get(f"{ALERTS_PATH}/{alert_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _hit(data: dict, rule_code: str) -> dict:
    hits = [hit for hit in data["rule_hits"] if hit["rule_code"] == rule_code]
    assert hits, f"命中依据里应当有 {rule_code}"
    return hits[0]


# --- 列表：筛选 ---


def test_the_list_carries_what_is_needed_to_decide_what_to_read_first(
    auth_client: TestClient,
):
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, engine, headers)

    rows = _list(auth_client, headers)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == alert["id"]
    assert row["customer_name"] == "王守成"
    assert row["alert_level"] == "轻度"
    assert row["confidence"] == 0.10
    assert row["rule_codes"] == ["R001"]
    assert row["rule_count"] == 1
    assert row["status"] == "未处理"
    assert row["work_order_id"] is None
    assert row["work_order_status"] is None


def test_alerts_are_listed_newest_first(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    older = _submit_alert(auth_client, engine, headers, occurred_at=TRADE_AT - timedelta(days=3))
    newer = _submit_alert(auth_client, engine, headers, occurred_at=TRADE_AT)

    rows = _list(auth_client, headers)

    assert [row["id"] for row in rows] == [newer["id"], older["id"]]


def test_the_list_filters_by_level(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    light = _submit_alert(auth_client, engine, headers)
    moderate = _submit_alert(
        auth_client,
        engine,
        headers,
        customer_username=CUSTOMER_MODERATE,
        product_code=PRODUCT_BOND,
        amount=MODERATE_AMOUNT,
    )
    assert moderate["alert_level"] == "中度"

    assert [row["id"] for row in _list(auth_client, headers, alert_level="轻度")] == [light["id"]]
    assert [row["id"] for row in _list(auth_client, headers, alert_level="中度")] == [
        moderate["id"]
    ]
    assert _list(auth_client, headers, alert_level="重度") == []


def test_the_list_filters_by_status(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    excluded = _submit_alert(auth_client, engine, headers)
    open_alert = _submit_alert(
        auth_client, engine, headers, occurred_at=TRADE_AT + timedelta(hours=1)
    )
    response = auth_client.post(
        f"{ALERTS_PATH}/{excluded['id']}/exclude",
        headers=headers,
        json={"reason": "客户资金来源为工资卡，误报"},
    )
    assert response.status_code == 200

    assert [row["id"] for row in _list(auth_client, headers, status="已排除")] == [excluded["id"]]
    assert [row["id"] for row in _list(auth_client, headers, status="未处理")] == [
        open_alert["id"]
    ]


def test_the_list_filters_by_when_the_alert_was_raised(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    _submit_alert(auth_client, engine, headers)

    past = (_now() - timedelta(hours=1)).isoformat()
    future = (_now() + timedelta(hours=1)).isoformat()

    assert len(_list(auth_client, headers, created_from=past)) == 1
    assert _list(auth_client, headers, created_from=future) == []
    assert len(_list(auth_client, headers, created_to=future)) == 1
    assert _list(auth_client, headers, created_to=past) == []


def test_no_alerts_at_all_is_an_empty_list(auth_client: TestClient):
    rows = _list(auth_client, _headers(auth_client))

    assert rows == []


# --- 详情：命中依据到字段与值 ---


def test_each_hit_is_rendered_down_to_the_field_the_value_and_the_threshold(
    auth_client: TestClient,
):
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, engine, headers, amount=LIGHT_AMOUNT)

    data = _detail(auth_client, headers, alert["id"])

    hit = _hit(data, "R001")
    assert hit["field"] == "amount"
    assert hit["field_label"] == "交易金额"
    assert hit["observed_value"] == "50000"
    assert hit["threshold"] == "50000"
    assert hit["operator"] == "gte"
    assert hit["operator_symbol"] == "≥"
    assert hit["evidence"] == "交易金额 50000 ≥ 阈值 50000"


def test_an_aggregate_hit_says_which_window_the_number_came_from(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(
        auth_client,
        engine,
        headers,
        customer_username=CUSTOMER_MODERATE,
        product_code=PRODUCT_BOND,
        amount=MODERATE_AMOUNT,
    )

    data = _detail(auth_client, headers, alert["id"])

    daily = _hit(data, "R003")
    assert daily["field"] == "amount"
    assert daily["observed_value"] == MODERATE_AMOUNT.split(".")[0]
    assert daily["threshold"] == "200000"
    assert daily["evidence"].startswith("同日交易金额合计")


def test_the_threshold_in_the_evidence_is_the_one_that_was_in_force_when_it_fired(
    auth_client: TestClient,
):
    """依据是命中那一刻的快照：阈值后来被调高，也不该把旧的预警重写成新口径。"""
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, engine, headers, amount=LIGHT_AMOUNT)
    assert _hit(_detail(auth_client, headers, alert["id"]), "R001")["threshold"] == "50000"

    rules = auth_client.get("/api/internal/risk-rules", headers=headers).json()["data"]["items"]
    r001 = next(rule for rule in rules if rule["rule_code"] == "R001")
    try:
        raised = auth_client.patch(
            f"/api/internal/risk-rules/{r001['id']}/threshold",
            headers=headers,
            json={"threshold": {"value": "1000000"}, "reason": "监管口径上调"},
        )
        assert raised.status_code == 200

        hit = _hit(_detail(auth_client, headers, alert["id"]), "R001")
        assert hit["threshold"] == "50000"
        assert hit["observed_value"] == "50000"
    finally:
        restored = auth_client.patch(
            f"/api/internal/risk-rules/{r001['id']}/threshold",
            headers=headers,
            json={"threshold": {"value": "50000"}, "reason": "用例收尾，恢复原口径"},
        )
        assert restored.status_code == 200


def test_the_detail_carries_the_related_transaction_without_switching_pages(
    auth_client: TestClient,
):
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, engine, headers, amount=LIGHT_AMOUNT)

    data = _detail(auth_client, headers, alert["id"])

    assert len(data["transactions"]) == 1
    transaction = data["transactions"][0]
    assert transaction["id"] == alert["transaction_ids"][0]
    assert transaction["transaction_type"] == "申购"
    assert transaction["amount"] == "50000.00"
    assert transaction["product_code"] == PRODUCT_LOW_RISK
    assert transaction["product_name"] == "天枢货币基金"


def test_the_detail_carries_the_customer_and_who_owns_the_relationship(
    auth_client: TestClient,
):
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, engine, headers)

    data = _detail(auth_client, headers, alert["id"])

    assert data["customer_name"] == "王守成"
    assert data["customer"]["real_name"] == "王守成"
    assert data["customer"]["customer_level"] == "普通"
    assert data["customer"]["risk_level"] == "C1"
    assert data["customer"]["manager_name"] == "刘经理"


def test_the_detail_lists_the_customers_other_alerts_as_history(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    older = _submit_alert(auth_client, engine, headers, occurred_at=TRADE_AT - timedelta(days=5))
    newer = _submit_alert(auth_client, engine, headers, occurred_at=TRADE_AT)

    data = _detail(auth_client, headers, newer["id"])

    assert [row["id"] for row in data["customer_history"]] == [older["id"]]
    assert data["customer_history"][0]["alert_level"] == "轻度"


def test_the_detail_shows_the_work_order_once_one_is_derived(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, engine, headers)
    assert _detail(auth_client, headers, alert["id"])["work_order"] is None

    derived = auth_client.post(
        f"{ALERTS_PATH}/{alert['id']}/work-orders",
        headers=headers,
        json={"reason": "金额与实际收入不匹配，需要核实资金来源"},
    )
    assert derived.status_code == 200
    work_order_id = derived.json()["data"]["id"]

    data = _detail(auth_client, headers, alert["id"])
    assert data["work_order"]["id"] == work_order_id
    assert data["work_order"]["status"] == "待处理"
    assert data["work_order"]["alert_id"] == alert["id"]
    assert [row["work_order_id"] for row in _list(auth_client, headers)] == [work_order_id]


def test_an_unknown_alert_is_reported_as_missing(auth_client: TestClient):
    response = auth_client.get(f"{ALERTS_PATH}/999999", headers=_headers(auth_client))

    assert response.status_code == 404


# --- 可见范围 ---


def test_an_account_manager_sees_only_their_own_customers_alerts(auth_client: TestClient):
    engine = _engine()
    officer = _headers(auth_client)
    mine = _submit_alert(auth_client, engine, officer)
    _submit_alert(auth_client, engine, officer, customer_username=CUSTOMER_OTHER_MANAGER)
    manager = _headers(auth_client, MANAGER_ONE_USERNAME)

    rows = _list(auth_client, manager)

    assert [row["id"] for row in rows] == [mine["id"]]


def test_the_other_manager_sees_a_different_set(auth_client: TestClient):
    engine = _engine()
    officer = _headers(auth_client)
    _submit_alert(auth_client, engine, officer)
    theirs = _submit_alert(
        auth_client, engine, officer, customer_username=CUSTOMER_OTHER_MANAGER
    )

    rows = _list(auth_client, _headers(auth_client, MANAGER_TWO_USERNAME))

    assert [row["id"] for row in rows] == [theirs["id"]]


def test_an_account_manager_cannot_open_an_alert_outside_their_book(auth_client: TestClient):
    engine = _engine()
    alert = _submit_alert(auth_client, engine, _headers(auth_client))

    response = auth_client.get(
        f"{ALERTS_PATH}/{alert['id']}", headers=_headers(auth_client, MANAGER_TWO_USERNAME)
    )

    assert response.status_code == 403
    assert "名下客户" in response.json()["message"]


def test_advisors_and_risk_officers_see_every_alert(auth_client: TestClient):
    engine = _engine()
    officer = _headers(auth_client)
    _submit_alert(auth_client, engine, officer)
    _submit_alert(auth_client, engine, officer, customer_username=CUSTOMER_OTHER_MANAGER)

    assert len(_list(auth_client, officer)) == 2
    assert len(_list(auth_client, _headers(auth_client, ADVISOR_USERNAME))) == 2


def test_reading_alerts_requires_an_internal_identity(auth_client: TestClient):
    assert auth_client.get(ALERTS_PATH).status_code == 401
    assert auth_client.get(f"{ALERTS_PATH}/1").status_code == 401


def test_the_disposition_is_visible_from_the_detail_page(auth_client: TestClient):
    """处置结果连同处置人一起出现在详情里，风控专员不必再去别处找。"""
    engine = _engine()
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, engine, headers)
    assert _detail(auth_client, headers, alert["id"])["handled_by_name"] == ""

    reason = "涉及跨机构资金往来，超出我的处置权限"
    auth_client.post(
        f"{ALERTS_PATH}/{alert['id']}/escalate", headers=headers, json={"reason": reason}
    )

    data = _detail(auth_client, headers, alert["id"])
    assert data["handled_by_name"] == "周风控"
    assert data["status"] == "已升级"
    assert data["handle_result"] == reason
