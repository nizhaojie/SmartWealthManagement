"""客户侧的转账，以及客户侧流水的两表合并读。

转账没有产品，事实落在自己的表 `fin_transfer` 里（ADR-0019）。这条断言链的重点不是
「转账能不能转」，而是两件容易静默出错的接线：

- 转账**不进** `fin_transaction`，但**必须在**客户侧的合并流水里——`INNER JOIN
  fin_product` 那处查询漏掉转账时不会报错，只会让那一行整行消失；
- 转账照常从同一个入海口进风控（`submit_transaction_event`），产品为空不能成为
  「产品不存在」的理由。

受理校验在写库之前（ADR-0018），因此每条拒绝路径都断言「库里没有任何变化」。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    Customer,
    FundingAccount,
    Holding,
    RiskAlert,
    Transaction,
    Transfer,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

PURCHASE_PATH = "/api/customer/transactions/purchase"
REDEMPTION_PATH = "/api/customer/transactions/redemption"
TRANSFER_PATH = "/api/customer/transactions/transfer"
ASSETS_PATH = "/api/customer/assets"
FUNDING_ACCOUNT_PATH = "/api/customer/funding-account"
TRANSACTIONS_PATH = "/api/customer/assets/transactions"

# 测试自己造的事实都落在 2026 年之后；种子数据最晚一笔在 2023 年，两者不会混。
TEST_EPOCH = datetime(2026, 1, 1)
# 一笔夹在种子与本次演示之间的转账：比它晚的都该排在它前面，比它早的都该排在后面。
MIDWAY_TRANSFER_AT = datetime(2026, 5, 1, 9, 0, 0)

CUSTOMER_MODERATE = "zhangc3"  # C3，可用余额 100 万，持有 F000003
CUSTOMER_LOW = "wangc1"  # C1，可用余额 2000——刻意留的余额不足客户
INTERNAL_USERNAME = "risk1"

PRODUCT_R3 = "F000003"  # 净值 1.500000，起投 1000，费率 1.20%

PAYEE_NAME = "李四"
PAYEE_ACCOUNT = "6222020200112233445"

PURCHASE = "申购"
REDEEM = "赎回"
TRANSFER = "转账"

# 合并后的流水按同一组字段读；产品那几列与收款人那两列是两类记录各自的专属信息。
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


def _internal_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _transfer(
    client: TestClient,
    username: str = CUSTOMER_MODERATE,
    *,
    amount: str = "50000.00",
    payee_name: str = PAYEE_NAME,
    payee_account: str = PAYEE_ACCOUNT,
    **extra,
):
    return client.post(
        TRANSFER_PATH,
        headers=_headers(client, username),
        json={
            "payee_name": payee_name,
            "payee_account": payee_account,
            "amount": amount,
            **extra,
        },
    )


def _purchase(client: TestClient, amount: str = "100000.00"):
    return client.post(
        PURCHASE_PATH,
        headers=_headers(client, CUSTOMER_MODERATE),
        json={"product_code": PRODUCT_R3, "amount": amount},
    )


def _available_balance(client: TestClient, username: str) -> str:
    response = client.get(FUNDING_ACCOUNT_PATH, headers=_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]["available_balance"]


def _transactions(client: TestClient, username: str, **params) -> list[dict]:
    response = client.get(
        TRANSACTIONS_PATH, headers=_headers(client, username), params=params
    )
    assert response.status_code == 200
    return response.json()["data"]["transactions"]


def _assets(client: TestClient, username: str) -> dict:
    response = client.get(ASSETS_PATH, headers=_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]


def _stored_transfers(engine, *, customer_id: int) -> list[Transfer]:
    with OrmSession(engine) as session:
        return list(
            session.scalars(
                select(Transfer)
                .where(Transfer.customer_id == customer_id)
                .order_by(Transfer.id.asc())
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


def _no_trade_was_recorded(engine, *, customer_id: int) -> bool:
    """被拒绝的受理不留下任何痕迹：没有转账、没有交易，也就没有预警。"""
    return (
        _stored_transfers(engine, customer_id=customer_id) == []
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


def _add_transfer_row(engine, *, customer_id: int, transfer_no: str, payee_name: str) -> None:
    """直接写一行转账。读模型不需要经过受理，这里也刻意绕开风控。"""
    with OrmSession(engine) as session:
        session.add(
            Transfer(
                transfer_no=transfer_no,
                customer_id=customer_id,
                amount=Decimal("1000.00"),
                payee_name=payee_name,
                payee_account="6222020200998877665",
                create_time=MIDWAY_TRANSFER_AT,
            )
        )
        session.commit()


def _purge(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(RiskAlert).where(RiskAlert.create_time >= TEST_EPOCH))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))
        session.execute(delete(Transfer).where(Transfer.create_time >= TEST_EPOCH))
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


def test_a_transfer_pays_the_payee_and_deducts_the_balance(auth_client: TestClient):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    response = _transfer(auth_client, amount="50000.00")
    assert response.status_code == 200
    data = response.json()["data"]

    transaction = data["transaction"]
    assert transaction["transaction_type"] == TRANSFER
    assert transaction["amount"] == "50000.00"
    assert transaction["payee_name"] == PAYEE_NAME
    assert transaction["payee_account"] == PAYEE_ACCOUNT
    assert transaction["status"] == "已确认"
    # 转账没有产品：产品那几列为空，这是它与申赎行唯一的形状差别。
    assert transaction["product_code"] is None
    assert transaction["product_name"] is None
    # 全额扣减，手续费只对申赎成立。
    assert data["available_balance"] == "950000.00"
    assert _available_balance(auth_client, CUSTOMER_MODERATE) == "950000.00"

    stored = _stored_transfers(engine, customer_id=customer_id)
    assert len(stored) == 1
    assert stored[0].transfer_no == transaction["transaction_no"]
    assert stored[0].amount == Decimal("50000.00")
    engine.dispose()


def test_a_transfer_leaves_the_holdings_alone(auth_client: TestClient):
    """转账只动可用余额：持仓、市值与客户在流水里看到的产品都不受影响。"""
    engine = _engine()
    before = _assets(auth_client, CUSTOMER_MODERATE)

    assert _transfer(auth_client).status_code == 200

    after = _assets(auth_client, CUSTOMER_MODERATE)
    assert after["holdings"] == before["holdings"]
    assert after["total_market_value"] == before["total_market_value"]
    engine.dispose()


def test_a_transfer_never_lands_in_the_transaction_table(auth_client: TestClient):
    """转账不进 `fin_transaction`——它没有产品，不借用那张表（ADR-0019）。"""
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    assert _transfer(auth_client).status_code == 200

    assert _stored_transfers(engine, customer_id=customer_id)
    assert [
        row
        for row in _stored_transactions(engine, customer_id=customer_id)
        if row.create_time >= TEST_EPOCH
    ] == []
    engine.dispose()


def test_a_transfer_reaches_the_rule_engine(auth_client: TestClient):
    """转账与申赎共用同一个入海口：产品为空不能成为「产品不存在」的理由。

    五十万的大额转账命中的是金额类规则，规则引擎不认类型也能判。预警的
    `transaction_ids` 为空是刻意的：那一列存的是 `fin_transaction` 的标识，转账没有
    那一行，混着填会让预警详情按 id 回查到另一笔毫不相干的交易。
    """
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    assert _transfer(auth_client, amount="500000.00").status_code == 200

    # 只数本次转账产生的那一条：种子里那笔历史申购现在也会回放出一条预警（issue 04），
    # 它带着 2020 年的时间戳，不是这里的对象。
    alerts = [
        alert
        for alert in _stored_alerts(engine, customer_id=customer_id)
        if alert.create_time >= TEST_EPOCH
    ]
    assert len(alerts) == 1
    alert = alerts[0]
    assert "R001" in alert.rule_codes
    assert alert.transaction_ids == []
    assert "500000" in alert.trigger_detail


def test_a_transfer_counts_toward_the_window_rules(auth_client: TestClient):
    """转账进历史回溯：只读 `fin_transaction` 不会报错，只会让窗口类规则少算几笔。

    先直接写四笔转账（它们只在 `fin_transfer` 里），再用接口发第五笔：它命中的
    「一小时内密集交易」数的是历史，历史里必须有转账，否则这条规则对本笔之外的转账
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
                Transfer(
                    transfer_no=f"TR2026010100000{offset}HISTORY",
                    customer_id=customer_id,
                    amount=Decimal("1000.00"),
                    payee_name="王五",
                    payee_account="6222020200998877665",
                    create_time=anchor - timedelta(minutes=offset * 2),
                )
            )
        session.commit()

    assert _transfer(auth_client, amount="1000.00").status_code == 200

    alerts = _stored_alerts(engine, customer_id=customer_id)
    assert alerts
    assert any({"R007", "R008"} & set(alert.rule_codes) for alert in alerts)


def test_a_forged_customer_id_in_the_request_is_ignored(auth_client: TestClient):
    """客户标识由身份推导：请求体里塞别的客户标识不作数。"""
    engine = _engine()
    forged = _customer_id(engine, CUSTOMER_MODERATE)
    caller = _customer_id(engine, CUSTOMER_LOW)

    response = _transfer(auth_client, CUSTOMER_LOW, amount="1000.00", customer_id=forged)
    assert response.status_code == 200

    stored = _stored_transfers(engine, customer_id=caller)
    assert len(stored) == 1
    assert stored[0].customer_id == caller
    engine.dispose()


def test_placing_a_transfer_requires_a_customer_identity(auth_client: TestClient):
    body = {"payee_name": PAYEE_NAME, "payee_account": PAYEE_ACCOUNT, "amount": "1000.00"}

    assert auth_client.post(TRANSFER_PATH, json=body).status_code == 401
    # 内部身份域签发的凭证在客户侧接口上一律无效。
    assert (
        auth_client.post(
            TRANSFER_PATH, headers=_internal_headers(auth_client, INTERNAL_USERNAME), json=body
        ).status_code
        == 403
    )


def test_a_transfer_beyond_the_available_balance_is_rejected(auth_client: TestClient):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_LOW)

    response = _transfer(auth_client, CUSTOMER_LOW, amount="5000.00")

    assert response.status_code == 400
    message = response.json()["message"]
    assert "余额不足" in message
    # 要给出还差多少，客户才知道补多少
    assert "3000.00" in message
    assert _no_trade_was_recorded(engine, customer_id=customer_id)
    assert _available_balance(auth_client, CUSTOMER_LOW) == "2000.00"
    engine.dispose()


def test_a_non_positive_transfer_amount_is_rejected(auth_client: TestClient):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    response = _transfer(auth_client, amount="0")

    assert response.status_code == 400
    assert "金额" in response.json()["message"]
    assert _no_trade_was_recorded(engine, customer_id=customer_id)
    assert _available_balance(auth_client, CUSTOMER_MODERATE) == "1000000.00"
    engine.dispose()


@pytest.mark.parametrize(
    ("payee_name", "payee_account", "expected"),
    [
        ("", PAYEE_ACCOUNT, "收款人姓名"),
        ("   ", PAYEE_ACCOUNT, "收款人姓名"),
        (PAYEE_NAME, "", "收款人账号"),
        (PAYEE_NAME, "   ", "收款人账号"),
    ],
)
def test_a_transfer_without_a_payee_is_rejected(
    auth_client: TestClient, payee_name: str, payee_account: str, expected: str
):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    response = _transfer(
        auth_client, payee_name=payee_name, payee_account=payee_account, amount="1000.00"
    )

    assert response.status_code == 400
    assert expected in response.json()["message"]
    assert _no_trade_was_recorded(engine, customer_id=customer_id)
    engine.dispose()


def test_the_merged_history_lists_purchase_redemption_and_transfer_together(
    auth_client: TestClient,
):
    """一张流水里有三类记录，按成交时间倒序。

    这正是 `INNER JOIN fin_product` 那个漏点的断言：漏掉转账不会报错，只会让那一行
    整行消失，所以这里专门盯「流水里有转账」。

    夹在中间的那笔转账给出了排序的判据——比它晚的三笔操作全在它前面，种子里的历史
    交易全在它后面，也就是说两张表真的被合成了一张按时间排序的列表。
    """
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    purchase_no = _purchase(auth_client).json()["data"]["transaction"]["transaction_no"]
    redeem_no = auth_client.post(
        REDEMPTION_PATH,
        headers=_headers(auth_client, CUSTOMER_MODERATE),
        json={"product_code": PRODUCT_R3, "shares": "16666.6667"},
    ).json()["data"]["transaction"]["transaction_no"]
    transfer_no = _transfer(auth_client, amount="50000.00").json()["data"]["transaction"][
        "transaction_no"
    ]

    midway_no = "TR20260501090000MIDWAY"
    _add_transfer_row(
        engine, customer_id=customer_id, transfer_no=midway_no, payee_name="王五"
    )

    rows = _transactions(auth_client, CUSTOMER_MODERATE)

    assert set(row["transaction_type"] for row in rows) >= {PURCHASE, REDEEM, TRANSFER}
    traded_at = [row["traded_at"] for row in rows]
    assert traded_at == sorted(traded_at, reverse=True)

    numbers = [row["transaction_no"] for row in rows]
    position = numbers.index(midway_no)
    # 这三笔 2026-09 的操作比它晚，因此都在它前面（它们彼此的先后由成交秒决定，
    # 所以只断言集合）。
    assert set(numbers[:position]) == {purchase_no, redeem_no, transfer_no}
    assert all(row["traded_at"] < MIDWAY_TRANSFER_AT.isoformat() for row in rows[position + 1 :])

    by_number = {row["transaction_no"]: row for row in rows}

    # 转账行：没有产品，有收款人。
    transfer_row = by_number[transfer_no]
    assert all(transfer_row[field] is None for field in PRODUCT_FIELDS)
    assert transfer_row["payee_name"] == PAYEE_NAME
    assert transfer_row["payee_account"] == PAYEE_ACCOUNT
    assert by_number[midway_no]["payee_name"] == "王五"

    # 申赎行：有产品，没有收款人。
    purchase_row = by_number[purchase_no]
    assert purchase_row["product_code"] == PRODUCT_R3
    assert purchase_row["product_name"]
    assert all(purchase_row[field] is None for field in PAYEE_FIELDS)
    assert all(by_number[redeem_no][field] is None for field in PAYEE_FIELDS)
    engine.dispose()


def test_the_history_can_be_filtered_to_one_kind(auth_client: TestClient):
    assert _purchase(auth_client).status_code == 200
    transfer_no = _transfer(auth_client).json()["data"]["transaction"]["transaction_no"]

    only_transfers = _transactions(auth_client, CUSTOMER_MODERATE, transaction_type=TRANSFER)
    assert [row["transaction_type"] for row in only_transfers] == [TRANSFER]

    # 筛申赎时读的是 `fin_transaction` 那张表：种子的历史申赎也在里面，但转账不在。
    only_purchases = _transactions(auth_client, CUSTOMER_MODERATE, transaction_type=PURCHASE)
    assert only_purchases
    assert {row["transaction_type"] for row in only_purchases} == {PURCHASE}
    assert transfer_no not in {row["transaction_no"] for row in only_purchases}


def test_the_date_range_caps_both_tables_with_one_rule(auth_client: TestClient):
    """时间范围对两张表用同一个口径：漏在一边，客户就会少看一笔。"""
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)

    midway_no = "TR20260501090000MIDWAY"
    _add_transfer_row(
        engine, customer_id=customer_id, transfer_no=midway_no, payee_name="王五"
    )
    assert _transfer(auth_client).status_code == 200

    within = _transactions(
        auth_client, CUSTOMER_MODERATE, start_date="2026-05-01", end_date="2026-05-31"
    )
    assert [row["transaction_no"] for row in within] == [midway_no]

    until = _transactions(auth_client, CUSTOMER_MODERATE, end_date="2026-04-30")
    assert midway_no not in {row["transaction_no"] for row in until}
    engine.dispose()


def test_an_unknown_transaction_type_filter_returns_nothing(auth_client: TestClient):
    """筛一个规则引擎也不认的类型，两张表都读不到东西——不做无差别的兜底。"""
    assert _transfer(auth_client).status_code == 200

    assert _transactions(auth_client, CUSTOMER_MODERATE, transaction_type="转托管") == []
