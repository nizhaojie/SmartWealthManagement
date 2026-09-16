"""客户经理对审核内容的查看范围与审核页留言（issue 04）。

Seam：后端 HTTP 层。客户经理能看能评论，但只能看自己名下的客户——
放行仍然只属于理财顾问（已在 test_advisory_review.py / test_advisory_plan.py
覆盖），这里只测查看范围与留言。
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
    AdvisoryReview,
    AdvisoryReviewAudit,
    AdvisoryReviewComment,
    Customer,
    CustomerProfile,
    Employee,
    Holding,
    ProfileTag,
    RiskAssessment,
    SuitabilityDecision,
)
from app.settings import get_settings

ADVISOR = "advisor1"
MANAGER_A = "manager1"
MANAGER_B = "manager2"
SEEDED_PASSWORD = "Test@1234"

TARGET_ALLOCATION = {"股票": 40, "债券": 35, "现金": 15, "另类": 10}
PRODUCT_PREFERENCE = {"基金": ["混合基金"]}


def _real_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _engine():
    return create_engine(get_settings().test_database_url)


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _insert_customer(*, username: str, manager_username: str) -> int:
    now = _real_now()

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            manager = session.scalar(
                select(Employee).where(Employee.username == manager_username)
            )
            assert manager is not None

            customer = Customer(
                username=username,
                password_hash=hash_password(SEEDED_PASSWORD),
                real_name=username,
                id_number=f"11010119900101{abs(hash(username)) % 10 ** 4:04d}",
                phone="13900000000",
                customer_level="普通",
                status="正常",
                manager_id=manager.id,
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
                        delete(AdvisoryReviewComment).where(
                            AdvisoryReviewComment.review_id.in_(review_ids)
                        )
                    )
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
def draft(auth_client: TestClient) -> Iterator[dict]:
    username = f"advisoryaccesstest_{id(object())}"
    customer_id = _insert_customer(username=username, manager_username=MANAGER_A)
    try:
        response = auth_client.post(
            f"/api/internal/advisory/customers/{customer_id}/plan",
            headers=_employee_headers(auth_client, ADVISOR),
            json={"tilt": None},
        )
        assert response.status_code == 200
        yield response.json()["data"]
    finally:
        _delete_customer(customer_id)


def test_the_managing_account_manager_can_view_the_draft_review_and_comments(
    auth_client: TestClient, draft
):
    headers = _employee_headers(auth_client, MANAGER_A)

    for path in ("", "/review", "/comments"):
        response = auth_client.get(
            f"/api/internal/advisory/drafts/{draft['id']}{path}", headers=headers
        )
        assert response.status_code == 200, path


def test_an_unrelated_account_manager_is_forbidden(auth_client: TestClient, draft):
    headers = _employee_headers(auth_client, MANAGER_B)

    for path in ("", "/review", "/comments"):
        response = auth_client.get(
            f"/api/internal/advisory/drafts/{draft['id']}{path}", headers=headers
        )
        assert response.status_code == 403, path


def test_the_advisor_is_never_scoped_by_customer_manager(auth_client: TestClient, draft):
    response = auth_client.get(
        f"/api/internal/advisory/drafts/{draft['id']}",
        headers=_employee_headers(auth_client, ADVISOR),
    )
    assert response.status_code == 200


def test_both_advisor_and_managing_account_manager_can_post_and_read_comments(
    auth_client: TestClient, draft
):
    advisor_headers = _employee_headers(auth_client, ADVISOR)
    manager_headers = _employee_headers(auth_client, MANAGER_A)

    posted = auth_client.post(
        f"/api/internal/advisory/drafts/{draft['id']}/comments",
        headers=manager_headers,
        json={"body": "客户询问什么时候能拿到方案"},
    )
    assert posted.status_code == 200
    assert posted.json()["data"]["author_role"] == "客户经理"

    listing = auth_client.get(
        f"/api/internal/advisory/drafts/{draft['id']}/comments", headers=advisor_headers
    ).json()["data"]["comments"]
    assert any(c["body"] == "客户询问什么时候能拿到方案" for c in listing)


def test_an_empty_comment_is_rejected(auth_client: TestClient, draft):
    response = auth_client.post(
        f"/api/internal/advisory/drafts/{draft['id']}/comments",
        headers=_employee_headers(auth_client, ADVISOR),
        json={"body": "   "},
    )
    assert response.status_code == 400


def test_an_unrelated_account_manager_cannot_comment(auth_client: TestClient, draft):
    response = auth_client.post(
        f"/api/internal/advisory/drafts/{draft['id']}/comments",
        headers=_employee_headers(auth_client, MANAGER_B),
        json={"body": "我路过看看"},
    )
    assert response.status_code == 403
