"""持仓穿透的 HTTP 层测试（Seam 1）。

穿透的结果由接口形状观察，不直接查库——测试关心的是客户拿到的层级与底层资产。
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.customer_assets.look_through import look_through
from app.db.models import Customer, Holding, Product
from app.db.seed import seed
from app.exceptions import AppError
from app.settings import get_settings

CUSTOMER_A = "wangc1"
CUSTOMER_C = "zhangc3"
SEEDED_PASSWORD = "Test@1234"

FLAT_PRODUCT_CODE = "F000001"
NESTED_PRODUCT_CODE = "F000003"
CYCLE_HEAD_PRODUCT_CODE = "F900001"
CYCLE_HEAD_MARKET_VALUE = Decimal("10000.00")
NESTED_MARKET_VALUE = Decimal("108000.00")


def _engine():
    return create_engine(get_settings().test_database_url)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _get(client: TestClient, username: str, product_code: str):
    return client.get(
        f"/api/customer/assets/holdings/{product_code}/look-through",
        headers=_headers(client, username),
    )


def _look_through(client: TestClient, username: str, product_code: str) -> dict:
    response = _get(client, username, product_code)
    assert response.status_code == 200
    assert response.json()["code"] == 200
    return response.json()["data"]


def _add_cyclic_holding() -> None:
    engine = _engine()
    with OrmSession(engine) as session:
        customer = session.scalar(select(Customer).where(Customer.username == CUSTOMER_A))
        product = session.scalar(
            select(Product).where(Product.product_code == CYCLE_HEAD_PRODUCT_CODE)
        )
        assert customer is not None
        assert product is not None
        session.add(
            Holding(
                customer_id=customer.id,
                product_id=product.id,
                shares=Decimal("10000.0000"),
                cost_amount=CYCLE_HEAD_MARKET_VALUE,
                current_value=CYCLE_HEAD_MARKET_VALUE,
                profit_loss=Decimal("0.00"),
                profit_ratio=Decimal("0.0000"),
                status="持有中",
            )
        )
        session.commit()
    engine.dispose()


def _remove_cyclic_holding() -> None:
    engine = _engine()
    with OrmSession(engine) as session:
        product = session.scalar(
            select(Product).where(Product.product_code == CYCLE_HEAD_PRODUCT_CODE)
        )
        assert product is not None
        session.execute(delete(Holding).where(Holding.product_id == product.id))
        session.commit()
    engine.dispose()


@pytest.fixture(autouse=True)
def _restore_seeded_state() -> Iterator[None]:
    try:
        yield
    finally:
        _remove_cyclic_holding()
        seed(get_settings().test_database_url)


def test_a_flat_holding_opens_into_its_underlying_assets(auth_client: TestClient):
    payload = _look_through(auth_client, CUSTOMER_A, FLAT_PRODUCT_CODE)

    assert payload["product_code"] == FLAT_PRODUCT_CODE
    root = payload["root"]
    assert root["depth"] == 1
    assert root["share"] == "1.000000"
    assert [(child["code"], child["depth"]) for child in root["children"]] == [
        ("CASH-0001", 2),
        ("CASH-0002", 2),
    ]
    assert root["children"][0]["asset_category"] == "现金"
    assert root["children"][0]["share"] == "0.600000"
    assert root["children"][0]["market_value"] == "12252.00"


def test_a_holding_is_expanded_through_two_levels_of_nested_products(auth_client: TestClient):
    payload = _look_through(auth_client, CUSTOMER_C, NESTED_PRODUCT_CODE)

    assert payload["market_value"] == str(NESTED_MARKET_VALUE)
    root = payload["root"]
    assert root["code"] == NESTED_PRODUCT_CODE
    assert root["depth"] == 1

    nested = [child for child in root["children"] if child["kind"] == "product"]
    assert [(child["code"], child["depth"]) for child in nested] == [
        ("F000002", 2),
        ("F000001", 2),
    ]

    fund_of_funds = next(child for child in nested if child["code"] == "F000002")
    assert [child["code"] for child in fund_of_funds["children"]] == [
        "BOND-0001",
        "BOND-0002",
        "BOND-0003",
        "CASH-0001",
    ]
    assert {child["kind"] for child in fund_of_funds["children"]} == {"asset"}
    assert {child["depth"] for child in fund_of_funds["children"]} == {3}
    assert fund_of_funds["share"] == "0.300000"
    assert fund_of_funds["market_value"] == "32400.00"


def test_every_node_states_the_same_proportion_whichever_level_it_sits_on(
    auth_client: TestClient,
):
    """占比与市值必须相乘自洽，否则同一张表里会并排出现两套口径。"""
    payload = _look_through(auth_client, CUSTOMER_C, NESTED_PRODUCT_CODE)
    holding_value = Decimal(payload["market_value"])

    def check(node: dict) -> None:
        expected = (holding_value * Decimal(node["share"])).quantize(Decimal("0.01"))
        assert Decimal(node["market_value"]) == expected, node
        for child in node["children"]:
            check(child)

    check(payload["root"])

    nested = next(child for child in payload["root"]["children"] if child["code"] == "F000002")
    deepest = nested["children"][0]
    assert deepest["depth"] == 3
    # 第 3 层的资产：占比是沿路径乘出来的，不是它相对 F000002 的局部占比。
    assert deepest["share"] == "0.135000"
    assert deepest["market_value"] == "14580.00"


def test_paths_that_lead_to_the_same_underlying_asset_are_merged(auth_client: TestClient):
    payload = _look_through(auth_client, CUSTOMER_C, NESTED_PRODUCT_CODE)
    by_code = {row["asset_code"]: row for row in payload["underlying_assets"]}

    assert by_code["BOND-0001"]["path_count"] == 2
    assert by_code["BOND-0001"]["market_value"] == "36180.00"
    assert by_code["CASH-0001"]["path_count"] == 2
    assert by_code["CASH-0001"]["market_value"] == "9720.00"
    assert by_code["EQTY-0001"]["path_count"] == 1
    assert by_code["EQTY-0001"]["market_value"] == "43200.00"

    merged = sum(Decimal(row["market_value"]) for row in payload["underlying_assets"])
    assert merged == NESTED_MARKET_VALUE


def test_a_cyclic_holding_relation_is_reported_instead_of_hanging(auth_client: TestClient):
    _add_cyclic_holding()

    response = _get(auth_client, CUSTOMER_A, CYCLE_HEAD_PRODUCT_CODE)
    payload = response.json()

    assert payload["code"] != 200
    assert "成环" in payload["message"]
    assert CYCLE_HEAD_PRODUCT_CODE in payload["message"]
    assert "F900002" in payload["message"]
    assert payload["data"] is None


def test_expansion_stops_at_the_depth_limit_and_says_so():
    engine = _engine()
    with OrmSession(engine) as session:
        customer = session.scalar(select(Customer).where(Customer.username == CUSTOMER_C))
        assert customer is not None

        with pytest.raises(AppError) as caught:
            look_through(
                session,
                customer_id=customer.id,
                product_code=NESTED_PRODUCT_CODE,
                max_depth=1,
            )

    assert "深度上限" in caught.value.message
    assert NESTED_PRODUCT_CODE in caught.value.message
    engine.dispose()


def test_a_customer_cannot_look_through_someone_elses_holding(auth_client: TestClient):
    response = _get(auth_client, CUSTOMER_A, NESTED_PRODUCT_CODE)

    assert response.status_code == 404


def test_looking_through_a_product_the_customer_does_not_hold_is_rejected(
    auth_client: TestClient,
):
    response = _get(auth_client, CUSTOMER_A, "F000004")

    assert response.status_code == 404
