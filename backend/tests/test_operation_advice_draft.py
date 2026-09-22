"""业务操作 Agent 与操作建议原稿（issue 06、ADR-0021）。

Seam：后端 HTTP 层。客户经理为名下客户发起建议，生成走真实链路——候选池（适当性
硬过滤）、客户持仓与资金账户、理由、审核中断、原稿落库，断言落在响应、库里的
原稿与审核记录上。

本文件盯住五件事：

- **发起权**：只有客户经理能发起，且只对名下客户（`CONTEXT.md`「客户经理」）；
- **产品与金额 / 份额由发起人给、原样采用**：图里不再选品，草案里的那只与那个数
  就是提交上来的那只与那个数（ADR-0021）；
- **受理校验与可选项是同一份计算**：候选池之外的产品、已持有做申购、未持有做赎回、
  低于起投、超余额、份额越界，一律在图编译之前被拒绝（护栏 1 的延续）；
- **三条硬边界**：一次一个产品一个方向、金额必填、理由里没有收益预测与配置比例表述；
- **原稿只写不改**：落库后没有 update 路径，与方案的 AI 原稿同一条约束。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review import claim_review, resume_review
from app.advisory.review_status import (
    ACTION_REJECT,
    ACTION_RELEASE,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RELEASED,
)
from app.db.models import (
    AdvisoryReview,
    AdvisoryReviewComment,
    AdvisoryReviewAudit,
    Customer,
    CustomerProfile,
    Employee,
    FundingAccount,
    Holding,
    OperationAdviceDraft,
    Product,
    ProfileTag,
    ProfileTagConflict,
    RiskAssessment,
    SuitabilityDecision,
)
from app.operation_advice import draft as draft_module
from app.operation_advice import options as options_module
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

MANAGER = "manager1"
OTHER_MANAGER = "manager2"
ADVISOR = "advisor1"
RISK_OFFICER = "risk1"

OPERATION_ADVICE_PATH = "/api/internal/customers/{customer_id}/operation-advice"
OPTIONS_PATH = "/api/internal/customers/{customer_id}/operation-advice-options"
CANDIDATE_POOL_PATH = "/api/customer/candidate-pool"

HELD_STATUS = "持有中"
# 新客户在应用里拿不到钱：开户建出来的是余额 0 的资金账户，余额的初始值来自种子。
# 测试因此直接把余额写成演示起点——它绕过的是「装库时没有入金」，不是「没有账户」，
# 更不是「应用里没有充值入口」（ADR-0023）。
SEEDED_BALANCE = Decimal("500000.00")


def _engine():
    return create_engine(get_settings().test_database_url)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        "username": f"advicetest_{suffix}",
        "real_name": "测试客户",
        "id_number": f"11010119800101{digits[:4]}",
        "phone": f"137{digits[:8]}",
        "customer_level": "普通",
        "annual_income_range": "100万以上",
        "total_assets": "1000000.00",
        "investment_experience": "10年以上",
        "target_allocation": {"股票": 30, "债券": 40, "现金": 30},
    }


def _open_account(client: TestClient, persona: dict) -> dict:
    """客户经理为客户开户：客户的关系归属人由此确定。"""
    response = client.post(
        "/api/internal/customers",
        headers=_employee_headers(client, MANAGER),
        json={**persona, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _fund_account(customer_id: int, balance: Decimal = SEEDED_BALANCE) -> None:
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


def _employee_id(username: str) -> int:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            employee_id = session.scalar(
                select(Employee.id).where(Employee.username == username)
            )
    finally:
        engine.dispose()
    assert employee_id is not None
    return int(employee_id)


def _delete_customer(customer_id: int) -> None:
    """清掉这位客户的一切：操作建议那一侧（留痕 → 审核 → 载荷）→ 持仓与资金账户 →
    画像 → 客户本身，顺序即外键依赖顺序。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            draft_ids = list(
                session.scalars(
                    select(OperationAdviceDraft.id).where(
                        OperationAdviceDraft.customer_id == customer_id
                    )
                ).all()
            )
            if draft_ids:
                review_ids = list(
                    session.scalars(
                        select(AdvisoryReview.id).where(
                            AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
                            AdvisoryReview.content_ref.in_(draft_ids),
                        )
                    ).all()
                )
                if review_ids:
                    session.execute(
                        delete(AdvisoryReviewComment).where(
                            AdvisoryReviewComment.review_id.in_(review_ids)
                        )
                    )
                    session.execute(
                        delete(AdvisoryReviewAudit).where(
                            AdvisoryReviewAudit.review_id.in_(review_ids)
                        )
                    )
                    session.execute(
                        delete(AdvisoryReview).where(AdvisoryReview.id.in_(review_ids))
                    )
                session.execute(
                    delete(OperationAdviceDraft).where(
                        OperationAdviceDraft.id.in_(draft_ids)
                    )
                )
            session.execute(delete(Holding).where(Holding.customer_id == customer_id))
            session.execute(
                delete(FundingAccount).where(FundingAccount.customer_id == customer_id)
            )
            session.execute(delete(ProfileTag).where(ProfileTag.customer_id == customer_id))
            session.execute(
                delete(ProfileTagConflict).where(
                    ProfileTagConflict.customer_id == customer_id
                )
            )
            session.execute(
                delete(SuitabilityDecision).where(
                    SuitabilityDecision.customer_id == customer_id
                )
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

    answers: dict[str, str] = {}
    for question in QUESTIONS:
        index = 0 if target == "C1" else -1
        answers[question.id] = question.options[index].id
    return answers


def _assess(client: TestClient, headers: dict[str, str], target: str) -> None:
    response = client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": _questionnaire_answers(target)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["risk_level"] == target


def _start_advice(
    client: TestClient, *, customer_id: int, body: dict, username: str = MANAGER
):
    return client.post(
        OPERATION_ADVICE_PATH.format(customer_id=customer_id),
        headers=_employee_headers(client, username),
        json=body,
    )


def _options(
    client: TestClient, *, customer_id: int, direction: str, username: str = MANAGER
) -> list[dict]:
    response = client.get(
        OPTIONS_PATH.format(customer_id=customer_id),
        headers=_employee_headers(client, username),
        params={"direction": direction},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["products"]


def _purchase_body(client: TestClient, customer_id: int) -> dict:
    """一份合法的申购请求体：第一只买得起的可选项 + 它的起投金额。

    产品与金额都取自可选项端点——发起受理读的是同一份计算（ADR-0021），测试因此
    不必写死一只今天在池里、明天可能不在的产品。
    """
    option = next(
        item
        for item in _options(client, customer_id=customer_id, direction="申购")
        if item["affordable"]
    )
    return {
        "direction": "申购",
        "product_code": option["product_code"],
        "amount": option["min_amount"],
    }


@pytest.fixture
def customer_of_manager(auth_client: TestClient) -> Iterator[dict]:
    """一位归属 manager1、做过风评、账上有钱的新客户。"""
    suffix = uuid4().hex[:10]
    persona = _persona(suffix)
    account = _open_account(auth_client, persona)
    customer_id = int(account["id"])
    _fund_account(customer_id)
    headers = _customer_login(auth_client, persona["username"])
    _assess(auth_client, headers, "C5")
    try:
        yield {
            "id": customer_id,
            "username": persona["username"],
            "headers": headers,
        }
    finally:
        _delete_customer(customer_id)


def _candidate_pool(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get(CANDIDATE_POOL_PATH, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["products"]


def _stored_review(draft_id: int) -> AdvisoryReview:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            review = session.scalar(
                select(AdvisoryReview).where(
                    AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
                    AdvisoryReview.content_ref == draft_id,
                )
            )
    finally:
        engine.dispose()
    assert review is not None
    return review


def _stored_draft(draft_id: int) -> OperationAdviceDraft:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            draft = session.get(OperationAdviceDraft, draft_id)
    finally:
        engine.dispose()
    assert draft is not None
    return draft


def _drafts_of(customer_id: int) -> list[OperationAdviceDraft]:
    """这位客户名下的全部原稿：被拒绝的发起不该在这里留下任何一行。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(
                    select(OperationAdviceDraft).where(
                        OperationAdviceDraft.customer_id == customer_id
                    )
                ).all()
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 第五份 Agent 配置
# ---------------------------------------------------------------------------


def test_the_registry_lists_the_operation_advice_agent(auth_client: TestClient):
    """注册表是「按 Agent 类型路由」的唯一出处：第五份配置与它的入口在这里写一遍。"""
    response = auth_client.get("/api/agents")
    assert response.status_code == 200, response.text
    entries = {entry["agent_type"]: entry for entry in response.json()["data"]}

    assert set(entries) == {
        "customer_service",
        "data_analysis",
        "advisory",
        "operation_advice",
        "risk_monitoring",
    }
    entry = entries["operation_advice"]
    assert entry["identity_domain"] == "internal"
    assert entry["content_classification_default"] == "投顾内容"
    assert entry["tools"] == [
        "candidate_pool_query",
        "customer_holdings_and_balance_query",
        "operation_advice_generation",
    ]
    # 注册表给出的就是发起建议实际打的那条路由——漂移即失败。
    assert entry["entry_path"] == OPERATION_ADVICE_PATH


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------


def test_the_chosen_purchase_is_adopted_as_is(
    auth_client: TestClient, customer_of_manager: dict
):
    """发起人选的哪只、多少钱，建议里就是哪只、多少钱——Agent 不再改动它们（ADR-0021）。"""
    customer_id = customer_of_manager["id"]
    pool_codes = {
        item["product_code"]
        for item in _candidate_pool(auth_client, customer_of_manager["headers"])
    }
    body = _purchase_body(auth_client, customer_id)

    response = _start_advice(auth_client, customer_id=customer_id, body=body)
    assert response.status_code == 200, response.text
    advice = response.json()["data"]

    # 投顾内容：送达前必须经理财顾问放行，免责声明按内容分类给。
    assert advice["content_classification"] == "投顾内容"
    assert advice["disclaimer"]
    assert advice["direction"] == "申购"
    # 产品与金额原样采用，一个字都不改：「谁选的」不在这条链路上第二次发生。
    assert advice["product_code"] == body["product_code"]
    assert advice["amount"] == body["amount"]
    # 产品仍在候选池内：范围本身一个字没变，只是检查从「Agent 顺手只挑池内的」
    # 变成「人可能挑池外的、必须明确拒绝」（护栏 1 的延续，见下一条用例）。
    assert advice["product_code"] in pool_codes
    assert advice["product_name"]
    assert Decimal(advice["amount"]) > 0

    # 理由必填，只引用候选池里的产品要素与客户自己的数字，且不越第三条硬边界：
    # 没有收益预测、没有配置比例表述（既有断言的延续）。
    assert advice["reason"]
    for forbidden in ("预期", "年化", "%", "仓位", "比例"):
        assert forbidden not in advice["reason"]
    # 建议本体的形状：只有「一个产品、一个方向、一个金额、一条理由」——
    # 方案特有的载荷不以空字段的形式跟着建议走。
    assert set(advice).isdisjoint(
        {"candidates", "allocation_suggestion", "warnings", "candidate_pool_snapshot"}
    )

    # 落库：产品、金额与请求里完全一致；申购不带份额。
    draft = _stored_draft(advice["id"])
    assert draft.customer_id == customer_id
    assert draft.manager_id == _employee_id(MANAGER)
    assert draft.direction == "申购"
    assert draft.product_code == body["product_code"]
    assert draft.amount == Decimal(body["amount"])
    assert draft.redeemed_shares is None
    assert draft.reason == advice["reason"]

    review = _stored_review(advice["id"])
    assert review.status == STATUS_PENDING
    assert review.thread_id
    # `draft_id` 是方案特有的列，操作建议不写它。
    assert review.draft_id is None

    # 同一条审核流水线：原稿立刻出现在理财顾问的待审队列里，并带类型标注。
    queue = auth_client.get(
        "/api/internal/advisory/queue", headers=_employee_headers(auth_client, ADVISOR)
    )
    assert queue.status_code == 200, queue.text
    pending = queue.json()["data"]["pending_reviews"]
    row = next(item for item in pending if item["content_ref"] == advice["id"])
    assert row["content_type"] == CONTENT_TYPE_OPERATION_ADVICE
    assert row["product_code"] == advice["product_code"]
    assert row["direction"] == "申购"
    assert row["amount"] == advice["amount"]


def test_a_product_outside_the_pool_is_rejected(
    auth_client: TestClient, customer_of_manager: dict
):
    """护栏 1 的延续：选择权移交之后，范围检查落在「人可能挑池外的」这一侧。"""
    customer_id = customer_of_manager["id"]
    body = _purchase_body(auth_client, customer_id)

    # F900002 在目录里但已停售，因此不在候选池内。
    assert "F900002" not in {
        item["product_code"]
        for item in _candidate_pool(auth_client, customer_of_manager["headers"])
    }
    refused = _start_advice(
        auth_client, customer_id=customer_id, body={**body, "product_code": "F900002"}
    )

    assert refused.status_code == 400
    assert "可申购" in refused.json()["message"]
    # 池外的产品连原稿都产不出：拒绝发生在图编译之前。
    assert _drafts_of(customer_id) == []


def test_a_held_product_cannot_be_purchased_again(
    auth_client: TestClient, customer_of_manager: dict
):
    """申购的方向资格：已持有的产品不再出现在申购方向的可选项里，提交上来也被拒绝。"""
    customer_id = customer_of_manager["id"]
    _add_holding(customer_id, product_code="F000003", shares=Decimal("100.0000"))
    body = _purchase_body(auth_client, customer_id)

    assert "F000003" not in {
        option["product_code"]
        for option in _options(auth_client, customer_id=customer_id, direction="申购")
    }
    refused = _start_advice(
        auth_client, customer_id=customer_id, body={**body, "product_code": "F000003"}
    )

    assert refused.status_code == 400
    assert "可申购" in refused.json()["message"]


def test_the_pool_for_a_conservative_customer_bounds_the_advice(
    auth_client: TestClient,
):
    """C1 客户的候选池里只有 R1 产品：池内那只提交得过，池外的被明确拒绝。"""
    suffix = uuid4().hex[:10]
    persona = _persona(suffix)
    account = _open_account(auth_client, persona)
    customer_id = int(account["id"])
    _fund_account(customer_id)
    headers = _customer_login(auth_client, persona["username"])
    _assess(auth_client, headers, "C1")
    try:
        pool = _candidate_pool(auth_client, headers)
        assert {item["product_code"] for item in pool} == {"F000001"}

        body = _purchase_body(auth_client, customer_id)
        assert body["product_code"] == "F000001"
        accepted = _start_advice(auth_client, customer_id=customer_id, body=body)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["product_code"] == "F000001"

        # F000005 是 R5 的在售产品：对这位客户来说它在候选池外。
        refused = _start_advice(
            auth_client, customer_id=customer_id, body={**body, "product_code": "F000005"}
        )
        assert refused.status_code == 400, refused.text
        assert "可申购" in refused.json()["message"]
    finally:
        _delete_customer(customer_id)


def test_a_redemption_advice_carries_the_chosen_shares(
    auth_client: TestClient, customer_of_manager: dict
):
    """赎回建议带发起人选定的份额——部分赎回也是一个具体的数（ADR-0021）。"""
    customer_id = customer_of_manager["id"]
    pool_codes = {
        item["product_code"]
        for item in _candidate_pool(auth_client, customer_of_manager["headers"])
    }
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))
    chosen = Decimal("600.0000")

    response = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={
            "direction": "赎回",
            "product_code": "F000003",
            "shares": str(chosen),
        },
    )
    assert response.status_code == 200, response.text
    advice = response.json()["data"]

    assert advice["direction"] == "赎回"
    assert advice["product_code"] == "F000003"
    # 赎回的产品同样来自候选池（硬保证，不因方向不同而放宽）。
    assert advice["product_code"] in pool_codes
    # 金额 = 份额 × 净值（成交口径），理由里带上这次赎回的份额。
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            nav = session.scalar(
                select(Product.nav).where(Product.product_code == "F000003")
            )
    finally:
        engine.dispose()
    assert Decimal(advice["amount"]) == (chosen * nav).quantize(Decimal("0.01"))
    # 理由是「从 1200.0000 份里赎回 600.0000 份」：持仓与这次赎回的份额是两个数，
    # 印成一个就把「客户持有多少」写错了（部分赎回时两者不相等）。
    assert "1200.0000" in advice["reason"]
    assert str(chosen) in advice["reason"]

    # 落库：份额与请求里完全一致——接受侧从此按这个数执行。
    draft = _stored_draft(advice["id"])
    assert draft.product_code == "F000003"
    assert draft.amount == Decimal(advice["amount"])
    assert draft.redeemed_shares == chosen


def test_a_redemption_advice_needs_a_holding_in_the_pool(
    auth_client: TestClient, customer_of_manager: dict
):
    # 没有任何持仓：赎回方向的可选项是空的，提交哪一只都被拒绝。
    refused = _start_advice(
        auth_client,
        customer_id=customer_of_manager["id"],
        body={"direction": "赎回", "product_code": "F000003", "shares": "100.0000"},
    )

    assert refused.status_code == 400
    assert "持仓" in refused.json()["message"]


def test_a_product_the_customer_does_not_hold_cannot_be_redeemed(
    auth_client: TestClient, customer_of_manager: dict
):
    """赎回的方向资格：持有的那只选得动，池内没持有的另一只提交上来仍被拒绝。"""
    customer_id = customer_of_manager["id"]
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))

    redeemable = {
        option["product_code"]
        for option in _options(auth_client, customer_id=customer_id, direction="赎回")
    }
    assert redeemable == {"F000003"}

    refused = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={"direction": "赎回", "product_code": "F000004", "shares": "100.0000"},
    )

    assert refused.status_code == 400
    assert "持仓" in refused.json()["message"]


def test_an_unknown_direction_is_rejected(
    auth_client: TestClient, customer_of_manager: dict
):
    response = _start_advice(
        auth_client,
        customer_id=customer_of_manager["id"],
        body={"direction": "持有", "product_code": "F000001", "amount": "1000.00"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "未知的操作方向"


# ---------------------------------------------------------------------------
# 受理校验：发起人给的输入不合法就被拒绝
# ---------------------------------------------------------------------------


def test_an_amount_below_the_minimum_is_rejected(
    auth_client: TestClient, customer_of_manager: dict
):
    customer_id = customer_of_manager["id"]
    body = _purchase_body(auth_client, customer_id)
    minimum = Decimal(body["amount"])

    refused = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={**body, "amount": str(minimum - Decimal("0.01"))},
    )

    assert refused.status_code == 400
    assert "起投" in refused.json()["message"]
    # 请求只是被拒绝：没有落下一份原稿。
    assert _drafts_of(customer_id) == []


def test_an_amount_above_the_available_balance_is_rejected(
    auth_client: TestClient, customer_of_manager: dict
):
    """上限由受理侧口径算：`purchase_cost(金额) > 可用余额` 即拒绝。"""
    customer_id = customer_of_manager["id"]
    option = next(
        item
        for item in _options(auth_client, customer_id=customer_id, direction="申购")
        if item["affordable"]
    )
    ceiling = Decimal(option["max_amount"])

    refused = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={
            "direction": "申购",
            "product_code": option["product_code"],
            "amount": str(ceiling + Decimal("0.01")),
        },
    )

    assert refused.status_code == 400
    assert "余额" in refused.json()["message"]

    # 上限本身是买得起的（与可选项端点同一份口径）：再提交一次就通过。
    accepted = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={
            "direction": "申购",
            "product_code": option["product_code"],
            "amount": str(ceiling),
        },
    )
    assert accepted.status_code == 200, accepted.text


def test_the_options_endpoint_and_the_acceptance_read_one_function(
    auth_client: TestClient, customer_of_manager: dict, monkeypatch: pytest.MonkeyPatch
):
    """可选项端点与发起受理对同一组输入给出同一结论（ADR-0021 的主要实现约束）。

    选品规则（申购 = 候选池 − 已持有、赎回 = 持有 ∩ 候选池）只写在 `advice_options`
    一处：端点渲染它、受理校验读它。受理侧若另写一套，漂移的表现是「下拉里有这只
    产品，一提交被拒」，不会有断言失败——只有这条把两个入口钉在同一个函数上的断言
    能提前发现它。这里用 spy 钉住受理这条入口：它必须走 `advice_options` 这一份，
    而不是自己再判一遍；结论与端点给的那只一字不差。
    """
    customer_id = customer_of_manager["id"]
    directions: list[str] = []
    original = options_module.advice_options

    def spy(*args, **kwargs):
        directions.append(kwargs["direction"])
        return original(*args, **kwargs)

    monkeypatch.setattr(options_module, "advice_options", spy)

    # 入口一：可选项端点——它给的那只产品来自同一份计算。
    option = next(
        item for item in _options(auth_client, customer_id=customer_id, direction="申购")
        if item["affordable"]
    )
    # 入口二：发起受理——`resolve_advice_choice` 内部读同一份 `advice_options`。
    response = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={
            "direction": "申购",
            "product_code": option["product_code"],
            "amount": option["min_amount"],
        },
    )
    assert response.status_code == 200, response.text
    # 受理校验走的就是 `advice_options` 这一份计算，没有第二套选品。
    assert directions == ["申购"]


def test_a_redemption_share_count_must_be_within_the_holding(
    auth_client: TestClient, customer_of_manager: dict
):
    customer_id = customer_of_manager["id"]
    held = Decimal("1200.0000")
    _add_holding(customer_id, product_code="F000003", shares=held)
    body = {"direction": "赎回", "product_code": "F000003"}

    for shares in ("0.0000", "-1.0000", str(held + Decimal("0.0001"))):
        refused = _start_advice(
            auth_client, customer_id=customer_id, body={**body, "shares": shares}
        )
        assert refused.status_code == 400, (shares, refused.text)
        assert "份额" in refused.json()["message"]

    # 恰等于持仓份额提交得过（部分赎回与全部赎回都是发起人给的份额）。
    accepted = _start_advice(
        auth_client, customer_id=customer_id, body={**body, "shares": str(held)}
    )
    assert accepted.status_code == 200, accepted.text
    assert _stored_draft(accepted.json()["data"]["id"]).redeemed_shares == held


def test_a_request_without_the_chosen_number_is_rejected(
    auth_client: TestClient, customer_of_manager: dict
):
    """哪个数必填由方向决定，缺了就是发起人的输入错了（不是请求体不成立）。"""
    customer_id = customer_of_manager["id"]
    body = _purchase_body(auth_client, customer_id)
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))

    missing_amount = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={"direction": "申购", "product_code": body["product_code"]},
    )
    assert missing_amount.status_code == 400
    assert "金额" in missing_amount.json()["message"]

    missing_shares = _start_advice(
        auth_client,
        customer_id=customer_id,
        body={"direction": "赎回", "product_code": "F000003"},
    )
    assert missing_shares.status_code == 400
    assert "份额" in missing_shares.json()["message"]


def test_a_request_without_a_product_is_rejected(
    auth_client: TestClient, customer_of_manager: dict
):
    """产品是必填字段：没有它的请求体本身不成立（参数错误）。"""
    refused = _start_advice(
        auth_client,
        customer_id=customer_of_manager["id"],
        body={"direction": "申购", "amount": "1000.00"},
    )

    assert refused.status_code == 400
    assert refused.json()["message"] == "参数错误"


# ---------------------------------------------------------------------------
# 发起权：只有客户经理，且只对名下客户
# ---------------------------------------------------------------------------


def test_only_the_owning_manager_can_start_an_advice(
    auth_client: TestClient, customer_of_manager: dict
):
    customer_id = customer_of_manager["id"]
    body = _purchase_body(auth_client, customer_id)

    # 理财顾问与风控专员没有发起入口：发起与放行是两件事，放行才是他们的。
    for username in (ADVISOR, RISK_OFFICER):
        refused = _start_advice(
            auth_client, customer_id=customer_id, body=body, username=username
        )
        assert refused.status_code == 403, refused.text

    # 另一位客户经理也不行：他名下没有这位客户。
    other_manager = _start_advice(
        auth_client,
        customer_id=customer_id,
        body=body,
        username=OTHER_MANAGER,
    )
    assert other_manager.status_code == 403
    assert "名下" in other_manager.json()["message"]

    assert _drafts_of(customer_id) == []

    # 归属人自己发起成功——被拒绝的是别人，不是这条链路本身。
    assert _start_advice(auth_client, customer_id=customer_id, body=body).status_code == 200


def test_an_unknown_customer_is_reported_as_missing(auth_client: TestClient):
    response = _start_advice(
        auth_client,
        customer_id=99999999,
        body={"direction": "申购", "product_code": "F000001", "amount": "1000.00"},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "客户不存在"


# ---------------------------------------------------------------------------
# 原稿只写不改
# ---------------------------------------------------------------------------


def test_the_advice_draft_is_write_once(auth_client: TestClient, customer_of_manager: dict):
    """AI 原稿落库后不可修改：载荷表上没有 update_time，模块里没有 update 路径。

    这条与 `biz_advisory_draft` 是同一条约束（迁移 0026），也是日后举证「审核是
    实质性的」的前提。
    """
    assert "update_time" not in OperationAdviceDraft.__table__.columns
    assert not any(name.startswith("update") for name in vars(draft_module))

    body = _purchase_body(auth_client, customer_of_manager["id"])
    first = _start_advice(
        auth_client, customer_id=customer_of_manager["id"], body=body
    )
    second = _start_advice(
        auth_client, customer_id=customer_of_manager["id"], body=body
    )
    assert first.status_code == 200 and second.status_code == 200
    # 再生成一次是**追加**一条，不是改写上一条。
    assert first.json()["data"]["id"] != second.json()["data"]["id"]
    assert _stored_draft(first.json()["data"]["id"]).reason


# ---------------------------------------------------------------------------
# 运行时可恢复
# ---------------------------------------------------------------------------


def _resume(draft_id: int, payload: dict) -> None:
    engine = _engine()
    cache = redis_lib.Redis.from_url(get_settings().test_redis_url)
    try:
        with OrmSession(engine) as session:
            review = claim_review(
                session,
                content_type=CONTENT_TYPE_OPERATION_ADVICE,
                content_ref=draft_id,
            )
            resume_review(session, cache, review, payload)
    finally:
        cache.close()
        engine.dispose()


def test_the_advice_runtime_resumes_at_the_interrupt(
    auth_client: TestClient, customer_of_manager: dict
):
    """放行与驳回在中断处续跑，跑的是操作建议自己的图（ADR-0020 的交接契约）。

    入口是 #07 的活，这里直接用流水线的那一对函数（claim_review / resume_review）验证
    图接得上：接不上，#07 的入口一上线就会撞在「没有登记运行时」或「续跑跑错了图」上，
    而后者不会有任何测试当场发现。
    """
    customer_id = customer_of_manager["id"]
    advisor_id = _employee_id(ADVISOR)
    body = _purchase_body(auth_client, customer_id)

    released_id = _start_advice(auth_client, customer_id=customer_id, body=body).json()[
        "data"
    ]["id"]
    _resume(
        released_id,
        {"action": ACTION_RELEASE, "advisor_id": advisor_id, "now": _now()},
    )
    assert _stored_review(released_id).status == STATUS_RELEASED

    rejected_id = _start_advice(auth_client, customer_id=customer_id, body=body).json()[
        "data"
    ]["id"]
    _resume(
        rejected_id,
        {
            "action": ACTION_REJECT,
            "reason": "金额与客户的流动性安排不符",
            "advisor_id": advisor_id,
            "now": _now(),
        },
    )
    review = _stored_review(rejected_id)
    assert review.status == STATUS_REJECTED

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            audits = list(
                session.scalars(
                    select(AdvisoryReviewAudit)
                    .where(AdvisoryReviewAudit.review_id.in_([review.id]))
                    .order_by(AdvisoryReviewAudit.id.asc())
                ).all()
            )
    finally:
        engine.dispose()
    assert [(row.action, row.reason) for row in audits] == [
        (ACTION_REJECT, "金额与客户的流动性安排不符")
    ]
