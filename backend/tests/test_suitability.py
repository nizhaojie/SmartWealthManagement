from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, CustomerProfile, RiskAssessment, SuitabilityDecision
from app.risk_assessment.service import ASSESSOR_TYPE
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"
SEEDED_USERNAMES = {"wangc1", "lisic2", "zhangc3", "zhaoc4", "qianc5"}
OVERGRADE_LEVELS = {"R2", "R3", "R4", "R5"}


def _purge_self_assessments_and_restore_wangc1(engine) -> None:
    with OrmSession(engine) as session:
        extras = session.scalars(
            select(Customer).where(Customer.username.not_in(SEEDED_USERNAMES))
        ).all()
        extra_ids = [row.id for row in extras]
        session.execute(delete(SuitabilityDecision))
        session.execute(delete(RiskAssessment).where(RiskAssessment.assessor_type == ASSESSOR_TYPE))
        if extra_ids:
            session.execute(delete(RiskAssessment).where(RiskAssessment.customer_id.in_(extra_ids)))
            session.execute(delete(CustomerProfile).where(CustomerProfile.customer_id.in_(extra_ids)))
            session.execute(delete(Customer).where(Customer.id.in_(extra_ids)))
        customer = session.scalar(select(Customer).where(Customer.username == CUSTOMER_USERNAME))
        assert customer is not None
        profile = session.scalar(
            select(CustomerProfile).where(CustomerProfile.customer_id == customer.id)
        )
        assert profile is not None
        profile.risk_level = "C1"
        profile.risk_score = 18
        profile.computed_at = datetime(2022, 3, 16, 9, 0, 0)
        session.commit()


@pytest.fixture(autouse=True)
def _restore_seeded_state(auth_client: TestClient) -> Iterator[None]:
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    _purge_self_assessments_and_restore_wangc1(engine)
    try:
        yield
    finally:
        _purge_self_assessments_and_restore_wangc1(engine)
        engine.dispose()


def _customer_headers(client: TestClient, username: str = CUSTOMER_USERNAME) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _employee_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _customer_id(headers: dict[str, str]) -> int:
    return int(
        pyjwt.decode(
            headers["Authorization"].split(" ", 1)[1],
            options={"verify_signature": False},
        )["sub"]
    )


def _answers_at_option_index(questions: list[dict], option_index: int) -> dict[str, str]:
    return {question["id"]: question["options"][option_index]["id"] for question in questions}


def _submit_conservative_assessment(client: TestClient, headers: dict[str, str]):
    questionnaire = client.get("/api/customer/risk-assessment/questionnaire", headers=headers)
    questions = questionnaire.json()["data"]["questions"]
    return client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": _answers_at_option_index(questions, 0)},
    )


def _pool_levels(client: TestClient, headers: dict[str, str], **params) -> set[str]:
    response = client.get("/api/customer/candidate-pool", headers=headers, params=params)
    assert response.status_code == 200
    products = response.json()["data"]["products"]
    assert products
    return {product["risk_level"] for product in products}


def test_c1_candidate_pool_excludes_r2_and_above(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    submitted = _submit_conservative_assessment(auth_client, headers)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C1"

    levels = _pool_levels(auth_client, headers)
    assert levels == {"R1"}
    assert levels.isdisjoint(OVERGRADE_LEVELS)


def test_c3_candidate_pool_includes_r1_to_r3_and_excludes_r4_r5(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    questionnaire = auth_client.get("/api/customer/risk-assessment/questionnaire", headers=headers)
    questions = questionnaire.json()["data"]["questions"]
    answers = {
        question["id"]: question["options"][1 if index < 8 else 2]["id"]
        for index, question in enumerate(questions)
    }
    submitted = auth_client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": answers},
    )
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C3"

    levels = _pool_levels(auth_client, headers)
    assert "R1" in levels
    assert "R2" in levels
    assert "R3" in levels
    assert "R4" not in levels
    assert "R5" not in levels


def test_request_params_cannot_raise_the_suitability_cap(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    submitted = _submit_conservative_assessment(auth_client, headers)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C1"

    levels = _pool_levels(
        auth_client,
        headers,
        max_risk_level="R5",
        risk_level="R5",
    )
    assert levels == {"R1"}
    assert levels.isdisjoint(OVERGRADE_LEVELS)


def _id_number_for_age(age: int) -> str:
    today = datetime.now(timezone.utc).date()
    birth = date(today.year - age, today.month, today.day)
    return f"110101{birth.strftime('%Y%m%d')}{age:03d}X"


def _insert_customer_with_assessment(
    *,
    username: str,
    id_number: str,
    risk_level: str = "C3",
    annual_income_range: str = "10-30万",
    total_assets: Decimal = Decimal("80000.00"),
    valid_until: date | None = None,
) -> int:
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    try:
        with OrmSession(engine) as session:
            template = session.scalar(select(Customer).where(Customer.username == CUSTOMER_USERNAME))
            assert template is not None
            customer = Customer(
                username=username,
                password_hash=template.password_hash,
                real_name=username,
                id_number=id_number,
                phone="13900000002",
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
                    investment_experience="1-3年",
                    annual_income_range=annual_income_range,
                    total_assets=total_assets,
                    target_allocation={"股票": 40, "债券": 40, "现金": 20, "另类": 0},
                    product_preference={"基金": ["混合基金"]},
                    confidence_score=Decimal("0.80"),
                    computed_at=datetime(2026, 1, 1, 9, 0, 0),
                )
            )
            session.add(
                RiskAssessment(
                    customer_id=customer.id,
                    assessment_date=date(2026, 1, 1),
                    total_score=50,
                    risk_level=risk_level,
                    answers=[],
                    assessor_type="人工评估",
                    valid_until=valid_until or date(2027, 1, 1),
                )
            )
            session.commit()
            return customer.id
    finally:
        engine.dispose()


def test_no_income_low_assets_candidate_pool_is_capped_at_r2(auth_client: TestClient):
    customer_id = _insert_customer_with_assessment(
        username="noincomepool",
        id_number=_id_number_for_age(40),
        risk_level="C3",
        annual_income_range="无收入",
        total_assets=Decimal("9999.99"),
    )
    response = auth_client.get(
        f"/api/internal/customers/{customer_id}/candidate-pool",
        headers=_employee_headers(auth_client),
    )
    assert response.status_code == 200
    products = response.json()["data"]["products"]
    assert products
    levels = {product["risk_level"] for product in products}
    assert "R1" in levels
    assert "R2" in levels
    assert "R3" not in levels
    assert "R4" not in levels
    assert "R5" not in levels


def test_expired_assessment_cannot_fetch_candidate_pool(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    response = auth_client.get("/api/customer/candidate-pool", headers=headers)
    assert response.status_code == 403
    payload = response.json()
    assert payload["code"] == 403
    assert "过期" in payload["message"]
    assert payload.get("data") in (None, {})

    internal = auth_client.get(
        f"/api/internal/customers/{_customer_id(headers)}/candidate-pool",
        headers=_employee_headers(auth_client),
    )
    assert internal.status_code == 403
    assert "过期" in internal.json()["message"]


def test_suitability_decision_records_the_assessment_it_used(auth_client: TestClient):
    customer = _customer_headers(auth_client)
    employee = _employee_headers(auth_client)
    customer_id = _customer_id(customer)
    submitted = _submit_conservative_assessment(auth_client, customer)
    assert submitted.status_code == 200

    history = auth_client.get(
        f"/api/internal/customers/{customer_id}/risk-assessments",
        headers=employee,
    )
    assert history.status_code == 200
    latest_assessment = history.json()["data"][-1]
    assert latest_assessment["risk_level"] == "C1"

    pool = auth_client.get("/api/customer/candidate-pool", headers=customer)
    assert pool.status_code == 200

    records = auth_client.get(
        f"/api/internal/customers/{customer_id}/suitability-decisions",
        headers=employee,
    )
    assert records.status_code == 200
    payload = records.json()["data"]
    assert payload
    latest = payload[-1]
    assert latest["assessment_id"] == latest_assessment["id"]
    assert latest["customer_risk_level"] == "C1"
    assert latest["allowed_product_risk_levels"] == ["R1"]
    assert latest["decided_at"]
