"""操作建议的内部入口（issue 09）。

Seam：后端 HTTP 层。队列的合并在 #05 已经钉住，这一份补的是「顾问打开一条建议」
与「客户经理看进度」这两条读取路径：

- **载荷是操作建议自己的**：只有「一个产品、一个方向、一个金额、一条理由」，
  方案特有的字段（候选池快照、配置建议、画像警示）一个都不出现——边界破了不会报错，
  只会让顾问在建议上看到一堆空列；
- **发起与放行不落进同一个人手里**：客户经理读得到、留言得了，调用放行 / 驳回被拒绝；
- **可见范围与审核队列同一个口径**：别的客户经理读不到这位客户的建议；
- **进度是两个口径**：审核记录说「顾问看了没有」，已放行之后再叠加客户决定。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review_status import (
    STATUS_PENDING,
    STATUS_RELEASED,
    STATUS_REJECTED as REVIEW_REJECTED,
)
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
    ProfileTag,
    ProfileTagConflict,
    RiskAssessment,
    SuitabilityDecision,
)
from app.operation_advice.decision import (
    STATUS_AWAITING,
    STATUS_REJECTED as DECISION_REJECTED,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

MANAGER = "manager1"
OTHER_MANAGER = "manager2"
ADVISOR = "advisor1"
RISK_OFFICER = "risk1"

START_PATH = "/api/internal/customers/{customer_id}/operation-advice"
OPTIONS_PATH = "/api/internal/customers/{customer_id}/operation-advice-options"
ADVICE_PATH = "/api/internal/operation-advice/{advice_id}"
REVIEW_PATH = "/api/internal/operation-advice/{advice_id}/review"
COMMENTS_PATH = "/api/internal/operation-advice/{advice_id}/comments"
RELEASE_PATH = "/api/internal/operation-advice/{advice_id}/release"
REJECT_PATH = "/api/internal/operation-advice/{advice_id}/reject"
CUSTOMER_DECISION_PATH = "/api/customer/operation-advice/{advice_id}/decision"

SEEDED_BALANCE = Decimal("500000.00")

# 方案特有的载荷字段：它们出现在操作建议上就是边界破了。
PLAN_ONLY_FIELDS = {
    "candidates",
    "allocation_suggestion",
    "warnings",
    "candidate_pool_snapshot",
    "tilt",
    "profile_computed_at",
    "advisory_request_id",
}


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
        "username": f"consoletest_{suffix}",
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
    response = client.post(
        "/api/internal/customers",
        headers=_employee_headers(client, MANAGER),
        json={**persona, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _fund_account(customer_id: int) -> None:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            session.add(
                FundingAccount(customer_id=customer_id, available_balance=SEEDED_BALANCE)
            )
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


def _delete_customer(customer_id: int) -> None:
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
                    delete(OperationAdviceDecision).where(
                        OperationAdviceDecision.advice_id.in_(draft_ids)
                    )
                )
                session.execute(
                    delete(OperationAdviceDraft).where(OperationAdviceDraft.id.in_(draft_ids))
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


def _advice_body(client: TestClient, *, customer_id: int, direction: str) -> dict:
    """一份合法的发起请求体：产品与金额 / 份额取自可选项端点。

    发起受理读的是同一份计算（ADR-0021），测试因此拿同一组输入去发起，而不是写死
    一只今天在池里的产品。
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
    return {
        "direction": direction,
        "product_code": option["product_code"],
        "shares": option["max_shares"],
    }


def _start_advice(
    client: TestClient, *, customer_id: int, direction: str = "申购", username: str = MANAGER
) -> dict:
    response = client.post(
        START_PATH.format(customer_id=customer_id),
        headers=_employee_headers(client, username),
        json=_advice_body(client, customer_id=customer_id, direction=direction),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ---------------------------------------------------------------------------
# 顾问打开一条建议：载荷是操作建议自己的
# ---------------------------------------------------------------------------


def test_the_advisor_reads_the_advice_payload_without_plan_fields(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _start_advice(auth_client, customer_id=customer_of_manager["id"])

    response = auth_client.get(
        ADVICE_PATH.format(advice_id=advice["id"]),
        headers=_employee_headers(auth_client, ADVISOR),
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]

    # 「一个产品、一个方向、一个金额、一条理由」——审核页要看的就这四件事。
    assert payload["product_code"] == advice["product_code"]
    assert payload["product_name"] == advice["product_name"]
    assert payload["direction"] == advice["direction"]
    assert payload["amount"] == advice["amount"]
    assert payload["reason"] == advice["reason"]
    # 方案特有的字段一个都不出现：不以空列的形式跟着建议走。
    assert set(payload).isdisjoint(PLAN_ONLY_FIELDS)


def test_an_unknown_advice_is_reported_as_missing(auth_client: TestClient):
    response = auth_client.get(
        ADVICE_PATH.format(advice_id=99999999),
        headers=_employee_headers(auth_client, ADVISOR),
    )
    assert response.status_code == 404


def test_review_status_follows_the_pipeline(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _start_advice(auth_client, customer_id=customer_of_manager["id"])
    advisor_headers = _employee_headers(auth_client, ADVISOR)

    pending = auth_client.get(
        REVIEW_PATH.format(advice_id=advice["id"]), headers=advisor_headers
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["data"] == {"advice_id": advice["id"], "status": STATUS_PENDING}

    released = auth_client.post(
        RELEASE_PATH.format(advice_id=advice["id"]), headers=advisor_headers
    )
    assert released.status_code == 200, released.text

    after = auth_client.get(
        REVIEW_PATH.format(advice_id=advice["id"]), headers=advisor_headers
    )
    assert after.json()["data"]["status"] == STATUS_RELEASED


# ---------------------------------------------------------------------------
# 客户经理：读得到、留言得了，放不了行
# ---------------------------------------------------------------------------


def test_the_manager_reads_and_comments_but_cannot_release(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _start_advice(auth_client, customer_id=customer_of_manager["id"])
    manager_headers = _employee_headers(auth_client, MANAGER)

    detail = auth_client.get(ADVICE_PATH.format(advice_id=advice["id"]), headers=manager_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["reason"] == advice["reason"]

    posted = auth_client.post(
        COMMENTS_PATH.format(advice_id=advice["id"]),
        headers=manager_headers,
        json={"body": "金额能不能再小一点？"},
    )
    assert posted.status_code == 200, posted.text

    comments = auth_client.get(
        COMMENTS_PATH.format(advice_id=advice["id"]), headers=manager_headers
    )
    assert comments.status_code == 200, comments.text
    bodies = [row["body"] for row in comments.json()["data"]["comments"]]
    assert bodies == ["金额能不能再小一点？"]

    # 发起与放行不落进同一个人手里：入口对客户经理关着。
    released = auth_client.post(
        RELEASE_PATH.format(advice_id=advice["id"]), headers=manager_headers
    )
    assert released.status_code == 403
    rejected = auth_client.post(
        REJECT_PATH.format(advice_id=advice["id"]),
        headers=manager_headers,
        json={"reason": "不合适"},
    )
    assert rejected.status_code == 403


def test_a_manager_cannot_read_another_managers_advice(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _start_advice(auth_client, customer_id=customer_of_manager["id"])
    other_headers = _employee_headers(auth_client, OTHER_MANAGER)

    for path in (
        ADVICE_PATH.format(advice_id=advice["id"]),
        REVIEW_PATH.format(advice_id=advice["id"]),
        COMMENTS_PATH.format(advice_id=advice["id"]),
        START_PATH.format(customer_id=customer_of_manager["id"]),
    ):
        response = auth_client.get(path, headers=other_headers)
        assert response.status_code == 403, f"{path}: {response.text}"

    # 风控专员没有审核内容的查看权（与方案那一侧同一个口径）。
    risk_headers = _employee_headers(auth_client, RISK_OFFICER)
    forbidden = auth_client.get(
        ADVICE_PATH.format(advice_id=advice["id"]), headers=risk_headers
    )
    assert forbidden.status_code == 403


# ---------------------------------------------------------------------------
# 客户经理看到的进度：审核进度 + 客户决定
# ---------------------------------------------------------------------------


def test_progress_reports_the_pipeline_state_before_release(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _start_advice(auth_client, customer_id=customer_of_manager["id"])

    response = auth_client.get(
        START_PATH.format(customer_id=customer_of_manager["id"]),
        headers=_employee_headers(auth_client, MANAGER),
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]["advice"]

    row = next(item for item in rows if item["id"] == advice["id"])
    assert row["review_status"] == STATUS_PENDING
    # 还没放行就没有「客户侧状态」：客户此刻读不到这条建议，谈不上待他决定。
    assert row["customer_status"] is None
    assert row["product_code"] == advice["product_code"]
    assert row["direction"] == advice["direction"]
    assert row["amount"] == advice["amount"]


def test_progress_adds_the_customer_decision_after_release(
    auth_client: TestClient, customer_of_manager: dict
):
    released = _start_advice(auth_client, customer_id=customer_of_manager["id"])
    auth_client.post(
        RELEASE_PATH.format(advice_id=released["id"]),
        headers=_employee_headers(auth_client, ADVISOR),
    )

    response = auth_client.get(
        START_PATH.format(customer_id=customer_of_manager["id"]),
        headers=_employee_headers(auth_client, MANAGER),
    )
    rows = response.json()["data"]["advice"]
    row = next(item for item in rows if item["id"] == released["id"])
    assert row["review_status"] == STATUS_RELEASED
    assert row["customer_status"] == STATUS_AWAITING

    # 客户拒绝之后，进度说的是客户的答案而不是顾问的。
    decided = auth_client.post(
        CUSTOMER_DECISION_PATH.format(advice_id=released["id"]),
        headers=customer_of_manager["headers"],
        json={"decision": "拒绝"},
    )
    assert decided.status_code == 200, decided.text

    after = auth_client.get(
        START_PATH.format(customer_id=customer_of_manager["id"]),
        headers=_employee_headers(auth_client, MANAGER),
    )
    updated = next(
        item for item in after.json()["data"]["advice"] if item["id"] == released["id"]
    )
    assert updated["review_status"] == STATUS_RELEASED
    assert updated["customer_status"] == DECISION_REJECTED


def test_a_rejected_advice_stays_rejected_and_never_reaches_the_customer(
    auth_client: TestClient, customer_of_manager: dict
):
    advice = _start_advice(auth_client, customer_id=customer_of_manager["id"])
    rejected = auth_client.post(
        REJECT_PATH.format(advice_id=advice["id"]),
        headers=_employee_headers(auth_client, ADVISOR),
        json={"reason": "金额与客户的流动性安排不符"},
    )
    assert rejected.status_code == 200, rejected.text

    response = auth_client.get(
        START_PATH.format(customer_id=customer_of_manager["id"]),
        headers=_employee_headers(auth_client, MANAGER),
    )
    row = next(
        item for item in response.json()["data"]["advice"] if item["id"] == advice["id"]
    )
    assert row["review_status"] == REVIEW_REJECTED
    assert row["customer_status"] is None

    # 被驳回的建议在客户侧读不到——护栏 5 的第二个出口在驳回这一侧同样成立。
    mine = auth_client.get("/api/customer/operation-advice", headers=customer_of_manager["headers"])
    assert mine.status_code == 200
    assert [item["id"] for item in mine.json()["data"]["advice"]] == []


def test_the_progress_list_covers_every_advice_of_the_customer(
    auth_client: TestClient, customer_of_manager: dict
):
    first = _start_advice(auth_client, customer_id=customer_of_manager["id"])
    second = _start_advice(auth_client, customer_id=customer_of_manager["id"])

    response = auth_client.get(
        START_PATH.format(customer_id=customer_of_manager["id"]),
        headers=_employee_headers(auth_client, MANAGER),
    )
    rows = response.json()["data"]["advice"]
    assert {item["id"] for item in rows} == {first["id"], second["id"]}
    # 后发起的在前：客户经理先看的是最新的那条。
    assert rows[0]["id"] == second["id"]

    # 另一位客户经理读不到：可见范围与审核队列同一个口径。
    forbidden = auth_client.get(
        START_PATH.format(customer_id=customer_of_manager["id"]),
        headers=_employee_headers(auth_client, OTHER_MANAGER),
    )
    assert forbidden.status_code == 403
