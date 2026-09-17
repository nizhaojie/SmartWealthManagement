"""Agent 间事件协作（ticket 04）。

Seam：后端 HTTP 层。两条协作在这里端到端固定下来——风控预警广播后，投顾为这位
客户生成的方案带上风险标记；客服察觉到高风险意图后，风控专员在风险关注列表里
看到这位客户。外加三条边界：订阅方抛错不影响发布方，事件总线不可用不影响核心
链路，新增订阅不必改发布方（后一条在 tests/test_event_bus.py 里用发布方实例固定）。

协作的落地物是**订阅方自己写下的风险关注记录**（`biz_risk_focus`），不是把预警表
当共享内存去读：发布方不知道有谁在听，订阅方各自记自己要的那一份。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

import app.agent.graph as agent_graph
from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import (
    AdvisoryDraft,
    AdvisoryFinal,
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
    CustomerProfile,
    Holding,
    Product,
    ProfileTag,
    RiskAlert,
    RiskAssessment,
    RiskFocus,
    SuitabilityDecision,
    Transaction,
)
from app.event_bus import (
    EVENT_RISK_ALERT_RAISED,
    Event,
    FanoutPublisher,
    Subscription,
    get_event_publisher,
)
from app.event_subscribers import build_subscriptions
from app.main import app
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER = "risk1"
ADVISOR = "advisor1"
# 只有种子客户能登录（密码是种子的一部分），因此客服侧的场景用种子客户。
CHAT_CUSTOMER = "wangc1"

TRANSACTION_PATH = "/api/internal/transaction-events"
FOCUS_PATH = "/api/internal/risk-focus"

PRODUCT_R1 = "F000001"
# R4：C3 客户买它是越级，配合大额与历史预警能凑出重度。
PRODUCT_R4 = "F000004"

TARGET_ALLOCATION = {"股票": 40, "债券": 35, "现金": 15, "另类": 10}
PRODUCT_PREFERENCE = {"基金": ["混合基金"]}

# 固定在工作时间内的交易时刻：写成「现在」的话，非工作时间（R017）会让分级多命中
# 一条，断言就变成取决于跑测试的时刻。
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)


class _SilentTransport:
    """出站通道正常，但不送任何地方。"""

    def publish(self, event: Event) -> None: ...


class _BrokenTransport:
    """出站通道掉线：发布就是会抛。"""

    def publish(self, event: Event) -> None:
        raise ConnectionError("事件总线不可用")


def _explode(event: Event) -> None:
    raise RuntimeError("订阅方炸了")


def _engine():
    return create_engine(get_settings().test_database_url)


def _real_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _employee_headers(client: TestClient, username: str = RISK_OFFICER) -> dict[str, str]:
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


def _insert_customer() -> int:
    """插一位与种子数据隔离的 C3 客户：投顾侧的断言不能依赖种子客户的评测有效期。"""
    now = _real_now()
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            customer = Customer(
                username=f"collabtest_{uuid4().hex[:10]}",
                password_hash="unused-in-these-tests",
                real_name="协作测试客户",
                id_number=f"11010119900101{uuid4().int % 10**4:04d}",
                phone="13900000000",
                customer_level="普通",
                status="正常",
                opened_at=datetime(2024, 1, 1, 10, 0, 0),
            )
            session.add(customer)
            session.flush()

            session.add(
                CustomerProfile(
                    customer_id=customer.id,
                    risk_level="C3",
                    risk_score=50,
                    investment_experience="3-5年",
                    annual_income_range="30-50万",
                    total_assets=Decimal("800000.00"),
                    target_allocation=TARGET_ALLOCATION,
                    product_preference=PRODUCT_PREFERENCE,
                    confidence_score=Decimal("0.90"),
                    computed_at=now,
                )
            )
            session.add(
                RiskAssessment(
                    customer_id=customer.id,
                    assessment_date=now.date(),
                    total_score=50,
                    risk_level="C3",
                    answers=[],
                    assessor_type="人工评估",
                    valid_until=now.date() + timedelta(days=365),
                )
            )
            tags = {
                "risk_level": "C3",
                "investment_experience": "3-5年",
                "annual_income_range": "30-50万",
                "total_assets": str(Decimal("800000.00")),
                "target_allocation": TARGET_ALLOCATION,
                "product_preference": PRODUCT_PREFERENCE,
            }
            for tag_key, tag_value in tags.items():
                session.add(
                    ProfileTag(
                        customer_id=customer.id,
                        tag_key=tag_key,
                        tag_value=tag_value,
                        source=SOURCE_QUESTIONNAIRE,
                        evidence_count=0,
                        observed_at=now,
                    )
                )
            session.commit()
            return customer.id
    finally:
        engine.dispose()


def _delete_customer(customer_id: int) -> None:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            session.execute(delete(RiskFocus).where(RiskFocus.customer_id == customer_id))
            session.execute(delete(RiskAlert).where(RiskAlert.customer_id == customer_id))
            session.execute(delete(Transaction).where(Transaction.customer_id == customer_id))
            draft_ids = session.scalars(
                select(AdvisoryDraft.id).where(AdvisoryDraft.customer_id == customer_id)
            ).all()
            if draft_ids:
                review_ids = session.scalars(
                    select(AdvisoryReview.id).where(AdvisoryReview.draft_id.in_(draft_ids))
                ).all()
                if review_ids:
                    session.execute(
                        delete(AdvisoryReviewAudit).where(
                            AdvisoryReviewAudit.review_id.in_(review_ids)
                        )
                    )
                session.execute(delete(AdvisoryFinal).where(AdvisoryFinal.draft_id.in_(draft_ids)))
                session.execute(delete(AdvisoryReview).where(AdvisoryReview.draft_id.in_(draft_ids)))
            session.execute(delete(AdvisoryDraft).where(AdvisoryDraft.customer_id == customer_id))
            session.execute(delete(Holding).where(Holding.customer_id == customer_id))
            session.execute(delete(ProfileTag).where(ProfileTag.customer_id == customer_id))
            session.execute(
                delete(SuitabilityDecision).where(SuitabilityDecision.customer_id == customer_id)
            )
            session.execute(delete(RiskAssessment).where(RiskAssessment.customer_id == customer_id))
            session.execute(delete(CustomerProfile).where(CustomerProfile.customer_id == customer_id))
            session.execute(delete(Customer).where(Customer.id == customer_id))
            session.commit()
    finally:
        engine.dispose()


def _purge_focus() -> None:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            session.execute(delete(RiskFocus))
            session.commit()
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _clean_focus(auth_client: TestClient) -> Iterator[None]:
    _purge_focus()
    try:
        yield
    finally:
        _purge_focus()


@pytest.fixture
def customer_id() -> Iterator[int]:
    created = _insert_customer()
    try:
        yield created
    finally:
        _delete_customer(created)


@contextmanager
def _use_publisher(publisher) -> Iterator[None]:
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_event_publisher, None)


def _submit(
    client: TestClient,
    headers: dict[str, str],
    *,
    customer_id: int,
    product_id: int,
    amount: str,
    occurred_at: datetime,
):
    return client.post(
        TRANSACTION_PATH,
        headers=headers,
        json={
            "customer_id": customer_id,
            "product_id": product_id,
            "transaction_type": "申购",
            "amount": amount,
            "occurred_at": occurred_at.isoformat(),
        },
    )


def _generate_plan(client: TestClient, customer_id: int):
    return client.post(
        f"/api/internal/advisory/customers/{customer_id}/plan",
        headers=_employee_headers(client, ADVISOR),
        json={"tilt": None},
    )


def _focus_rows(engine, customer_id: int) -> list[RiskFocus]:
    with OrmSession(engine) as session:
        return list(
            session.scalars(
                select(RiskFocus)
                .where(RiskFocus.customer_id == customer_id)
                .order_by(RiskFocus.id)
            )
        )


def _severe_alert_for(client: TestClient, engine, customer_id: int) -> dict:
    """先一条轻度预警，再一条多规则交叉命中——后者因为有历史记录升为重度。"""
    headers = _employee_headers(client)
    product_id = _product_id(engine, PRODUCT_R4)

    first = _submit(
        client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        amount="1000.00",
        occurred_at=TRADE_AT,
    )
    assert first.status_code == 200
    assert first.json()["data"]["alerts"][0]["alert_level"] == "轻度"

    second = _submit(
        client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        amount="600000.00",
        occurred_at=TRADE_AT + timedelta(hours=1),
    )
    assert second.status_code == 200
    severe = second.json()["data"]["alerts"][0]
    assert severe["alert_level"] == "重度"
    return severe


def test_a_risk_alert_broadcast_marks_the_advisory_content(
    auth_client: TestClient, customer_id: int
):
    """风控刚发出重度预警，顾问为这位客户生成方案时就看到风险标记。"""
    engine = _engine()
    _severe_alert_for(auth_client, engine, customer_id)

    response = _generate_plan(auth_client, customer_id)

    assert response.status_code == 200
    warnings = {item["code"]: item["message"] for item in response.json()["data"]["warnings"]}
    assert "ACTIVE_RISK_ALERT" in warnings
    assert "重度" in warnings["ACTIVE_RISK_ALERT"]

    # 标记来自订阅方写下的关注记录：发布方不知道投顾在听，投顾也没读预警表。
    rows = _focus_rows(engine, customer_id)
    assert [row.focus_type for row in rows] == ["风控预警", "风控预警"]
    assert {row.source for row in rows} == {"risk-monitoring-agent"}
    assert [row.severity for row in rows] == ["轻度", "重度"]


def test_a_customer_without_a_risk_alert_gets_no_risk_marker(
    auth_client: TestClient, customer_id: int
):
    """没有预警就没有标记：提示是订阅的结果，不是无条件加上的。"""
    response = _generate_plan(auth_client, customer_id)

    codes = {item["code"] for item in response.json()["data"]["warnings"]}
    assert "ACTIVE_RISK_ALERT" not in codes


def test_an_old_risk_alert_does_not_mark_todays_plan(auth_client: TestClient, customer_id: int):
    """窗口外的关注记录不参与：半年前的预警不该混进今天的配置建议。"""
    engine = _engine()
    with OrmSession(engine) as session:
        session.add(
            RiskFocus(
                customer_id=customer_id,
                focus_type="风控预警",
                severity="重度",
                reason="风控预警（重度）：命中规则 R001",
                source="risk-monitoring-agent",
                trace_id="trace-old",
                occurred_at=_real_now() - timedelta(days=200),
            )
        )
        session.commit()

    response = _generate_plan(auth_client, customer_id)

    codes = {item["code"] for item in response.json()["data"]["warnings"]}
    assert "ACTIVE_RISK_ALERT" not in codes


def test_a_subscriber_that_raises_leaves_the_publishers_request_successful(
    auth_client: TestClient, customer_id: int
):
    """一位听众没听懂，发布方的请求仍然成功，其他听众也照常落地。"""
    engine = _engine()
    subscriptions = build_subscriptions(lambda: OrmSession(engine))
    subscriptions.subscribe(
        Subscription(EVENT_RISK_ALERT_RAISED, "exploding", _explode)
    )

    with _use_publisher(FanoutPublisher(_SilentTransport(), subscriptions)):
        response = _submit(
            auth_client,
            _employee_headers(auth_client),
            customer_id=customer_id,
            product_id=_product_id(engine, PRODUCT_R1),
            amount="50000.00",
            occurred_at=TRADE_AT,
        )

    assert response.status_code == 200
    assert response.json()["data"]["alerts"]
    assert _focus_rows(engine, customer_id), "其余订阅方没有被那位听众的失败带倒"


def test_an_unavailable_bus_does_not_stop_the_core_chain(
    auth_client: TestClient, customer_id: int
):
    """通道掉线只记日志：交易与预警照常落库，进程内的协作也照常。"""
    engine = _engine()
    subscriptions = build_subscriptions(lambda: OrmSession(engine))
    headers = _employee_headers(auth_client)

    with _use_publisher(FanoutPublisher(_BrokenTransport(), subscriptions)):
        response = _submit(
            auth_client,
            headers,
            customer_id=customer_id,
            product_id=_product_id(engine, PRODUCT_R1),
            amount="50000.00",
            occurred_at=TRADE_AT,
        )

    assert response.status_code == 200
    assert response.json()["data"]["alerts"][0]["alert_level"] == "轻度"
    assert _focus_rows(engine, customer_id), "本进程的订阅不依赖出站通道"


@pytest.fixture
def chat_client(auth_client: TestClient) -> Iterator[TestClient]:
    """与客服 Agent 自己的测试同一套隔离：测试向量集合 + 从不重建的图谱命名空间。"""
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": "wealth_test_cross_agent_collaboration_unused",
        }
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_customer_service_flags_a_high_risk_intent_to_risk_monitoring(
    chat_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """客服察觉到客户在反复打听转账限额，风控专员收到风险关注。"""
    # 检索链路与本协作无关：固定走兜底，让这条用例只验证事件那一半。
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *args, **kwargs: [])

    engine = _engine()
    customer_id = _customer_id(engine, CHAT_CUSTOMER)
    login = chat_client.post(
        "/api/customer/auth/login",
        json={"username": CHAT_CUSTOMER, "password": SEEDED_PASSWORD},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = chat_client.post(
        "/api/customer/chat/messages",
        headers=headers,
        json={"message": "我想问下我的转账限额是多少"},
    )
    second = chat_client.post(
        "/api/customer/chat/messages",
        headers=headers,
        json={"message": "那我分几笔转出去，是不是就不受限额限制了"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    listed = chat_client.get(FOCUS_PATH, headers=_employee_headers(chat_client))
    assert listed.status_code == 200
    rows = [row for row in listed.json()["data"] if row["customer_id"] == customer_id]

    assert rows, "客服察觉到的高风险意图应当出现在风控的风险关注里"
    assert {row["focus_type"] for row in rows} == {"高风险意图"}
    assert {row["source"] for row in rows} == {"customer-service-agent"}
    # 最近的一条在前：同一会话里问到第二次，理由里才写「反复」。
    assert "反复" in rows[0]["reason"]
    assert "转账限额" in rows[0]["reason"]


def test_an_ordinary_customer_question_raises_no_focus(
    chat_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *args, **kwargs: [])

    engine = _engine()
    customer_id = _customer_id(engine, CHAT_CUSTOMER)
    login = chat_client.post(
        "/api/customer/auth/login",
        json={"username": CHAT_CUSTOMER, "password": SEEDED_PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    response = chat_client.post(
        "/api/customer/chat/messages",
        headers=headers,
        json={"message": "你好呀，今天天气不错"},
    )

    assert response.status_code == 200
    assert _focus_rows(engine, customer_id) == []


def test_the_focus_list_requires_an_internal_identity(chat_client: TestClient):
    assert chat_client.get(FOCUS_PATH).status_code == 401


def test_the_focus_list_can_be_narrowed_to_the_high_risk_intents(chat_client: TestClient):
    engine = _engine()
    customer_id = _customer_id(engine, CHAT_CUSTOMER)
    with OrmSession(engine) as session:
        session.add(
            RiskFocus(
                customer_id=customer_id,
                focus_type="风控预警",
                severity="轻度",
                reason="风控预警（轻度）：命中规则 R001",
                source="risk-monitoring-agent",
                trace_id="trace-alert",
                occurred_at=_real_now(),
            )
        )
        session.add(
            RiskFocus(
                customer_id=customer_id,
                focus_type="高风险意图",
                severity=None,
                reason="客服识别到高风险意图：打听转账限额规避方式",
                source="customer-service-agent",
                trace_id="trace-intent",
                occurred_at=_real_now(),
            )
        )
        session.commit()

    response = chat_client.get(
        FOCUS_PATH, params={"focus_type": "高风险意图"}, headers=_employee_headers(chat_client)
    )

    assert response.status_code == 200
    rows = [row for row in response.json()["data"] if row["customer_id"] == customer_id]
    assert [row["focus_type"] for row in rows] == ["高风险意图"]


def test_a_customer_token_cannot_read_the_focus_list(chat_client: TestClient):
    engine = _engine()
    login = chat_client.post(
        "/api/customer/auth/login",
        json={"username": CHAT_CUSTOMER, "password": SEEDED_PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    response = chat_client.get(FOCUS_PATH, headers=headers)

    assert response.status_code in (401, 403)
    assert _customer_id(engine, CHAT_CUSTOMER)  # 身份本身是有效的，只是用错了域


def test_chat_stream_also_flags_the_risk_intent(
    chat_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """流式入口走同一条回合实现，不能只有 `/messages` 会广播。"""
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *args, **kwargs: [])

    engine = _engine()
    customer_id = _customer_id(engine, CHAT_CUSTOMER)
    login = chat_client.post(
        "/api/customer/auth/login",
        json={"username": CHAT_CUSTOMER, "password": SEEDED_PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    response = chat_client.post(
        "/api/customer/chat/stream",
        headers=headers,
        json={"message": "我想把转账拆成几笔，规避限额"},
    )

    assert response.status_code == 200
    rows = _focus_rows(engine, customer_id)
    assert [row.focus_type for row in rows] == ["高风险意图"]
