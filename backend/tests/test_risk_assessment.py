from datetime import date, datetime, timezone
from collections.abc import Iterator

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, CustomerProfile, RiskAssessment
from app.risk_assessment.service import ASSESSOR_TYPE
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"

EXPECTED_DIMENSIONS = {"收入", "投资经验", "风险承受力", "投资目标"}
CUSTOMER_HIDDEN_FIELDS = {
    "confidence_score",
    "confidence",
    "dimension_scores",
    "judgement",
    "judgment",
    "conflict_records",
}


def _purge_self_assessments_and_restore_wangc1(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(RiskAssessment).where(RiskAssessment.assessor_type == ASSESSOR_TYPE))
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
def _restore_seeded_assessment_state(auth_client: TestClient) -> Iterator[None]:
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    _purge_self_assessments_and_restore_wangc1(engine)
    try:
        yield
    finally:
        _purge_self_assessments_and_restore_wangc1(engine)
        engine.dispose()



def _customer_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_questionnaire_has_sixteen_questions_across_four_dimensions(auth_client: TestClient):
    response = auth_client.get(
        "/api/customer/risk-assessment/questionnaire",
        headers=_customer_headers(auth_client),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    questions = payload["questions"]
    assert len(questions) == 16
    assert {question["dimension"] for question in questions} == EXPECTED_DIMENSIONS
    for dimension in EXPECTED_DIMENSIONS:
        assert sum(1 for question in questions if question["dimension"] == dimension) == 4
    for question in questions:
        assert len(question["options"]) == 4
        assert "score" not in question
        for option in question["options"]:
            assert "score" not in option
            assert option["id"]
            assert option["label"]


def test_saved_answers_are_restored_when_questionnaire_is_fetched_again(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    save_response = auth_client.put(
        "/api/customer/risk-assessment/draft",
        headers=headers,
        json={"answers": {"q01": "B", "q09": "C"}},
    )
    assert save_response.status_code == 200

    restored = auth_client.get(
        "/api/customer/risk-assessment/questionnaire",
        headers=_customer_headers(auth_client),
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["answers"] == {"q01": "B", "q09": "C"}


def _questionnaire(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get("/api/customer/risk-assessment/questionnaire", headers=headers)
    assert response.status_code == 200
    return response.json()["data"]


def _answers_at_option_index(questions: list[dict], option_index: int) -> dict[str, str]:
    return {question["id"]: question["options"][option_index]["id"] for question in questions}


def _assert_customer_visible_result(payload: dict, *, risk_level: str) -> None:
    assert payload["risk_level"] == risk_level
    assert set(payload) <= {"risk_level", "valid_until"}
    assert CUSTOMER_HIDDEN_FIELDS.isdisjoint(payload)
    valid_until = date.fromisoformat(payload["valid_until"])
    today = datetime.now(timezone.utc).date()
    try:
        expected = today.replace(year=today.year + 1)
    except ValueError:
        expected = today.replace(year=today.year + 1, day=28)
    assert valid_until == expected


def test_answering_every_question_conservatively_returns_c1(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    questions = _questionnaire(auth_client, headers)["questions"]
    response = auth_client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": _answers_at_option_index(questions, 0)},
    )

    assert response.status_code == 200
    _assert_customer_visible_result(response.json()["data"], risk_level="C1")


def _submit_at_option_index(client: TestClient, headers: dict[str, str], option_index: int):
    questions = _questionnaire(client, headers)["questions"]
    return client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": _answers_at_option_index(questions, option_index)},
    )


def test_aggressive_answers_update_the_customer_visible_result_to_c5(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    submit_response = _submit_at_option_index(auth_client, headers, 3)
    assert submit_response.status_code == 200
    _assert_customer_visible_result(submit_response.json()["data"], risk_level="C5")

    current = auth_client.get("/api/customer/risk-assessment", headers=headers)
    assert current.status_code == 200
    _assert_customer_visible_result(current.json()["data"], risk_level="C5")

    questionnaire = _questionnaire(auth_client, headers)
    assert questionnaire["answers"] == {}


def test_resubmitting_keeps_previous_assessments(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    first = _submit_at_option_index(auth_client, headers, 0)
    second = _submit_at_option_index(auth_client, headers, 3)
    assert first.status_code == second.status_code == 200

    current = auth_client.get("/api/customer/risk-assessment", headers=headers)
    _assert_customer_visible_result(current.json()["data"], risk_level="C5")

    employee = auth_client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    employee_headers = {"Authorization": f"Bearer {employee.json()['data']['access_token']}"}
    customer_id = int(
        pyjwt.decode(
            headers["Authorization"].split(" ", 1)[1],
            options={"verify_signature": False},
        )["sub"]
    )
    history = auth_client.get(
        f"/api/internal/customers/{customer_id}/risk-assessments",
        headers=employee_headers,
    )
    assert history.status_code == 200
    levels = [item["risk_level"] for item in history.json()["data"]]
    assert levels.count("C1") >= 1
    assert levels.count("C5") >= 1
    assert len(history.json()["data"]) >= 3


def test_balanced_answers_return_c3(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    questions = _questionnaire(auth_client, headers)["questions"]
    answers = {
        question["id"]: question["options"][1 if index < 8 else 2]["id"]
        for index, question in enumerate(questions)
    }
    response = auth_client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": answers},
    )
    assert response.status_code == 200
    _assert_customer_visible_result(response.json()["data"], risk_level="C3")


def _employee_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_employee_token_is_rejected_on_customer_risk_assessment(auth_client: TestClient):
    headers = _employee_headers(auth_client)
    questionnaire = auth_client.get("/api/customer/risk-assessment/questionnaire", headers=headers)
    current = auth_client.get("/api/customer/risk-assessment", headers=headers)
    assert questionnaire.status_code in (401, 403)
    assert current.status_code in (401, 403)


def test_customer_token_is_rejected_on_internal_assessment_history(auth_client: TestClient):
    headers = _customer_headers(auth_client)
    response = auth_client.get("/api/internal/customers/1/risk-assessments", headers=headers)
    assert response.status_code in (401, 403)
