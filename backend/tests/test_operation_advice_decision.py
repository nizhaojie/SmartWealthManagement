"""客户的最终决定权（issue 07）。

Seam：后端 HTTP 层。链路从客户经理发起的原稿出发：顾问放行 → 客户可见 → 客户接受或拒绝。
断言落在响应、库里的决定记录与交易上。

这一份盯住五件事：

- **护栏 5 的第二个出口**：未放行的建议在任何客户侧接口都读不到；
- **发起与放行不落进同一个人手里**：客户经理调用放行接口被拒绝；
- **状态集与有效期**：`待客户决定 → 已接受 / 已拒绝 / 已过期`，7 个自然日；
- **接受即成交，且是一次原子操作**：复用受理服务与同一个交易事件入海口，校验不过则
  接受失败、建议留在待客户决定、库里不留任何交易；
- **赎回按草案里的份额成交**（ADR-0021）：部分赎回按比例减持、份额恰等持仓时清仓、
  客户自己动过持仓导致份额不足则接受失败，份额列为空的历史行仍按当下全部成交。
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

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review_status import ACTION_RELEASE, STATUS_PENDING, STATUS_RELEASED
from app.db.models import (
    AdvisoryReview,
    AdvisoryReviewAudit,
    AdvisoryReviewComment,
    Customer,
    CustomerProfile,
    FundingAccount,
    Holding,
    OperationAdviceDecision,
    OperationAdviceDraft,
    Product,
    ProfileTag,
    ProfileTagConflict,
    RiskAlert,
    RiskAssessment,
    RiskFocus,
    SuitabilityDecision,
    Transaction,
    Transfer,
)
from app.operation_advice.decision import (
    CUSTOMER_VISIBLE_ADVICE_FIELDS,
    DECISION_ACCEPT,
    DECISION_REJECT,
    STATUS_ACCEPTED,
    STATUS_AWAITING,
    STATUS_EXPIRED,
    STATUS_REJECTED,
)
from app.risk_monitoring import alerting
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

MANAGER = "manager1"
OTHER_CUSTOMER = "qianc5"
ADVISOR = "advisor1"
RISK_OFFICER = "risk1"

OPERATION_ADVICE_PATH = "/api/internal/customers/{customer_id}/operation-advice"
OPTIONS_PATH = "/api/internal/customers/{customer_id}/operation-advice-options"
RELEASE_PATH = "/api/internal/operation-advice/{advice_id}/release"
REJECT_PATH = "/api/internal/operation-advice/{advice_id}/reject"
MY_ADVICE_PATH = "/api/customer/operation-advice"

HELD_STATUS = "持有中"
# 份额归零的持仓不再是「持有中」（受理侧 `order_acceptance.CLEARED_STATUS`）。
CLEARED_STATUS = "已清仓"
# 新客户在应用里拿不到钱：余额的初始值来自种子。测试因此直接写一个资金账户——它是
# 演示起点，不是被测行为（应用里有充值入口，见 ADR-0023）。
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
        "username": f"decisiontest_{suffix}",
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
    """开户已经建出资金账户（余额 0），这里只是把余额写成演示起点。

    测试直接写它是为了绕过「装库时没有入金」这件事，而不是为了建账户——再 INSERT 一行
    会撞 `uk_funding_account_customer`（应用里的充值入口见 ADR-0023）。
    """
    _set_balance(customer_id, balance)


def _set_balance(customer_id: int, balance: Decimal) -> None:
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


def _holding_status(customer_id: int, product_code: str) -> str:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            status = session.scalar(
                select(Holding.status)
                .join(Product, Product.id == Holding.product_id)
                .where(
                    Holding.customer_id == customer_id,
                    Product.product_code == product_code,
                )
            )
    finally:
        engine.dispose()
    assert status is not None
    return status


def _holding(customer_id: int, product_code: str) -> dict:
    """这一笔持仓的四个数：份额、成本、市值与状态（成交后的对照基准）。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            row = session.scalar(
                select(Holding)
                .join(Product, Product.id == Holding.product_id)
                .where(
                    Holding.customer_id == customer_id,
                    Product.product_code == product_code,
                )
            )
    finally:
        engine.dispose()
    assert row is not None
    return {
        "shares": row.shares,
        "cost_amount": row.cost_amount,
        "current_value": row.current_value,
        "status": row.status,
    }


def _set_holding_shares(
    customer_id: int, *, product_code: str, shares: Decimal
) -> None:
    """把持仓改成另一个份额：模拟「建议生成之后客户自己动过持仓」。

    与 `_set_balance` 一样，这是场景的起点而不是被测行为，因此直接改库。成本与市值按
    同一比例同向调整，持仓仍自洽——受理侧只读份额，但让测试数据自相矛盾没有好处。
    """
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            holding = session.scalar(
                select(Holding)
                .join(Product, Product.id == Holding.product_id)
                .where(
                    Holding.customer_id == customer_id,
                    Product.product_code == product_code,
                )
            )
            assert holding is not None
            ratio = shares / holding.shares
            holding.shares = shares
            holding.cost_amount = (holding.cost_amount * ratio).quantize(Decimal("0.01"))
            holding.current_value = (holding.current_value * ratio).quantize(
                Decimal("0.01")
            )
            session.commit()
    finally:
        engine.dispose()


def _stored_shares(advice_id: int) -> Decimal | None:
    """草案里存的赎回份额（改动之后落库的行：赎回必带份额）。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            return session.scalar(
                select(OperationAdviceDraft.redeemed_shares).where(
                    OperationAdviceDraft.id == advice_id
                )
            )
    finally:
        engine.dispose()


def _clear_redeemed_shares(advice_id: int) -> None:
    """把草案的份额列清空：还原成改动之前落库的那一行（空值 = 全部赎回）。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            draft = session.get(OperationAdviceDraft, advice_id)
            assert draft is not None
            draft.redeemed_shares = None
            session.commit()
    finally:
        engine.dispose()


def _delete_customer(customer_id: int) -> None:
    """清掉这位客户的一切，顺序即外键依赖顺序。

    客户决定与它派生出来的交易、预警、风险关注都要一起走——不然下一位跑到的用例会
    看见别人的账。
    """
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
                session.execute(
                    delete(OperationAdviceDecision).where(
                        OperationAdviceDecision.advice_id.in_(draft_ids)
                    )
                )
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
            session.execute(delete(RiskFocus).where(RiskFocus.customer_id == customer_id))
            session.execute(delete(RiskAlert).where(RiskAlert.customer_id == customer_id))
            session.execute(
                delete(Transaction).where(Transaction.customer_id == customer_id)
            )
            session.execute(delete(Transfer).where(Transfer.customer_id == customer_id))
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
        yield {"id": customer_id, "username": persona["username"], "headers": headers}
    finally:
        _delete_customer(customer_id)


# ---------------------------------------------------------------------------
# 走一遍链路
# ---------------------------------------------------------------------------


def _advice_body(
    client: TestClient,
    *,
    customer_id: int,
    direction: str,
    shares: Decimal | None = None,
) -> dict:
    """一份合法的发起请求体：产品与金额 / 份额取自可选项端点。

    发起受理读的是同一份计算（ADR-0021），测试因此与端点用同一组输入——申购取第一
    只买得起的产品的起投金额，赎回默认取那只持仓的全部份额，也可以指定一个部分份额。
    """
    response = client.get(
        OPTIONS_PATH.format(customer_id=customer_id),
        headers=_employee_headers(client, MANAGER),
        params={"direction": direction},
    )
    assert response.status_code == 200, response.text
    options = response.json()["data"]["products"]
    assert options, direction
    if direction == "申购":
        option = next(item for item in options if item["affordable"])
        return {
            "direction": direction,
            "product_code": option["product_code"],
            "amount": option["min_amount"],
        }
    option = options[0]
    chosen = shares if shares is not None else option["max_shares"]
    return {
        "direction": direction,
        "product_code": option["product_code"],
        "shares": str(chosen),
    }


def _generate(
    client: TestClient,
    customer_id: int,
    direction: str = "申购",
    shares: Decimal | None = None,
) -> dict:
    response = client.post(
        OPERATION_ADVICE_PATH.format(customer_id=customer_id),
        headers=_employee_headers(client, MANAGER),
        json=_advice_body(
            client, customer_id=customer_id, direction=direction, shares=shares
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _release(client: TestClient, advice_id: int, username: str = ADVISOR):
    return client.post(
        RELEASE_PATH.format(advice_id=advice_id),
        headers=_employee_headers(client, username),
        json={},
    )


def _reject(client: TestClient, advice_id: int, reason: str, username: str = ADVISOR):
    return client.post(
        REJECT_PATH.format(advice_id=advice_id),
        headers=_employee_headers(client, username),
        json={"reason": reason},
    )


def _decide(
    client: TestClient, advice_id: int, decision: str, headers: dict[str, str]
):
    return client.post(
        f"{MY_ADVICE_PATH}/{advice_id}/decision",
        headers=headers,
        json={"decision": decision},
    )


def _list_my_advice(client: TestClient, headers: dict[str, str]) -> list[dict]:
    """「我的建议」的第一页（ADR-0024 的分页信封）。"""
    response = client.get(MY_ADVICE_PATH, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def _view(client: TestClient, advice_id: int, headers: dict[str, str]) -> dict:
    response = client.get(f"{MY_ADVICE_PATH}/{advice_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _stored_decision(advice_id: int) -> OperationAdviceDecision | None:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            return session.scalar(
                select(OperationAdviceDecision).where(
                    OperationAdviceDecision.advice_id == advice_id
                )
            )
    finally:
        engine.dispose()


def _stored_review_status(advice_id: int) -> str:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            status = session.scalar(
                select(AdvisoryReview.status).where(
                    AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
                    AdvisoryReview.content_ref == advice_id,
                )
            )
    finally:
        engine.dispose()
    assert status is not None
    return status


def _transactions_of(customer_id: int) -> list[Transaction]:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(
                    select(Transaction).where(Transaction.customer_id == customer_id)
                ).all()
            )
    finally:
        engine.dispose()


def _age_delivery(advice_id: int, *, days: int) -> None:
    """把放行留痕的时间拨回 days 天：有效期从送达起算，用它模拟建议过期。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            review_id = session.scalar(
                select(AdvisoryReview.id).where(
                    AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
                    AdvisoryReview.content_ref == advice_id,
                )
            )
            audit = session.scalar(
                select(AdvisoryReviewAudit).where(
                    AdvisoryReviewAudit.review_id == review_id,
                    AdvisoryReviewAudit.action == ACTION_RELEASE,
                )
            )
            assert audit is not None
            audit.decided_at = audit.decided_at - timedelta(days=days)
            session.commit()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 护栏 5 的第二个出口：未放行的建议客户侧读不到
# ---------------------------------------------------------------------------


def test_an_unreleased_advice_is_invisible_to_the_customer(
    auth_client: TestClient, customer_of_manager: dict
):
    """未放行的建议在任何客户侧接口都读不到——读、决定两边都读不到。"""
    advice = _generate(auth_client, customer_of_manager["id"])
    headers = customer_of_manager["headers"]

    assert _list_my_advice(auth_client, headers) == []
    assert (
        auth_client.get(f"{MY_ADVICE_PATH}/{advice['id']}", headers=headers).status_code
        == 404
    )
    # 接受与拒绝也是客户侧接口：未放行时它们与「这条建议不存在」同义。
    assert _decide(auth_client, advice["id"], DECISION_ACCEPT, headers).status_code == 404
    assert _decide(auth_client, advice["id"], DECISION_REJECT, headers).status_code == 404

    # 库里那条审核记录还在等顾问，谁也没有读过它。
    assert _stored_review_status(advice["id"]) == STATUS_PENDING
    assert _stored_decision(advice["id"]) is None


def test_only_the_advisor_can_release_an_advice(
    auth_client: TestClient, customer_of_manager: dict
):
    """发起与放行不落进同一个人手里：客户经理（与风控专员）调用放行接口被拒绝。"""
    advice = _generate(auth_client, customer_of_manager["id"])

    for username in (MANAGER, RISK_OFFICER):
        refused = _release(auth_client, advice["id"], username=username)
        assert refused.status_code == 403, (username, refused.text)

    # 归属人自己发起、顾问放行成功——被拦住的是别人，不是这条链路本身。
    released = _release(auth_client, advice["id"])
    assert released.status_code == 200, released.text
    assert released.json()["data"]["status"] == STATUS_RELEASED
    assert _stored_review_status(advice["id"]) == STATUS_RELEASED


def test_a_rejected_advice_never_reaches_the_customer(
    auth_client: TestClient, customer_of_manager: dict
):
    """驳回与未放行一样：客户侧读不到（拒绝理由必填是顾问那一侧的事）。"""
    advice = _generate(auth_client, customer_of_manager["id"])

    missing_reason = _reject(auth_client, advice["id"], "")
    assert missing_reason.status_code == 400

    rejected = _reject(auth_client, advice["id"], "金额与客户的流动性安排不符")
    assert rejected.status_code == 200, rejected.text

    headers = customer_of_manager["headers"]
    assert _list_my_advice(auth_client, headers) == []
    assert (
        auth_client.get(f"{MY_ADVICE_PATH}/{advice['id']}", headers=headers).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# 送达视图与有效期
# ---------------------------------------------------------------------------


def test_a_released_advice_reaches_the_customer_with_a_seven_day_window(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _generate(auth_client, customer_of_manager["id"])
    assert _release(auth_client, advice["id"]).status_code == 200
    headers = customer_of_manager["headers"]

    listed = _list_my_advice(auth_client, headers)
    assert [row["id"] for row in listed] == [advice["id"]]
    row = _view(auth_client, advice["id"], headers)

    assert row["status"] == STATUS_AWAITING
    assert row["product_code"] == advice["product_code"]
    assert row["product_name"] == advice["product_name"]
    assert row["direction"] == "申购"
    assert row["amount"] == advice["amount"]
    assert row["reason"] == advice["reason"]
    assert row["disclaimer"]
    assert row["decision"] is None
    assert row["decided_at"] is None

    # 有效期 7 个自然日，从放行那一刻起算。
    released = datetime.fromisoformat(row["released_at"])
    expires = datetime.fromisoformat(row["expires_at"])
    assert expires - released == timedelta(days=7)

    # 送达视图是服务端裁剪（ADR-0016）：发起人、内容分类、客户标识都不在里面。
    # 逐项相等而不是「包含」——加字段时默认是内部字段，要让它送达客户必须显式加一次。
    assert set(row) == set(CUSTOMER_VISIBLE_ADVICE_FIELDS)


def test_an_expired_advice_can_no_longer_be_decided(
    auth_client: TestClient, customer_of_manager: dict
):
    """过期即终态：接受与拒绝都不再受理，状态读出来就是已过期。"""
    customer_id = customer_of_manager["id"]
    advice = _generate(auth_client, customer_id)
    assert _release(auth_client, advice["id"]).status_code == 200
    _age_delivery(advice["id"], days=8)

    headers = customer_of_manager["headers"]
    accepted = _decide(auth_client, advice["id"], DECISION_ACCEPT, headers)
    assert accepted.status_code == 409
    assert "过期" in accepted.json()["message"]
    assert _decide(auth_client, advice["id"], DECISION_REJECT, headers).status_code == 409

    assert _stored_decision(advice["id"]) is None
    assert _view(auth_client, advice["id"], headers)["status"] == STATUS_EXPIRED
    assert _transactions_of(customer_id) == []


# ---------------------------------------------------------------------------
# 接受即成交：一次原子操作
# ---------------------------------------------------------------------------


def _spy_on_acceptance(monkeypatch: pytest.MonkeyPatch) -> tuple[list, list]:
    """钉住「接受走的是同一个交易事件入海口，并且过了规则引擎」。"""
    submissions: list = []
    evaluated: list = []
    original_submit = alerting.submit_transaction_event
    original_evaluate = alerting.create_alerts_for_event

    def submit(db, *, publisher, submission, operator_id, now):
        submissions.append((submission, operator_id))
        return original_submit(
            db, publisher=publisher, submission=submission, operator_id=operator_id, now=now
        )

    def evaluate(db, *, event, publisher, now):
        evaluated.append(event)
        return original_evaluate(db, event=event, publisher=publisher, now=now)

    monkeypatch.setattr(alerting, "submit_transaction_event", submit)
    monkeypatch.setattr(alerting, "create_alerts_for_event", evaluate)
    return submissions, evaluated


def test_accepting_an_advice_strikes_a_trade_through_the_rule_engine(
    auth_client: TestClient, customer_of_manager: dict, monkeypatch: pytest.MonkeyPatch
):
    customer_id = customer_of_manager["id"]
    advice = _generate(auth_client, customer_id)
    assert _release(auth_client, advice["id"]).status_code == 200
    submissions, evaluated = _spy_on_acceptance(monkeypatch)

    response = _decide(
        auth_client, advice["id"], DECISION_ACCEPT, customer_of_manager["headers"]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["status"] == STATUS_ACCEPTED
    assert data["decision"] == DECISION_ACCEPT
    assert data["decided_at"]
    assert data["transaction"]["transaction_type"] == "申购"
    assert data["transaction"]["amount"] == advice["amount"]

    # 决定落成一条记录：谁、什么时候、对哪条建议、接受。
    row = _stored_decision(advice["id"])
    assert row is not None
    assert row.customer_id == customer_id
    assert row.decision == DECISION_ACCEPT
    assert row.decided_at is not None

    # 成交走的是同一个交易事件入海口（接受的受理服务与直接交易共用它），
    # 客户自助发起因此没有经办员工（Q22）。
    assert len(submissions) == 1
    submission, operator_id = submissions[0]
    assert submission.customer_id == customer_id
    assert submission.transaction_type == "申购"
    assert submission.amount == Decimal(advice["amount"])
    assert operator_id is None

    # 同一笔事件过了规则引擎——风控的输入不只来自直接交易。
    stored = _transactions_of(customer_id)
    assert len(stored) == 1
    assert stored[0].operator_id is None
    assert [event.transaction_id for event in evaluated] == [stored[0].id]


def test_an_acceptance_short_of_balance_stays_awaiting_the_decision(
    auth_client: TestClient, customer_of_manager: dict
):
    """接受失败（余额不足）时建议留在待客户决定，且没有产生任何交易。

    补足余额后可以再来一次——不存在「已接受但成交失败」这个状态。
    """
    customer_id = customer_of_manager["id"]
    advice = _generate(auth_client, customer_id)
    assert _release(auth_client, advice["id"]).status_code == 200
    headers = customer_of_manager["headers"]

    _set_balance(customer_id, Decimal("0.00"))
    failed = _decide(auth_client, advice["id"], DECISION_ACCEPT, headers)
    assert failed.status_code == 400, failed.text
    assert "余额不足" in failed.json()["message"]

    assert _stored_decision(advice["id"]) is None
    assert _transactions_of(customer_id) == []
    assert _view(auth_client, advice["id"], headers)["status"] == STATUS_AWAITING

    # 客户补足条件后再来一次：这次成交。
    _set_balance(customer_id, SEEDED_BALANCE)
    retried = _decide(auth_client, advice["id"], DECISION_ACCEPT, headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == STATUS_ACCEPTED
    assert len(_transactions_of(customer_id)) == 1


def test_rejecting_records_the_decision_without_a_trade(
    auth_client: TestClient, customer_of_manager: dict
):
    customer_id = customer_of_manager["id"]
    advice = _generate(auth_client, customer_id)
    assert _release(auth_client, advice["id"]).status_code == 200

    response = _decide(
        auth_client, advice["id"], DECISION_REJECT, customer_of_manager["headers"]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == STATUS_REJECTED
    assert data["decision"] == DECISION_REJECT
    assert data["decided_at"]

    row = _stored_decision(advice["id"])
    assert row is not None
    assert row.customer_id == customer_id
    assert row.decision == DECISION_REJECT
    assert _transactions_of(customer_id) == []


def test_a_decided_advice_cannot_be_decided_twice(
    auth_client: TestClient, customer_of_manager: dict
):
    customer_id = customer_of_manager["id"]
    advice = _generate(auth_client, customer_id)
    assert _release(auth_client, advice["id"]).status_code == 200
    headers = customer_of_manager["headers"]

    assert _decide(auth_client, advice["id"], DECISION_REJECT, headers).status_code == 200
    again = _decide(auth_client, advice["id"], DECISION_ACCEPT, headers)
    assert again.status_code == 409
    assert _stored_decision(advice["id"]).decision == DECISION_REJECT
    assert _transactions_of(customer_id) == []


def test_an_unknown_decision_is_rejected(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _generate(auth_client, customer_of_manager["id"])
    assert _release(auth_client, advice["id"]).status_code == 200

    response = _decide(
        auth_client, advice["id"], "同意", customer_of_manager["headers"]
    )
    assert response.status_code == 400
    assert _stored_decision(advice["id"]) is None


def test_accepting_a_redemption_advice_redeems_the_whole_holding(
    auth_client: TestClient, customer_of_manager: dict
):
    """赎回按草案里的份额成交：份额恰等于持仓时，成交后持仓状态为「已清仓」。"""
    customer_id = customer_of_manager["id"]
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))
    advice = _generate(auth_client, customer_id, "赎回")
    # 改动之后落库的赎回建议一律带份额——「空 = 全部」是历史行的语义，不是新行的写法。
    assert _stored_shares(advice["id"]) == Decimal("1200.0000")
    assert _release(auth_client, advice["id"]).status_code == 200

    response = _decide(
        auth_client, advice["id"], DECISION_ACCEPT, customer_of_manager["headers"]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["status"] == STATUS_ACCEPTED
    assert data["transaction"]["transaction_type"] == "赎回"
    assert data["transaction"]["shares"] == "1200.0000"
    # 份额归零的持仓不再是「持有中」，资产页与穿透都不再看到它。
    assert _holding_status(customer_id, "F000003") == CLEARED_STATUS


def test_accepting_a_partial_redemption_advice_reduces_the_holding_proportionally(
    auth_client: TestClient, customer_of_manager: dict
):
    """部分赎回：接受后剩余份额、成本与市值按比例减持，持仓状态仍是「持有中」。"""
    customer_id = customer_of_manager["id"]
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))
    before = _holding(customer_id, "F000003")
    advice = _generate(auth_client, customer_id, "赎回", shares=Decimal("600.0000"))
    assert _stored_shares(advice["id"]) == Decimal("600.0000")
    assert _release(auth_client, advice["id"]).status_code == 200

    response = _decide(
        auth_client, advice["id"], DECISION_ACCEPT, customer_of_manager["headers"]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["status"] == STATUS_ACCEPTED
    assert data["transaction"]["transaction_type"] == "赎回"
    # 成交的是草案里的那一个数，不是接受那一刻的全部持仓。
    assert data["transaction"]["shares"] == "600.0000"

    after = _holding(customer_id, "F000003")
    assert after["shares"] == Decimal("600.0000")
    # 成本与市值各减持一半（净值 1.5，1200 份的成本与市值都是 1800.00），盈亏比例不变。
    assert after["cost_amount"] == before["cost_amount"] / 2
    assert after["current_value"] == before["current_value"] / 2
    assert after["status"] == HELD_STATUS


def test_an_acceptance_short_of_shares_stays_awaiting_the_decision(
    auth_client: TestClient, customer_of_manager: dict
):
    """赎回建议生成之后客户自己动过持仓导致份额不足 → 接受失败，建议仍在待客户决定。

    与余额不足同一套语义（`decision._accept` 的既有回滚路径）：决定不落库、不产生交易。
    """
    customer_id = customer_of_manager["id"]
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))
    advice = _generate(auth_client, customer_id, "赎回", shares=Decimal("600.0000"))
    assert _release(auth_client, advice["id"]).status_code == 200
    headers = customer_of_manager["headers"]

    # 建议生成之后客户自己赎到只剩 400 份：草案里的 600 份已经赎不出来了。
    _set_holding_shares(customer_id, product_code="F000003", shares=Decimal("400.0000"))
    failed = _decide(auth_client, advice["id"], DECISION_ACCEPT, headers)
    assert failed.status_code == 400, failed.text
    assert "超过" in failed.json()["message"]

    assert _stored_decision(advice["id"]) is None
    assert _transactions_of(customer_id) == []
    assert _view(auth_client, advice["id"], headers)["status"] == STATUS_AWAITING

    # 客户把持仓补回去之后再来一次：这次按草案的 600 份成交。
    _set_holding_shares(customer_id, product_code="F000003", shares=Decimal("1200.0000"))
    retried = _decide(auth_client, advice["id"], DECISION_ACCEPT, headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == STATUS_ACCEPTED
    assert _holding(customer_id, "F000003")["shares"] == Decimal("600.0000")


def test_a_legacy_redemption_advice_without_shares_redeems_the_current_whole_holding(
    auth_client: TestClient, customer_of_manager: dict
):
    """改动之前的赎回建议（份额列为空）接受时仍按当下的全部份额成交。

    空值 = 全部赎回是既有语义的忠实延续，不是特例——它只服务改动之前已有的行。
    """
    customer_id = customer_of_manager["id"]
    _add_holding(customer_id, product_code="F000003", shares=Decimal("1200.0000"))
    advice = _generate(auth_client, customer_id, "赎回", shares=Decimal("600.0000"))
    assert _release(auth_client, advice["id"]).status_code == 200
    # 把这一行还原成改动之前落库的形状：份额列为空。
    _clear_redeemed_shares(advice["id"])

    # 期间客户自己动过持仓：现在只剩 900 份。旧语义按当下的全部成交——900 份，而不是
    # 草案里那个早已不存在的 600（新行会因份额不足而失败，两者由此分得开）。
    _set_holding_shares(customer_id, product_code="F000003", shares=Decimal("900.0000"))
    response = _decide(
        auth_client, advice["id"], DECISION_ACCEPT, customer_of_manager["headers"]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["status"] == STATUS_ACCEPTED
    assert data["transaction"]["shares"] == "900.0000"
    assert _holding_status(customer_id, "F000003") == CLEARED_STATUS


def test_another_customer_cannot_read_or_decide_on_it(
    auth_client: TestClient, customer_of_manager: dict
):
    """别人的建议与不存在的建议同义：读不到、也决定不了。"""
    advice = _generate(auth_client, customer_of_manager["id"])
    assert _release(auth_client, advice["id"]).status_code == 200
    outsider = _customer_login(auth_client, OTHER_CUSTOMER)

    assert (
        auth_client.get(f"{MY_ADVICE_PATH}/{advice['id']}", headers=outsider).status_code
        == 404
    )
    assert _decide(auth_client, advice["id"], DECISION_ACCEPT, outsider).status_code == 404
    assert all(row["id"] != advice["id"] for row in _list_my_advice(auth_client, outsider))
    # 越权的接受也没有在库里留下痕迹。
    assert _stored_decision(advice["id"]) is None


def test_a_customer_identity_is_derived_from_the_credential(
    auth_client: TestClient, customer_of_manager: dict
):
    """决定记录上的客户由凭证推导：请求体里塞别的客户标识不作数。"""
    customer_id = customer_of_manager["id"]
    advice = _generate(auth_client, customer_id)
    assert _release(auth_client, advice["id"]).status_code == 200

    response = auth_client.post(
        f"{MY_ADVICE_PATH}/{advice['id']}/decision",
        headers=customer_of_manager["headers"],
        json={"decision": DECISION_REJECT, "customer_id": customer_id + 999},
    )
    assert response.status_code == 200, response.text
    assert _stored_decision(advice["id"]).customer_id == customer_id
