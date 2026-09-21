"""审核流水线泛化出内容类型（issue 05）。

Seam：后端 HTTP 层为主——审核队列与审核历史同时返回两类内容且各带类型标注。
操作建议的生成入口要等业务操作 Agent（下一份 issue），所以这里直接落一条载荷 +
审核记录，把「流水线本身与内容类型无关」这件事单独钉住：加锁加在审核记录上、
恢复按内容类型查表、队列与历史不漏掉任何一类。
"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TypedDict
from uuid import uuid4

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.agent.classification import ADVISORY_CONTENT
from app.advisory import pipeline as pipeline_module
from app.advisory.pipeline import (
    CONTENT_TYPE_OPERATION_ADVICE,
    CONTENT_TYPE_PLAN,
    NO_RESUME_RUNTIME_MESSAGE,
)
from app.advisory.queue import list_my_history
from app.advisory.review import (
    LOCKED_MESSAGE,
    claim_review,
    resume_review,
)
from app.advisory.review_status import STATUS_IN_PROGRESS, STATUS_PENDING
from app.advisory.runtime import ADVISORY_CHECKPOINTER
from app.auth.security import hash_password
from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import (
    AdvisoryDraft,
    AdvisoryFinal,
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
    CustomerProfile,
    Employee,
    Holding,
    OperationAdviceDraft,
    ProfileTag,
    RiskAssessment,
    SuitabilityDecision,
)
from app.exceptions import AppError
from app.settings import get_settings

ADVISOR = "advisor1"
MANAGER = "manager1"
SEEDED_PASSWORD = "Test@1234"

TARGET_ALLOCATION = {"股票": 40, "债券": 35, "现金": 15, "另类": 10}
PRODUCT_PREFERENCE = {"基金": ["混合基金"]}
ADVICE_PRODUCT_CODE = "F000001"


def _real_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _engine():
    return create_engine(get_settings().test_database_url)


def _employee_headers(client: TestClient, username: str = ADVISOR) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _insert_customer(*, username: str) -> int:
    now = _real_now()

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            customer = Customer(
                username=username,
                password_hash=hash_password(SEEDED_PASSWORD),
                real_name=username,
                id_number=f"11010119900101{abs(hash(username)) % 10 ** 4:04d}",
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
            for tag_key, value in tags.items():
                session.add(
                    ProfileTag(
                        customer_id=customer.id,
                        tag_key=tag_key,
                        tag_value=value,
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
            # 操作建议那一侧：审核留痕 -> 审核记录 -> 载荷。
            advice_ids = session.scalars(
                select(OperationAdviceDraft.id).where(
                    OperationAdviceDraft.customer_id == customer_id
                )
            ).all()
            advice_review_ids = session.scalars(
                select(AdvisoryReview.id).where(
                    AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE
                )
            ).all()
            if advice_review_ids:
                session.execute(
                    delete(AdvisoryReviewAudit).where(
                        AdvisoryReviewAudit.review_id.in_(advice_review_ids)
                    )
                )
            session.execute(
                delete(AdvisoryReview).where(
                    AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE
                )
            )
            if advice_ids:
                session.execute(
                    delete(OperationAdviceDraft).where(
                        OperationAdviceDraft.id.in_(advice_ids)
                    )
                )

            # 方案那一侧，与既有用例同样的清理顺序。
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


@pytest.fixture
def customer() -> Iterator[tuple[int, str]]:
    username = f"pipelinecontenttest_{id(object())}"
    created_id = _insert_customer(username=username)
    try:
        yield created_id, username
    finally:
        _delete_customer(created_id)


def _employee_id(username: str) -> int:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            employee_id = session.scalar(select(Employee.id).where(Employee.username == username))
            assert employee_id is not None
            return employee_id
    finally:
        engine.dispose()


def _insert_advice_draft(customer_id: int, *, thread_id: str) -> tuple[int, int]:
    """落一条操作建议原稿与它的审核记录，返回 (原稿 id, 审核记录 id)。

    生成入口属于业务操作 Agent 那一份 issue，这里直接把载荷与审核记录写进去——
    本 issue 要钉的是流水线这一侧。
    """
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            advice = OperationAdviceDraft(
                customer_id=customer_id,
                manager_id=_employee_id(MANAGER),
                product_code=ADVICE_PRODUCT_CODE,
                direction="申购",
                amount=Decimal("200000.00"),
                reason="客户现金仓位偏高，且这只产品的期限与他的流动性安排一致。",
                content_classification=ADVISORY_CONTENT,
                generated_at=_real_now(),
            )
            session.add(advice)
            session.flush()

            review = AdvisoryReview(
                content_type=CONTENT_TYPE_OPERATION_ADVICE,
                content_ref=advice.id,
                thread_id=thread_id,
                status=STATUS_PENDING,
            )
            session.add(review)
            session.commit()
            return advice.id, review.id
    finally:
        engine.dispose()


def _generate_plan(client: TestClient, customer_id: int) -> dict:
    response = client.post(
        f"/api/internal/advisory/customers/{customer_id}/plan",
        headers=_employee_headers(client),
        json={"tilt": None},
    )
    assert response.status_code == 200
    return response.json()["data"]


def _queue(client: TestClient) -> dict:
    response = client.get("/api/internal/advisory/queue", headers=_employee_headers(client))
    assert response.status_code == 200
    return response.json()["data"]


def test_queue_returns_both_content_types_each_labelled(auth_client: TestClient, customer):
    customer_id, username = customer
    draft = _generate_plan(auth_client, customer_id)
    advice_id, _review_id = _insert_advice_draft(customer_id, thread_id=uuid4().hex)

    pending = _queue(auth_client)["pending_reviews"]

    plan_row = next(row for row in pending if row["content_ref"] == draft["id"])
    assert plan_row["content_type"] == CONTENT_TYPE_PLAN
    assert plan_row["draft_id"] == draft["id"]
    assert plan_row["customer_name"] == username

    advice_row = next(row for row in pending if row["content_ref"] == advice_id)
    assert advice_row["content_type"] == CONTENT_TYPE_OPERATION_ADVICE
    assert advice_row["customer_name"] == username
    assert advice_row["status"] == STATUS_PENDING
    assert advice_row["waiting_seconds"] >= 0
    assert advice_row["product_code"] == ADVICE_PRODUCT_CODE
    assert advice_row["direction"] == "申购"
    assert advice_row["amount"] == "200000.00"


def test_plan_reviews_are_labelled_as_plans_and_point_at_their_draft(
    auth_client: TestClient, customer
):
    """既有方案链路落在泛化后的记录上：类型是「方案」，内容引用就是原稿 id。"""
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            review = session.scalar(
                select(AdvisoryReview).where(AdvisoryReview.draft_id == draft["id"])
            )
            assert review is not None
            assert review.content_type == CONTENT_TYPE_PLAN
            assert review.content_ref == draft["id"]
    finally:
        engine.dispose()


def test_both_content_types_share_the_same_concurrency_lock(auth_client: TestClient, customer):
    """加锁加在审核记录上：两类内容在审核期间锁的是同一套东西、给同一个答复。"""
    customer_id, _username = customer
    plan_draft = _generate_plan(auth_client, customer_id)
    advice_id, advice_review_id = _insert_advice_draft(customer_id, thread_id=uuid4().hex)

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            advice_review = session.get(AdvisoryReview, advice_review_id)
            advice_review.status = STATUS_IN_PROGRESS
            plan_review = session.scalar(
                select(AdvisoryReview).where(AdvisoryReview.draft_id == plan_draft["id"])
            )
            plan_review.status = STATUS_IN_PROGRESS
            session.commit()
    finally:
        engine.dispose()

    plan_response = auth_client.post(
        f"/api/internal/advisory/drafts/{plan_draft['id']}/release",
        headers=_employee_headers(auth_client),
        json={},
    )
    assert plan_response.status_code == 409
    assert plan_response.json()["message"] == LOCKED_MESSAGE

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            with pytest.raises(AppError) as raised:
                claim_review(
                    session, content_type=CONTENT_TYPE_OPERATION_ADVICE, content_ref=advice_id
                )
            assert raised.value.code == 409
            assert raised.value.message == LOCKED_MESSAGE
    finally:
        engine.dispose()


def _build_stub_advice_graph(_db, _cache):
    """一份最小的操作建议运行时：只有一个会被中断的审核节点。

    真正的业务操作 Agent 图属于下一份 issue；这里只要证明「续跑时喂进去的
    决定落到该内容类型自己的图上」。
    """

    class AdviceState(TypedDict, total=False):
        decision: dict

    graph = StateGraph(AdviceState)

    def await_review_node(state: AdviceState) -> dict:
        return {"decision": interrupt({"content_type": CONTENT_TYPE_OPERATION_ADVICE})}

    graph.add_node("await_review", await_review_node)
    graph.set_entry_point("await_review")
    graph.add_edge("await_review", END)
    return graph.compile(checkpointer=ADVISORY_CHECKPOINTER)


def test_resume_dispatch_picks_the_runtime_of_the_content_type(
    auth_client: TestClient, customer, monkeypatch
):
    """恢复用哪张图由内容类型决定，不落到别的内容类型的图上。"""
    customer_id, _username = customer
    stub_graph = _build_stub_advice_graph(None, None)
    thread_id = f"operation-advice-{uuid4().hex}"
    stub_graph.invoke({}, {"configurable": {"thread_id": thread_id}})

    advice_id, _review_id = _insert_advice_draft(customer_id, thread_id=thread_id)

    def _plan_graph_must_not_be_used(_db, _cache):
        raise AssertionError("操作建议的审核记录被喂给了方案的运行时")

    monkeypatch.setitem(
        pipeline_module._RESUME_GRAPH_BUILDERS,
        CONTENT_TYPE_OPERATION_ADVICE,
        lambda _db, _cache: stub_graph,
    )
    monkeypatch.setitem(
        pipeline_module._RESUME_GRAPH_BUILDERS, CONTENT_TYPE_PLAN, _plan_graph_must_not_be_used
    )

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            review = claim_review(
                session, content_type=CONTENT_TYPE_OPERATION_ADVICE, content_ref=advice_id
            )
            payload = {"action": "放行", "advisor_id": _employee_id(ADVISOR), "now": _real_now()}
            resume_review(session, redis_lib.Redis.from_url(get_settings().test_redis_url), review, payload)
    finally:
        engine.dispose()

    resumed = stub_graph.get_state({"configurable": {"thread_id": thread_id}})
    assert resumed.values["decision"] == payload


def test_a_content_type_without_a_runtime_fails_loudly_and_unlocks(
    auth_client: TestClient, customer, monkeypatch
):
    """没有登记运行时的内容类型宁可报错，也不回退到别的图上，并且不把内容卡住。"""
    customer_id, _username = customer
    advice_id, review_id = _insert_advice_draft(customer_id, thread_id=uuid4().hex)
    monkeypatch.delitem(
        pipeline_module._RESUME_GRAPH_BUILDERS,
        CONTENT_TYPE_OPERATION_ADVICE,
        raising=False,
    )

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            review = claim_review(
                session, content_type=CONTENT_TYPE_OPERATION_ADVICE, content_ref=advice_id
            )
            assert review.status == STATUS_IN_PROGRESS
            with pytest.raises(AppError) as raised:
                resume_review(
                    session,
                    redis_lib.Redis.from_url(get_settings().test_redis_url),
                    review,
                    {"action": "放行"},
                )
            assert raised.value.message == NO_RESUME_RUNTIME_MESSAGE
            assert session.get(AdvisoryReview, review_id).status == STATUS_PENDING
    finally:
        engine.dispose()


def test_history_covers_both_content_types(auth_client: TestClient, customer):
    """审核历史同样按类型无关地工作：只记方案等于另一类内容的审核没发生过。"""
    customer_id, _username = customer
    _advice_id, advice_review_id = _insert_advice_draft(customer_id, thread_id=uuid4().hex)
    advisor_id = _employee_id(ADVISOR)

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            session.add(
                AdvisoryReviewAudit(
                    review_id=advice_review_id,
                    advisor_id=advisor_id,
                    action="驳回",
                    reason="金额与客户的流动性安排不符",
                    decided_at=_real_now(),
                )
            )
            session.commit()

            history = list_my_history(session, advisor_id)
    finally:
        engine.dispose()

    entry = next(
        row for row in history if row["reason"] == "金额与客户的流动性安排不符"
    )
    assert entry["content_type"] == CONTENT_TYPE_OPERATION_ADVICE
    assert entry["action"] == "驳回"
    assert entry["customer_name"] == _username


def test_the_advice_payload_does_not_carry_plan_specific_columns():
    """操作建议的载荷另建表：方案特有的字段不以空列的形式跟着建议走。"""
    columns = set(OperationAdviceDraft.__table__.columns.keys())
    assert columns == {
        "id",
        "customer_id",
        "manager_id",
        "product_code",
        "direction",
        "amount",
        "reason",
        "content_classification",
        "generated_at",
        "create_time",
    }
