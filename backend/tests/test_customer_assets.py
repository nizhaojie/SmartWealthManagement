from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, Holding, Product, RiskAssessment, Transaction
from app.db.seed import seed
from app.risk_assessment.service import ASSESSOR_TYPE
from app.settings import get_settings

CUSTOMER_A = "wangc1"
CUSTOMER_B = "lisic2"
SEEDED_PASSWORD = "Test@1234"

HOLDING_A_PRODUCT_CODE = "F000001"
HOLDING_B_PRODUCT_CODE = "F000002"
HOLDING_A_MARKET_VALUE = "20420.00"
TRANSACTION_A_NO = "TX202204100001"
TRANSACTION_A_AT = datetime(2022, 4, 10, 10, 30, 0)
EXTRA_TRANSACTION_NO = "TX202305060001"
EXTRA_TRANSACTION_AT = datetime(2023, 5, 6, 15, 0, 0)
REDEEM = "赎回"
SUBSCRIBE = "申购"


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(username: str) -> int:
    with OrmSession(_engine()) as session:
        customer = session.scalar(select(Customer).where(Customer.username == username))
        assert customer is not None
        return customer.id


def _purge_self_assessments(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(RiskAssessment).where(RiskAssessment.assessor_type == ASSESSOR_TYPE))
        session.commit()


def _add_extra_transaction(engine, customer_id: int, product_id: int) -> None:
    with OrmSession(engine) as session:
        if session.scalar(
            select(Transaction).where(Transaction.transaction_no == EXTRA_TRANSACTION_NO)
        ) is None:
            session.add(
                Transaction(
                    transaction_no=EXTRA_TRANSACTION_NO,
                    customer_id=customer_id,
                    product_id=product_id,
                    transaction_type=REDEEM,
                    amount=5000,
                    shares=4890,
                    nav=1.0225,
                    fee=5,
                    status="已确认",
                    create_time=EXTRA_TRANSACTION_AT,
                )
            )
            session.commit()


def _remove_extra_transaction(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(
            delete(Transaction).where(Transaction.transaction_no == EXTRA_TRANSACTION_NO)
        )
        session.commit()


@pytest.fixture(autouse=True)
def _stable_asset_state() -> Iterator[None]:
    engine = _engine()
    _purge_self_assessments(engine)
    with OrmSession(engine) as session:
        product = session.scalar(
            select(Product).where(Product.product_code == HOLDING_A_PRODUCT_CODE)
        )
        assert product is not None
        product_id = product.id
    _add_extra_transaction(engine, _customer_id(CUSTOMER_A), product_id)
    try:
        yield
    finally:
        _remove_extra_transaction(engine)
        _purge_self_assessments(engine)
        seed(get_settings().test_database_url)
        engine.dispose()


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _assets(client: TestClient, username: str, **params) -> dict:
    response = client.get(
        "/api/customer/assets", headers=_headers(client, username), params=params
    )
    assert response.status_code == 200
    return response.json()["data"]


def _transactions(client: TestClient, username: str, **params) -> list[dict]:
    response = client.get(
        "/api/customer/transactions", headers=_headers(client, username), params=params
    )
    assert response.status_code == 200
    return response.json()["data"]["transactions"]


def test_assets_are_aggregated_server_side_so_the_customer_need_not_add_them_up(
    auth_client: TestClient,
):
    payload = _assets(auth_client, CUSTOMER_A)

    assert payload["holding_count"] == 1
    assert payload["total_market_value"] == HOLDING_A_MARKET_VALUE
    assert payload["risk_level"] == "C1"


def test_holding_rows_carry_product_shares_cost_market_value_and_profit(
    auth_client: TestClient,
):
    payload = _assets(auth_client, CUSTOMER_A)

    [holding] = payload["holdings"]
    assert holding["product_code"] == HOLDING_A_PRODUCT_CODE
    assert holding["product_name"] == "天枢货币基金"
    assert holding["shares"] == "20000.0000"
    assert holding["cost_amount"] == "20000.00"
    assert holding["market_value"] == HOLDING_A_MARKET_VALUE
    assert holding["profit_loss"] == "420.00"


def test_total_market_value_is_the_sum_of_the_holding_rows(auth_client: TestClient):
    payload = _assets(auth_client, CUSTOMER_B)
    summed = sum(float(holding["market_value"]) for holding in payload["holdings"])

    assert len(payload["holdings"]) == payload["holding_count"]
    assert float(payload["total_market_value"]) == pytest.approx(summed)


def test_transactions_are_listed_newest_first_with_their_product(auth_client: TestClient):
    rows = _transactions(auth_client, CUSTOMER_A)

    assert [row["transaction_no"] for row in rows] == [EXTRA_TRANSACTION_NO, TRANSACTION_A_NO]
    assert rows[1]["transaction_type"] == SUBSCRIBE
    assert rows[1]["product_code"] == HOLDING_A_PRODUCT_CODE
    assert rows[0]["transaction_type"] == REDEEM


def test_transactions_can_be_filtered_by_date_range_and_transaction_type(
    auth_client: TestClient,
):
    from_start = _transactions(auth_client, CUSTOMER_A, start_date="2023-01-01")
    assert [row["transaction_no"] for row in from_start] == [EXTRA_TRANSACTION_NO]

    until_end = _transactions(auth_client, CUSTOMER_A, end_date="2022-12-31")
    assert [row["transaction_no"] for row in until_end] == [TRANSACTION_A_NO]

    within = _transactions(auth_client, CUSTOMER_A, start_date="2022-04-10", end_date="2022-04-10")
    assert [row["transaction_no"] for row in within] == [TRANSACTION_A_NO]

    redeems = _transactions(auth_client, CUSTOMER_A, transaction_type=REDEEM)
    assert [row["transaction_no"] for row in redeems] == [EXTRA_TRANSACTION_NO]

    combined = _transactions(
        auth_client,
        CUSTOMER_A,
        start_date="2022-01-01",
        end_date="2022-12-31",
        transaction_type=REDEEM,
    )
    assert combined == []


def test_a_customer_sees_only_their_own_holdings_and_transactions(auth_client: TestClient):
    mine = _assets(auth_client, CUSTOMER_A)
    theirs = _assets(auth_client, CUSTOMER_B)
    their_codes = {row["product_code"] for row in theirs["holdings"]}

    assert [row["product_code"] for row in mine["holdings"]] == [HOLDING_A_PRODUCT_CODE]
    assert HOLDING_B_PRODUCT_CODE in their_codes
    assert not {row["product_code"] for row in mine["holdings"]} & their_codes

    my_transactions = {row["transaction_no"] for row in _transactions(auth_client, CUSTOMER_A)}
    their_transactions = {row["transaction_no"] for row in _transactions(auth_client, CUSTOMER_B)}

    assert my_transactions == {EXTRA_TRANSACTION_NO, TRANSACTION_A_NO}
    assert their_transactions
    assert my_transactions.isdisjoint(their_transactions)


def test_a_forged_customer_id_in_the_request_is_ignored_and_the_callers_data_is_returned(
    auth_client: TestClient,
):
    forged = _customer_id(CUSTOMER_B)

    payload = _assets(auth_client, CUSTOMER_A, customer_id=forged)
    assert [row["product_code"] for row in payload["holdings"]] == [HOLDING_A_PRODUCT_CODE]

    rows = _transactions(auth_client, CUSTOMER_A, customer_id=forged)
    assert {row["transaction_no"] for row in rows} == {EXTRA_TRANSACTION_NO, TRANSACTION_A_NO}


def test_a_customer_without_holdings_gets_an_empty_set_instead_of_an_error(
    auth_client: TestClient,
):
    engine = _engine()
    with OrmSession(engine) as session:
        session.execute(delete(Holding).where(Holding.customer_id == _customer_id(CUSTOMER_A)))
        session.commit()

    payload = _assets(auth_client, CUSTOMER_A)

    assert payload["holdings"] == []
    assert payload["holding_count"] == 0
    assert payload["total_market_value"] == "0.00"


def test_holdings_stay_visible_for_a_customer_without_an_assessment(auth_client: TestClient):
    engine = _engine()
    with OrmSession(engine) as session:
        session.execute(
            delete(RiskAssessment).where(RiskAssessment.customer_id == _customer_id(CUSTOMER_A))
        )
        session.commit()

    payload = _assets(auth_client, CUSTOMER_A)

    assert payload["risk_level"] is None
    assert payload["risk_level_valid_until"] is None
    assert [row["product_code"] for row in payload["holdings"]] == [HOLDING_A_PRODUCT_CODE]
