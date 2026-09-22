"""客户侧的充值：资金账户的第一个入口。

充值没有产品，事实落在自己的表 `fin_deposit` 里（ADR-0023）。这条断言链的重点不是
「充值能不能充」，而是三件容易静默出错的接线：

- 充值**不进** `fin_transaction`，但**照常**从同一个入海口进风控——大额入金在受理侧
  不被拒收，而是交给规则引擎申报与预警（ADR-0018 的延续）；
- 充值计入窗口与累计类规则的历史——`_history_events` 漏读 `fin_deposit` 不会报错，
  只会让窗口与累计类规则一起少算入金；
- 受理校验只有两条（金额 > 0、资金账户存在），全部在写库之前，因此每条拒绝路径都
  断言「库里没有任何变化」。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.auth.security import hash_password
from app.db.models import (
    Customer,
    Deposit,
    FundingAccount,
    Holding,
    RiskAlert,
    Transaction,
    Transfer,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

DEPOSIT_PATH = "/api/customer/transactions/deposit"
FUNDING_ACCOUNT_PATH = "/api/customer/funding-account"
TRANSACTIONS_PATH = "/api/customer/transactions"
PURCHASE_PATH = "/api/customer/transactions/purchase"
REDEMPTION_PATH = "/api/customer/transactions/redemption"
TRANSFER_PATH = "/api/customer/transactions/transfer"

# 测试自己造的事实都落在 2026 年之后；种子数据最晚一笔在 2023 年，两者不会混。
TEST_EPOCH = datetime(2026, 1, 1)

CUSTOMER_MODERATE = "zhangc3"  # C3，可用余额 100 万，持有 F000003
CUSTOMER_LOW = "wangc1"  # C1，可用余额 2000

PRODUCT_R3 = "F000003"  # 净值 1.500000，起投 1000，费率 1.20%

PAYEE_NAME = "李四"
PAYEE_ACCOUNT = "6222020200112233445"

PURCHASE = "申购"
REDEEM = "赎回"
TRANSFER = "转账"
DEPOSIT = "充值"

# 充值的呈现形状：没有产品，也没有收款人——产品那几列与对手方那两列都为空。
PRODUCT_FIELDS = ("product_code", "product_name", "shares", "nav", "fee")
PAYEE_FIELDS = ("payee_name", "payee_account")


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == username))
    assert value is not None
    return int(value)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _deposit(
    client: TestClient, username: str = CUSTOMER_MODERATE, *, amount: str = "50000.00"
):
    return client.post(
        DEPOSIT_PATH,
        headers=_headers(client, username),
        json={"amount": amount},
    )


def _purchase(client: TestClient, amount: str = "100000.00"):
    return client.post(
        PURCHASE_PATH,
        headers=_headers(client, CUSTOMER_MODERATE),
        json={"product_code": PRODUCT_R3, "amount": amount},
    )


def _redeem(client: TestClient, shares: str = "16666.6667"):
    return client.post(
        REDEMPTION_PATH,
        headers=_headers(client, CUSTOMER_MODERATE),
        json={"product_code": PRODUCT_R3, "shares": shares},
    )


def _transfer(
    client: TestClient,
    *,
    amount: str = "50000.00",
    payee_name: str = PAYEE_NAME,
    payee_account: str = PAYEE_ACCOUNT,
):
    return client.post(
        TRANSFER_PATH,
        headers=_headers(client, CUSTOMER_MODERATE),
        json={"payee_name": payee_name, "payee_account": payee_account, "amount": amount},
    )


def _transactions(client: TestClient, username: str, **params) -> list[dict]:
    response = client.get(
        TRANSACTIONS_PATH, headers=_headers(client, username), params=params
    )
    assert response.status_code == 200
    return response.json()["data"]["transactions"]


def _available_balance(client: TestClient, username: str) -> str:
    response = client.get(FUNDING_ACCOUNT_PATH, headers=_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]["available_balance"]


def _stored_deposits(engine, *, customer_id: int) -> list[Deposit]:
    with OrmSession(engine) as session:
        return list(
            session.scalars(
                select(Deposit)
                .where(Deposit.customer_id == customer_id)
                .order_by(Deposit.id.asc())
            ).all()
        )


def _stored_transactions(engine, *, customer_id: int) -> list[Transaction]:
    with OrmSession(engine) as session:
        return list(
            session.scalars(
                select(Transaction).where(Transaction.customer_id == customer_id)
            ).all()
        )


def _stored_alerts(engine, *, customer_id: int) -> list[RiskAlert]:
    with OrmSession(engine) as session:
        return list(
            session.scalars(select(RiskAlert).where(RiskAlert.customer_id == customer_id)).all()
        )


def _no_deposit_was_recorded(engine, *, customer_id: int) -> bool:
    """被拒绝的受理不留下任何痕迹：没有充值、没有交易，也就没有预警。"""
    return (
        _stored_deposits(engine, customer_id=customer_id) == []
        and [
            row
            for row in _stored_transactions(engine, customer_id=customer_id)
            if row.create_time >= TEST_EPOCH
        ]
        == []
        and [
            row
            for row in _stored_alerts(engine, customer_id=customer_id)
            if row.create_time >= TEST_EPOCH
        ]
        == []
    )


def _add_customer_without_account(engine) -> str:
    """直接写一位没有资金账户的客户：登录能成功，但充值会被「资金账户不存在」拒绝。

    开户那条路会在同一个事务里建出资金账户（余额 0），因此「有客户没账户」只能绕过
    开户直接落库构造——这也正是受理层要把「没钱」与「没有账户」分开拒绝的原因。
    """
    suffix = uuid4().hex[:10]
    username = f"deposit_noacct_{suffix}"
    with OrmSession(engine) as session:
        session.add(
            Customer(
                username=username,
                password_hash=hash_password(SEEDED_PASSWORD),
                real_name="无账户客户",
                id_number=f"9{str(uuid4().int)[:17]}",
                phone=f"138{str(uuid4().int)[:8]}",
                customer_level="普通",
                status="正常",
                manager_id=None,
                opened_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        session.commit()
    return username


def _delete_customer(engine, customer_id: int) -> None:
    with OrmSession(engine) as session:
        customer = session.get(Customer, customer_id)
        if customer is not None:
            session.delete(customer)
            session.commit()


def _purge(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(RiskAlert).where(RiskAlert.create_time >= TEST_EPOCH))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))
        session.execute(delete(Transfer).where(Transfer.create_time >= TEST_EPOCH))
        session.execute(delete(Deposit).where(Deposit.create_time >= TEST_EPOCH))
        session.commit()


def _snapshot(engine) -> dict:
    """成交会改余额与持仓；跑完要把演示的起点放回去。"""
    with OrmSession(engine) as session:
        balances = {
            row.customer_id: row.available_balance
            for row in session.scalars(select(FundingAccount)).all()
        }
        holdings = [
            {
                "id": row.id,
                "shares": row.shares,
                "cost_amount": row.cost_amount,
                "current_value": row.current_value,
                "profit_loss": row.profit_loss,
                "profit_ratio": row.profit_ratio,
                "status": row.status,
            }
            for row in session.scalars(select(Holding)).all()
        ]
    return {"balances": balances, "holdings": holdings}


def _restore(engine, snapshot: dict) -> None:
    _purge(engine)
    with OrmSession(engine) as session:
        for customer_id, balance in snapshot["balances"].items():
            account = session.scalar(
                select(FundingAccount).where(FundingAccount.customer_id == customer_id)
            )
            if account is not None:
                account.available_balance = balance

        known = {row["id"] for row in snapshot["holdings"]}
        for row in session.scalars(select(Holding)).all():
            if row.id not in known:
                session.delete(row)
        for saved in snapshot["holdings"]:
            holding = session.get(Holding, saved["id"])
            if holding is None:
                continue
            holding.shares = saved["shares"]
            holding.cost_amount = saved["cost_amount"]
            holding.current_value = saved["current_value"]
            holding.profit_loss = saved["profit_loss"]
            holding.profit_ratio = saved["profit_ratio"]
            holding.status = saved["status"]
        session.commit()


@pytest.fixture(autouse=True)
def _restore_seeded_state(auth_client: TestClient) -> Iterator[None]:
    engine = _engine()
    _purge(engine)
    before = _snapshot(engine)
    try:
        yield
    finally:
        _restore(engine, before)
        engine.dispose()


def test_a_deposit_adds_to_the_available_balance(auth_client: TestClient):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    response = _deposit(auth_client, amount="50000.00")
    assert response.status_code == 200
    data = response.json()["data"]

    transaction = data["transaction"]
    assert transaction["transaction_type"] == DEPOSIT
    assert transaction["transaction_no"].startswith("DP")
    assert transaction["amount"] == "50000.00"
    assert transaction["status"] == "已确认"
    # 充值没有产品，也没有收款人：产品那几列与对手方那两列都为空。
    assert all(transaction[field] is None for field in PRODUCT_FIELDS)
    assert all(transaction[field] is None for field in PAYEE_FIELDS)
    # 余额只增，手续费只对申赎成立。
    assert data["available_balance"] == "1050000.00"
    assert _available_balance(auth_client, CUSTOMER_MODERATE) == "1050000.00"

    stored = _stored_deposits(engine, customer_id=customer_id)
    assert len(stored) == 1
    assert stored[0].deposit_no == transaction["transaction_no"]
    assert stored[0].amount == Decimal("50000.00")
    engine.dispose()


def test_a_deposit_never_lands_in_the_transaction_table(auth_client: TestClient):
    """充值不进 `fin_transaction`——它没有产品，不借用那张表（ADR-0023）。"""
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    assert _deposit(auth_client).status_code == 200

    assert _stored_deposits(engine, customer_id=customer_id)
    assert [
        row
        for row in _stored_transactions(engine, customer_id=customer_id)
        if row.create_time >= TEST_EPOCH
    ] == []
    engine.dispose()


def test_a_deposit_reaches_the_rule_engine(auth_client: TestClient):
    """充值与申赎、转账共用同一个入海口：大额入金在受理侧不被拒收，而是过规则引擎。

    六十万的入金命中的是金额类规则，规则引擎不认类型也能判。预警的 `transaction_ids`
    为空是刻意的：那一列存的是 `fin_transaction` 的标识，充值没有那一行，混着填会让
    预警详情按 id 回查到另一笔毫不相干的交易。
    """
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    assert _deposit(auth_client, amount="600000.00").status_code == 200

    # 只数本次充值产生的那一条：种子里的历史交易回放出的预警带着旧时间戳，不是这里的对象。
    alerts = [
        alert
        for alert in _stored_alerts(engine, customer_id=customer_id)
        if alert.create_time >= TEST_EPOCH
    ]
    assert len(alerts) == 1
    alert = alerts[0]
    assert "R001" in alert.rule_codes
    assert alert.transaction_ids == []
    assert "600000" in alert.trigger_detail
    engine.dispose()


def test_a_deposit_counts_toward_the_window_rules(auth_client: TestClient):
    """充值进历史回溯：只读 `fin_transaction` 与 `fin_transfer` 不会报错，只会让窗口类
    规则少算几笔充值。

    先直接写四笔充值（它们只在 `fin_deposit` 里），再用接口发第五笔：它命中的
    「一小时内密集交易」数的是历史，历史里必须有充值，否则这条规则对本笔之外的充值
    等于不存在。

    四笔刻意拉开到分钟级：成交时间是秒精度，同一秒的记录会被四舍五入到下一秒，
    挤在一起测的是精度而不是规则。
    """
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)
    anchor = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    with OrmSession(engine) as session:
        for offset in range(1, 5):
            session.add(
                Deposit(
                    deposit_no=f"DP2026010100000{offset}HISTORY",
                    customer_id=customer_id,
                    amount=Decimal("1000.00"),
                    create_time=anchor - timedelta(minutes=offset * 2),
                )
            )
        session.commit()

    assert _deposit(auth_client, amount="1000.00").status_code == 200

    alerts = _stored_alerts(engine, customer_id=customer_id)
    assert alerts
    assert any({"R007", "R008"} & set(alert.rule_codes) for alert in alerts)
    engine.dispose()


@pytest.mark.parametrize("amount", ["0", "-1000.00"])
def test_a_non_positive_deposit_amount_is_rejected(auth_client: TestClient, amount: str):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    response = _deposit(auth_client, amount=amount)

    assert response.status_code == 400
    assert "金额" in response.json()["message"]
    assert _no_deposit_was_recorded(engine, customer_id=customer_id)
    assert _available_balance(auth_client, CUSTOMER_MODERATE) == "1000000.00"
    engine.dispose()


def test_a_deposit_without_a_funding_account_is_rejected(auth_client: TestClient):
    """「没钱」与「没有账户」是两件事：后者被「资金账户不存在」拒绝，不给任何写库。"""
    engine = _engine()
    username = _add_customer_without_account(engine)
    customer_id = _customer_id(engine, username)
    try:
        response = _deposit(auth_client, username=username, amount="1000.00")

        assert response.status_code == 404
        assert "资金账户不存在" in response.json()["message"]
        assert _no_deposit_was_recorded(engine, customer_id=customer_id)
    finally:
        _delete_customer(engine, customer_id)
    engine.dispose()


def test_a_forged_customer_id_in_the_request_is_ignored(auth_client: TestClient):
    """客户标识由身份推导：请求体里塞别的客户标识不作数，充值只落在凭证那一位客户名下。"""
    engine = _engine()
    forged = _customer_id(engine, CUSTOMER_MODERATE)
    caller = _customer_id(engine, CUSTOMER_LOW)

    response = auth_client.post(
        DEPOSIT_PATH,
        headers=_headers(auth_client, CUSTOMER_LOW),
        json={"amount": "1000.00", "customer_id": forged},
    )
    assert response.status_code == 200

    stored = _stored_deposits(engine, customer_id=caller)
    assert len(stored) == 1
    assert stored[0].customer_id == caller
    engine.dispose()


def test_a_deposit_appears_in_the_customer_flow(auth_client: TestClient):
    """充值必须出现在客户自己的合并流水里：漏读 `fin_deposit` 不会报错，只会整行消失。

    与 ADR-0019 那次是同一个失败形态，所以这里专门盯「流水里有充值」这一行，而不是
    充值能不能充（那是 #01 的断言）。
    """
    engine = _engine()
    deposit_no = _deposit(auth_client, amount="50000.00").json()["data"]["transaction"][
        "transaction_no"
    ]
    assert deposit_no.startswith("DP")

    rows = _transactions(auth_client, CUSTOMER_MODERATE)
    by_number = {row["transaction_no"]: row for row in rows}
    assert deposit_no in by_number

    deposit_row = by_number[deposit_no]
    assert deposit_row["transaction_type"] == DEPOSIT
    # 充值没有产品，也没有收款人：产品那几列与对手方那两列都为空。
    assert all(deposit_row[field] is None for field in PRODUCT_FIELDS)
    assert all(deposit_row[field] is None for field in PAYEE_FIELDS)
    engine.dispose()


def test_the_merged_history_lists_four_kinds_in_reverse_chronological_order(
    auth_client: TestClient,
):
    """一张流水里有四类记录，按成交时间倒序。

    申购、赎回、转账、充值分别落在三张表里，合并读要一张不漏地读回来。漏掉充值这一张
    表不会报错，只会让那一行整行消失——这正是三表扇入要钉住的断言。
    """
    engine = _engine()

    purchase_no = _purchase(auth_client).json()["data"]["transaction"]["transaction_no"]
    redeem_no = _redeem(auth_client).json()["data"]["transaction"]["transaction_no"]
    transfer_no = _transfer(auth_client).json()["data"]["transaction"]["transaction_no"]
    deposit_no = _deposit(auth_client, amount="50000.00").json()["data"]["transaction"][
        "transaction_no"
    ]

    rows = _transactions(auth_client, CUSTOMER_MODERATE)

    assert set(row["transaction_type"] for row in rows) >= {
        PURCHASE,
        REDEEM,
        TRANSFER,
        DEPOSIT,
    }
    traded_at = [row["traded_at"] for row in rows]
    assert traded_at == sorted(traded_at, reverse=True)

    assert {purchase_no, redeem_no, transfer_no, deposit_no} <= {
        row["transaction_no"] for row in rows
    }
    engine.dispose()


def test_an_unknown_transaction_type_filter_returns_nothing(auth_client: TestClient):
    """筛一个三张表都不认的类型，三张表都读不到东西——不做无差别的兜底。"""
    assert _deposit(auth_client).status_code == 200
    assert _transfer(auth_client).status_code == 200

    assert _transactions(auth_client, CUSTOMER_MODERATE, transaction_type="转托管") == []
