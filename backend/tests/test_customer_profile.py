from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal

import jwt as pyjwt
import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    Customer,
    CustomerProfile,
    Holding,
    ProfileTag,
    ProfileTagConflict,
    RiskAssessment,
    SuitabilityDecision,
    Transaction,
)
from app.main import app
from app.redis_client import get_redis
from app.risk_assessment.service import ASSESSOR_TYPE
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"
SEEDED_USERNAMES = {"wangc1", "lisic2", "zhangc3", "zhaoc4", "qianc5"}

CUSTOMER_HIDDEN_FIELDS = {
    "confidence_score",
    "confidence",
    "dimension_scores",
    "judgement",
    "judgment",
    "conflict_records",
    "tags",
}


def _customer_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
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


def _customer_id_from_headers(headers: dict[str, str]) -> int:
    return int(
        pyjwt.decode(
            headers["Authorization"].split(" ", 1)[1],
            options={"verify_signature": False},
        )["sub"]
    )


def _write_tag(
    client: TestClient,
    headers: dict[str, str],
    customer_id: int,
    *,
    tag_key: str,
    value,
    source: str,
    reason: str | None = None,
):
    body: dict = {"tag_key": tag_key, "value": value, "source": source}
    if reason is not None:
        body["reason"] = reason
    return client.put(
        f"/api/internal/customers/{customer_id}/profile/tags",
        headers=headers,
        json=body,
    )


def _get_profile(client: TestClient, headers: dict[str, str], customer_id: int):
    return client.get(f"/api/internal/customers/{customer_id}/profile", headers=headers)


def _purge_profile_writes(engine) -> None:
    with OrmSession(engine) as session:
        extras = session.scalars(
            select(Customer).where(Customer.username.not_in(SEEDED_USERNAMES))
        ).all()
        extra_ids = [row.id for row in extras]
        session.execute(delete(SuitabilityDecision))
        session.execute(delete(ProfileTagConflict))
        session.execute(delete(ProfileTag))
        session.execute(delete(RiskAssessment).where(RiskAssessment.assessor_type == ASSESSOR_TYPE))
        if extra_ids:
            session.execute(delete(Holding).where(Holding.customer_id.in_(extra_ids)))
            session.execute(delete(Transaction).where(Transaction.customer_id.in_(extra_ids)))
            session.execute(delete(RiskAssessment).where(RiskAssessment.customer_id.in_(extra_ids)))
            session.execute(delete(CustomerProfile).where(CustomerProfile.customer_id.in_(extra_ids)))
            session.execute(delete(Customer).where(Customer.id.in_(extra_ids)))
        customer = session.scalar(select(Customer).where(Customer.username == CUSTOMER_USERNAME))
        if customer is not None:
            profile = session.scalar(
                select(CustomerProfile).where(CustomerProfile.customer_id == customer.id)
            )
            if profile is not None:
                profile.risk_level = "C1"
                profile.risk_score = 18
                profile.annual_income_range = "10万以下"
                profile.total_assets = Decimal("80000.00")
                profile.investment_experience = "0-1年"
                profile.computed_at = datetime(2022, 3, 16, 9, 0, 0)
        session.commit()


@pytest.fixture(autouse=True)
def _restore_profile_tags(auth_client: TestClient) -> Iterator[None]:
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    _purge_profile_writes(engine)
    try:
        yield
    finally:
        _purge_profile_writes(engine)
        engine.dispose()


def test_customer_profile_omits_confidence_scores_and_conflict_records(auth_client: TestClient):
    employee = _employee_headers(auth_client)
    customer = _customer_headers(auth_client)
    customer_id = _customer_id_from_headers(customer)
    _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="investment_experience",
        value="3-5年",
        source="客户自述",
    )
    _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="investment_experience",
        value="5-10年",
        source="风评问卷",
    )

    response = auth_client.get("/api/customer/profile", headers=customer)

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["risk_level"] == "C1"
    assert "valid_until" in payload
    assert set(payload) <= {"risk_level", "valid_until"}
    assert CUSTOMER_HIDDEN_FIELDS.isdisjoint(payload)
    dumped = str(payload)
    assert "置信" not in dumped
    assert "3-5年" not in dumped
    assert "conflict" not in dumped


def test_written_tag_is_readable_with_source_and_confidence(auth_client: TestClient):
    employee = _employee_headers(auth_client)
    customer_id = _customer_id_from_headers(_customer_headers(auth_client))

    write = _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="investment_experience",
        value="3-5年",
        source="客户自述",
    )
    assert write.status_code == 200

    profile = _get_profile(auth_client, employee, customer_id)
    assert profile.status_code == 200
    payload = profile.json()["data"]
    tag = next(item for item in payload["tags"] if item["key"] == "investment_experience")
    assert tag["value"] == "3-5年"
    assert tag["source"] == "客户自述"
    assert tag["confidence"] == 0.55
    assert "computed_at" in payload


def test_tag_conflict_keeps_the_old_value_in_a_queryable_record(auth_client: TestClient):
    employee = _employee_headers(auth_client)
    customer_id = _customer_id_from_headers(_customer_headers(auth_client))
    _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="investment_experience",
        value="0-1年",
        source="客户自述",
    )
    overwrite = _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="investment_experience",
        value="3-5年",
        source="风评问卷",
    )
    assert overwrite.status_code == 200

    payload = _get_profile(auth_client, employee, customer_id).json()["data"]
    tag = next(item for item in payload["tags"] if item["key"] == "investment_experience")
    assert tag["value"] == "3-5年"
    assert tag["source"] == "风评问卷"
    assert len(payload["conflict_records"]) == 1
    record = payload["conflict_records"][0]
    assert record["tag_key"] == "investment_experience"
    assert record["old_value"] == "0-1年"
    assert record["old_source"] == "客户自述"
    assert record["new_value"] == "3-5年"
    assert record["new_source"] == "风评问卷"
    assert record["changed_at"]


def test_advisor_correction_is_not_overwritten_by_ai_extraction(auth_client: TestClient):
    employee = _employee_headers(auth_client)
    customer_id = _customer_id_from_headers(_customer_headers(auth_client))
    correction = _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="annual_income_range",
        value="30-50万",
        source="理财顾问手工修正",
        reason="访谈确认客户年收入约四十万",
    )
    assert correction.status_code == 200

    ai_write = _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="annual_income_range",
        value="100万以上",
        source="AI对话提取",
    )
    assert ai_write.status_code == 200

    payload = _get_profile(auth_client, employee, customer_id).json()["data"]
    tag = next(item for item in payload["tags"] if item["key"] == "annual_income_range")
    assert tag["value"] == "30-50万"
    assert tag["source"] == "理财顾问手工修正"
    assert payload["conflict_records"] == []


def test_advisor_correction_requires_a_reason(auth_client: TestClient):
    employee = _employee_headers(auth_client)
    customer_id = _customer_id_from_headers(_customer_headers(auth_client))
    response = _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="product_preference",
        value={"基金": ["债券基金"]},
        source="理财顾问手工修正",
    )
    assert response.status_code == 400
    assert response.json()["message"] == "手工修正必须填写理由"


def test_same_source_lets_the_new_value_replace_the_old(auth_client: TestClient):
    employee = _employee_headers(auth_client)
    customer_id = _customer_id_from_headers(_customer_headers(auth_client))
    _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="investment_experience",
        value="1-3年",
        source="AI对话提取",
    )
    _write_tag(
        auth_client,
        employee,
        customer_id,
        tag_key="investment_experience",
        value="3-5年",
        source="AI对话提取",
    )
    payload = _get_profile(auth_client, employee, customer_id).json()["data"]
    tag = next(item for item in payload["tags"] if item["key"] == "investment_experience")
    assert tag["value"] == "3-5年"
    assert payload["conflict_records"][0]["old_value"] == "1-3年"


def test_customer_token_is_rejected_on_internal_profile(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    listed = auth_client.get("/api/internal/customers", headers=headers)
    profile = auth_client.get("/api/internal/customers/1/profile", headers=headers)
    assert listed.status_code in (401, 403)
    assert profile.status_code in (401, 403)


def test_employee_token_is_rejected_on_customer_profile(auth_client: TestClient):
    response = auth_client.get("/api/customer/profile", headers=_employee_headers(auth_client))
    assert response.status_code in (401, 403)


def test_account_manager_only_sees_their_own_customers(auth_client: TestClient):
    # 客户经理的客户目录按归属收窄：只能看到自己名下的客户，看不到其他
    # 客户经理名下的客户。
    response = auth_client.post(
        "/api/internal/auth/login",
        json={"username": "manager1", "password": SEEDED_PASSWORD},
    )
    manager_headers = {"Authorization": f"Bearer {response.json()['data']['access_token']}"}

    listed = auth_client.get("/api/internal/customers", headers=manager_headers)
    assert listed.status_code == 200
    usernames = {row["username"] for row in listed.json()["data"]}
    # manager1 名下只有 wangc1 / lisic2 / zhangc3；zhaoc4 / qianc5 归 manager2。
    assert usernames == {"wangc1", "lisic2", "zhangc3"}


def test_advisor_sees_the_full_customer_directory(auth_client: TestClient):
    # 理财顾问不受归属收窄，能看到全量客户目录。
    listed = auth_client.get("/api/internal/customers", headers=_employee_headers(auth_client))
    assert listed.status_code == 200
    usernames = {row["username"] for row in listed.json()["data"]}
    assert SEEDED_USERNAMES <= usernames


def _id_number_for_age(age: int) -> str:
    today = datetime.now(timezone.utc).date()
    birth = date(today.year - age, today.month, today.day)
    return f"110101{birth.strftime('%Y%m%d')}{age:03d}X"


def _insert_customer(*, username: str, id_number: str, **profile_fields) -> int:
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
                phone="13900000001",
                customer_level="普通",
                status="正常",
                opened_at=datetime(2024, 1, 1, 10, 0, 0),
            )
            session.add(customer)
            session.flush()
            fields = {
                "risk_level": "C3",
                "risk_score": 50,
                "investment_experience": "1-3年",
                "annual_income_range": "10-30万",
                "total_assets": Decimal("80000.00"),
                "target_allocation": {"股票": 40, "债券": 40, "现金": 20, "另类": 0},
                "product_preference": {"基金": ["混合基金"]},
                "confidence_score": Decimal("0.80"),
                "computed_at": datetime(2026, 1, 1, 9, 0, 0),
            }
            fields.update(profile_fields)
            session.add(CustomerProfile(customer_id=customer.id, **fields))
            session.commit()
            return customer.id
    finally:
        engine.dispose()


def _judgement(client: TestClient, headers: dict[str, str], customer_id: int) -> dict:
    payload = _get_profile(client, headers, customer_id).json()["data"]
    return payload["judgement"]


def test_age_under_18_circuit_breaks_before_scoring(auth_client: TestClient):
    customer_id = _insert_customer(username="minor17", id_number=_id_number_for_age(17))
    judgement = _judgement(auth_client, _employee_headers(auth_client), customer_id)
    assert judgement["circuit_break"] is True
    assert judgement["risk_level"] is None
    assert judgement["dimension_scores"] is None
    assert any(item["code"] == "AGE_UNDER_18" for item in judgement["reasons"])
    assert any("18" in item["message"] for item in judgement["reasons"])


def test_age_over_80_circuit_breaks_before_scoring(auth_client: TestClient):
    customer_id = _insert_customer(username="elder81", id_number=_id_number_for_age(81))
    judgement = _judgement(auth_client, _employee_headers(auth_client), customer_id)
    assert judgement["circuit_break"] is True
    assert judgement["risk_level"] is None
    assert any(item["code"] == "AGE_OVER_80" for item in judgement["reasons"])
    assert any("80" in item["message"] for item in judgement["reasons"])


def test_no_income_and_low_assets_circuit_breaks(auth_client: TestClient):
    customer_id = _insert_customer(
        username="noincome",
        id_number=_id_number_for_age(40),
        annual_income_range="无收入",
        total_assets=Decimal("9999.99"),
    )
    judgement = _judgement(auth_client, _employee_headers(auth_client), customer_id)
    assert judgement["circuit_break"] is True
    assert judgement["risk_level"] is None
    assert any(item["code"] == "NO_INCOME_LOW_ASSETS" for item in judgement["reasons"])
    assert any("万元" in item["message"] for item in judgement["reasons"])


def test_expired_assessment_circuit_breaks(auth_client: TestClient):
    customer_id = _customer_id_from_headers(_customer_headers(auth_client))
    judgement = _judgement(auth_client, _employee_headers(auth_client), customer_id)
    assert judgement["circuit_break"] is True
    assert judgement["risk_level"] is None
    assert any(item["code"] == "ASSESSMENT_EXPIRED" for item in judgement["reasons"])
    assert any("过期" in item["message"] for item in judgement["reasons"])


def test_four_dimension_scores_are_readable_after_fresh_assessment(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    employee = _employee_headers(auth_client)
    customer_id = _customer_id_from_headers(headers)
    questionnaire = auth_client.get("/api/customer/risk-assessment/questionnaire", headers=headers)
    questions = questionnaire.json()["data"]["questions"]
    answers = {question["id"]: question["options"][0]["id"] for question in questions}
    submitted = auth_client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": answers},
    )
    assert submitted.status_code == 200

    payload = _get_profile(auth_client, employee, customer_id).json()["data"]
    judgement = payload["judgement"]
    assert judgement["circuit_break"] is False
    assert judgement["dimension_scores"] == {
        "基础属性": 43.33,
        "投资经验": 20.0,
        "风险偏好": 20.0,
        "行为异常": 70.0,
    }
    assert judgement["weighted_score"] == 35.83
    assert judgement["risk_level"] == "C2"


def test_profile_remains_readable_when_cache_is_unavailable(auth_client: TestClient):
    settings = get_settings()
    real = redis_lib.Redis.from_url(settings.test_redis_url, decode_responses=True)

    class ProfileCacheDown:
        def get(self, name, *args, **kwargs):
            if str(name).startswith("customer_profile:"):
                raise redis_lib.ConnectionError("down")
            return real.get(name, *args, **kwargs)

        def set(self, name, value=None, *args, **kwargs):
            if str(name).startswith("customer_profile:"):
                raise redis_lib.ConnectionError("down")
            return real.set(name, value, *args, **kwargs)

        def delete(self, name, *args, **kwargs):
            if str(name).startswith("customer_profile:"):
                raise redis_lib.ConnectionError("down")
            return real.delete(name, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(real, name)

    app.dependency_overrides[get_redis] = lambda: ProfileCacheDown()
    try:
        employee = _employee_headers(auth_client)
        customer_id = _customer_id_from_headers(_customer_headers(auth_client))
        write = _write_tag(
            auth_client,
            employee,
            customer_id,
            tag_key="investment_experience",
            value="1-3年",
            source="客户自述",
        )
        assert write.status_code == 200
        profile = _get_profile(auth_client, employee, customer_id)
        assert profile.status_code == 200
        tag = next(
            item for item in profile.json()["data"]["tags"] if item["key"] == "investment_experience"
        )
        assert tag["value"] == "1-3年"
        assert tag["source"] == "客户自述"
    finally:
        app.dependency_overrides[get_redis] = lambda: real

