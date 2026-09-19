from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import AdvisoryRequest, Customer
from app.settings import get_settings

CUSTOMER_A = "wangc1"
CUSTOMER_B = "lisic2"
ADVISOR = "advisor1"
SEEDED_PASSWORD = "Test@1234"

BOND_FILTERS = {"product_type": "债券基金", "max_term_days": "365"}
MONEY_FILTERS = {"product_type": "货币基金"}

STATUS_PENDING = "待处理"
STATUS_IN_PROGRESS = "处理中"
STATUS_COMPLETED = "已完成"


def _engine():
    return create_engine(get_settings().test_database_url)


@pytest.fixture(autouse=True)
def _clean_advisory_requests() -> Iterator[None]:
    engine = _engine()
    _delete_all(engine)
    try:
        yield
    finally:
        _delete_all(engine)
        engine.dispose()


def _delete_all(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(AdvisoryRequest))
        session.commit()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _employee_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": ADVISOR, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_id(username: str) -> int:
    with OrmSession(_engine()) as session:
        customer = session.scalar(select(Customer).where(Customer.username == username))
        assert customer is not None
        return customer.id


def _submit(client: TestClient, username: str, filters: dict) -> dict:
    response = client.post(
        "/api/customer/advisory-requests", headers=_headers(client, username), json=filters
    )
    assert response.status_code == 200
    return response.json()["data"]


def _my_requests(client: TestClient, username: str) -> list[dict]:
    response = client.get("/api/customer/advisory-requests", headers=_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]["requests"]


def _internal_requests(client: TestClient, **params) -> list[dict]:
    response = client.get(
        "/api/internal/advisory-requests", headers=_employee_headers(client), params=params
    )
    assert response.status_code == 200
    return response.json()["data"]["requests"]


def test_submitted_request_is_listed_back_to_its_submitter_with_a_status(auth_client: TestClient):
    created = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)

    assert created["status"] == STATUS_PENDING
    assert created["request_no"]

    mine = _my_requests(auth_client, CUSTOMER_A)
    assert [row["request_no"] for row in mine] == [created["request_no"]]
    assert mine[0]["status"] == STATUS_PENDING


def test_request_records_its_submit_time_and_triggering_filters(auth_client: TestClient):
    before = _utc_now() - timedelta(seconds=5)

    created = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)

    assert created["filters"] == BOND_FILTERS
    submitted_at = datetime.fromisoformat(created["submitted_at"])
    assert before <= submitted_at <= _utc_now() + timedelta(seconds=5)


def test_customer_only_sees_the_requests_they_submitted(auth_client: TestClient):
    mine = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)["request_no"]
    theirs = _submit(auth_client, CUSTOMER_B, MONEY_FILTERS)["request_no"]

    assert {row["request_no"] for row in _my_requests(auth_client, CUSTOMER_A)} == {mine}
    assert {row["request_no"] for row in _my_requests(auth_client, CUSTOMER_B)} == {theirs}


def test_a_forged_customer_id_in_the_request_body_is_ignored(auth_client: TestClient):
    forged = {**BOND_FILTERS, "customer_id": _customer_id(CUSTOMER_B)}

    headers = _headers(auth_client, CUSTOMER_A)
    response = auth_client.post("/api/customer/advisory-requests", headers=headers, json=forged)

    assert response.status_code == 200
    # 请求归属于令牌圈定的客户 A，而不是请求体里伪造的客户 B。
    created_no = response.json()["data"]["request_no"]
    assert [row["request_no"] for row in _my_requests(auth_client, CUSTOMER_A)] == [created_no]
    assert all(row["request_no"] != created_no for row in _my_requests(auth_client, CUSTOMER_B))


def test_customer_side_responses_do_not_echo_the_internal_customer_id(
    auth_client: TestClient,
):
    created = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)
    assert "customer_id" not in created

    listed = _my_requests(auth_client, CUSTOMER_A)
    assert all("customer_id" not in row for row in listed)


def test_requests_can_be_listed_on_the_internal_side_for_the_review_queue(auth_client: TestClient):
    mine = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)["request_no"]
    theirs = _submit(auth_client, CUSTOMER_B, MONEY_FILTERS)["request_no"]

    rows = _internal_requests(auth_client)
    assert {row["request_no"] for row in rows} == {mine, theirs}

    pending = _internal_requests(auth_client, status=STATUS_PENDING)
    assert [row["request_no"] for row in pending] == [mine, theirs]


def test_repeating_the_same_conditions_does_not_pile_up_open_requests(auth_client: TestClient):
    first = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)
    repeated = _submit(auth_client, CUSTOMER_A, dict(BOND_FILTERS))

    assert repeated["request_no"] == first["request_no"]
    assert len(_my_requests(auth_client, CUSTOMER_A)) == 1
    assert len(_internal_requests(auth_client)) == 1

    different = _submit(auth_client, CUSTOMER_A, MONEY_FILTERS)
    assert different["request_no"] != first["request_no"]
    assert len(_internal_requests(auth_client)) == 2


def test_a_completed_request_does_not_absorb_a_new_request_for_the_same_conditions(
    auth_client: TestClient,
):
    first = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)

    engine = _engine()
    with OrmSession(engine) as session:
        row = session.get(AdvisoryRequest, first["id"])
        assert row is not None
        row.status = STATUS_COMPLETED
        session.commit()

    repeated = _submit(auth_client, CUSTOMER_A, dict(BOND_FILTERS))
    assert repeated["request_no"] != first["request_no"]
    assert len(_internal_requests(auth_client, status=STATUS_PENDING)) == 1


def test_a_request_being_handled_still_absorbs_a_repeat_submission(auth_client: TestClient):
    first = _submit(auth_client, CUSTOMER_A, BOND_FILTERS)

    engine = _engine()
    with OrmSession(engine) as session:
        row = session.get(AdvisoryRequest, first["id"])
        assert row is not None
        row.status = STATUS_IN_PROGRESS
        session.commit()

    repeated = _submit(auth_client, CUSTOMER_A, dict(BOND_FILTERS))
    assert repeated["request_no"] == first["request_no"]
    assert len(_internal_requests(auth_client)) == 1
