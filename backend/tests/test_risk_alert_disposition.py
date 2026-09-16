"""预警自身的处置判定：排除与升级。

预警是事实记录，它只收下一个由人做出的判定结果：**已排除**（误报，附原因）或
**已升级**（超出处置权限，交上去）。两条路径都要求处置人与非空理由，都只能做出
一次——第二个请求会撞上一个已经被写下的结论。

这里也覆盖「系统不自动关闭任何预警」的另一半：没有处置这个动作，预警就一直停在
「未处理」，无论它多低置信、过了多久。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, Employee, Product, RiskAlert, Transaction
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER_USERNAME = "risk1"
ADVISOR_USERNAME = "advisor1"

SUBMIT_PATH = "/api/internal/transaction-events"
ALERTS_PATH = "/api/internal/risk-alerts"

TEST_EPOCH = datetime(2026, 1, 1)
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)

CUSTOMER_LIGHT = "wangc1"
PRODUCT_R1 = "F000001"

EXCLUDE_REASON = "客户资金来源为工资卡，误报"
ESCALATE_REASON = "涉及跨机构资金往来，超出我的处置权限"


def _engine():
    return create_engine(get_settings().test_database_url)


def _purge(engine) -> None:
    with OrmSession(engine) as session:
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


def _an_alert(client: TestClient, engine, headers: dict[str, str]) -> int:
    with OrmSession(engine) as session:
        customer_id = session.scalar(select(Customer.id).where(Customer.username == CUSTOMER_LIGHT))
        product_id = session.scalar(
            select(Product.id).where(Product.product_code == PRODUCT_R1)
        )
    response = client.post(
        SUBMIT_PATH,
        headers=headers,
        json={
            "customer_id": int(customer_id),
            "product_id": int(product_id),
            "transaction_type": "申购",
            "amount": "50000.00",
            "occurred_at": TRADE_AT.isoformat(),
        },
    )
    assert response.status_code == 200
    return int(response.json()["data"]["alerts"][0]["id"])


def _officer_id(engine) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(
            select(Employee.id).where(Employee.username == RISK_OFFICER_USERNAME)
        )
    assert value is not None
    return int(value)


def test_excluding_an_alert_records_the_handler_and_the_reason(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    response = auth_client.post(
        f"{ALERTS_PATH}/{alert_id}/exclude", headers=headers, json={"reason": EXCLUDE_REASON}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "已排除"
    assert data["handle_result"] == EXCLUDE_REASON
    assert data["handled_by_name"] == "周风控"

    with OrmSession(engine) as session:
        stored = session.get(RiskAlert, alert_id)
    assert stored is not None
    assert stored.handler_id == _officer_id(engine)
    assert stored.handle_result == EXCLUDE_REASON


def test_escalating_an_alert_records_the_handler_and_the_reason(auth_client: TestClient):
    """升级不改编预警的等级与置信度：那是规则命中算出来的事实，不由人改写。"""
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    response = auth_client.post(
        f"{ALERTS_PATH}/{alert_id}/escalate", headers=headers, json={"reason": ESCALATE_REASON}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "已升级"
    assert data["handle_result"] == ESCALATE_REASON
    assert data["alert_level"] == "轻度"
    assert data["rule_codes"] == ["R001"]


def test_a_disposition_without_a_reason_is_rejected(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    for action in ("exclude", "escalate"):
        response = auth_client.post(
            f"{ALERTS_PATH}/{alert_id}/{action}", headers=headers, json={"reason": "  "}
        )
        assert response.status_code == 400, action
        assert "理由" in response.json()["message"]

    with OrmSession(engine) as session:
        stored = session.get(RiskAlert, alert_id)
    assert stored is not None
    assert stored.status == "未处理"
    assert stored.handler_id is None
    assert stored.handle_result is None


def test_an_alert_can_only_be_judged_once(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    alert_id = _an_alert(auth_client, engine, headers)

    first = auth_client.post(
        f"{ALERTS_PATH}/{alert_id}/exclude", headers=headers, json={"reason": EXCLUDE_REASON}
    )
    assert first.status_code == 200

    again = auth_client.post(
        f"{ALERTS_PATH}/{alert_id}/exclude", headers=headers, json={"reason": "再排除一次"}
    )
    assert again.status_code == 409
    assert "已处置" in again.json()["message"]

    other = auth_client.post(
        f"{ALERTS_PATH}/{alert_id}/escalate", headers=headers, json={"reason": ESCALATE_REASON}
    )
    assert other.status_code == 409

    with OrmSession(engine) as session:
        stored = session.get(RiskAlert, alert_id)
    assert stored is not None and stored.handle_result == EXCLUDE_REASON


def test_only_risk_officers_can_judge_an_alert(auth_client: TestClient):
    engine = _engine()
    officer = _headers(auth_client, RISK_OFFICER_USERNAME)
    advisor = _headers(auth_client, ADVISOR_USERNAME)
    alert_id = _an_alert(auth_client, engine, officer)

    for action in ("exclude", "escalate"):
        assert (
            auth_client.post(
                f"{ALERTS_PATH}/{alert_id}/{action}",
                headers=advisor,
                json={"reason": EXCLUDE_REASON},
            ).status_code
            == 403
        ), action

    assert (
        auth_client.post(
            f"{ALERTS_PATH}/{alert_id}/exclude", json={"reason": EXCLUDE_REASON}
        ).status_code
        == 401
    )


def test_judging_an_unknown_alert_is_reported_as_missing(auth_client: TestClient):
    headers = _headers(auth_client)
    response = auth_client.post(
        f"{ALERTS_PATH}/999999/exclude", headers=headers, json={"reason": EXCLUDE_REASON}
    )
    assert response.status_code == 404
