"""客户送达视图与客户侧方案接口（advisory-plan-visibility issue 01）。

Seam：后端 HTTP 层。客户侧读到的不是顾问定稿本身，而是它在客户可见
视图以内的子集——裁剪发生在服务端，所以这里比的都是响应体的形状：
越权按 id 读别人的定稿、无定稿时的空列表、内部字段不外泄。
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

# 客户送达视图里产品清单保留的字段（ADR-0016）。测试里独立写一份，
# 而不是引用生产代码里的常量：裁剪清单就是这里要比的东西。
CUSTOMER_VISIBLE_PRODUCT_FIELDS = (
    "product_code",
    "product_name",
    "product_type",
    "risk_level",
    "expected_return",
    "term_days",
)

INTERNAL_ONLY_FIELDS = (
    "warnings",
    "composite_score",
    "score_breakdown",
    "reason",
    "content_classification",
    "customer_id",
    "advisor_id",
    "draft_id",
)


def _real_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _engine():
    return create_engine(get_settings().test_database_url)


def _employee_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": ADVISOR, "password": SEEDED_PASSWORD},
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
    username = f"deliveryviewtest_{id(object())}"
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
    candidates: list[dict] | None = None,
    allocation_suggestion: dict | None = None,
) -> dict:
    response = client.post(
        f"/api/internal/advisory/drafts/{draft_id}/release",
        headers=_employee_headers(client),
        json={
            "candidates": candidates,
            "allocation_suggestion": allocation_suggestion,
            "warnings": None,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def _customer_products(candidates: list[dict]) -> list[dict]:
    return [
        {field: candidate.get(field) for field in CUSTOMER_VISIBLE_PRODUCT_FIELDS}
        for candidate in candidates
    ]


def _plans(client: TestClient, username: str) -> dict:
    response = client.get("/api/customer/advisory/plans", headers=_customer_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]


def test_no_released_plan_yields_an_empty_list_not_a_404(auth_client: TestClient, customer):
    customer_id, username = customer
    _generate_plan(auth_client, customer_id)

    headers = _customer_headers(auth_client, username)
    empty = auth_client.get("/api/customer/advisory/plans", headers=headers).json()["data"]
    assert empty == {"items": [], "total": 0, "page": 1, "page_size": 20}
    # 尚无已放行的方案时，最新一份那个出口仍是 404（语义不变）。
    assert auth_client.get("/api/customer/advisory/plan", headers=headers).status_code == 404


def test_released_finals_are_listed_newest_first_with_the_advisor_confirmed_allocation(
    auth_client: TestClient, customer
):
    customer_id, username = customer

    first_draft = _generate_plan(auth_client, customer_id)
    edited_allocation = {**first_draft["allocation_suggestion"]}
    edited_allocation["现金"] = float(edited_allocation.get("现金", 0)) + 5
    first_final = _release(auth_client, first_draft["id"], allocation_suggestion=edited_allocation)

    second_draft = _generate_plan(auth_client, customer_id)
    second_final = _release(auth_client, second_draft["id"])

    plans = _plans(auth_client, username)["items"]
    assert [plan["id"] for plan in plans] == [second_final["id"], first_final["id"]]

    delivered = plans[1]
    assert delivered["allocation_suggestion"] == edited_allocation
    assert delivered["allocation_suggestion"] != first_draft["allocation_suggestion"]
    assert delivered["candidates"] == _customer_products(first_draft["candidates"])
    assert delivered["advisor_name"]
    assert delivered["released_at"]

    # 详情出口与列表出口是同一个序列化函数，拿到的是同一份形状。
    detail = auth_client.get(
        f"/api/customer/advisory/plans/{first_final['id']}",
        headers=_customer_headers(auth_client, username),
    )
    assert detail.status_code == 200
    assert detail.json()["data"] == delivered

    # 「最新一份」与列表首行是同一个口径，两个出口不该给出不同的方案。
    latest = auth_client.get(
        "/api/customer/advisory/plan", headers=_customer_headers(auth_client, username)
    ).json()["data"]
    assert latest == plans[0]


def test_the_customer_delivery_view_carries_no_internal_fields(auth_client: TestClient, customer):
    customer_id, username = customer
    draft = _generate_plan(auth_client, customer_id)
    final = _release(auth_client, draft["id"])

    headers = _customer_headers(auth_client, username)
    delivery_view = auth_client.get("/api/customer/advisory/plan", headers=headers).json()["data"]
    listed = _plans(auth_client, username)["items"][0]
    detail = auth_client.get(
        f"/api/customer/advisory/plans/{final['id']}", headers=headers
    ).json()["data"]

    for view in (delivery_view, listed, detail):
        for field in INTERNAL_ONLY_FIELDS:
            assert field not in view, field

    # 产品清单逐项拣选：得分、排序依据与推荐理由都不在客户送达视图里。
    for product in delivery_view["candidates"]:
        assert set(product) == set(CUSTOMER_VISIBLE_PRODUCT_FIELDS)

    assert delivery_view["candidates"] == _customer_products(draft["candidates"])


def test_a_customer_cannot_read_another_customers_final_by_id(auth_client: TestClient, customer):
    _customer_id_a, username_a = customer
    username_b = f"deliveryviewother_{id(object())}"
    other_id = _insert_customer(username=username_b)
    try:
        other_final = _release(auth_client, _generate_plan(auth_client, other_id)["id"])

        # 这份定稿确实存在，且归客户 B：B 按 id 读得到。
        readable = auth_client.get(
            f"/api/customer/advisory/plans/{other_final['id']}",
            headers=_customer_headers(auth_client, username_b),
        )
        assert readable.status_code == 200
        assert readable.json()["data"]["id"] == other_final["id"]

        headers_a = _customer_headers(auth_client, username_a)
        # 不属于调用者的 id 与不存在同义：404 而不是 403——不确认他人资源是否存在。
        assert (
            auth_client.get(
                f"/api/customer/advisory/plans/{other_final['id']}", headers=headers_a
            ).status_code
            == 404
        )
        assert auth_client.get("/api/customer/advisory/plan", headers=headers_a).status_code == 404
        assert _plans(auth_client, username_a)["items"] == []
    finally:
        _delete_customer(other_id)


def test_reading_a_final_by_an_unknown_id_is_a_404(auth_client: TestClient, customer):
    _customer_id, username = customer

    response = auth_client.get(
        "/api/customer/advisory/plans/99999999",
        headers=_customer_headers(auth_client, username),
    )
    assert response.status_code == 404
