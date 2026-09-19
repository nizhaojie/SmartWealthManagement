"""资金账户与可用余额。

可用余额与画像里的总资产是两个概念（CONTEXT「资金账户」「可用余额」）：总资产是客户
自述的资产规模，可用余额只装客户在本机构能在这里动用的钱。两者不共用字段、不互相写。

可见范围沿用既有的归属规则：客户只拿得到自己的可用余额（标识由凭证推导），客户经理
只看得到名下客户的可用余额（`app.customer_scope`），理财顾问不受限。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, CustomerProfile, FundingAccount
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

CUSTOMER_LOW = "wangc1"  # C1；种子刻意留的余额不足客户
CUSTOMER_OTHER_MANAGER = "zhaoc4"  # 归 manager2 名下

MANAGER_ONE = "manager1"  # 名下：wangc1 / lisic2 / zhangc3
MANAGER_TWO = "manager2"  # 名下：zhaoc4 / qianc5
ADVISOR = "advisor1"  # 不绑定客户归属，可用余额可见范围不受限

CUSTOMER_PATH = "/api/customer/funding-account"
INTERNAL_PATH = "/api/internal/customers/{customer_id}/funding-account"

# 与 app.db.seed 的配置值一一对应：种子是可用余额的唯一来源（不做入金）。
SEEDED_AVAILABLE_BALANCES = {
    "wangc1": "2000.00",
    "lisic2": "120000.00",
    "zhangc3": "1000000.00",
    "zhaoc4": "2500000.00",
    "qianc5": "5000000.00",
}
LOW_BALANCE_CEILING = Decimal("10000.00")


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == username))
    assert value is not None
    return int(value)


def _total_assets(engine, username: str) -> Decimal:
    with OrmSession(engine) as session:
        value = session.scalar(
            select(CustomerProfile.total_assets)
            .join(Customer, Customer.id == CustomerProfile.customer_id)
            .where(Customer.username == username)
        )
    assert value is not None
    return Decimal(value)


def _customer_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _internal_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _available_balance(client: TestClient, username: str) -> dict:
    response = client.get(CUSTOMER_PATH, headers=_customer_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]


def _internal_available_balance(client: TestClient, manager: str, customer_id: int):
    return client.get(
        INTERNAL_PATH.format(customer_id=customer_id),
        headers=_internal_headers(client, manager),
    )


def test_a_customer_reads_their_own_available_balance(auth_client: TestClient):
    assert _available_balance(auth_client, CUSTOMER_LOW) == {
        "available_balance": SEEDED_AVAILABLE_BALANCES[CUSTOMER_LOW]
    }


def test_the_customer_identifier_comes_from_the_credential(auth_client: TestClient):
    """请求串里塞别的客户标识不作数：取谁的可用余额只由凭证决定。"""
    engine = _engine()
    forged = _customer_id(engine, CUSTOMER_OTHER_MANAGER)

    response = auth_client.get(
        CUSTOMER_PATH,
        headers=_customer_headers(auth_client, CUSTOMER_LOW),
        params={"customer_id": forged},
    )

    assert response.status_code == 200
    assert response.json()["data"]["available_balance"] == SEEDED_AVAILABLE_BALANCES[
        CUSTOMER_LOW
    ]
    engine.dispose()


def test_a_customer_credential_cannot_reach_another_customers_balance(
    auth_client: TestClient,
):
    engine = _engine()
    forged = _customer_id(engine, CUSTOMER_OTHER_MANAGER)
    assert SEEDED_AVAILABLE_BALANCES[CUSTOMER_LOW] != SEEDED_AVAILABLE_BALANCES[
        CUSTOMER_OTHER_MANAGER
    ]

    # 客户身份域在内部接口上一律无效——那里才是按 customer_id 取数的入口。
    blocked = auth_client.get(
        INTERNAL_PATH.format(customer_id=forged),
        headers=_customer_headers(auth_client, CUSTOMER_LOW),
    )

    assert blocked.status_code == 403
    engine.dispose()


def test_a_manager_sees_only_the_balances_of_their_own_customers(auth_client: TestClient):
    engine = _engine()
    own = _customer_id(engine, CUSTOMER_LOW)
    not_own = _customer_id(engine, CUSTOMER_OTHER_MANAGER)

    mine = _internal_available_balance(auth_client, MANAGER_ONE, own)
    assert mine.status_code == 200
    assert mine.json()["data"]["available_balance"] == SEEDED_AVAILABLE_BALANCES[CUSTOMER_LOW]

    theirs = _internal_available_balance(auth_client, MANAGER_ONE, not_own)
    assert theirs.status_code == 403

    visible_to_their_manager = _internal_available_balance(auth_client, MANAGER_TWO, not_own)
    assert visible_to_their_manager.status_code == 200
    assert visible_to_their_manager.json()["data"]["available_balance"] == (
        SEEDED_AVAILABLE_BALANCES[CUSTOMER_OTHER_MANAGER]
    )
    engine.dispose()


def test_an_advisor_is_not_limited_to_their_own_customers(auth_client: TestClient):
    """理财顾问在本系统里不绑定客户归属（与既有口径一致）。"""
    engine = _engine()
    response = _internal_available_balance(
        auth_client, ADVISOR, _customer_id(engine, CUSTOMER_OTHER_MANAGER)
    )

    assert response.status_code == 200
    engine.dispose()


def test_an_unknown_customer_is_reported_as_missing(auth_client: TestClient):
    response = _internal_available_balance(auth_client, MANAGER_ONE, 999999)

    assert response.status_code == 404
    assert "客户" in response.json()["message"]


def test_every_seeded_customer_has_an_available_balance(auth_client: TestClient):
    for username, expected in SEEDED_AVAILABLE_BALANCES.items():
        assert _available_balance(auth_client, username)["available_balance"] == expected


def test_one_customer_is_deliberately_left_short(auth_client: TestClient):
    """演示「余额不足被拒绝」需要一位余额很少的客户，其余客户要给足。"""
    low = Decimal(SEEDED_AVAILABLE_BALANCES[CUSTOMER_LOW])
    others = [
        Decimal(value)
        for username, value in SEEDED_AVAILABLE_BALANCES.items()
        if username != CUSTOMER_LOW
    ]

    assert low < LOW_BALANCE_CEILING
    assert min(others) >= LOW_BALANCE_CEILING
    assert _available_balance(auth_client, CUSTOMER_LOW)["available_balance"] == format(low, "f")


def test_the_available_balance_precision_matches_the_transaction_amount(
    auth_client: TestClient,
):
    with _engine().connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT TABLE_NAME, NUMERIC_PRECISION, NUMERIC_SCALE
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND DATA_TYPE = 'decimal'
                      AND (
                        (TABLE_NAME = 'fin_funding_account' AND COLUMN_NAME = 'available_balance')
                        OR (TABLE_NAME = 'fin_transaction' AND COLUMN_NAME = 'amount')
                      )
                    """
                )
            )
            .mappings()
            .all()
        )

    precision = {
        row["TABLE_NAME"]: (row["NUMERIC_PRECISION"], row["NUMERIC_SCALE"]) for row in rows
    }
    assert precision["fin_transaction"] == (18, 2)
    assert precision["fin_funding_account"] == precision["fin_transaction"]


def test_a_customer_has_at_most_one_funding_account(auth_client: TestClient):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_LOW)

    with OrmSession(engine) as session:
        session.add(FundingAccount(customer_id=customer_id, available_balance=Decimal("1.00")))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with OrmSession(engine) as session:
        accounts = list(
            session.scalars(select(FundingAccount).where(FundingAccount.customer_id == customer_id))
        )
    assert len(accounts) == 1
    engine.dispose()


def test_the_available_balance_and_the_profile_total_assets_stay_separate(
    auth_client: TestClient,
):
    """可用余额与总资产不共用字段、不互相写：读它不改变总资产，两者也不相等。"""
    engine = _engine()

    with engine.connect() as connection:
        crossing = connection.execute(
            text(
                """
                SELECT TABLE_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND (
                    (TABLE_NAME = 'fin_funding_account' AND COLUMN_NAME = 'total_assets')
                    OR (TABLE_NAME = 'fin_customer_profile' AND COLUMN_NAME = 'available_balance')
                  )
                """
            )
        ).all()
    assert crossing == []

    for username, available_balance in SEEDED_AVAILABLE_BALANCES.items():
        assert Decimal(available_balance) != _total_assets(engine, username)

    before = _total_assets(engine, CUSTOMER_LOW)
    payload = _available_balance(auth_client, CUSTOMER_LOW)
    after = _total_assets(engine, CUSTOMER_LOW)

    assert after == before
    assert Decimal(payload["available_balance"]) != after
    engine.dispose()
