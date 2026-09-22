"""客户侧的申购与赎回：受理校验、成交口径，以及成交后的持仓与余额自洽。

客户第一次自己动钱。校验集由 spec Q11 定：产品在售、提交过风险测评、适当性不越级、
不低于起投金额、余额足够、赎回不超过持仓份额。校验在受理服务里、落库之前（ADR-0018），
因此这里断言的核心是「被拒绝时库里没有任何变化」。

成交口径固定为 申购 `份额 = 金额 / 净值`、赎回 `成交金额 = 份额 × 净值`，手续费两边都按
费率单列一行。持仓的当前市值仍是独立维护的字段，不写成 `份额 × 净值` 的推导值。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    Customer,
    CustomerProfile,
    FundingAccount,
    Holding,
    Product,
    ProfileTag,
    RiskAlert,
    RiskAssessment,
    RiskFocus,
    Transaction,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

PURCHASE_PATH = "/api/customer/transactions/purchase"
REDEMPTION_PATH = "/api/customer/transactions/redemption"
FUNDING_ACCOUNT_PATH = "/api/customer/funding-account"
ASSETS_PATH = "/api/customer/assets"
TRANSACTIONS_PATH = "/api/customer/transactions"

# 测试自己造的成交都落在 2026 年之后；种子数据最晚一笔在 2023 年，两者不会混。
TEST_EPOCH = datetime(2026, 1, 1)

CUSTOMER_LOW = "wangc1"  # C1，可用余额 2000；也是清仓一条持仓用的那位
CUSTOMER_MODERATE = "zhangc3"  # C3，可用余额 100 万
CUSTOMER_PRIVATE = "qianc5"  # C5
UNASSESSED_USERNAME = "nograde1"  # 从未提交过风险测评
INTERNAL_USERNAME = "risk1"

PRODUCT_R1 = "F000001"  # 净值 1.000000，起投 1000，费率 0.25%
PRODUCT_R3 = "F000003"  # 净值 1.500000，起投 1000，费率 1.20%
PRODUCT_R4 = "F000004"  # 越级用：wangc1 是 C1，只能持有 R1
PRODUCT_R5 = "F000005"  # 起投 5000
PRODUCT_OFF_SALE = "F900001"

HELD_STATUS = "持有中"


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


def _trade(
    client: TestClient, username: str, path: str, body: dict
):
    return client.post(path, headers=_headers(client, username), json=body)


def _questionnaire_answers(target: str) -> dict[str, str]:
    """全选第一项 = 16 分（C1）；全选最后一项 = 64 分（C5）。"""
    from app.risk_assessment.questionnaire import QUESTIONS

    answers: dict[str, str] = {}
    for question in QUESTIONS:
        index = 0 if target == "C1" else -1
        answers[question.id] = question.options[index].id
    return answers


def _take_the_assessment(client: TestClient, username: str, target: str) -> None:
    response = client.post(
        "/api/customer/risk-assessment",
        headers=_headers(client, username),
        json={"answers": _questionnaire_answers(target)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["risk_level"] == target


def _available_balance(client: TestClient, username: str) -> str:
    response = client.get(FUNDING_ACCOUNT_PATH, headers=_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]["available_balance"]


def _assets(client: TestClient, username: str) -> dict:
    response = client.get(ASSETS_PATH, headers=_headers(client, username))
    assert response.status_code == 200
    return response.json()["data"]


def _holding(client: TestClient, username: str, product_code: str) -> dict | None:
    for row in _assets(client, username)["holdings"]:
        if row["product_code"] == product_code:
            return row
    return None


def _stored_transaction(engine, transaction_no: str) -> Transaction:
    with OrmSession(engine) as session:
        row = session.scalar(
            select(Transaction).where(Transaction.transaction_no == transaction_no)
        )
    assert row is not None
    return row


def _stored_transactions(engine) -> list[Transaction]:
    with OrmSession(engine) as session:
        return list(session.scalars(select(Transaction)).all())


def _stored_holding(engine, *, customer_id: int, product_code: str) -> Holding:
    with OrmSession(engine) as session:
        row = session.execute(
            select(Holding)
            .join(Product, Product.id == Holding.product_id)
            .where(Holding.customer_id == customer_id, Product.product_code == product_code)
        ).scalar_one_or_none()
    assert row is not None
    return row


def _no_trade_was_recorded(engine) -> bool:
    """被拒绝的受理不留下任何痕迹：没有交易，也就没有预警。"""
    with OrmSession(engine) as session:
        transactions = session.scalar(
            select(Transaction.id).where(Transaction.create_time >= TEST_EPOCH)
        )
        alerts = session.scalar(select(RiskAlert.id).where(RiskAlert.create_time >= TEST_EPOCH))
    return transactions is None and alerts is None


def _snapshot(engine) -> dict:
    """成交会同时改余额与持仓；每个用例跑完都要把它们放回去，否则后面的用例看到的是别人
    的账。种子的余额与持仓是演示的起点，测试不该把它们永久改掉。"""
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
    with OrmSession(engine) as session:
        # 测试造出来的交易与预警一律不留：它们带着 2026 年之后的时间戳。
        session.execute(delete(RiskAlert).where(RiskAlert.create_time >= TEST_EPOCH))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))

        known = {row["id"] for row in snapshot["holdings"]}
        for row in session.scalars(select(Holding)).all():
            if row.id not in known:
                session.delete(row)
        for row in snapshot["holdings"]:
            holding = session.get(Holding, row["id"])
            if holding is None:
                continue
            holding.shares = row["shares"]
            holding.cost_amount = row["cost_amount"]
            holding.current_value = row["current_value"]
            holding.profit_loss = row["profit_loss"]
            holding.profit_ratio = row["profit_ratio"]
            holding.status = row["status"]

        for customer_id, balance in snapshot["balances"].items():
            account = session.scalar(
                select(FundingAccount).where(FundingAccount.customer_id == customer_id)
            )
            if account is not None:
                account.available_balance = balance
        session.commit()


@pytest.fixture(autouse=True)
def _restore_seeded_state(auth_client: TestClient) -> Iterator[None]:
    engine = _engine()
    before = _snapshot(engine)
    try:
        yield
    finally:
        _restore(engine, before)
        engine.dispose()


def _purge_customer(customer_id: int) -> None:
    """删掉这位客户名下的一切，顺序即外键依赖顺序。

    成交留下的持仓与流水、风评写回的画像与标签都要一起走：不删干净，下一轮 seed 的
    「5 位客户 / 5 份风评」会数出多余的行，而残留的持仓还会挡住客户那一行的删除。
    """
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            session.execute(delete(RiskAlert).where(RiskAlert.customer_id == customer_id))
            # 预警广播的订阅方会为这位客户写下风险关注（`biz_risk_focus`），它指着客户。
            session.execute(delete(RiskFocus).where(RiskFocus.customer_id == customer_id))
            session.execute(delete(Transaction).where(Transaction.customer_id == customer_id))
            session.execute(delete(Holding).where(Holding.customer_id == customer_id))
            session.execute(
                delete(RiskAssessment).where(RiskAssessment.customer_id == customer_id)
            )
            session.execute(delete(ProfileTag).where(ProfileTag.customer_id == customer_id))
            session.execute(
                delete(CustomerProfile).where(CustomerProfile.customer_id == customer_id)
            )
            session.execute(
                delete(FundingAccount).where(FundingAccount.customer_id == customer_id)
            )
            session.execute(delete(Customer).where(Customer.id == customer_id))
            session.commit()
    finally:
        engine.dispose()


@pytest.fixture
def unassessed_customer(auth_client: TestClient) -> Iterator[str]:
    """一位从未提交过风险测评的客户。

    开户时画像上写下的等级是占位，不是测评结论，因此这位客户在这里没有
    `fin_risk_assessment` 记录——判定「做没做过风评」的唯一依据就是有没有这条记录。

    画像本身必须有（与 `app.customer_onboarding.open_account` 一致）：风评提交时结论要
    写回画像，缺那一行的话，客户按提示做完风评只会再撞上一个 404——引导的出口自己堵住了。

    测试库跨运行持久，而账号是固定的：先把上一轮中断留下的同名客户清掉，再建。
    """
    engine = _engine()
    with OrmSession(engine) as session:
        leftover = session.scalar(
            select(Customer.id).where(Customer.username == UNASSESSED_USERNAME)
        )
    engine.dispose()
    if leftover is not None:
        _purge_customer(int(leftover))

    engine = _engine()
    with OrmSession(engine) as session:
        template = session.scalar(select(Customer).where(Customer.username == CUSTOMER_LOW))
        assert template is not None
        customer = Customer(
            username=UNASSESSED_USERNAME,
            password_hash=template.password_hash,
            real_name="未测评客户",
            id_number="110101199001010011",
            phone="13800138999",
            customer_level="普通",
            status="正常",
            manager_id=template.manager_id,
            opened_at=datetime(2024, 1, 1, 9, 0, 0),
        )
        session.add(customer)
        session.flush()
        customer_id = customer.id
        session.add(
            FundingAccount(customer_id=customer_id, available_balance=Decimal("500000.00"))
        )
        session.add(
            CustomerProfile(
                customer_id=customer_id,
                risk_level="C1",
                risk_score=0,
                investment_experience="0-1年",
                annual_income_range="10-30万",
                total_assets=Decimal("300000.00"),
                target_allocation={},
                product_preference={},
                confidence_score=Decimal("0.30"),
                computed_at=datetime(2024, 1, 1, 9, 0, 0),
            )
        )
        session.commit()
    engine.dispose()
    try:
        yield UNASSESSED_USERNAME
    finally:
        _purge_customer(customer_id)


def test_a_purchase_records_shares_cost_and_balance_together(auth_client: TestClient):
    """一笔申购成交后，交易、持仓、余额三方自洽。"""
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_MODERATE,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R3, "amount": "100000.00"},
    )
    assert response.status_code == 200
    data = response.json()["data"]

    # 份额 = 金额 / 净值 = 100000 / 1.5；手续费 = 100000 × 1.20%
    assert data["transaction"]["transaction_type"] == "申购"
    assert data["transaction"]["amount"] == "100000.00"
    assert data["transaction"]["shares"] == "66666.6667"
    assert data["transaction"]["nav"] == "1.500000"
    assert data["transaction"]["fee"] == "1200.00"
    assert data["transaction"]["status"] == "已确认"
    # 余额扣减 = 金额 + 手续费
    assert data["available_balance"] == "898800.00"
    assert _available_balance(auth_client, CUSTOMER_MODERATE) == "898800.00"

    holding = _holding(auth_client, CUSTOMER_MODERATE, PRODUCT_R3)
    assert holding is not None
    # 原有 66666.6667 份、成本 100000；买进来同样的份额与金额
    assert holding["shares"] == "133333.3334"
    assert holding["cost_amount"] == "200000.00"
    # 市值是独立维护的字段：买入按投入金额增加，不写成 份额 × 净值（两者此时并不相等）
    assert holding["market_value"] == "208000.00"
    assert Decimal(holding["market_value"]) != (
        Decimal(holding["shares"]) * Decimal(data["transaction"]["nav"])
    ).quantize(Decimal("0.01"))
    assert holding["profit_loss"] == "8000.00"
    engine.dispose()


def test_a_customer_initiated_trade_has_no_operator(auth_client: TestClient):
    """交易的来源不加字段（Q22）：客户自助发起的交易没有经办员工。

    这条是隐式约定——`fin_transaction.operator_id` 本来就为空，语义也对得上。没有机制
    拦着别人给它填一个值，这条断言就是它唯一的护栏。
    """
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_MODERATE,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R3, "amount": "100000.00"},
    )
    assert response.status_code == 200
    transaction_no = response.json()["data"]["transaction"]["transaction_no"]

    stored = _stored_transaction(engine, transaction_no)
    assert stored.operator_id is None
    assert stored.customer_id == _customer_id(engine, CUSTOMER_MODERATE)
    engine.dispose()


def test_a_customer_trade_reaches_the_rule_engine(auth_client: TestClient):
    """客户的资金操作是风控的真实输入：成交后过一遍规则引擎，命中即产生预警。"""
    engine = _engine()
    before = len(_stored_transactions(engine))

    response = _trade(
        auth_client,
        CUSTOMER_MODERATE,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R3, "amount": "100000.00"},
    )
    assert response.status_code == 200

    stored = _stored_transaction(
        engine, response.json()["data"]["transaction"]["transaction_no"]
    )
    with OrmSession(engine) as session:
        alerts = list(
            session.scalars(
                select(RiskAlert).where(RiskAlert.customer_id == stored.customer_id)
            ).all()
        )

    assert len(_stored_transactions(engine)) == before + 1
    assert alerts
    assert any(stored.id in (alert.transaction_ids or []) for alert in alerts)
    engine.dispose()


def test_a_customer_credential_cannot_trade_on_behalf_of_another(auth_client: TestClient):
    """客户标识由身份推导：请求体里塞别的客户标识不作数。"""
    engine = _engine()
    forged = _customer_id(engine, CUSTOMER_MODERATE)

    response = _trade(
        auth_client,
        CUSTOMER_LOW,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R1, "amount": "1000.00", "customer_id": forged},
    )
    assert response.status_code == 200
    stored = _stored_transaction(
        engine, response.json()["data"]["transaction"]["transaction_no"]
    )

    assert stored.customer_id == _customer_id(engine, CUSTOMER_LOW)
    engine.dispose()


def test_placing_a_trade_requires_a_customer_identity(auth_client: TestClient):
    body = {"product_code": PRODUCT_R1, "amount": "1000.00"}

    assert auth_client.post(PURCHASE_PATH, json=body).status_code == 401
    # 内部身份域签发的凭证在客户侧接口上一律无效。
    assert (
        auth_client.post(
            PURCHASE_PATH, headers=_internal_headers(auth_client, INTERNAL_USERNAME), json=body
        ).status_code
        == 403
    )
    assert (
        auth_client.post(
            REDEMPTION_PATH, json={"product_code": PRODUCT_R1, "shares": "1.0000"}
        ).status_code
        == 401
    )


def test_an_overgrade_purchase_is_rejected(auth_client: TestClient):
    """客户直接挑产品时没有候选池兜底，适当性必须在受理处再守一次。"""
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_LOW,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R4, "amount": "1000.00"},
    )

    assert response.status_code == 403
    assert "风险等级" in response.json()["message"]
    assert _no_trade_was_recorded(engine)
    assert _available_balance(auth_client, CUSTOMER_LOW) == "2000.00"
    engine.dispose()


def test_a_purchase_beyond_the_available_balance_is_rejected(auth_client: TestClient):
    engine = _engine()
    # 5000 + 手续费 12.50 = 5012.50，余额只有 2000.00
    response = _trade(
        auth_client,
        CUSTOMER_LOW,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R1, "amount": "5000.00"},
    )

    assert response.status_code == 400
    message = response.json()["message"]
    assert "余额不足" in message
    # 要给出还差多少，客户才知道补多少
    assert "3012.50" in message
    assert _no_trade_was_recorded(engine)
    assert _available_balance(auth_client, CUSTOMER_LOW) == "2000.00"
    engine.dispose()


def test_a_customer_who_never_took_the_assessment_is_asked_to_take_one(
    auth_client: TestClient, unassessed_customer: str
):
    """文案是「请先完成风险测评」，不是「风险等级不足」——开户时写下的等级是占位，不是结论。"""
    engine = _engine()
    response = _trade(
        auth_client,
        unassessed_customer,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R1, "amount": "1000.00"},
    )

    assert response.status_code == 403
    message = response.json()["message"]
    assert message == "请先完成风险测评"
    assert "风险等级" not in message
    assert _no_trade_was_recorded(engine)
    engine.dispose()


def test_the_same_customer_can_trade_after_taking_the_assessment(
    auth_client: TestClient, unassessed_customer: str
):
    """未测评被拒绝 → 做完风评 → 同一笔交易当场就能成。

    拒绝只是这条引导的一半：客户按提示做完风评之后，那一笔必须真的走得通。留一个
    「过不去的门槛」等于让客户反复重试同一件注定失败的事，而且他看不出是系统的问题
    还是自己的问题——失败形态与「稍后再试」一模一样。
    """
    engine = _engine()
    body = {"product_code": PRODUCT_R1, "amount": "1000.00"}

    refused = _trade(auth_client, unassessed_customer, PURCHASE_PATH, body)
    assert refused.status_code == 403
    assert refused.json()["message"] == "请先完成风险测评"

    _take_the_assessment(auth_client, unassessed_customer, "C1")

    accepted = _trade(auth_client, unassessed_customer, PURCHASE_PATH, body)
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()["data"]
    assert data["transaction"]["transaction_type"] == "申购"
    # 校验过了就当场成交：余额扣减 = 1000 + 手续费 2.50。
    assert data["available_balance"] == "498997.50"
    engine.dispose()


def test_a_purchase_below_the_minimum_amount_is_rejected(auth_client: TestClient):
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_PRIVATE,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R5, "amount": "1000.00"},
    )

    assert response.status_code == 400
    assert "起投金额" in response.json()["message"]
    assert _no_trade_was_recorded(engine)
    engine.dispose()


def test_a_product_that_is_not_on_sale_is_rejected(auth_client: TestClient):
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_PRIVATE,
        PURCHASE_PATH,
        {"product_code": PRODUCT_OFF_SALE, "amount": "10000.00"},
    )

    assert response.status_code == 400
    assert "不在售" in response.json()["message"]
    assert _no_trade_was_recorded(engine)
    engine.dispose()


def test_a_redemption_returns_money_and_reduces_the_holding(auth_client: TestClient):
    engine = _engine()
    # 种子持仓：66666.6667 份、成本 100000、市值 108000
    response = _trade(
        auth_client,
        CUSTOMER_MODERATE,
        REDEMPTION_PATH,
        {"product_code": PRODUCT_R3, "shares": "16666.6667"},
    )
    assert response.status_code == 200
    data = response.json()["data"]

    # 成交金额 = 份额 × 净值 = 25000.00；手续费 = 25000 × 1.20% = 300.00；到账 24700.00
    assert data["transaction"]["transaction_type"] == "赎回"
    assert data["transaction"]["shares"] == "16666.6667"
    assert data["transaction"]["nav"] == "1.500000"
    assert data["transaction"]["fee"] == "300.00"
    assert data["transaction"]["amount"] == "25000.00"
    assert data["available_balance"] == "1024700.00"

    holding = _holding(auth_client, CUSTOMER_MODERATE, PRODUCT_R3)
    assert holding is not None
    # 赎回四分之一份额，成本与市值各减持四分之一，盈亏比例不变
    assert holding["shares"] == "50000.0000"
    assert holding["cost_amount"] == "75000.00"
    assert holding["market_value"] == "81000.00"
    assert holding["profit_loss"] == "6000.00"
    assert holding["profit_ratio"] == "8.0000"
    engine.dispose()


def test_a_redemption_beyond_the_holding_is_rejected(auth_client: TestClient):
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_MODERATE,
        REDEMPTION_PATH,
        {"product_code": PRODUCT_R3, "shares": "999999.0000"},
    )

    assert response.status_code == 400
    assert "超过" in response.json()["message"]
    assert _no_trade_was_recorded(engine)
    assert _available_balance(auth_client, CUSTOMER_MODERATE) == "1000000.00"
    engine.dispose()


def test_redeeming_something_that_is_not_held_is_rejected(auth_client: TestClient):
    """qianc5 是 C5，看得到 R3 产品，但没有这只产品的持仓。"""
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_PRIVATE,
        REDEMPTION_PATH,
        {"product_code": PRODUCT_R3, "shares": "1.0000"},
    )

    assert response.status_code == 400
    assert "持仓" in response.json()["message"]
    assert _no_trade_was_recorded(engine)
    engine.dispose()


def test_a_full_redemption_takes_the_holding_off_the_asset_page(auth_client: TestClient):
    """份额归零后状态不再是「持有中」，资产页与穿透都不再看到它。"""
    engine = _engine()
    response = _trade(
        auth_client,
        CUSTOMER_LOW,
        REDEMPTION_PATH,
        {"product_code": PRODUCT_R1, "shares": "20000.0000"},
    )
    assert response.status_code == 200
    data = response.json()["data"]

    # 成交金额 = 20000 × 1.000000 = 20000.00；手续费 = 20000 × 0.25% = 50.00；到账 19950.00
    assert data["transaction"]["amount"] == "20000.00"
    assert data["transaction"]["fee"] == "50.00"
    assert data["available_balance"] == "21950.00"

    assets = _assets(auth_client, CUSTOMER_LOW)
    assert assets["holdings"] == []
    assert assets["holding_count"] == 0
    assert assets["total_market_value"] == "0.00"

    stored = _stored_holding(
        engine, customer_id=_customer_id(engine, CUSTOMER_LOW), product_code=PRODUCT_R1
    )
    assert stored.status != HELD_STATUS
    assert stored.shares == 0
    engine.dispose()


def test_a_redeemed_holding_can_be_bought_back(auth_client: TestClient):
    """清仓过的持仓再买回来：份额、成本与市值从零重新起算，状态回到「持有中」。"""
    engine = _engine()
    first = _trade(
        auth_client,
        CUSTOMER_LOW,
        REDEMPTION_PATH,
        {"product_code": PRODUCT_R1, "shares": "20000.0000"},
    )
    assert first.status_code == 200

    second = _trade(
        auth_client,
        CUSTOMER_LOW,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R1, "amount": "1000.00"},
    )
    assert second.status_code == 200

    holding = _holding(auth_client, CUSTOMER_LOW, PRODUCT_R1)
    assert holding is not None
    # 1000 / 1.000000 份，成本与市值都是刚投进去的 1000.00
    assert holding["shares"] == "1000.0000"
    assert holding["cost_amount"] == "1000.00"
    assert holding["market_value"] == "1000.00"
    assert holding["profit_loss"] == "0.00"
    engine.dispose()


def test_the_trade_shows_up_in_the_customer_transaction_history(auth_client: TestClient):
    response = _trade(
        auth_client,
        CUSTOMER_MODERATE,
        PURCHASE_PATH,
        {"product_code": PRODUCT_R3, "amount": "100000.00"},
    )
    assert response.status_code == 200
    transaction_no = response.json()["data"]["transaction"]["transaction_no"]

    listed = auth_client.get(
        TRANSACTIONS_PATH, headers=_headers(auth_client, CUSTOMER_MODERATE)
    )
    assert listed.status_code == 200
    rows = listed.json()["data"]["transactions"]
    assert rows
    assert rows[0]["transaction_no"] == transaction_no
    assert rows[0]["transaction_type"] == "申购"
    assert rows[0]["product_name"] == "天璇混合基金"


def test_a_non_positive_amount_or_share_is_rejected(auth_client: TestClient):
    engine = _engine()

    assert (
        _trade(
            auth_client,
            CUSTOMER_MODERATE,
            PURCHASE_PATH,
            {"product_code": PRODUCT_R3, "amount": "0"},
        ).status_code
        == 400
    )
    assert (
        _trade(
            auth_client,
            CUSTOMER_MODERATE,
            REDEMPTION_PATH,
            {"product_code": PRODUCT_R3, "shares": "0"},
        ).status_code
        == 400
    )
    assert _no_trade_was_recorded(engine)
    engine.dispose()


def test_an_unknown_product_code_is_reported_as_missing(auth_client: TestClient):
    response = _trade(
        auth_client,
        CUSTOMER_MODERATE,
        PURCHASE_PATH,
        {"product_code": "F999999", "amount": "1000.00"},
    )

    assert response.status_code == 404
    assert "产品" in response.json()["message"]


def test_the_seeded_trades_follow_the_same_strike_convention(auth_client: TestClient):
    """种子里的历史成交与产品要素是同一个成交口径：份额 = 金额 / 净值、手续费 = 金额 × 费率。

    两处对不上，演示时第一步就散架——产品详情上写着 1.20% 的费率，流水里却是另一个数。
    """
    engine = _engine()
    with OrmSession(engine) as session:
        rows = session.execute(
            select(Transaction, Product)
            .join(Product, Product.id == Transaction.product_id)
            .where(Transaction.create_time < TEST_EPOCH)
        ).all()

    assert len(rows) == 5
    for transaction, product in rows:
        assert product.nav > 0
        assert transaction.nav == product.nav
        assert transaction.shares == (transaction.amount / product.nav).quantize(
            Decimal("0.0001")
        )
        assert transaction.fee == (transaction.amount * product.fee_rate / 100).quantize(
            Decimal("0.01")
        )
    engine.dispose()
