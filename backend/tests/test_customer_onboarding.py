"""开户这一个入口的行为。

本文件补的是一个一直没有自己测试文件的入口：开户此前只被端到端旅程顺带走过
（`test_end_to_end_customer_journey.py` 的 `_open_account`），于是两处缺口都没被
拦住——开户采集的**目标配置**只是一组数字，没有人核对它是不是一个比例；
开户建的客户**没有资金账户**，而 `CONTEXT.md` 说「一个客户一个」。

Seam 仍是后端 HTTP 层。读到的东西尽量从客户自己的凭证取（`GET /api/customer/funding-account`），
而不是直接读库——「库里有一行」与「客户拿得到它」不是同一件事，后者才是缺口二的样子。
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.customer_profile.confidence import SOURCE_ADVISOR
from app.db.models import (
    Customer,
    CustomerProfile,
    FundingAccount,
    Holding,
    ProfileTag,
    ProfileTagConflict,
    RiskAlert,
    RiskAssessment,
    Transaction,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

MANAGER = "manager1"
ADVISOR = "advisor1"

CUSTOMERS_PATH = "/api/internal/customers"
TAGS_PATH = "/api/internal/customers/{customer_id}/profile/tags"
FUNDING_ACCOUNT_PATH = "/api/customer/funding-account"
PURCHASE_PATH = "/api/customer/transactions/purchase"

# 合计恰好 100：这是一个成立的目标配置。
BALANCED_TARGET = {"股票": 60, "债券": 20, "现金": 10, "另类": 10}
# 合计 180：各类占比加起来超过整体，定义上就不成立。
OVER_TARGET = {"股票": 80, "债券": 60, "现金": 40}
# 合计 50：缺项不会被下游当成「其余类别」，只会被 `100 - sum(其余)` 记到被侧重的那个类别上。
UNDER_TARGET = {"股票": 30, "债券": 20}

PRODUCT_R1 = "F000001"
PURCHASE_AMOUNT = "1000.00"


def _engine():
    return create_engine(get_settings().test_database_url)


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_headers(client: TestClient, username: str) -> dict[str, str]:
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
        "username": f"onboard_{suffix}",
        "password": SEEDED_PASSWORD,
        "real_name": "开户测试客户",
        "id_number": f"11010119850505{digits[:4]}",
        "phone": f"136{digits[:8]}",
        "customer_level": "普通",
        "annual_income_range": "10-30万",
        "total_assets": "200000.00",
        "investment_experience": "0-1年",
        "target_allocation": dict(BALANCED_TARGET),
    }


def _open_account(client: TestClient, persona: dict) -> dict:
    response = client.post(
        CUSTOMERS_PATH, headers=_employee_headers(client, MANAGER), json=persona
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _customer_id(username: str) -> int | None:
    with OrmSession(_engine()) as session:
        return session.scalar(select(Customer.id).where(Customer.username == username))


def _purge_customer(customer_id: int) -> None:
    """删掉这位客户名下的一切，顺序即外键依赖顺序。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            for model in (RiskAlert, Transaction, Holding, RiskAssessment):
                session.execute(delete(model).where(model.customer_id == customer_id))
            session.execute(
                delete(ProfileTagConflict).where(
                    ProfileTagConflict.customer_id == customer_id
                )
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
def opened_customer(auth_client: TestClient) -> Iterator[dict]:
    """一位刚开出来的客户：除了开户采集的自述信息，什么都没有。"""
    suffix = uuid4().hex[:10]
    persona = _persona(suffix)
    account = _open_account(auth_client, persona)
    try:
        yield {"account": account, "persona": persona, "id": int(account["id"])}
    finally:
        customer_id = _customer_id(persona["username"])
        if customer_id is not None:
            _purge_customer(int(customer_id))


def _profile_tags(client: TestClient, customer_id: int) -> dict[str, object]:
    response = client.get(
        f"/api/internal/customers/{customer_id}/profile",
        headers=_employee_headers(client, ADVISOR),
    )
    assert response.status_code == 200, response.text
    return {tag["key"]: tag["value"] for tag in response.json()["data"]["tags"]}


def _take_the_assessment(client: TestClient, headers: dict[str, str], target: str = "C1") -> None:
    from app.risk_assessment.questionnaire import QUESTIONS

    answers = {
        question.id: question.options[0 if target == "C1" else -1].id
        for question in QUESTIONS
    }
    response = client.post(
        "/api/customer/risk-assessment", headers=headers, json={"answers": answers}
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# 目标配置：一组比例，合计必须为 100
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [OVER_TARGET, UNDER_TARGET],
    ids=["合计超过 100", "合计不足 100"],
)
def test_a_target_allocation_that_does_not_total_one_hundred_is_rejected(
    auth_client: TestClient, target: dict
):
    """合计 180 是矛盾，合计 50 会被下游「100 减去其余」吃掉差额——两者都不是比例。"""
    persona = _persona(uuid4().hex[:10])
    total = sum(target.values())

    response = auth_client.post(
        CUSTOMERS_PATH,
        headers=_employee_headers(auth_client, MANAGER),
        json={**persona, "target_allocation": target},
    )

    assert response.status_code == 400, response.text
    message = response.json()["message"]
    assert str(total) in message
    assert "目标配置" in message
    # 拒绝要拒绝干净：客户不能落库，否则这位客户带着一个不成立的目标配置活在库里。
    assert _customer_id(persona["username"]) is None


def test_a_negative_share_is_rejected(auth_client: TestClient):
    persona = _persona(uuid4().hex[:10])

    response = auth_client.post(
        CUSTOMERS_PATH,
        headers=_employee_headers(auth_client, MANAGER),
        json={**persona, "target_allocation": {"股票": -10, "债券": 110}},
    )

    assert response.status_code == 400, response.text
    assert "目标配置" in response.json()["message"]
    assert _customer_id(persona["username"]) is None


def test_a_balanced_target_allocation_is_recorded_on_the_profile(
    auth_client: TestClient, opened_customer: dict
):
    assert _profile_tags(auth_client, opened_customer["id"])["target_allocation"] == (
        BALANCED_TARGET
    )


@pytest.mark.parametrize(
    "target",
    [{}, {category: 0 for category in ("股票", "债券", "现金", "另类")}],
    ids=["不带这个字段", "五项全为 0"],
)
def test_the_target_allocation_can_be_left_empty(auth_client: TestClient, target: dict):
    """目标配置是可选项：不填就是不知道，不能因此开不了户。

    「五项全为 0」与「不带这个字段」是同一件事——开户表单的 `allocationPayload`
    正是这么处理的，后端不能对两者给两种答案。
    """
    persona = _persona(uuid4().hex[:10])
    body = {key: value for key, value in persona.items() if key != "target_allocation"}
    if target:
        body["target_allocation"] = target
    customer_id: int | None = None
    try:
        account = _open_account(auth_client, body)
        customer_id = int(account["id"])
        assert account["username"] == persona["username"]
    finally:
        if customer_id is not None:
            _purge_customer(customer_id)


def test_a_target_allocation_with_cents_is_read_at_the_same_scale_as_the_form(
    auth_client: TestClient,
):
    """开户表单按百分位算合计（JS 里 33.33 + 33.33 + 33.34 不等于 100），后端比同一个刻度。

    两边不对齐的话，界面会显示「合计 100%」放行、后端回一句不是 100——用户看不出该改哪里。
    """
    persona = _persona(uuid4().hex[:10])
    customer_id: int | None = None
    try:
        account = _open_account(
            auth_client,
            {**persona, "target_allocation": {"股票": 33.33, "债券": 33.33, "现金": 33.34}},
        )
        customer_id = int(account["id"])
        assert _profile_tags(auth_client, customer_id)["target_allocation"] == {
            "股票": 33.33,
            "债券": 33.33,
            "现金": 33.34,
        }
    finally:
        if customer_id is not None:
            _purge_customer(customer_id)


def test_the_target_allocation_cannot_be_smuggled_in_through_the_tag_correction(
    auth_client: TestClient, opened_customer: dict
):
    """手工修正标签是目标配置的第二个入口：同一份判据，同样拦得住。"""
    response = auth_client.put(
        TAGS_PATH.format(customer_id=opened_customer["id"]),
        headers=_employee_headers(auth_client, ADVISOR),
        json={
            "tag_key": "target_allocation",
            "value": OVER_TARGET,
            "source": SOURCE_ADVISOR,
            "reason": "访谈后按客户意愿调整",
        },
    )

    assert response.status_code == 400, response.text
    assert "目标配置" in response.json()["message"]
    # 拒绝之后画像上还是原来那份，没有被半途改写。
    assert _profile_tags(auth_client, opened_customer["id"])["target_allocation"] == (
        BALANCED_TARGET
    )


# ---------------------------------------------------------------------------
# 资金账户：开户即建，余额 0
# ---------------------------------------------------------------------------


def test_a_newly_opened_customer_has_a_funding_account_with_no_money(
    auth_client: TestClient, opened_customer: dict
):
    """「一个客户一个资金账户」是 CONTEXT 的定义；没有入金不等于没有账户。"""
    headers = _customer_headers(auth_client, opened_customer["persona"]["username"])

    response = auth_client.get(FUNDING_ACCOUNT_PATH, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"available_balance": "0.00"}


def test_a_freshly_opened_customer_is_short_of_balance_not_missing_an_account(
    auth_client: TestClient, opened_customer: dict
):
    """钱不够与账户不存在是两件事：界面上的「—」不该是这个客户应有的样子。"""
    headers = _customer_headers(auth_client, opened_customer["persona"]["username"])
    _take_the_assessment(auth_client, headers, "C1")

    response = auth_client.post(
        PURCHASE_PATH,
        headers=headers,
        json={"product_code": PRODUCT_R1, "amount": PURCHASE_AMOUNT},
    )

    assert response.status_code == 400, response.text
    message = response.json()["message"]
    assert "余额不足" in message
    assert "资金账户不存在" not in message
    # 被拒绝之后余额仍是 0，没有凭空多出钱来。
    balance = auth_client.get(FUNDING_ACCOUNT_PATH, headers=headers)
    assert balance.json()["data"]["available_balance"] == format(Decimal("0.00"), "f")


def test_the_funding_account_is_created_with_the_customer_in_one_transaction(
    auth_client: TestClient, opened_customer: dict
):
    """客户与资金账户要么一起在，要么都不在——不给「有客户没账户」留窗口。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            account = session.scalar(
                select(FundingAccount).where(
                    FundingAccount.customer_id == opened_customer["id"]
                )
            )
    finally:
        engine.dispose()

    assert account is not None
    assert account.available_balance == Decimal("0.00")
    assert account.create_time is not None
