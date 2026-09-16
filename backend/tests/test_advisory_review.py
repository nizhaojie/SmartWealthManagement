"""审核流：中断、放行驳回与并发加锁（issue 03）。

Seam：后端 HTTP 层。发起生成 -> 断言进入待审状态 -> 放行/驳回 -> 断言
产出顾问定稿或驳回记录——不测运行时内部的节点状态，只测这条链路在
HTTP 层能观察到的行为。
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.advisory.review_status import STATUS_IN_PROGRESS, STATUS_PENDING
from app.auth.security import hash_password
from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import (
    AdvisoryDraft,
    AdvisoryFinal,
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
    CustomerProfile,
    Holding,
    ProfileTag,
    RiskAssessment,
    SuitabilityDecision,
)
from app.settings import get_settings

ADVISOR = "advisor1"
ACCOUNT_MANAGER = "manager1"
SEEDED_PASSWORD = "Test@1234"

TARGET_ALLOCATION = {"股票": 40, "债券": 35, "现金": 15, "另类": 10}
PRODUCT_PREFERENCE = {"基金": ["混合基金"]}


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


def _customer_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
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
    username = f"advisoryreviewtest_{id(object())}"
    created_id = _insert_customer(username=username)
    try:
        yield created_id, username
    finally:
        _delete_customer(created_id)


def _generate_plan(client: TestClient, customer_id: int) -> dict:
    response = client.post(
        f"/api/internal/advisory/customers/{customer_id}/plan",
        headers=_employee_headers(client),
        json={"tilt": None},
    )
    assert response.status_code == 200
    return response.json()["data"]


def _release(
    client: TestClient,
    draft_id: int,
    *,
    employee: str = ADVISOR,
    candidates: list[dict] | None = None,
    allocation_suggestion: dict | None = None,
    warnings: list[dict] | None = None,
):
    return client.post(
        f"/api/internal/advisory/drafts/{draft_id}/release",
        headers=_employee_headers(client, employee),
        json={
            "candidates": candidates,
            "allocation_suggestion": allocation_suggestion,
            "warnings": warnings,
        },
    )


def _reject(client: TestClient, draft_id: int, *, employee: str = ADVISOR, reason: str | None):
    return client.post(
        f"/api/internal/advisory/drafts/{draft_id}/reject",
        headers=_employee_headers(client, employee),
        json={"reason": reason},
    )


def test_generating_a_plan_creates_a_pending_review(auth_client: TestClient, customer):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    response = auth_client.get(
        f"/api/internal/advisory/drafts/{draft['id']}/review",
        headers=_employee_headers(auth_client),
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"draft_id": draft["id"], "status": STATUS_PENDING}


def test_customer_cannot_read_a_plan_before_it_is_released(auth_client: TestClient, customer):
    customer_id, username = customer
    _generate_plan(auth_client, customer_id)

    response = auth_client.get(
        "/api/customer/advisory/plan", headers=_customer_headers(auth_client, username)
    )
    assert response.status_code == 404


def test_account_manager_cannot_release(auth_client: TestClient, customer):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    response = _release(auth_client, draft["id"], employee=ACCOUNT_MANAGER)
    assert response.status_code == 403


def test_releasing_produces_a_final_the_customer_can_read(auth_client: TestClient, customer):
    customer_id, username = customer
    draft = _generate_plan(auth_client, customer_id)

    response = _release(auth_client, draft["id"])
    assert response.status_code == 200
    final = response.json()["data"]
    assert final["draft_id"] == draft["id"]
    assert final["candidates"] == draft["candidates"]

    customer_view = auth_client.get(
        "/api/customer/advisory/plan", headers=_customer_headers(auth_client, username)
    ).json()["data"]
    assert customer_view["candidates"] == draft["candidates"]
    assert customer_view["disclaimer"]
    # 客户要知道方案是谁出具的才知道该找谁，光有内部的 advisor_id 不够。
    assert customer_view["advisor_name"]


def test_advisor_edit_at_release_is_what_the_customer_sees_and_the_draft_stays_untouched(
    auth_client: TestClient, customer
):
    customer_id, username = customer
    draft = _generate_plan(auth_client, customer_id)
    edited_candidates = draft["candidates"][:1]
    assert edited_candidates and len(edited_candidates) < len(draft["candidates"])

    release_response = _release(auth_client, draft["id"], candidates=edited_candidates)
    assert release_response.status_code == 200
    assert release_response.json()["data"]["candidates"] == edited_candidates

    customer_view = auth_client.get(
        "/api/customer/advisory/plan", headers=_customer_headers(auth_client, username)
    ).json()["data"]
    assert customer_view["candidates"] == edited_candidates

    # 原稿是举证材料，不随顾问的编辑改变——差异正是审核实质性的依据。
    refetched_draft = auth_client.get(
        f"/api/internal/advisory/drafts/{draft['id']}",
        headers=_employee_headers(auth_client),
    ).json()["data"]
    assert refetched_draft["candidates"] == draft["candidates"]


def test_release_rejected_when_edited_candidate_is_outside_the_candidate_pool(
    auth_client: TestClient, customer
):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)
    # C3 客户的候选池只到 R3；F000004 是 R4，属于越级产品。
    smuggled = [*draft["candidates"], {"product_code": "F000004", "product_name": "越级产品"}]

    response = _release(auth_client, draft["id"], candidates=smuggled)
    assert response.status_code == 400

    # 放行被拒绝后锁必须释放——顾问改回合规的版本可以重试并成功。
    retry = _release(auth_client, draft["id"])
    assert retry.status_code == 200


def test_reject_requires_a_non_empty_reason(auth_client: TestClient, customer):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    empty_reason = _reject(auth_client, draft["id"], reason="")
    assert empty_reason.status_code == 400

    missing_reason = _reject(auth_client, draft["id"], reason=None)
    assert missing_reason.status_code == 400


def test_reject_records_reason_advisor_and_timestamp(auth_client: TestClient, customer):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    response = _reject(auth_client, draft["id"], reason="推荐理由没有引用客户的流动性诉求")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "已驳回"

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            review = session.scalar(
                select(AdvisoryReview).where(AdvisoryReview.draft_id == draft["id"])
            )
            assert review.status == "已驳回"
            audit = session.scalar(
                select(AdvisoryReviewAudit).where(AdvisoryReviewAudit.review_id == review.id)
            )
            assert audit.action == "驳回"
            assert audit.reason == "推荐理由没有引用客户的流动性诉求"
            assert audit.advisor_id is not None
            assert audit.decided_at is not None
    finally:
        engine.dispose()

    # 驳回之后客户侧仍然读不到任何投顾内容。
    no_final = auth_client.get(f"/api/internal/advisory/drafts/{draft['id']}/final",
                                headers=_employee_headers(auth_client))
    assert no_final.status_code == 404


def test_a_decided_draft_cannot_be_decided_again(auth_client: TestClient, customer):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    first = _release(auth_client, draft["id"])
    assert first.status_code == 200

    second_release = _release(auth_client, draft["id"])
    assert second_release.status_code == 409

    second_reject = _reject(auth_client, draft["id"], reason="太晚了")
    assert second_reject.status_code == 409


def test_a_locked_review_rejects_a_concurrent_decision(auth_client: TestClient, customer):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    # 模拟另一个请求已经把这份内容的审核状态切到「处理中」——同一份内容
    # 在审核期间加锁，第二个请求必须被拒绝，而不是拿到相同的处理机会。
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            review = session.scalar(
                select(AdvisoryReview).where(AdvisoryReview.draft_id == draft["id"])
            )
            review.status = STATUS_IN_PROGRESS
            session.commit()
    finally:
        engine.dispose()

    response = _release(auth_client, draft["id"])
    assert response.status_code == 409


def test_two_concurrent_releases_of_the_same_draft_only_let_one_through(
    auth_client: TestClient, customer
):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id)

    # 真正并发地打两个放行请求到同一份原稿——加锁必须靠数据库层面的原子
    # 更新兜底并发，而不是应用层先读后写，否则两个线程都可能读到「待审」
    # 然后都通过。
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_release, auth_client, draft["id"]) for _ in range(2)]
        statuses = sorted(future.result().status_code for future in futures)

    assert statuses == [200, 409]
