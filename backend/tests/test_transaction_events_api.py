"""内部补录：先落库、再广播、后过规则引擎，以及预警分级。

补录是修复数据与演示用的窄口，它绕过适当性、起投金额与余额的校验（ADR-0018），
因此**只对风控专员开放**——这是护栏 7 在接口层的落点。交易的常规入口是客户侧的
受理（`app.api.customer_transactions`）：那一条路径的断言、「广播不可用仍照常落库」
与来源标注都在 `tests/test_transactions_as_risk_input.py`。

分级的行为在这里端到端固定下来：同一笔交易命中的规则数与该客户的历史预警记录
共同决定等级。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, Product, RiskAlert, Transaction
from app.event_bus import (
    EVENT_RISK_ALERT_RAISED,
    EVENT_TRANSACTION_SUBMITTED,
    Event,
    get_event_publisher,
)
from app.main import app
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
INTERNAL_USERNAME = "risk1"
ADVISOR_USERNAME = "advisor1"
MANAGER_USERNAME = "manager1"

SUBMIT_PATH = "/api/internal/transaction-events"

# 测试自己造的交易都落在 2026 年之后；种子数据最晚一笔在 2023 年，两者不会混。
TEST_EPOCH = datetime(2026, 1, 1)
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)

CUSTOMER_LIGHT = "wangc1"  # C1，总资产 8 万
CUSTOMER_MODERATE = "zhangc3"  # C3，总资产 80 万
CUSTOMER_SEVERE = "lisic2"  # C2，总资产 30 万

PRODUCT_R1 = "F000001"
PRODUCT_R4 = "F000004"
PRODUCT_R5 = "F000005"


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)


class _PersistenceProbe:
    """广播时从另一个连接回查：能查到，才说明「先落库、再广播」是真的。"""

    def __init__(self, engine) -> None:
        self._engine = engine
        self.persisted_when_broadcast: bool | None = None

    def publish(self, event: Event) -> None:
        if event.event_type != EVENT_TRANSACTION_SUBMITTED:
            return
        with OrmSession(self._engine) as session:
            row = session.scalar(
                select(Transaction.id).where(
                    Transaction.transaction_no == event.payload["transaction_no"]
                )
            )
        self.persisted_when_broadcast = row is not None


def _engine():
    return create_engine(get_settings().test_database_url)


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


def _purge(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(RiskAlert))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))
        session.commit()


@pytest.fixture(autouse=True)
def _clean_risk_state(auth_client: TestClient) -> Iterator[None]:
    engine = _engine()
    _purge(engine)
    try:
        yield
    finally:
        _purge(engine)
        engine.dispose()


@contextmanager
def _use_publisher(publisher) -> Iterator[None]:
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_event_publisher, None)


def _headers(client: TestClient, username: str = INTERNAL_USERNAME) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _submit(
    client: TestClient,
    headers: dict[str, str],
    *,
    customer_id: int,
    product_id: int,
    amount: str,
    transaction_type: str = "申购",
    occurred_at: datetime = TRADE_AT,
    **extra,
):
    body = {
        "customer_id": customer_id,
        "product_id": product_id,
        "transaction_type": transaction_type,
        "amount": amount,
        "occurred_at": occurred_at.isoformat(),
        **extra,
    }
    return client.post(SUBMIT_PATH, headers=headers, json=body)


def _stored_alerts(engine) -> list[RiskAlert]:
    with OrmSession(engine) as session:
        return list(session.scalars(select(RiskAlert)).all())


def test_a_single_matching_rule_produces_a_light_alert(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)

    response = _submit(
        auth_client,
        headers,
        customer_id=_customer_id(engine, CUSTOMER_LIGHT),
        product_id=_product_id(engine, PRODUCT_R1),
        amount="50000.00",
    )
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["transaction"]["amount"] == "50000.00"
    assert data["transaction"]["status"] == "已确认"

    alerts = data["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["alert_level"] == "轻度"
    assert alert["alert_type"] == "大额交易"
    assert alert["rule_codes"] == ["R001"]
    # 1.00 / 10.00：单条命中就是低置信，置信度只用于排序与展示。
    assert alert["confidence"] == 0.1


def test_the_alert_records_the_rules_the_transaction_and_the_customer(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    # C3 客户买 R4 产品 10 万：命中 R001（大额）与 R019（越级），各一条依据。
    response = _submit(
        auth_client,
        headers,
        customer_id=customer_id,
        product_id=_product_id(engine, PRODUCT_R4),
        amount="100000.00",
    )
    alert = response.json()["data"]["alerts"][0]

    stored = _stored_alerts(engine)
    assert len(stored) == 1
    row = stored[0]
    assert row.customer_id == customer_id
    assert row.alert_level == "中度"
    assert row.rule_codes == ["R001", "R019"]
    assert row.transaction_ids == alert["transaction_ids"]
    assert row.confidence == Decimal("0.35")
    # 命中依据落到字段与值的粒度，而不只是「命中大额交易规则」。
    assert "交易金额 100000 ≥ 阈值 50000" in row.trigger_detail
    assert "产品风险等级与风险承受等级之差 1 ≥ 阈值 1" in row.trigger_detail


def test_crossing_rules_without_a_history_is_moderate_and_stays_one_alert(auth_client: TestClient):
    """一笔交易命中多条规则时只产生一条预警：分级看的是这一笔命中了多少条。"""
    engine = _engine()
    headers = _headers(auth_client)

    response = _submit(
        auth_client,
        headers,
        customer_id=_customer_id(engine, CUSTOMER_MODERATE),
        product_id=_product_id(engine, PRODUCT_R4),
        amount="600000.00",
    )
    alerts = response.json()["data"]["alerts"]

    assert len(alerts) == 1
    assert alerts[0]["alert_level"] == "中度"
    assert set(alerts[0]["rule_codes"]) == {"R001", "R003", "R004", "R005", "R019"}


def test_crossing_rules_with_a_history_is_severe(auth_client: TestClient):
    """同一位客户先有一条轻度预警，再出现多规则交叉命中，等级升到重度。"""
    engine = _engine()
    headers = _headers(auth_client)
    customer_id = _customer_id(engine, CUSTOMER_SEVERE)
    product_id = _product_id(engine, PRODUCT_R5)

    first = _submit(
        auth_client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        amount="1000.00",
    )
    assert first.json()["data"]["alerts"][0]["alert_level"] == "轻度"

    second = _submit(
        auth_client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        amount="600000.00",
        occurred_at=TRADE_AT + timedelta(hours=1),
    )
    severe = second.json()["data"]["alerts"][0]

    assert severe["alert_level"] == "重度"
    assert {"R001", "R019"} <= set(severe["rule_codes"])


def test_an_alert_recorded_in_the_same_second_still_counts_as_history(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """秒精度的 create_time 会把小数秒四舍五入，刚记下的预警可能比请求时刻还晚。

    它仍然是这位客户的历史记录。用「create_time < 请求时刻」去比会把它排除在外，
    同一秒里接连发生的两笔交易于是被算成没有历史——多规则交叉的重度降成中度，
    最该先看的那一条反而排在后面。

    时刻是写死的，不靠跑得够快：`.6` 秒那一行落库一定变成下一秒，请求时刻固定在
    它之前 0.05 秒，于是这条断言要么一直是绿的，要么一直指得出问题。
    """
    engine = _engine()
    headers = _headers(auth_client)
    customer_id = _customer_id(engine, CUSTOMER_SEVERE)
    product_id = _product_id(engine, PRODUCT_R5)

    written_at = datetime(2026, 9, 10, 11, 0, 0, 600_000)
    with OrmSession(engine) as session:
        session.add(
            RiskAlert(
                customer_id=customer_id,
                alert_type="大额交易",
                alert_level="轻度",
                confidence=Decimal("0.10"),
                rule_codes=["R001"],
                trigger_detail="交易金额 1000 ≥ 阈值 50000",
                transaction_ids=[],
                status="未处理",
                handler_id=None,
                handle_result=None,
                create_time=written_at,
                update_time=written_at,
            )
        )
        session.commit()

    monkeypatch.setattr(
        "app.api.transaction_events._now", lambda: datetime(2026, 9, 10, 11, 0, 0, 650_000)
    )
    response = _submit(
        auth_client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        amount="600000.00",
    )

    assert response.json()["data"]["alerts"][0]["alert_level"] == "重度"


def test_the_transaction_is_committed_before_it_is_broadcast(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    probe = _PersistenceProbe(engine)

    with _use_publisher(probe):
        response = _submit(
            auth_client,
            headers,
            customer_id=_customer_id(engine, CUSTOMER_LIGHT),
            product_id=_product_id(engine, PRODUCT_R1),
            amount="50000.00",
        )

    assert response.status_code == 200
    assert probe.persisted_when_broadcast is True


def test_both_events_carry_what_a_subscriber_needs(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    recorder = _RecordingPublisher()
    customer_id = _customer_id(engine, CUSTOMER_LIGHT)
    product_id = _product_id(engine, PRODUCT_R1)

    with _use_publisher(recorder):
        response = _submit(
            auth_client,
            headers,
            customer_id=customer_id,
            product_id=product_id,
            amount="50000.00",
        )

    assert response.status_code == 200
    assert [event.event_type for event in recorder.events] == [
        EVENT_TRANSACTION_SUBMITTED,
        EVENT_RISK_ALERT_RAISED,
    ]

    transaction_event, alert_event = recorder.events
    assert transaction_event.payload["customer_id"] == customer_id
    assert transaction_event.payload["product_id"] == product_id

    alert = response.json()["data"]["alerts"][0]
    assert alert_event.channel == "event:risk_alert"
    assert alert_event.payload["alert_id"] == alert["id"]
    assert alert_event.payload["customer_id"] == customer_id
    assert alert_event.payload["alert_level"] == "轻度"
    assert alert_event.payload["rule_codes"] == ["R001"]
    assert alert_event.trace_id


def test_a_low_confidence_alert_is_never_closed_by_the_system(auth_client: TestClient):
    """置信度只用于排序与分级展示，不构成任何自动关闭的依据。

    「低置信自动关掉能减少工作量」是一个很容易被当作优化提出的想法，这里把它
    固定成一条断言：0.10 的置信度也不改变预警的状态，处置只能由人做出。
    """
    engine = _engine()
    headers = _headers(auth_client)

    response = _submit(
        auth_client,
        headers,
        customer_id=_customer_id(engine, CUSTOMER_LIGHT),
        product_id=_product_id(engine, PRODUCT_R1),
        amount="50000.00",
    )
    alert = response.json()["data"]["alerts"][0]
    assert alert["confidence"] < 0.5

    with OrmSession(engine) as session:
        stored = list(session.scalars(select(RiskAlert)).all())

    assert [row.status for row in stored] == ["未处理"]
    assert stored[0].handler_id is None
    assert stored[0].handle_result is None


def test_submitting_requires_an_internal_identity(auth_client: TestClient):
    engine = _engine()
    body = {
        "customer_id": _customer_id(engine, CUSTOMER_LIGHT),
        "product_id": _product_id(engine, PRODUCT_R1),
        "transaction_type": "申购",
        "amount": "50000.00",
    }

    assert auth_client.post(SUBMIT_PATH, json=body).status_code == 401
    assert auth_client.post(SUBMIT_PATH, headers={}, json=body).status_code == 401

    customer_login = auth_client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_LIGHT, "password": SEEDED_PASSWORD},
    )
    customer_headers = {
        "Authorization": f"Bearer {customer_login.json()['data']['access_token']}"
    }
    assert auth_client.post(SUBMIT_PATH, headers=customer_headers, json=body).status_code == 403


def test_an_unknown_customer_or_product_is_reported_as_missing(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)

    missing_customer = _submit(
        auth_client,
        headers,
        customer_id=999999,
        product_id=_product_id(engine, PRODUCT_R1),
        amount="50000.00",
    )
    assert missing_customer.status_code == 404

    missing_product = _submit(
        auth_client,
        headers,
        customer_id=_customer_id(engine, CUSTOMER_LIGHT),
        product_id=999999,
        amount="50000.00",
    )
    assert missing_product.status_code == 404
    assert _stored_alerts(engine) == []


def test_a_transfer_is_accepted(auth_client: TestClient):
    """需求里点名的场景是「50 万大额转账」，规则建在金额上，不认类型也能判。"""
    engine = _engine()
    headers = _headers(auth_client)

    response = _submit(
        auth_client,
        headers,
        customer_id=_customer_id(engine, CUSTOMER_LIGHT),
        product_id=_product_id(engine, PRODUCT_R1),
        amount="50000.00",
        transaction_type="转账",
    )

    assert response.status_code == 200
    assert response.json()["data"]["alerts"][0]["rule_codes"] == ["R001"]


def test_a_transaction_type_the_rules_do_not_know_is_rejected(auth_client: TestClient):
    """类型决定申购 / 赎回金额与反向交易配对。

    收下一个规则引擎不认得的类型，会让这两类规则永远不命中——静默漏报，所以当场
    报错而不是照单落库。
    """
    engine = _engine()
    headers = _headers(auth_client)

    response = _submit(
        auth_client,
        headers,
        customer_id=_customer_id(engine, CUSTOMER_LIGHT),
        product_id=_product_id(engine, PRODUCT_R1),
        amount="50000.00",
        transaction_type="转托管",
    )

    assert response.status_code == 400
    assert "交易类型" in response.json()["message"]
    with OrmSession(engine) as session:
        assert session.scalar(select(Transaction.id).where(Transaction.create_time >= TEST_EPOCH)) is None


def test_a_non_positive_amount_is_rejected(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)

    response = _submit(
        auth_client,
        headers,
        customer_id=_customer_id(engine, CUSTOMER_LIGHT),
        product_id=_product_id(engine, PRODUCT_R1),
        amount="0",
    )

    assert response.status_code == 400
    assert "金额" in response.json()["message"]


def test_a_duplicate_transaction_no_is_rejected(auth_client: TestClient):
    engine = _engine()
    headers = _headers(auth_client)
    customer_id = _customer_id(engine, CUSTOMER_LIGHT)
    product_id = _product_id(engine, PRODUCT_R1)

    first = _submit(
        auth_client, headers, customer_id=customer_id, product_id=product_id,
        amount="50000.00", transaction_no="TX-IT-0001",
    )
    assert first.status_code == 200

    duplicate = _submit(
        auth_client, headers, customer_id=customer_id, product_id=product_id,
        amount="50000.00", transaction_no="TX-IT-0001",
    )
    assert duplicate.status_code == 409
    assert "流水号" in duplicate.json()["message"]


def test_backfilling_a_transaction_is_reserved_for_the_risk_officer(auth_client: TestClient):
    """内部补录只对风控专员开放（ADR-0018、ADR-0009 的护栏 7）。

    这条口子绕过了适当性、起投金额与余额的校验，能补出一笔越级或超额的交易——
    修复数据需要它，所以它不能消失，只能收窄到一个角色手里。
    """
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_LIGHT)
    product_id = _product_id(engine, PRODUCT_R1)

    for username in (ADVISOR_USERNAME, MANAGER_USERNAME):
        headers = _headers(auth_client, username)
        assert _submit(
            auth_client,
            headers,
            customer_id=customer_id,
            product_id=product_id,
            amount="50000.00",
        ).status_code == 403

    # 风控专员的补录照常成功——护栏收的是角色，不是这条通道本身。
    accepted = _submit(
        auth_client,
        _headers(auth_client),
        customer_id=customer_id,
        product_id=product_id,
        amount="50000.00",
    )
    assert accepted.status_code == 200

    # 被拒绝的两次在库里没有留下任何痕迹：只有风控专员那一次落成了一笔交易。
    with OrmSession(engine) as session:
        stored = list(
            session.scalars(
                select(Transaction).where(Transaction.create_time >= TEST_EPOCH)
            ).all()
        )
    assert len(stored) == 1
    assert stored[0].operator_id is not None
