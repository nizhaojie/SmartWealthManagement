from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, CustomerProfile, RiskAssessment, SuitabilityDecision
from app.risk_assessment.service import ASSESSOR_TYPE
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
SEEDED_PASSWORD = "Test@1234"
SEEDED_USERNAMES = {"wangc1", "lisic2", "zhangc3", "zhaoc4", "qianc5"}
CODE_ORDER = ["F000001", "F000002", "F000003", "F000004", "F000005"]
YIELD_DESC_ORDER = ["F000005", "F000004", "F000003", "F000001", "F000002"]
YIELD_ASC_ORDER = ["F000002", "F000001", "F000003", "F000004", "F000005"]
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


def _answers_at_option_index(questions: list[dict], option_index: int) -> dict[str, str]:
    return {question["id"]: question["options"][option_index]["id"] for question in questions}


def _submit_assessment(client: TestClient, headers: dict[str, str], option_index: int):
    questionnaire = client.get("/api/customer/risk-assessment/questionnaire", headers=headers)
    questions = questionnaire.json()["data"]["questions"]
    return client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": _answers_at_option_index(questions, option_index)},
    )


def _product_codes(payload: dict) -> list[str]:
    return [product["product_code"] for product in payload["data"]["products"]]


def test_product_list_ignores_client_sort_params_and_stays_ordered_by_product_code(
    auth_client: TestClient,
):
    headers = _customer_headers(auth_client)
    submitted = _submit_assessment(auth_client, headers, 3)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C5"

    baseline = auth_client.get("/api/customer/products", headers=headers)
    assert baseline.status_code == 200
    assert _product_codes(baseline.json()) == CODE_ORDER

    attacked = auth_client.get(
        "/api/customer/products",
        headers=headers,
        params={
            "sort": "expected_return",
            "sort_by": "expected_return",
            "order": "desc",
            "order_by": "expected_return",
            "orderBy": "desc",
        },
    )
    assert attacked.status_code == 200
    codes = _product_codes(attacked.json())
    assert codes == CODE_ORDER
    assert codes != YIELD_DESC_ORDER
    assert codes != YIELD_ASC_ORDER


def _list_products(client: TestClient, headers: dict[str, str], **params):
    response = client.get("/api/customer/products", headers=headers, params=params)
    assert response.status_code == 200
    products = response.json()["data"]["products"]
    assert products
    return products


def test_c1_screening_excludes_r2_and_above(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    submitted = _submit_assessment(auth_client, headers, 0)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C1"

    products = _list_products(auth_client, headers)
    levels = {product["risk_level"] for product in products}
    assert levels == {"R1"}
    assert levels.isdisjoint(OVERGRADE_LEVELS)


def test_screening_params_cannot_raise_the_suitability_cap(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    submitted = _submit_assessment(auth_client, headers, 0)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C1"

    response = auth_client.get(
        "/api/customer/products",
        headers=headers,
        params={
            "max_risk_level": "R5",
            "risk_level": "R5",
            "recommended": "true",
        },
    )
    assert response.status_code == 200
    products = response.json()["data"]["products"]
    levels = {product["risk_level"] for product in products}
    assert levels.isdisjoint(OVERGRADE_LEVELS)


def test_screening_filters_by_objective_disclosed_fields(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    submitted = _submit_assessment(auth_client, headers, 3)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C5"

    by_type = _list_products(auth_client, headers, product_type="货币基金")
    assert [product["product_code"] for product in by_type] == ["F000001"]

    by_risk = _list_products(auth_client, headers, risk_level="R2")
    assert [product["product_code"] for product in by_risk] == ["F000002"]
    assert by_risk[0]["risk_level"] == "R2"

    by_amount = _list_products(auth_client, headers, min_amount="1000")
    assert [product["product_code"] for product in by_amount] == [
        "F000001",
        "F000002",
        "F000003",
        "F000004",
    ]

    by_benchmark = _list_products(auth_client, headers, min_expected_return="10")
    assert [product["product_code"] for product in by_benchmark] == ["F000004", "F000005"]

    by_term = _list_products(auth_client, headers, max_term_days="0")
    assert [product["product_code"] for product in by_term] == [
        "F000001",
        "F000002",
        "F000003",
        "F000005",
    ]


def test_product_detail_shows_disclosed_fields_and_hides_overgrade_products(
    auth_client: TestClient,
):
    headers = _customer_headers(auth_client)
    submitted = _submit_assessment(auth_client, headers, 3)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C5"

    response = auth_client.get("/api/customer/products/F000003", headers=headers)
    assert response.status_code == 200
    product = response.json()["data"]
    assert product["product_code"] == "F000003"
    assert product["product_name"] == "天璇混合基金"
    assert product["product_type"] == "混合基金"
    assert product["risk_level"] == "R3"
    assert product["expected_return"] == "8.0000"
    assert product["min_amount"] == "1000.00"
    assert product["term_days"] == 0
    assert product["fund_manager"] == "冯川"
    assert product["fee_rate"] == "1.2000"

    conservative = _customer_headers(auth_client)
    submitted_c1 = _submit_assessment(auth_client, conservative, 0)
    assert submitted_c1.status_code == 200
    assert submitted_c1.json()["data"]["risk_level"] == "C1"
    hidden = auth_client.get("/api/customer/products/F000005", headers=conservative)
    assert hidden.status_code == 404
    assert hidden.json()["data"] in (None, {})
