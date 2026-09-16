"""审核队列：客户方案请求的消费、待审内容展示与顾问的审核历史（issue 04）。

Seam：后端 HTTP 层。复用 test_advisory_review.py 的客户构造方式，额外
覆盖方案请求 -> 生成 -> 放行/驳回这条链路上请求状态的流转。
"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.auth.security import hash_password
from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import (
    AdvisoryDraft,
    AdvisoryFinal,
    AdvisoryRequest,
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
SEEDED_PASSWORD = "Test@1234"

TARGET_ALLOCATION = {"股票": 40, "债券": 35, "现金": 15, "另类": 10}
PRODUCT_PREFERENCE = {"基金": ["混合基金"]}
BOND_FILTERS = {"product_type": "债券基金", "max_term_days": "365"}


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
            session.execute(
                delete(AdvisoryRequest).where(AdvisoryRequest.customer_id == customer_id)
            )
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
    username = f"advisoryqueuetest_{id(object())}"
    created_id = _insert_customer(username=username)
    try:
        yield created_id, username
    finally:
        _delete_customer(created_id)


def _submit_request(client: TestClient, username: str, filters: dict) -> dict:
    response = client.post(
        "/api/customer/advisory-requests",
        headers=_customer_headers(client, username),
        json=filters,
    )
    assert response.status_code == 200
    return response.json()["data"]


def _generate_plan(
    client: TestClient,
    customer_id: int,
    *,
    advisory_request_id: int | None = None,
    employee: str = ADVISOR,
):
    return client.post(
        f"/api/internal/advisory/customers/{customer_id}/plan",
        headers=_employee_headers(client, employee),
        json={"tilt": None, "advisory_request_id": advisory_request_id},
    )


def _release(client: TestClient, draft_id: int):
    return client.post(
        f"/api/internal/advisory/drafts/{draft_id}/release",
        headers=_employee_headers(client),
        json={},
    )


def _reject(client: TestClient, draft_id: int, *, reason: str = "需要重新核对"):
    return client.post(
        f"/api/internal/advisory/drafts/{draft_id}/reject",
        headers=_employee_headers(client),
        json={"reason": reason},
    )


def _queue(client: TestClient) -> dict:
    response = client.get(
        "/api/internal/advisory/queue", headers=_employee_headers(client)
    )
    assert response.status_code == 200
    return response.json()["data"]


def _request_status(request_id: int) -> str:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            row = session.get(AdvisoryRequest, request_id)
            assert row is not None
            return row.status
    finally:
        engine.dispose()


def test_generating_a_plan_from_a_request_claims_it(auth_client: TestClient, customer):
    customer_id, username = customer
    request = _submit_request(auth_client, username, BOND_FILTERS)

    response = _generate_plan(auth_client, customer_id, advisory_request_id=request["id"])
    assert response.status_code == 200
    assert response.json()["data"]["advisory_request_id"] == request["id"]
    assert _request_status(request["id"]) == "处理中"


def test_a_claimed_request_cannot_be_claimed_again(auth_client: TestClient, customer):
    customer_id, username = customer
    request = _submit_request(auth_client, username, BOND_FILTERS)

    first = _generate_plan(auth_client, customer_id, advisory_request_id=request["id"])
    assert first.status_code == 200

    second = _generate_plan(auth_client, customer_id, advisory_request_id=request["id"])
    assert second.status_code == 409


def test_a_request_for_a_different_customer_is_rejected(auth_client: TestClient, customer):
    customer_id, username = customer
    other_id = _insert_customer(username=f"otherqueue_{id(object())}")
    try:
        request = _submit_request(auth_client, username, BOND_FILTERS)

        response = _generate_plan(auth_client, other_id, advisory_request_id=request["id"])
        assert response.status_code == 400
        # 校验失败不应该把请求悬在处理中。
        assert _request_status(request["id"]) == "待处理"
    finally:
        _delete_customer(other_id)


def test_releasing_the_draft_completes_its_source_request(auth_client: TestClient, customer):
    customer_id, username = customer
    request = _submit_request(auth_client, username, BOND_FILTERS)
    draft = _generate_plan(
        auth_client, customer_id, advisory_request_id=request["id"]
    ).json()["data"]

    response = _release(auth_client, draft["id"])
    assert response.status_code == 200
    assert _request_status(request["id"]) == "已完成"


def test_rejecting_the_draft_reopens_its_source_request(auth_client: TestClient, customer):
    customer_id, username = customer
    request = _submit_request(auth_client, username, BOND_FILTERS)
    draft = _generate_plan(
        auth_client, customer_id, advisory_request_id=request["id"]
    ).json()["data"]

    response = _reject(auth_client, draft["id"])
    assert response.status_code == 200
    assert _request_status(request["id"]) == "待处理"


def test_queue_lists_pending_requests_and_pending_reviews_with_waiting_time(
    auth_client: TestClient, customer
):
    customer_id, username = customer
    request = _submit_request(auth_client, username, BOND_FILTERS)
    other_id = _insert_customer(username=f"queuereview_{id(object())}")
    try:
        draft = _generate_plan(auth_client, other_id).json()["data"]

        queue = _queue(auth_client)

        request_row = next(
            row for row in queue["pending_requests"] if row["id"] == request["id"]
        )
        assert request_row["customer_name"] == username
        assert request_row["waiting_seconds"] >= 0

        review_row = next(
            row for row in queue["pending_reviews"] if row["draft_id"] == draft["id"]
        )
        assert review_row["status"] == "待审"
        assert review_row["waiting_seconds"] >= 0

        # 已经生成过原稿的请求不再挂在「待生成」里——它已经进了待审队列。
        _generate_plan(auth_client, customer_id, advisory_request_id=request["id"])
        queue_after = _queue(auth_client)
        assert all(row["id"] != request["id"] for row in queue_after["pending_requests"])
    finally:
        _delete_customer(other_id)


def test_advisor_can_see_their_own_review_history(auth_client: TestClient, customer):
    customer_id, _username = customer
    draft = _generate_plan(auth_client, customer_id).json()["data"]
    _release(auth_client, draft["id"])

    response = auth_client.get(
        "/api/internal/advisory/history", headers=_employee_headers(auth_client)
    )
    assert response.status_code == 200
    history = response.json()["data"]["history"]
    entry = next(row for row in history if row["draft_id"] == draft["id"])
    assert entry["action"] == "放行"
    assert entry["decided_at"]
