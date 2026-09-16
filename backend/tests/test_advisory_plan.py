"""投顾助手 Agent：候选池内排序（issue 01）。

Seam：后端 HTTP 层。用专门插入、与种子数据隔离的客户做验证，这样断言
不依赖种子客户风险评测是否仍在有效期内，也不会污染其他测试文件里对
种子客户状态的假设。
"""

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

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


def _insert_customer(
    *,
    username: str,
    risk_level: str = "C3",
    computed_at: datetime | None = None,
    tag_overrides: dict[str, tuple[str, datetime]] | None = None,
    held_product_codes: tuple[str, ...] = (),
) -> int:
    now = _real_now()
    computed_at = computed_at or now
    tag_overrides = tag_overrides or {}

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            customer = Customer(
                username=username,
                password_hash="unused-in-these-tests",
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
                    risk_level=risk_level,
                    risk_score=50,
                    investment_experience="3-5年",
                    annual_income_range="30-50万",
                    total_assets=Decimal("800000.00"),
                    target_allocation=TARGET_ALLOCATION,
                    product_preference=PRODUCT_PREFERENCE,
                    confidence_score=Decimal("0.90"),
                    computed_at=computed_at,
                )
            )
            session.add(
                RiskAssessment(
                    customer_id=customer.id,
                    assessment_date=now.date(),
                    total_score=50,
                    risk_level=risk_level,
                    answers=[],
                    assessor_type="人工评估",
                    valid_until=now.date() + timedelta(days=365),
                )
            )

            base_tags = {
                "risk_level": (risk_level, now),
                "investment_experience": ("3-5年", now),
                "annual_income_range": ("30-50万", now),
                "total_assets": (str(Decimal("800000.00")), now),
                "target_allocation": (TARGET_ALLOCATION, now),
                "product_preference": (PRODUCT_PREFERENCE, now),
            }
            base_tags.update(tag_overrides)
            for tag_key, (value, observed_at) in base_tags.items():
                session.add(
                    ProfileTag(
                        customer_id=customer.id,
                        tag_key=tag_key,
                        tag_value=value,
                        source=SOURCE_QUESTIONNAIRE,
                        evidence_count=0,
                        observed_at=observed_at,
                    )
                )

            if held_product_codes:
                products = {
                    row.product_code: row
                    for row in session.scalars(
                        select(Product).where(Product.product_code.in_(held_product_codes))
                    ).all()
                }
                for code in held_product_codes:
                    product = products[code]
                    session.add(
                        Holding(
                            customer_id=customer.id,
                            product_id=product.id,
                            shares=Decimal("1000.0000"),
                            cost_amount=Decimal("1000.00"),
                            current_value=Decimal("1000.00"),
                            profit_loss=Decimal("0.00"),
                            profit_ratio=Decimal("0.0000"),
                            status="持有中",
                            create_time=now,
                        )
                    )

            session.commit()
            return customer.id
    finally:
        engine.dispose()


@pytest.fixture
def customer_id() -> Iterator[int]:
    username = f"advisorytest_{id(object())}"
    created_id = _insert_customer(username=username, held_product_codes=("F000002",))
    try:
        yield created_id
    finally:
        _delete_customer(created_id)


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


def _generate_plan(client: TestClient, customer_id: int, *, tilt: str | None = None, employee: str = ADVISOR):
    return client.post(
        f"/api/internal/advisory/customers/{customer_id}/plan",
        headers=_employee_headers(client, employee),
        json={"tilt": tilt},
    )


def _customer_headers(client: TestClient, username: str = "wangc1") -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def test_plan_only_ranks_products_from_the_candidate_pool_and_excludes_already_held_ones(
    auth_client: TestClient, customer_id: int
):
    # C3 客户的候选池是 R1-R3；F000002（R2）已被这位客户持有，
    # 因此期望结果只剩 F000001（R1）与 F000003（R3）。
    response = _generate_plan(auth_client, customer_id)

    assert response.status_code == 200
    data = response.json()["data"]
    codes = {item["product_code"] for item in data["candidates"]}
    assert codes == {"F000001", "F000003"}

    for candidate in data["candidates"]:
        total = round(sum(item["contribution"] for item in candidate["score_breakdown"]), 4)
        assert total == candidate["composite_score"]
        assert "C3" in candidate["reason"]


def test_content_classification_defaults_to_advisory_content(
    auth_client: TestClient, customer_id: int
):
    response = _generate_plan(auth_client, customer_id)
    assert response.json()["data"]["content_classification"] == "投顾内容"


def test_account_manager_cannot_generate_a_plan(auth_client: TestClient, customer_id: int):
    response = _generate_plan(auth_client, customer_id, employee=ACCOUNT_MANAGER)
    assert response.status_code == 403


def test_an_unknown_tilt_is_rejected(auth_client: TestClient, customer_id: int):
    response = _generate_plan(auth_client, customer_id, tilt="不存在的侧重")
    assert response.status_code == 400


def test_allocation_suggestion_shifts_toward_equity_when_tilted_for_return(
    auth_client: TestClient, customer_id: int
):
    balanced = _generate_plan(auth_client, customer_id).json()["data"]["allocation_suggestion"]
    return_tilted = _generate_plan(auth_client, customer_id, tilt="收益优先").json()["data"][
        "allocation_suggestion"
    ]

    assert return_tilted["股票"] > balanced["股票"]
    assert round(sum(return_tilted.values()), 2) == 100.0


def test_low_confidence_tag_surfaces_as_a_warning(auth_client: TestClient):
    stale_observed_at = _real_now() - timedelta(days=365 * 4)
    created_id = _insert_customer(
        username=f"advisorylowconf_{id(object())}",
        tag_overrides={"product_preference": (PRODUCT_PREFERENCE, stale_observed_at)},
    )
    try:
        response = _generate_plan(auth_client, created_id)
        codes = {item["code"] for item in response.json()["data"]["warnings"]}
        assert "LOW_CONFIDENCE" in codes
    finally:
        _delete_customer(created_id)


def test_a_concentrated_industry_from_holdings_look_through_surfaces_as_a_warning(
    auth_client: TestClient,
):
    # F000002 的底层资产里 BOND-0001（45%）与 BOND-0002（30%）同属「利率债」，
    # 穿透合并后这一个行业就占了 75%，远超集中度阈值。
    created_id = _insert_customer(
        username=f"advisoryconcentrated_{id(object())}",
        held_product_codes=("F000002",),
    )
    try:
        response = _generate_plan(auth_client, created_id)
        assert response.status_code == 200
        codes = {item["code"] for item in response.json()["data"]["warnings"]}
        assert "INDUSTRY_CONCENTRATION" in codes
    finally:
        _delete_customer(created_id)


def test_a_customer_without_holdings_gets_no_industry_concentration_warning(
    auth_client: TestClient,
):
    created_id = _insert_customer(username=f"advisorynoholdings_{id(object())}")
    try:
        response = _generate_plan(auth_client, created_id)
        codes = {item["code"] for item in response.json()["data"]["warnings"]}
        assert "INDUSTRY_CONCENTRATION" not in codes
    finally:
        _delete_customer(created_id)


def test_stale_profile_surfaces_as_a_warning_without_blocking_generation(auth_client: TestClient):
    stale_computed_at = _real_now() - timedelta(days=200)
    created_id = _insert_customer(
        username=f"advisorystale_{id(object())}",
        computed_at=stale_computed_at,
    )
    try:
        response = _generate_plan(auth_client, created_id)
        assert response.status_code == 200
        codes = {item["code"] for item in response.json()["data"]["warnings"]}
        assert "PROFILE_STALE" in codes
    finally:
        _delete_customer(created_id)


# --- AI 原稿落库与内容分类（issue 02） ---


def test_generating_a_plan_persists_an_ai_draft_that_can_be_read_back(
    auth_client: TestClient, customer_id: int
):
    generated = _generate_plan(auth_client, customer_id).json()["data"]
    draft_id = generated["id"]

    fetched = auth_client.get(
        f"/api/internal/advisory/drafts/{draft_id}",
        headers=_employee_headers(auth_client),
    ).json()["data"]

    assert fetched["id"] == draft_id
    assert fetched["candidates"] == generated["candidates"]
    assert fetched["content_classification"] == "投顾内容"


def test_each_generation_persists_a_new_immutable_draft(
    auth_client: TestClient, customer_id: int
):
    first = _generate_plan(auth_client, customer_id).json()["data"]
    second = _generate_plan(auth_client, customer_id).json()["data"]
    assert first["id"] != second["id"]

    # 重新生成不会改写第一条原稿——再次读取第一条，内容仍与生成时一致。
    refetched_first = auth_client.get(
        f"/api/internal/advisory/drafts/{first['id']}",
        headers=_employee_headers(auth_client),
    ).json()["data"]
    assert refetched_first["candidates"] == first["candidates"]


def test_ai_draft_records_generation_time_profile_version_and_candidate_pool_snapshot(
    auth_client: TestClient, customer_id: int
):
    data = _generate_plan(auth_client, customer_id).json()["data"]

    assert data["generated_at"]
    assert data["profile_computed_at"]
    snapshot = data["candidate_pool_snapshot"]
    assert snapshot["customer_risk_level"] == "C3"
    assert {item["product_code"] for item in snapshot["products"]} >= {
        "F000001",
        "F000002",
        "F000003",
    }


def test_content_classification_stays_advisory_even_with_an_empty_candidate_list(
    auth_client: TestClient,
):
    # C1 客户的候选池只有 R1（F000001）；把它也持有掉，候选池内排序无产品
    # 可排——分类由「调用了推荐类工具」决定，不看排序有没有产出结果。
    created_id = _insert_customer(
        username=f"advisoryempty_{id(object())}",
        risk_level="C1",
        held_product_codes=("F000001",),
    )
    try:
        response = _generate_plan(auth_client, created_id)
        data = response.json()["data"]
        assert data["candidates"] == []
        assert data["content_classification"] == "投顾内容"
    finally:
        _delete_customer(created_id)


def test_advisory_content_carries_a_template_disclaimer(
    auth_client: TestClient, customer_id: int
):
    data = _generate_plan(auth_client, customer_id).json()["data"]
    assert data["disclaimer"]
    assert "不构成任何直接投资建议" in data["disclaimer"]


def test_customer_token_cannot_read_an_ai_draft(auth_client: TestClient, customer_id: int):
    generated = _generate_plan(auth_client, customer_id).json()["data"]

    response = auth_client.get(
        f"/api/internal/advisory/drafts/{generated['id']}",
        headers=_customer_headers(auth_client),
    )
    assert response.status_code in (401, 403)


def test_account_manager_cannot_read_an_ai_draft(auth_client: TestClient, customer_id: int):
    generated = _generate_plan(auth_client, customer_id).json()["data"]

    response = auth_client.get(
        f"/api/internal/advisory/drafts/{generated['id']}",
        headers=_employee_headers(auth_client, ACCOUNT_MANAGER),
    )
    assert response.status_code == 403
