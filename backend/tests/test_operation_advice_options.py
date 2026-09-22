"""操作建议的可选项端点（issue 01）。

Seam：后端 HTTP 层。客户经理在发起前读「这位客户在这个方向下能选哪些产品、每只的
金额区间是多少」，断言落在响应上，以及它与受理侧成交口径的一致性上。

本文件盯住三件事：

- **方向过滤只有一处**：申购不出现已持有、赎回只出现「候选池 ∩ 已持有」；
- **买不起的项仍然出现**：带 `affordable: false`，不是从列表里消失（藏掉会让经理
  以为候选池里少了一只，而那只正是他要拿来跟客户解释的东西）；
- **区间走受理侧口径**：`affordable` 与 `max_amount` 都能被 `purchase_cost` 复核，
  上限就是「再添一分钱就买不起」的那一分钱。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

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
    ProfileTagConflict,
    RiskAssessment,
    SuitabilityDecision,
)
from app.order_acceptance.service import purchase_cost
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

MANAGER = "manager1"
OTHER_MANAGER = "manager2"
ADVISOR = "advisor1"
RISK_OFFICER = "risk1"

OPTIONS_PATH = "/api/internal/customers/{customer_id}/operation-advice-options"
CANDIDATE_POOL_PATH = "/api/customer/candidate-pool"

HELD_STATUS = "持有中"
# C5 客户的候选池就是全部五只在售产品——用产品代码断言方向过滤的输入足够稳定。
POOL_CODES = {"F000001", "F000002", "F000003", "F000004", "F000005"}
MONEY = Decimal("0.01")

SEEDED_BALANCE = Decimal("500000.00")


def _engine():
    return create_engine(get_settings().test_database_url)


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _digits(suffix: str) -> str:
    return str(int(suffix, 16)).zfill(12)


def _persona(suffix: str) -> dict:
    digits = _digits(suffix)
    return {
        "username": f"optionstest_{suffix}",
        "real_name": "测试客户",
        "id_number": f"11010119800101{digits[:4]}",
        "phone": f"137{digits[:8]}",
        "customer_level": "普通",
        "annual_income_range": "100万以上",
        "total_assets": "1000000.00",
        "investment_experience": "10年以上",
        "target_allocation": {"股票": 30, "债券": 40, "现金": 30},
    }


def _fund_account(customer_id: int, balance: Decimal) -> None:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            account = session.scalar(
                select(FundingAccount).where(FundingAccount.customer_id == customer_id)
            )
            assert account is not None
            account.available_balance = balance
            session.commit()
    finally:
        engine.dispose()


def _add_holding(customer_id: int, *, product_code: str, shares: Decimal) -> None:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            product = session.scalar(
                select(Product).where(Product.product_code == product_code)
            )
            assert product is not None
            session.add(
                Holding(
                    customer_id=customer_id,
                    product_id=product.id,
                    shares=shares,
                    cost_amount=shares * product.nav,
                    current_value=shares * product.nav,
                    profit_loss=Decimal("0.00"),
                    profit_ratio=Decimal("0.0000"),
                    status=HELD_STATUS,
                )
            )
            session.commit()
    finally:
        engine.dispose()


def _product_rows(product_codes: list[str]) -> dict[str, Product]:
    """产品行：费率与起投金额在行上，端点给的区间要用受理侧口径复核。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            rows = session.scalars(
                select(Product).where(Product.product_code.in_(product_codes))
            ).all()
            return {row.product_code: row for row in rows}
    finally:
        engine.dispose()


def _delete_customer(customer_id: int) -> None:
    """清掉这位客户的一切：持仓与资金账户 → 画像 → 客户本身，顺序即外键依赖顺序。

    候选池端点每读一次都会写一条适当性判定（`app.suitability.service`），因此它也在
    清理之列。
    """
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            session.execute(delete(Holding).where(Holding.customer_id == customer_id))
            session.execute(
                delete(FundingAccount).where(FundingAccount.customer_id == customer_id)
            )
            session.execute(delete(ProfileTag).where(ProfileTag.customer_id == customer_id))
            session.execute(
                delete(ProfileTagConflict).where(ProfileTagConflict.customer_id == customer_id)
            )
            session.execute(
                delete(SuitabilityDecision).where(SuitabilityDecision.customer_id == customer_id)
            )
            session.execute(
                delete(RiskAssessment).where(RiskAssessment.customer_id == customer_id)
            )
            session.execute(
                delete(CustomerProfile).where(CustomerProfile.customer_id == customer_id)
            )
            session.execute(delete(Customer).where(Customer.id == customer_id))
            session.commit()
    finally:
        engine.dispose()


def _questionnaire_answers(target: str) -> dict[str, str]:
    from app.risk_assessment.questionnaire import QUESTIONS

    return {
        question.id: question.options[0 if target == "C1" else -1].id
        for question in QUESTIONS
    }


def _options_response(
    client: TestClient,
    *,
    customer_id: int,
    direction: str | None = None,
    username: str = MANAGER,
):
    params = {} if direction is None else {"direction": direction}
    return client.get(
        OPTIONS_PATH.format(customer_id=customer_id),
        headers=_employee_headers(client, username),
        params=params,
    )


def _options(
    client: TestClient, *, customer_id: int, direction: str
) -> list[dict]:
    response = _options_response(client, customer_id=customer_id, direction=direction)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["direction"] == direction
    return response.json()["data"]["products"]


@pytest.fixture
def open_customer(auth_client: TestClient) -> Iterator[Callable[..., dict]]:
    """开一位归属 manager1、做过风评（C5）、账上有钱的新客户。

    余额可指定：区间与 `affordable` 的断言要拿一个确定的数去复核。
    """
    created: list[int] = []

    def _open(*, balance: Decimal = SEEDED_BALANCE) -> dict:
        suffix = uuid4().hex[:10]
        persona = _persona(suffix)
        response = auth_client.post(
            "/api/internal/customers",
            headers=_employee_headers(auth_client, MANAGER),
            json={**persona, "password": SEEDED_PASSWORD},
        )
        assert response.status_code == 200, response.text
        customer_id = int(response.json()["data"]["id"])
        _fund_account(customer_id, balance)
        headers = _customer_login(auth_client, persona["username"])
        assessed = auth_client.post(
            "/api/customer/risk-assessment",
            headers=headers,
            json={"answers": _questionnaire_answers("C5")},
        )
        assert assessed.status_code == 200, assessed.text
        assert assessed.json()["data"]["risk_level"] == "C5"
        created.append(customer_id)
        return {"id": customer_id, "username": persona["username"], "headers": headers}

    try:
        yield _open
    finally:
        for customer_id in created:
            _delete_customer(customer_id)


# ---------------------------------------------------------------------------
# 方向过滤：申购 = 候选池 − 已持有，赎回 = 候选池 ∩ 已持有
# ---------------------------------------------------------------------------


def test_a_purchase_option_list_excludes_held_products(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    customer = open_customer()
    customer_id = customer["id"]
    pool = auth_client.get(CANDIDATE_POOL_PATH, headers=customer["headers"]).json()["data"]
    assert {item["product_code"] for item in pool["products"]} == POOL_CODES

    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))

    options = _options(auth_client, customer_id=customer_id, direction="申购")

    codes = {option["product_code"] for option in options}
    assert "F000003" not in codes
    assert codes == POOL_CODES - {"F000003"}

    # 每一项都带齐发起表单要显示的五要素与金额区间（Q13）。
    for option in options:
        assert option["product_name"]
        assert option["product_type"]
        assert option["risk_level"] in {"R1", "R2", "R3", "R4", "R5"}
        assert isinstance(option["term_days"], int)
        assert Decimal(option["min_amount"]) > 0
        assert Decimal(option["max_amount"]) >= Decimal(option["min_amount"])
        # 申购的区间是金额：份额不在这一侧的呈现里。
        assert "max_shares" not in option


def test_a_redemption_option_list_is_the_pool_intersect_holdings(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    customer = open_customer()
    customer_id = customer["id"]
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))
    # 持有一只已停售、因而不在候选池里的产品：赎回的产品范围仍是「持有 ∩ 候选池」。
    _add_holding(customer_id, product_code="F900002", shares=Decimal("500.0000"))

    options = _options(auth_client, customer_id=customer_id, direction="赎回")

    assert [option["product_code"] for option in options] == ["F000003"]
    option = options[0]
    # 赎回的区间是份额：金额由份额与净值在成交时算出来，这里不给 max_amount。
    assert "max_amount" not in option
    assert option["max_shares"] == "1200.0000"
    assert option["affordable"] is True


def test_a_direction_with_nothing_to_choose_gives_an_empty_list(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    customer = open_customer()
    customer_id = customer["id"]

    # 没有任何持仓：赎回方向没有可选项，但这不是错误——空态有专门的文案。
    assert _options(auth_client, customer_id=customer_id, direction="赎回") == []

    # 候选池里的每一只都已经持有：申购方向同样为空。
    for code in POOL_CODES:
        _add_holding(customer_id, product_code=code, shares=Decimal("100.0000"))
    assert _options(auth_client, customer_id=customer_id, direction="申购") == []


# ---------------------------------------------------------------------------
# 买不起的项仍然出现，区间走受理侧口径
# ---------------------------------------------------------------------------


def test_a_product_that_cannot_be_afforded_stays_on_the_list(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    # 余额只买得起起投 1000 的那几只：起投 5000 的 F000005 买不起，但它仍然在列表里。
    customer = open_customer(balance=Decimal("1050.00"))

    options = _options(auth_client, customer_id=customer["id"], direction="申购")

    by_code = {option["product_code"]: option for option in options}
    assert set(by_code) == POOL_CODES
    assert by_code["F000005"]["affordable"] is False
    assert by_code["F000001"]["affordable"] is True


def test_the_range_matches_the_acceptance_side(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    """`affordable` 与 `max_amount` 都是受理侧口径算好的数，前端不复算费率。

    上限的定义钉在这里：把它填进受理，买得起；再添一分钱，受理拒绝。
    """
    balance = Decimal("1050.00")
    customer = open_customer(balance=balance)

    options = _options(auth_client, customer_id=customer["id"], direction="申购")
    rows = _product_rows([option["product_code"] for option in options])

    assert options
    for option in options:
        product = rows[option["product_code"]]
        ceiling = Decimal(option["max_amount"])
        assert option["affordable"] == (
            purchase_cost(product, product.min_amount) <= balance
        )
        assert purchase_cost(product, ceiling) <= balance
        assert purchase_cost(product, ceiling + MONEY) > balance


# ---------------------------------------------------------------------------
# 谁读得到：只有客户经理，且只对自己名下客户
# ---------------------------------------------------------------------------


def test_only_the_owning_manager_can_read_the_options(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    customer_id = open_customer()["id"]

    # 理财顾问与风控专员没有发起表单，因此也没有可选项可读（角色这道门与发起同一道）。
    for username in (ADVISOR, RISK_OFFICER):
        refused = _options_response(
            auth_client, customer_id=customer_id, direction="申购", username=username
        )
        assert refused.status_code == 403, refused.text

    # 另一位客户经理也不行：他名下没有这位客户（归属是另一道独立的门）。
    other_manager = _options_response(
        auth_client,
        customer_id=customer_id,
        direction="申购",
        username=OTHER_MANAGER,
    )
    assert other_manager.status_code == 403
    assert "名下" in other_manager.json()["message"]

    # 归属人自己读得到——被拒绝的是别人，不是这条链路本身。
    assert _options(auth_client, customer_id=customer_id, direction="申购")


def test_an_unknown_customer_is_reported_as_missing(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    open_customer()

    response = _options_response(auth_client, customer_id=99999999, direction="申购")

    assert response.status_code == 404
    assert response.json()["message"] == "客户不存在"


def test_an_unknown_direction_is_rejected(
    auth_client: TestClient, open_customer: Callable[..., dict]
):
    customer_id = open_customer()["id"]

    # 方向非法：口径与受理入口的 `ALLOWED_DIRECTIONS` 一致，文案也是同一句。
    unknown = _options_response(auth_client, customer_id=customer_id, direction="持有")
    assert unknown.status_code == 400
    assert unknown.json()["message"] == "未知的操作方向"

    # 方向缺失是请求本身不成立，与受理入口缺字段一样是「参数错误」。
    missing = _options_response(auth_client, customer_id=customer_id)
    assert missing.status_code == 400
